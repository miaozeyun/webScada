"""历史区间查询（M8，契约 §4.2 / 03 §2.10）：JWT 任意角色或分享 token 双通道。

- stepMs>0：服务端窗口聚合降采样，agg 缺省 mean，可选 min/max/last/sum（阶段二 Task 1）；
  点数仍超 maxPoints 时自动增大步长（强制聚合路径同样按所选 agg）
- stepMs=0：原始采样点；超 maxPoints 等距抽稀（保真采样值，不造数）
- 行数上限：逐 key 最多拉取 HISTORY_MAX_ROWS_PER_KEY 行（终审 #2），触顶且原始模式时
  自动提升 stepMs 强制聚合（防分享 token 免登录通道全窗加载 OOM DoS）
- 分享 token：`Authorization: Bearer <shareToken>` 形态，服务端识别 token 类型
  （JWT 解析失败即落分享通道；revoked/expired 403、跨工程 403）
- CSV 导出（阶段二 Task 2）：GET .../history/export 单 key 原始行流式写出（keyset 分页迭代，
  不整载、不设行数上限）；from/to 必填（epoch 毫秒）且跨度 ≤30 天；限流同 REST_HISTORY_PER_MIN
"""
import re
import uuid as uuidlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.base import get_db
from app.db.models import HistoryValue, ShareLink, User
from app.schemas.history import HistoryResponse
from app.services import project_service

router = APIRouter(tags=["history"])
_bearer = HTTPBearer(auto_error=False)

MAX_KEYS = 20

# CSV 导出（阶段二 Task 2）：keyset 分页页大小——每轮最多取 5000 原始行，循环至空/短页（防整载 OOM）
_EXPORT_PAGE = 5000
# 导出跨度上限（天）：与查询侧 HISTORY_RETENTION_DAYS 口径独立（导出无行数上限，靠跨度封顶单次成本）
_EXPORT_MAX_SPAN_DAYS = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ts_ms(dt: datetime) -> int:
    """epoch 毫秒；SQLite 方言读回 naive datetime 时按 UTC 口径（生产 PG 返回 aware）。"""
    return int(_aware(dt).timestamp() * 1000)


async def _resolve_share_token(db: AsyncSession, token: str, project_id) -> None:
    share = (await db.execute(select(ShareLink).where(ShareLink.token == token))).scalars().first()
    if share is None:
        raise AppError("UNAUTHORIZED", "无效的访问凭证", 401)
    if share.revoked_at is not None:
        raise AppError("SHARE_REVOKED", "分享链接已撤销", 403)
    if share.expires_at is not None and _aware(share.expires_at) < datetime.now(timezone.utc):
        raise AppError("SHARE_EXPIRED", "分享链接已过期", 403)
    if share.project_id != project_id:
        raise AppError("FORBIDDEN", "分享链接与目标工程不匹配", 403)


async def _resolve_viewer(db: AsyncSession, creds: HTTPAuthorizationCredentials | None, project_id) -> None:
    """双通道鉴权：合法 JWT（任意角色）直通；否则按分享 token 校验（契约 §4.2）。"""
    if creds is None:
        raise AppError("UNAUTHORIZED", "未登录或缺少凭证", 401)
    token = creds.credentials
    try:
        payload = decode_access_token(token)
        user = await db.get(User, uuidlib.UUID(payload["sub"]))
        if user is not None:
            return
    except AppError:
        pass  # JWT 无效/过期 → 落分享 token 通道
    except (KeyError, ValueError):
        pass
    await _resolve_share_token(db, token, project_id)


def _bucket_agg(pts: list[tuple[int, float]], from_ms: int, step_ms: int, agg: str) -> list[list[float]]:
    """窗口聚合（单点实现，阶段二 Task 1 泛化自 _bucket_mean）：桶内一次累积 count/sum/min/max/last，按 agg 取值。

    pts 须按 ts 升序（last=窗口内最后一个点依赖此序：升序输入下最后写入桶的即窗口末点）。
    """
    acc: dict[int, list[float]] = {}  # 桶起点 → [count, sum, min, max, last]
    for t, v in pts:
        b = from_ms + ((t - from_ms) // step_ms) * step_ms
        c = acc.get(b)
        if c is None:
            acc[b] = [1.0, v, v, v, v]
        else:
            c[0] += 1
            c[1] += v
            if v < c[2]:
                c[2] = v
            if v > c[3]:
                c[3] = v
            c[4] = v

    def _pick(c: list[float]) -> float:
        if agg == "mean":
            return c[1] / c[0]
        if agg == "min":
            return c[2]
        if agg == "max":
            return c[3]
        if agg == "sum":
            return c[1]
        return c[4]  # last

    return [[float(b), _pick(acc[b])] for b in sorted(acc)]


def _build_series(rows, from_ms: int, step_ms: int, max_points: int, agg: str = "mean") -> list[list[float]]:
    pts = [(_ts_ms(ts), float(v)) for ts, v in rows]
    if step_ms > 0:
        step = step_ms
        out = _bucket_agg(pts, from_ms, step, agg)
        while len(out) > max_points:  # 03 §2.10：超出自动增大 stepMs
            step *= max(2, -(-len(out) // max_points))
            out = _bucket_agg(pts, from_ms, step, agg)
        return out
    if len(pts) <= max_points:
        return [[float(t), v] for t, v in pts]
    stride = -(-len(pts) // max_points)  # 等距抽稀： ceil(len/max) 为步长取样
    return [[float(t), v] for i, (t, v) in enumerate(pts) if i % stride == 0]


@router.get("/projects/{project_id}/history", response_model=HistoryResponse)
async def query_history(
    project_id: str,
    keys: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    stepMs: int = Query(default=0, ge=0),
    maxPoints: int = Query(default=2000, ge=1, le=10000),
    agg: str = Query(default="mean", pattern="^(mean|min|max|last|sum)$"),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    project = await project_service.get_project(db, project_id)
    await _resolve_viewer(db, creds, project.id)

    key_list = [k.strip() for k in keys.split(",") if k.strip()] if keys else None
    if key_list is not None and len(key_list) > MAX_KEYS:
        raise AppError("validation_error", f"keys 最多 {MAX_KEYS} 个", 422)

    to_dt = _aware(to) if to else datetime.now(timezone.utc)
    from_dt = _aware(from_) if from_ else to_dt - timedelta(days=settings.HISTORY_RETENTION_DAYS)
    if from_dt >= to_dt:
        raise AppError("validation_error", "from 必须早于 to", 422)
    if to_dt - from_dt > timedelta(days=settings.HISTORY_RETENTION_DAYS):
        raise AppError("validation_error", f"查询跨度不能超过 {settings.HISTORY_RETENTION_DAYS} 天", 422)

    if key_list is None:  # 03 §2.10：keys 缺省=全工程变量（区间内有数据的全部 key）
        key_list = list(
            (
                await db.execute(
                    select(HistoryValue.variable_key)
                    .where(
                        HistoryValue.project_id == project.id,
                        HistoryValue.ts >= from_dt,
                        HistoryValue.ts <= to_dt,
                    )
                    .distinct()
                )
            ).scalars()
        )

    from_ms = int(from_dt.timestamp() * 1000)
    to_ms = int(to_dt.timestamp() * 1000)
    # 终审 #2：逐 key 行数硬上限——分享 token 免登录，缺省全 key + 全窗加载可被构造 OOM DoS
    cap = settings.HISTORY_MAX_ROWS_PER_KEY
    # 触顶时原始模式的强制聚合步长：窗口跨度 / maxPoints 向上取整（保证聚合后点数 ≤ maxPoints）
    forced_step = max(1, -(-(to_ms - from_ms) // maxPoints))
    series: dict[str, list[list[float]]] = {}
    for key in key_list:
        # 先倒序限量取最新 cap 行，再回正升序（窗口超限时保留近期数据）
        rows = list(
            (
                await db.execute(
                    select(HistoryValue.ts, HistoryValue.value)
                    .where(
                        HistoryValue.project_id == project.id,
                        HistoryValue.variable_key == key,
                        HistoryValue.ts >= from_dt,
                        HistoryValue.ts <= to_dt,
                    )
                    .order_by(HistoryValue.ts.desc())
                    .limit(cap)
                )
            ).all()
        )
        rows.reverse()
        step_ms = stepMs
        if step_ms <= 0 and len(rows) >= cap:
            # 行数触顶且为原始模式：自动提升 stepMs 强制聚合，不给 422 保可用性
            step_ms = forced_step
        series[key] = _build_series(rows, from_ms, step_ms, maxPoints, agg)
    return HistoryResponse(series=series)


def _safe_filename(s: str) -> str:
    """文件名安全化：非 [A-Za-z0-9._-] 一律下划线（Content-Disposition 头须 ASCII，变量 key 可能含中文/斜杠）。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


@router.get("/projects/{project_id}/history/export")
async def export_history_csv(
    project_id: str,
    key: str = Query(...),
    from_: int = Query(..., alias="from", description="起始 epoch 毫秒（含）"),
    to: int = Query(..., description="截止 epoch 毫秒（含）"),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """单变量原始行 CSV 流式导出（阶段二 Task 2）。

    - 独立于查询端点：不复用行数上限（HISTORY_MAX_ROWS_PER_KEY）/聚合降采样，
      keyset 分页（ts > last_ts ORDER BY ts ASC LIMIT _EXPORT_PAGE）循环迭代原始行逐块写出，
      全程单批驻内存（30 天 5s 采样 ≈ 51.8 万行不整载）
    - 列头 ts,value：ts ISO8601 UTC、升序；value 原样（存库工程值，不做任何换算/聚合）
    - from/to 必填（epoch 毫秒）、跨度 ≤30 天；鉴权与查询端点同口径（JWT/分享 token 双通道）；
      限流与 .../history 同额共用 REST_HISTORY_PER_MIN（core/rate_limit 后缀规则 /history/export）
    """
    project = await project_service.get_project(db, project_id)
    await _resolve_viewer(db, creds, project.id)

    if from_ >= to:
        raise AppError("validation_error", "from 必须早于 to", 422)
    if to - from_ > _EXPORT_MAX_SPAN_DAYS * 86_400_000:
        raise AppError("validation_error", f"导出跨度不能超过 {_EXPORT_MAX_SPAN_DAYS} 天", 422)

    from_dt = datetime.fromtimestamp(from_ / 1000, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to / 1000, tz=timezone.utc)

    async def _rows() -> AsyncIterator[str]:
        yield "ts,value\n"
        last_ts: datetime | None = None
        while True:
            # keyset 游标：首轮 ts >= from，后续 ts > last_ts（升序稳定翻页，杜绝 offset 深翻页）
            where_ts = HistoryValue.ts > last_ts if last_ts is not None else HistoryValue.ts >= from_dt
            batch = (
                await db.execute(
                    select(HistoryValue.ts, HistoryValue.value)
                    .where(
                        HistoryValue.project_id == project.id,
                        HistoryValue.variable_key == key,
                        where_ts,
                        HistoryValue.ts <= to_dt,
                    )
                    .order_by(HistoryValue.ts.asc())
                    .limit(_EXPORT_PAGE)
                )
            ).all()
            if not batch:
                break  # 空页即终页
            for ts, v in batch:
                yield f"{_aware(ts).isoformat()},{v!r}\n"
            if len(batch) < _EXPORT_PAGE:
                break  # 短页即末页（免一次空查询）
            last_ts = batch[-1].ts

    filename = f"history_{_safe_filename(key)}_{from_}_{to}.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
