"""运行态 WS（M8 工作包 A）：/api/v1/ws/runtime（契约 §4.6/§5，帧协议权威 03-接口清单 §3）。

连接序列：token 双鉴权（JWT 签名/有效期｜shareToken 存在/未撤销/未过期）→ 并发上限检查
（超限 error(RATE_LIMITED) 后 close 4000）→ 立即推 snapshot → values/alarm/writeAck/reload 持续推送。
鉴权失败不做握手阶段 HTTP 拒绝：统一 accept 后推 error 帧 + close(4000)（03 §3.1）。

DB 会话纪律：鉴权/快照查询均短会话即用即还，不占 WS 连接生命周期（连接可存活数小时）。
"""
import json
import uuid as uuidlib
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import Project, ShareLink, User
from app.services import ws_manager as ws_manager_mod
from app.services.ws_manager import Connection, now_monotonic

# 进程内单例（runtime_boot 同时挂 app.state；测试以 reset() 复位）
manager = ws_manager_mod.manager

router = APIRouter(tags=["ws"])


class _HandshakeError(Exception):
    """握手期失败：code 即 error 帧 code（03 §3.3），统一 close 4000。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _is_jwt(token: str) -> bool:
    # share token 由 token_urlsafe 生成（仅 [A-Za-z0-9_-]）；JWT 含两个 '.'，以点区分
    return token.count(".") == 2


def _parse_uuid(value: str) -> uuidlib.UUID | None:
    try:
        return uuidlib.UUID(value)
    except (ValueError, AttributeError):
        return None


async def _load_project(db, project_param: str) -> Project:
    pid = _parse_uuid(project_param)
    if pid is None:
        raise _HandshakeError("PROJECT_REMOVED", "工程不存在或已删除")
    project = await db.get(Project, pid)
    if project is None:
        raise _HandshakeError("PROJECT_REMOVED", "工程不存在或已删除")
    return project


async def _handshake(websocket: WebSocket, project_param: str, token: str, page: str) -> Connection:
    """token 校验 + 并发上限 + 注册。短会话；失败抛 _HandshakeError。"""
    from app.db.base import SessionLocal  # 惰性取用：测试经 monkeypatch 指向测试库

    if not token:
        raise _HandshakeError("TOKEN_EXPIRED", "缺少 token 参数")

    async with SessionLocal() as db:
        if _is_jwt(token):
            try:
                payload = decode_access_token(token)
                user_id = uuidlib.UUID(str(payload.get("sub")))
            except _HandshakeError:
                raise
            except Exception:  # noqa: BLE001 - AppError(TOKEN_EXPIRED)/解析失败统一口径
                raise _HandshakeError("TOKEN_EXPIRED", "登录已过期，请重新登录") from None
            user = await db.get(User, user_id)
            if user is None:
                raise _HandshakeError("TOKEN_EXPIRED", "用户不存在")
            project = await _load_project(db, project_param)
            if manager.count_for_user_project(user.id, project.id) >= settings.JWT_WS_MAX_PER_USER_PROJECT:
                raise _HandshakeError("RATE_LIMITED", "该用户对本工程的连接数已达上限")
            conn = Connection(
                websocket, project.id, "jwt", token,
                user_id=user.id, username=user.username, role=user.role, page=page,
            )
        else:
            link = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalar_one_or_none()
            if link is None or link.revoked_at is not None:
                raise _HandshakeError("SHARE_REVOKED", "分享链接不存在或已撤销")
            expires_at = link.expires_at
            if expires_at is not None:
                if expires_at.tzinfo is None:  # SQLite 存取丢失 tzinfo；PG 返回 aware
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= datetime.now(timezone.utc):
                    raise _HandshakeError("SHARE_EXPIRED", "分享链接已过期")
            project = await _load_project(db, str(link.project_id))
            if manager.count_for_token(token) >= settings.SHARE_MAX_WS_PER_TOKEN:
                raise _HandshakeError("RATE_LIMITED", "该分享链接的连接数已达上限")
            conn = Connection(websocket, project.id, "share", token, page=page)

    if manager.total_count() >= settings.WS_MAX_CONNECTIONS:
        raise _HandshakeError("RATE_LIMITED", "服务端连接数已达上限")
    try:
        await manager.register(conn)  # 锁内双检配额（防握手窗口突发超限）
    except ws_manager_mod.QuotaExceeded as exc:
        raise _HandshakeError(exc.code, "连接数已达上限，请稍后重连") from None
    return conn


async def _on_client_frame(conn: Connection, raw: str) -> None:
    """C→S 帧：pong（活跃时间已在循环更新）/ write；其余忽略（P0 无订阅帧）。"""
    try:
        frame = json.loads(raw)
    except ValueError:
        return
    if not isinstance(frame, dict):
        return
    if frame.get("type") == "write":
        await _handle_write(conn, frame)
    # 其余帧类型忽略


async def _handle_write(conn: Connection, frame: dict) -> None:
    """write → writeAck 全 code 路径（契约 §5）。成功写透后值随下一帧 values 广播。"""
    req_id = str(frame.get("reqId", ""))
    variable_key = frame.get("variableKey")
    value = frame.get("value")

    async def ack(ok: bool, code: str | None = None, message: str | None = None) -> None:
        payload: dict = {"type": "writeAck", "reqId": req_id, "ok": ok}
        if code is not None:
            payload["code"] = code
            payload["message"] = message
        await manager.send_to(conn, payload)

    # 分享 token 连接一律只读（03 §3.4）
    if conn.kind == "share":
        await ack(False, "READ_ONLY", "分享链接为只读，不允许反控")
        return
    # 角色门槛：operator/admin（viewer 只读）
    if conn.role not in ("operator", "admin"):
        await ack(False, "FORBIDDEN", "viewer 角色不允许反控写入")
        return
    if not isinstance(value, (bool, int, float, str)):
        await ack(False, "WRITE_FAILED", "写入值类型非法（仅允许 number/boolean/string）")
        return

    from app.services import collector as collector_mod
    from app.services import hub as hub_mod

    var = hub_mod.hub.variable(conn.project_id, str(variable_key or ""))
    if var is None:
        await ack(False, "VARIABLE_NOT_FOUND", f"变量 {variable_key} 不存在")
        return
    if var.expr:
        await ack(False, "NOT_WRITABLE", f"虚拟变量 {var.key} 不可写（由表达式驱动）")
        return
    if not var.writable:
        await ack(False, "NOT_WRITABLE", f"变量 {var.key} 未开启可写（writable）")
        return

    try:
        await collector_mod.collector.write(conn.project_id, var, value)
    except Exception as exc:  # noqa: BLE001 - 通道失败不中断连接
        await ack(False, "WRITE_FAILED", str(exc) or type(exc).__name__)
        return

    await ack(True)
    await _audit_write(conn, var.key, value)


async def _audit_write(conn: Connection, variable_key: str, value: object) -> None:
    """write_var 审计：audit_service（C 包）缺席时静默跳过；审计失败不阻断写路径。"""
    try:
        from app.db.base import SessionLocal  # noqa: PLC0415
        from app.db.models import User  # noqa: PLC0415
        from app.services import audit_service  # noqa: PLC0415 - 跨包惰性 import
    except Exception:  # noqa: BLE001 - C 未合入的中间态
        return
    try:
        async with SessionLocal() as db:
            user = await db.get(User, conn.user_id) if conn.user_id else None
        await audit_service.audit(
            None, user, "write_var", "variable", variable_key,
            detail={"projectId": str(conn.project_id), "value": value},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"write_var 审计失败（忽略）：{type(exc).__name__} {exc}")


@router.websocket("/ws/runtime")
async def ws_runtime(
    websocket: WebSocket,
    project: str = Query(default=""),
    token: str = Query(default=""),
    page: str = Query(default=""),
) -> None:
    await websocket.accept()
    try:
        conn = await _handshake(websocket, project, token, page)
    except _HandshakeError as exc:
        try:
            await websocket.send_text(json.dumps({"type": "error", "code": exc.code, "message": exc.message}, ensure_ascii=False))
            await websocket.close(code=4000)
        except Exception:  # noqa: BLE001
            pass
        return

    logger.debug(f"ws 连接建立 project={conn.project_id} kind={conn.kind} user={conn.username}")
    try:
        # 立即推 snapshot（内嵌 activeAlarms；B 缺席时降级空列表）
        await manager.send_to(conn, await manager.build_snapshot(conn.project_id))
        while True:
            raw = await websocket.receive_text()
            conn.last_recv = now_monotonic()
            await _on_client_frame(conn, raw)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - 网络级异常按断开处理
        logger.debug(f"ws 连接异常断开 project={conn.project_id}")
    finally:
        await manager.unregister(conn)
        logger.debug(f"ws 连接关闭 project={conn.project_id} kind={conn.kind}")
