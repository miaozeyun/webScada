"""审计服务（M8 RBAC 配套，契约 §6.3）：全部安全敏感写路径的埋点唯一入口。

七类 action（models.AuditLog 注释同步冻结）：login / write_var / alarm_ack /
project_save / share_create / share_revoke / user_mgmt；M8 终审 #1 新增 datasource_test
（数据源连通性测试：凭证注回的唯一明文出口，须留痕）。

关键设计：
- 自建短会话提交：审计不搭主请求事务，主事务回滚不会吞掉审计记录（安全事件必须留痕）
- 写入失败仅 log 不抛：审计故障不阻断业务主流程
- ip 口径：取 X-Forwarded-For 首段（uvicorn --proxy-headers 已信任 nginx，首段为真实客户端），
  缺失回落 request.client.host；request 为 None（引擎/后台路径）时 ip 为空
- username 冗余快照：用户被删后（user_id 外键 SET NULL）审计仍可读
"""
from fastapi import Request
from loguru import logger

from app.db.models import AuditLog, User

# action 枚举（契约 §6.3 七类 + M8 终审新增 datasource_test）；未知 action 仍记录但告警，便于发现漏改的埋点
ALLOWED_ACTIONS = frozenset(
    {"login", "write_var", "alarm_ack", "project_save", "share_create", "share_revoke", "user_mgmt", "datasource_test"}
)

# 会话工厂注入点：默认取 app.db.base.SessionLocal（惰性 import，防模块导入期连库副作用）；
# 测试 monkeypatch 本模块属性指向测试库工厂
session_factory = None


def client_ip(request: Request | None) -> str | None:
    """X-Forwarded-For 首段为真实客户端（nginx 反代追加了代理链，末段不可信）。"""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _get_session_factory():
    if session_factory is not None:
        return session_factory
    from app.db.base import SessionLocal  # 惰性：避免包间导入顺序问题

    return SessionLocal


async def audit(
    request: Request | None,
    user: User | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """落一条审计（fire-and-forget 语义：调用方无需 await 结果处理）。

    request/user 均可 None：login 失败（用户不存在）传 user=None，username 进 detail；
    引擎侧埋点（write_var/alarm_ack 由 WS/任务路径触发）request=None。
    """
    if action not in ALLOWED_ACTIONS:
        logger.warning("审计 action 不在七类枚举内（仍记录）：{}", action)
    ip = client_ip(request)
    username = user.username if user is not None else None
    user_id = user.id if user is not None else None
    try:
        factory = _get_session_factory()
        async with factory() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    username=username,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                    ip=ip,
                )
            )
            await session.commit()
    except Exception as exc:  # 审计失败不抛：业务主流程不受阻断
        logger.warning("审计写入失败（action={} username={}）: {}", action, username, exc)
