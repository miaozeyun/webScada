"""服务端报警判定引擎（M8，契约 §6.2；迟滞与持续窗逐条实现 02 §2.11 恢复判定表）。

判定规则（q != 'good' 不判定；boolean 以 1/0 参与；string 值跳过——doc 校验已禁 string 规则）：
- 未激活：满足触发条件 → 记录连续满足起点 since；持续满足 durationMs（0/缺省=立即）才触发；
  中途不满足即重置 since（迟滞回差带内的值不满足触发条件，同样重置）
- 已激活：仅越过回差带反向区间才恢复（`>`: v ≤ th−H；`>=`: v < th−H；
  `<`: v ≥ th+H；`<=`: v > th+H；`==`/`!=`: 反向判定即恢复，H 不适用）

规则来源与新鲜度（契约未指定 doc 同步机制，本实现自治并已记入 deviations）：
- sync(project_id, doc) 直灌（background_jobs 启动全量预载 / 测试直灌）
- 值事件路径按 RULES_TTL_SEC 周期后台刷新（读 projects.doc），工程保存后 ≤TTL 生效；
  未加载过的工程首个事件也会触发一次刷新（下个事件生效）

并发与调用约定：on_value 为同步函数（与 historian.push 同约定，兼容 hub 以同步或
isawaitable 两种方式调用）；入库/广播/通知等异步后续经 loop.create_task 派发，
per-(project, rule) asyncio.Lock 串行化；任务内按 spawn 时刻的状态对象同一性复核
（拦截规则重载/删除换代后的陈旧任务），翻转序列逐条落库不丢帧。
"""
import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app.db.models import Project

# 规则缓存后台刷新周期（秒）：工程保存后规则生效的最大延迟
RULES_TTL_SEC = 5.0

# 会话工厂注入点（与 audit_service 同款测试缝）：None 时惰性取 app.db.base.SessionLocal
session_factory = None


def _get_session_factory():
    if session_factory is not None:
        return session_factory
    from app.db.base import SessionLocal  # 惰性：避免导入期连库副作用

    return SessionLocal


@dataclass
class _RuleEntry:
    """已解析规则（doc AlarmRule + 作用变量快照字段，02 §2.11 结构）。"""

    rule_id: str
    variable_id: str
    op: str
    threshold: float
    level: str
    message: str
    hysteresis: float
    duration_ms: float
    var_key: str
    var_label: str
    var_precision: float | None


@dataclass
class _RuleState:
    active: bool = False
    since: float | None = None  # 触发条件连续满足起点（epoch 秒）


def _to_number(value) -> float | None:
    """boolean→1/0；有限数值→float；其余（string/None/NaN/Inf）→ None 不判定。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    return None


def _ts_to_epoch_sec(ts) -> float:
    """epoch 毫秒（≥1e11，hub/WS 口径）/ epoch 秒 / datetime → epoch 秒。"""
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    n = float(ts)
    return n / 1000.0 if n >= 1e11 else n


def _epoch_sec_to_dt(sec: float) -> datetime:
    return datetime.fromtimestamp(sec, tz=timezone.utc)


def _fmt_num(n: float, precision: float | None) -> str:
    """展示值：与前端 fmtNum 同口径（precision 缺省 2 位小数）。"""
    p = 2 if precision is None else max(0, int(precision))
    return f"{n:.{p}f}"


def _trigger_pred(e: _RuleEntry, v: float) -> bool:
    t = e.threshold
    if e.op == ">":
        return v > t
    if e.op == ">=":
        return v >= t
    if e.op == "<":
        return v < t
    if e.op == "<=":
        return v <= t
    if e.op == "==":
        return v == t
    if e.op == "!=":
        return v != t
    return False


def _recover_pred(e: _RuleEntry, v: float) -> bool:
    """恢复判定（02 §2.11 表格逐条；hysteresis=H，等值规则反向判定、H 不适用）。"""
    H = e.hysteresis
    t = e.threshold
    if e.op == ">":
        return v <= t - H
    if e.op == ">=":
        return v < t - H
    if e.op == "<":
        return v >= t + H
    if e.op == "<=":
        return v > t + H
    if e.op == "==":
        return v != t
    if e.op == "!=":
        return v == t
    return False


class RulesEngine:
    """服务端 7x24 报警判定（内存态；单实例进程口径）。"""

    def __init__(self) -> None:
        self._entries: dict[str, list[_RuleEntry]] = {}
        self._states: dict[tuple[str, str], _RuleState] = {}
        self._loaded_at: dict[str, float] = {}
        self._refreshing: set[str] = set()
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        # 已观察到非 good 质量的变量（(project_id, variable_id)）：坏质量收口只做一次，
        # 恢复 good 时移除。避免 stale 帧高频重复派发 clear 任务。
        self._bad_vars: set[tuple[str, str]] = set()

    # ---------------- 规则注册表 ----------------

    def sync(self, project_id, doc: dict) -> int:
        """灌入/刷新工程规则集（返回启用规则数）。doc 为 ProjectDoc dict（容错非 dict）。"""
        pid = str(project_id)
        doc = doc if isinstance(doc, dict) else {}
        variables = {v.get("id"): v for v in (doc.get("variables") or []) if isinstance(v, dict)}
        entries: list[_RuleEntry] = []
        for r in doc.get("alarmRules") or []:
            if not isinstance(r, dict) or not r.get("enabled", True):
                continue
            var = variables.get(r.get("variableId"))
            if var is None or not r.get("id"):
                continue
            try:
                threshold = float(r.get("threshold", 0))
                hysteresis = float(r.get("hysteresis") or 0)
                duration_ms = float(r.get("durationMs") or 0)
            except (TypeError, ValueError):
                logger.warning("报警规则 {} 阈值/回差非法，跳过", r.get("id"))
                continue
            entries.append(
                _RuleEntry(
                    rule_id=str(r["id"]),
                    variable_id=str(r.get("variableId")),
                    op=str(r.get("op", ">")),
                    threshold=threshold,
                    level=str(r.get("level", "warn")),
                    message=str(r.get("message", "")),
                    hysteresis=hysteresis,
                    duration_ms=duration_ms,
                    var_key=str(var.get("key", "")),
                    var_label=str(var.get("label", "")),
                    var_precision=var.get("precision"),
                )
            )
        self._entries[pid] = entries
        self._loaded_at[pid] = time.monotonic()
        # 已消失规则的内存态一并清理（规则删除/改 id 不残留旧状态）
        live = {(pid, e.rule_id) for e in entries}
        for key in [k for k in self._states if k[0] == pid and k not in live]:
            self._states.pop(key, None)
        return len(entries)

    def remove(self, project_id) -> None:
        pid = str(project_id)
        self._entries.pop(pid, None)
        self._loaded_at.pop(pid, None)
        for key in [k for k in self._states if k[0] == pid]:
            self._states.pop(key, None)

    def attach(self, hub) -> bool:
        """注册值监听（契约 §6.2）；hub 缺 add_value_listener（A 未合入）返回 False。"""
        add = getattr(hub, "add_value_listener", None)
        if not callable(add):
            return False
        add(self.on_value)
        return True

    async def reload_project(self, project_id) -> int:
        """从库内 doc 刷新单工程规则（TTL 后台刷新用；工程不存在则清空注册）。"""
        try:
            pid = uuid.UUID(str(project_id))
        except ValueError:
            return 0
        async with _get_session_factory()() as db:
            row = await db.get(Project, pid)
        if row is None:
            self.remove(project_id)
            return 0
        return self.sync(str(pid), row.doc if isinstance(row.doc, dict) else {})

    async def reload_all(self) -> int:
        """启动预载：全部工程规则一次灌入（background_jobs.startup 调用）。"""
        async with _get_session_factory()() as db:
            rows = (await db.execute(select(Project.id, Project.doc))).all()
        total = 0
        for pid, doc in rows:
            total += self.sync(str(pid), doc)
        return total

    # ---------------- 值监听入口（同步；契约监听器签名） ----------------

    def on_value(self, project_id, variable, value, q, ts) -> None:
        pid = str(project_id)
        var_id = self._var_field(variable, "id")
        var_id = str(var_id) if var_id is not None else ""
        entries = self._entries.get(pid)
        # 缓存缺席/过期 → 后台刷新（本事件按现有缓存判定，下个事件起生效）
        if entries is None or time.monotonic() - self._loaded_at.get(pid, -1e18) > RULES_TTL_SEC:
            self._schedule_refresh(pid)
        if q != "good":
            # 设备断线/停更时质量转 stale/bad：该变量的活动工艺报警必须收口，
            # 否则会永远挂在「触发中」，值班员看到一条永远不恢复的报警。
            if var_id:
                self._on_bad_quality(pid, var_id, ts)
            return
        if var_id:
            self._bad_vars.discard((pid, var_id))
        if not entries:
            return
        ts_sec = _ts_to_epoch_sec(ts)
        for e in entries:
            if e.variable_id != var_id:
                continue
            num = _to_number(value)
            if num is None:
                continue
            self._eval_rule(pid, e, num, ts_sec)

    def _on_bad_quality(self, pid: str, var_id: str, ts) -> None:
        """质量非 good：把该变量所有活动规则置为恢复（派发 clear 任务，入库+广播）。

        用 _bad_vars 去重：stale 帧可能每秒到达，但收口只做一次；值恢复 good 后
        重新允许下一次断线收口。规则缓存缺席时先触发刷新，下个坏质量帧再收口。
        """
        key = (pid, var_id)
        if key in self._bad_vars:
            return
        self._bad_vars.add(key)
        entries = self._entries.get(pid) or []
        if not entries:
            self._schedule_refresh(pid)
            return
        ts_sec = _ts_to_epoch_sec(ts)
        for e in entries:
            if e.variable_id != var_id:
                continue
            st = self._states.get((pid, e.rule_id))
            if st is None or not st.active:
                continue
            st.active = False
            st.since = None
            logger.info("质量非 good 收口：project={} rule={} variable={}", pid, e.rule_id, var_id)
            self._spawn_state_task(pid, e, "clear", 0.0, ts_sec, st)

    @staticmethod
    def _var_field(variable, name: str):
        if isinstance(variable, dict):
            return variable.get(name)
        return getattr(variable, name, None)

    def _schedule_refresh(self, pid: str) -> None:
        if pid in self._refreshing:
            return
        self._refreshing.add(pid)
        task = self._spawn(self._refresh(pid))
        if task is not None:
            task.add_done_callback(lambda _t, p=pid: self._refreshing.discard(p))
        else:
            self._refreshing.discard(pid)

    async def _refresh(self, pid: str) -> None:
        try:
            await self.reload_project(pid)
        except Exception as exc:
            logger.warning("报警规则后台刷新失败（project={}）：{}", pid, exc)
            self._loaded_at[pid] = time.monotonic()  # 防失败后每事件重试风暴

    # ---------------- 判定状态机 ----------------

    def _eval_rule(self, pid: str, e: _RuleEntry, v: float, ts_sec: float) -> None:
        st = self._states.setdefault((pid, e.rule_id), _RuleState())
        if st.active:
            if _recover_pred(e, v):
                st.active = False
                st.since = None
                self._spawn_state_task(pid, e, "clear", v, ts_sec, st)
            return
        if not _trigger_pred(e, v):
            st.since = None  # 触发条件不再连续满足 → 重置持续窗
            return
        if st.since is None:
            st.since = ts_sec
        if e.duration_ms <= 0 or (ts_sec - st.since) * 1000.0 >= e.duration_ms:
            st.active = True
            st.since = None
            self._spawn_state_task(pid, e, "trigger", v, ts_sec, st)

    def _spawn_state_task(self, pid: str, e: _RuleEntry, kind: str, v: float, ts_sec: float, st: _RuleState) -> None:
        self._spawn(self._apply_state(pid, e, kind, v, ts_sec, st))

    async def _apply_state(self, pid: str, e: _RuleEntry, kind: str, v: float, ts_sec: float, st: _RuleState) -> None:
        """入库派发（自建短会话；per-rule 锁串行化）。

        复核用「spawn 时刻的状态对象同一性」而非 current active：每次翻转各自派发
        任务且按 spawn 序持锁，落库语义即翻转序列本身；若比对 current，快速
        「触发→恢复→再触发」序列会吞掉中间的 clear（首行滞留 triggered、恢复帧
        丢失、再触发被幂等并入首行）。同一性仅拦截 sync/remove 换代后的陈旧任务。
        """
        lock = self._locks.setdefault((pid, e.rule_id), asyncio.Lock())
        async with lock:
            if self._states.get((pid, e.rule_id)) is not st:
                return  # 规则重载/删除已换代 → 陈旧任务放弃
            from app.services import alarm_service  # 同包，惰性防 import 环

            at = _epoch_sec_to_dt(ts_sec)
            async with _get_session_factory()() as db:
                if kind == "trigger":
                    snapshot = {
                        "id": e.rule_id,
                        "variableKey": e.var_key,
                        "level": e.level,
                        "message": self._format_message(e, v),
                    }
                    await alarm_service.trigger(db, pid, snapshot, _fmt_num(v, e.var_precision), at)
                else:
                    await alarm_service.clear(db, pid, e.rule_id, at)

    def _format_message(self, e: _RuleEntry, v: float) -> str:
        """占位符与前端 formatMessage 同口径：{key} {label} {value} {threshold}（值为工程值）。"""
        text = e.message or f"{e.var_label} 报警"
        return (
            text.replace("{key}", e.var_key)
            .replace("{label}", e.var_label)
            .replace("{value}", _fmt_num(v, e.var_precision))
            .replace("{threshold}", _fmt_num(e.threshold, e.var_precision))
        )

    def _spawn(self, coro) -> asyncio.Task | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("无事件循环，报警判定派发放弃")
            return None
        task = loop.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task


# 模块级单例（background_jobs 挂载 / A 包 snapshot 查询共用）
_engine = RulesEngine()


def get_engine() -> RulesEngine:
    return _engine
