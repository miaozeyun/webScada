"""WSManager：/api/v1/ws/runtime 连接注册表与帧调度（M8 工作包 A）。

帧协议权威：docs/design/03-接口清单 §3 + 实施契约 §5：
- 100ms 合帧 + 变化抑制 → values 帧（hub 侧已做抑制，此处再按 key 去重合并）
- 20s ping / 40s 无入站判死 close(4000)
- snapshot 组装：hub 值池 + activeAlarms（惰性 import alarm_service，B 未合入/缺席时降级空列表）
- broadcast_alarm / broadcast_alarm_clear / broadcast_alarm_ack（B 调用）
- broadcast_reload(token) / close_share_token(token, code, message)（C 的 shares 调用，终审 #3）
- broadcast_project_removed（A 的 project_service 调用）

单实例口径（契约 §11.3）：心跳/并发计数/合帧均为进程内实现。
发送带 per-conn 超时（SEND_TIMEOUT_SEC）：超时/失败即摘除，单个停滞客户端不得拖停广播。
"""
import asyncio
import json
import time
import uuid as uuidlib
from typing import Any

from fastapi import WebSocket
from loguru import logger

from app.core import stats
from app.core.config import settings

# 心跳参数（模块级常量：测试可 monkeypatch 缩短）
PING_INTERVAL_SEC = 20.0
DEAD_AFTER_SEC = 40.0
# 单帧发送超时（秒）：对端停滞（停止收取、发送缓冲写满）时 send 可能永不返回，
# 不设超时会拖停该工程广播乃至心跳/合帧循环——超时即放弃，交由调用方摘除连接
SEND_TIMEOUT_SEC = 10.0
# 快照报警截断（03 §3.4：≤200 条，critical>warn>info 优先保留）
SNAPSHOT_ALARM_LIMIT = 200
_LEVEL_RANK = {"critical": 0, "warn": 1, "info": 2}


def _now() -> float:
    return time.monotonic()


def now_monotonic() -> float:
    """供 ws.py 更新连接活跃时间（同一时钟源）。"""
    return time.monotonic()


def _now_ms() -> int:
    return int(time.time() * 1000)


class QuotaExceeded(Exception):
    """register 时配额复核未通过（code 见 _quota_error，调用方转 error 帧）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Connection:
    """单条运行态 WS 连接。kind='jwt'（编辑器/大屏，可按角色写）| 'share'（分享，只读）。"""

    def __init__(
        self,
        ws: WebSocket,
        project_id: uuidlib.UUID,
        kind: str,
        token: str,
        *,
        user_id: uuidlib.UUID | None = None,
        username: str = "",
        role: str = "viewer",
        page: str = "",
        send_timeout: float | None = None,
    ) -> None:
        self.ws = ws
        self.project_id = project_id
        self.kind = kind
        self.token = token
        self.user_id = user_id
        self.username = username
        self.role = role
        self.page = page
        self.lock = asyncio.Lock()
        self.send_timeout = SEND_TIMEOUT_SEC if send_timeout is None else send_timeout
        self.last_recv = _now()

    async def send_json(self, frame: dict) -> bool:
        """串行化发送；超时/失败即视为连接死亡（由调用方摘除）。返回是否成功。

        per-conn 超时：单个停滞客户端不允许无限占住锁，把同工程广播、心跳与
        合帧循环一并拖到停摆——超时放弃本次发送并交由调用方摘除该连接。
        """
        try:
            async with self.lock:
                await asyncio.wait_for(
                    self.ws.send_text(json.dumps(frame, ensure_ascii=False, separators=(",", ":"))),
                    timeout=self.send_timeout,
                )
            stats.inc(f"ws_frames_{frame.get('type', 'unknown')}_total")
            return True
        except Exception:  # noqa: BLE001 - 网络断开/已关闭/发送超时（停滞连接）
            return False


class WSManager:
    def __init__(self) -> None:
        # project_id -> 连接列表
        self._conns: dict[uuidlib.UUID, list[Connection]] = {}
        self._reg_lock = asyncio.Lock()  # 注册双检临界区（quota 检查 + append 原子化）
        # project_id -> {key: entry} 待下发变化（100ms 合帧窗口内同 key 后到覆盖先到）
        self._dirty: dict[uuidlib.UUID, dict[str, dict[str, Any]]] = {}
        self._tasks: list[asyncio.Task] = []
        self._started = False

    # ---- 生命周期 ----

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._tasks.append(asyncio.create_task(self._coalesce_loop()))
        self._tasks.append(asyncio.create_task(self._ping_loop()))
        logger.info("ws_manager 已启动（合帧 {}ms / ping {}s）", settings.WS_FRAME_COALESCE_MS, PING_INTERVAL_SEC)

    async def stop(self) -> None:
        self._started = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        # 全量断开
        for conns in list(self._conns.values()):
            for conn in conns:
                await self._close(conn, code=1001)
        self._conns.clear()
        self._dirty.clear()

    # ---- 并发计数（契约 §4.6）----

    def total_count(self) -> int:
        return sum(len(v) for v in self._conns.values())

    def count_for_token(self, token: str) -> int:
        return sum(1 for conns in self._conns.values() for c in conns if c.token == token)

    def count_for_user_project(self, user_id: uuidlib.UUID, project_id: uuidlib.UUID) -> int:
        return sum(1 for c in self._conns.get(project_id, []) if c.kind == "jwt" and c.user_id == user_id)

    # ---- 注册 / 摘除 ----

    def _quota_error(self, conn: Connection) -> str | None:
        """按连接类型复核配额（终审 minor：防 check-then-act 跨 await 突破上限）。"""
        if self.total_count() >= settings.WS_MAX_CONNECTIONS:
            return "RATE_LIMITED"
        if conn.kind == "share":
            if self.count_for_token(conn.token) >= settings.SHARE_MAX_WS_PER_TOKEN:
                return "RATE_LIMITED"
        elif self.count_for_user_project(conn.user_id, conn.project_id) >= settings.JWT_WS_MAX_PER_USER_PROJECT:
            return "RATE_LIMITED"
        return None

    async def register(self, conn: Connection) -> None:
        # 双检持锁：_handshake 的预检查到此处之间有 await 窗口，突发重连可短暂超限
        async with self._reg_lock:
            err = self._quota_error(conn)
            if err is not None:
                raise QuotaExceeded(err)
            self._conns.setdefault(conn.project_id, []).append(conn)
            stats.set_gauge("ws_connections", float(self.total_count()))

    async def unregister(self, conn: Connection) -> None:
        conns = self._conns.get(conn.project_id, [])
        if conn in conns:
            conns.remove(conn)
        if not conns:
            self._conns.pop(conn.project_id, None)
        stats.set_gauge("ws_connections", float(self.total_count()))

    # ---- 契约 §6.1 别名（connect/ws_close；实现即注册/摘除 + 关闭） ----

    async def connect(self, conn: Connection) -> None:
        await self.register(conn)

    async def ws_close(self, conn: Connection, code: int = 4000) -> None:
        await self.unregister(conn)
        await self._close(conn, code=code)

    # ---- 发送原语 ----

    async def send_to(self, conn: Connection, frame: dict) -> bool:
        ok = await conn.send_json(frame)
        if not ok:
            await self.unregister(conn)
        return ok

    async def _broadcast_project(self, project_id: uuidlib.UUID, frame: dict) -> None:
        for conn in list(self._conns.get(project_id, [])):
            await self.send_to(conn, frame)

    async def _close(self, conn: Connection, code: int = 4000) -> None:
        try:
            await conn.ws.close(code=code)
        except Exception:  # noqa: BLE001
            pass

    async def send_error_and_close(self, conn: Connection, code: str, message: str) -> None:
        """error 即时帧 + close(4000)（03 §3.3：原因只看帧 code）。PROJECT_MISMATCH 不在此列（不关连接）。"""
        await conn.send_json({"type": "error", "code": code, "message": message})
        await self.unregister(conn)
        await self._close(conn)

    # ---- 值帧（100ms 合帧 + 变化抑制）----

    def mark_dirty(self, project_id: uuidlib.UUID, key: str, entry: dict[str, Any]) -> None:
        """hub 值变化入口（v 或 q 变化才被调用）。窗口内同 key 以最新为准。"""
        self._dirty.setdefault(project_id, {})[key] = entry

    async def _coalesce_loop(self) -> None:
        while True:
            interval_ms = settings.WS_FRAME_COALESCE_MS  # 每轮读取：测试可缩窗
            await asyncio.sleep(max(interval_ms, 10) / 1000)
            if not self._dirty:
                continue
            pending, self._dirty = self._dirty, {}
            for project_id, data in pending.items():
                if data:
                    await self._broadcast_project(project_id, {"type": "values", "data": data})

    # ---- 心跳 ----

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_SEC)
            now = _now()
            for conns in list(self._conns.values()):
                for conn in list(conns):
                    if now - conn.last_recv > DEAD_AFTER_SEC:
                        # 判死：不发 error 帧（03 §3.5），客户端按网络级失败退避重连
                        await self.unregister(conn)
                        await self._close(conn)
                    elif not await conn.send_json({"type": "ping"}):
                        # 发送失败（含停滞超时）→ 摘除，防死连接常驻
                        await self.unregister(conn)

    # ---- snapshot 组装 ----

    async def build_snapshot(self, project_id: uuidlib.UUID) -> dict[str, Any]:
        """snapshot 帧：值池 + activeAlarms（≤200，critical>warn>info 截断置 truncated）。"""
        from app.services import hub as hub_mod

        data = hub_mod.hub.pool(project_id)
        alarms, total, truncated = await self._active_alarms(project_id)
        return {
            "type": "snapshot",
            "ts": _now_ms(),
            "data": data,
            "activeAlarms": alarms,
            "totalActive": total,
            "truncated": truncated,
        }

    async def _active_alarms(self, project_id: uuidlib.UUID) -> tuple[list[dict], int, bool]:
        """惰性 import alarm_service（B 包）：模块缺席/查询异常一律降级空列表（契约 §6.4/§5）。

        totalActive 口径：返回的展示条数；条数触顶时 truncated=True（客户端提示「还有更多」）。
        """
        try:  # 跨包惰性 import：B 未合入的中间态不致命
            from app.services import alarm_service  # noqa: PLC0415

            from app.db.base import SessionLocal  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return [], 0, False
        try:
            async with SessionLocal() as db:
                rows = await alarm_service.active_for_snapshot(db, project_id, limit=SNAPSHOT_ALARM_LIMIT)
        except Exception as exc:  # noqa: BLE001 - 表缺失（测试环境）等；debug 级防连接风暴刷屏
            logger.debug(f"snapshot activeAlarms 查询降级：{type(exc).__name__} {exc}")
            return [], 0, False
        rows = sorted(rows, key=lambda r: _LEVEL_RANK.get(str(r.get("level")), 3))  # 稳定排序：同级保持原序
        # active_for_snapshot 侧已按 limit 截断：len==limit 即视为「还有更多」（alarm_service 契约口径）
        truncated = len(rows) >= SNAPSHOT_ALARM_LIMIT
        return rows, len(rows), truncated

    # ---- B 包广播原语 ----

    async def broadcast_alarm(self, project_id: uuidlib.UUID, alarm: dict) -> None:
        await self._broadcast_project(project_id, {"type": "alarm", "alarm": alarm})

    async def broadcast_alarm_clear(self, project_id: uuidlib.UUID, alarm_id: int, recovered_at: int) -> None:
        await self._broadcast_project(
            project_id, {"type": "alarmClear", "alarmId": alarm_id, "recoveredAt": recovered_at}
        )

    async def broadcast_alarm_ack(self, project_id: uuidlib.UUID, alarm_id: int, acked_at: int, acked_by: str) -> None:
        await self._broadcast_project(
            project_id, {"type": "alarmAck", "alarmId": alarm_id, "ackedAt": acked_at, "ackedBy": acked_by}
        )

    # ---- C 包 / 本包钩子 ----

    async def broadcast_reload(self, token: str) -> None:
        """分享快照 refresh → 该 token 全部连接 reload（03 §3.4）。经 send_to：失败即摘除。"""
        for conns in list(self._conns.values()):
            for conn in list(conns):
                if conn.kind == "share" and conn.token == token:
                    await self.send_to(conn, {"type": "reload"})

    async def close_share_token(self, token: str, code: str, message: str) -> None:
        """分享撤销/过期 → 该 token 全部 share 连接 error 帧 + close(4000)（03 §2.6：撤权即时生效）。"""
        for conns in list(self._conns.values()):
            for conn in list(conns):
                if conn.kind == "share" and conn.token == token:
                    await self.send_error_and_close(conn, code, message)

    async def broadcast_project_removed(self, project_id: uuidlib.UUID) -> None:
        """工程 DELETE → 全部连接 error(PROJECT_REMOVED) + close(4000)。"""
        for conn in list(self._conns.get(project_id, [])):
            await self.send_error_and_close(conn, "PROJECT_REMOVED", "工程已删除，连接即将关闭")

    # ---- 测试辅助 ----

    async def reset(self) -> None:
        await self.stop()
        self._started = False


# 进程内单例（runtime_boot 挂 app.state；B/C 惰性 import 本模块取 manager）
manager = WSManager()


# ---- 模块级转发（契约 §6.1：广播原语为模块函数形态，B/C 包惰性 import 直接调用）----

async def broadcast_alarm(project_id: uuidlib.UUID, alarm: dict) -> None:
    await manager.broadcast_alarm(project_id, alarm)


async def broadcast_alarm_clear(project_id: uuidlib.UUID, alarm_id: int, recovered_at: int) -> None:
    await manager.broadcast_alarm_clear(project_id, alarm_id, recovered_at)


async def broadcast_alarm_ack(project_id: uuidlib.UUID, alarm_id: int, acked_at: int, acked_by: str) -> None:
    await manager.broadcast_alarm_ack(project_id, alarm_id, acked_at, acked_by)


async def broadcast_reload(token: str) -> None:
    await manager.broadcast_reload(token)


async def close_share_token(token: str, code: str, message: str) -> None:
    await manager.close_share_token(token, code, message)


async def broadcast_project_removed(project_id: uuidlib.UUID) -> None:
    await manager.broadcast_project_removed(project_id)
