"""hub：per-project 变量池（M8 工作包 A）。

职责（契约 §6.1 签名）：
- pool(project_id)：值池 {key: {v,q,t}}（v=工程值，q∈good|stale|bad，t=epoch 毫秒）
- set_doc/remove：doc 热更新（变量索引 + 虚拟变量拓扑重建 + stale 超时表）；键集裁剪时保留未删变量的现值
- ingest：collector 唯一入口 → convert 换算 → 变化判定 → 监听器（B: rules_engine/historian）→ mark_dirty
- 虚拟变量 expr 拓扑求值（Kahn 序 + BFS 前向传播，visited 集防环不死循环；求值失败回落上一值并 warn 一次）
- sweep_stale：超过 staleTimeoutMs 未见新帧 → q=good→stale（值保留），由 runtime_boot 定时驱动

变化抑制口径（03 §3.4）：v 与 q 均未变化 → 仅推进 t（新鲜度），不广播、不触发监听。
"""
import math
import time
import uuid as uuidlib
from collections import deque
from typing import Any, Callable

from loguru import logger

from app.schemas.doc import ProjectDoc, VariableDef
from app.services import convert
from app.services.convert import QUALITY_BAD, QUALITY_GOOD, QUALITY_STALE, EngineeringValue
from app.services.expr_eval import eval_expr, expr_idents

ValueListener = Callable[[uuidlib.UUID, VariableDef, "float | bool | str | None", str, int], None]

_EVAL_FAILED = object()  # 虚拟变量求值失败哨兵（区别于合法值 None）

# M9 批次4：内置秒节拍变量（key 以下划线开头，与用户变量命名空间隔离；标识符文法允许 _ 开头）。
# 虚拟变量 expr 引用 _tick 即获得每秒重算（对标业界主流组态「定时器脚本」的低风险等价物），仅 expr 可引用，不入变量绑定下拉。
TICK_KEY = "_tick"


def _tick_var() -> VariableDef:
    return VariableDef(id="builtin_tick", key=TICK_KEY, label="秒节拍（内置）", type="number", datasourceId="virtual")


def _now_ms() -> int:
    return int(time.time() * 1000)


class Hub:
    def __init__(self) -> None:
        # project_id -> {key: {"v": 工程值|None, "q": good|stale|bad, "t": epochMs}}
        self._pools: dict[uuidlib.UUID, dict[str, dict[str, Any]]] = {}
        # project_id -> {key: VariableDef}
        self._vars: dict[uuidlib.UUID, dict[str, VariableDef]] = {}
        # project_id -> {key: staleTimeoutMs}
        self._stale_ms: dict[uuidlib.UUID, dict[str, int]] = {}
        # project_id -> 虚拟变量 key 的 Kahn 拓扑序（环上节点按出现序排在尾部）
        self._topo: dict[uuidlib.UUID, list[str]] = {}
        # project_id -> {key: [依赖它的虚拟变量 key]}
        self._dependents: dict[uuidlib.UUID, dict[str, list[str]]] = {}
        self._listeners: list[ValueListener] = []
        self._warned: set[str] = set()  # 求值失败一次性告警去重 f"{pid}:{key}"

    # ---- 查询 ----

    def pool(self, project_id: uuidlib.UUID) -> dict[str, dict[str, Any]]:
        """值池快照（副本；签名冻结）。未装配工程返回空 dict。"""
        src = self._pools.get(project_id)
        if not src:
            return {}
        return {k: dict(v) for k, v in src.items()}

    def variable(self, project_id: uuidlib.UUID, key: str) -> VariableDef | None:
        return self._vars.get(project_id, {}).get(key)

    def keys(self, project_id: uuidlib.UUID) -> list[str]:
        return list(self._vars.get(project_id, {}).keys())

    def stale_timeout_ms(self, project_id: uuidlib.UUID, key: str) -> int:
        return self._stale_ms.get(project_id, {}).get(key, 0)

    # ---- doc 装配 ----

    def set_doc(self, project_id: uuidlib.UUID, doc: dict) -> None:
        """doc 热更新（PUT/导入/启动 sync 共用）：重建索引与拓扑，裁剪消失的键，保留存续键现值。"""
        try:
            model = ProjectDoc.model_validate(doc)
        except Exception as exc:  # noqa: BLE001 - 结构非法不致命（doc 校验链已拦截），值流不中断
            logger.warning(f"hub.set_doc 结构解析失败 project={project_id}：{exc}")
            return

        vars_by_key: dict[str, VariableDef] = {}
        stale_ms: dict[str, int] = {}
        ds_by_id = {ds.id: ds for ds in model.datasources}
        for var in model.variables:
            vars_by_key[var.key] = var
            stale_ms[var.key] = self._effective_stale_ms(var, ds_by_id.get(var.datasourceId))
        # 内置 _tick：stale 永不触发（timeout=0 跳过扫描），池条目经裁剪幸存（在 live_keys 内）
        vars_by_key[TICK_KEY] = _tick_var()
        stale_ms[TICK_KEY] = 0

        # 依赖图：变量 key → 直接依赖它的虚拟变量 key
        dependents: dict[str, list[str]] = {}
        virtual_keys: list[str] = []
        for var in model.variables:
            if not var.expr:
                continue
            virtual_keys.append(var.key)
            for ident in expr_idents(var.expr):
                if ident in vars_by_key:  # 未知标识符忽略（求值期 ReferenceError 回落旧值）
                    dependents.setdefault(ident, []).append(var.key)

        # Kahn 拓扑排序（依赖先行）；环上节点按出现序追加（求值期 visited 防死循环）
        in_deg = {k: 0 for k in virtual_keys}
        for deps in dependents.values():
            for d in deps:
                if d in in_deg:
                    in_deg[d] += 1
        queue = deque(k for k in virtual_keys if in_deg[k] == 0)
        ordered: list[str] = []
        seen_edge: dict[str, int] = dict(in_deg)
        while queue:
            k = queue.popleft()
            ordered.append(k)
            for d in dependents.get(k, []):
                if d not in seen_edge:
                    continue
                seen_edge[d] -= 1
                if seen_edge[d] == 0:
                    queue.append(d)
        for k in virtual_keys:  # 环上节点兜底
            if k not in ordered:
                ordered.append(k)

        pool = self._pools.setdefault(project_id, {})
        live_keys = set(vars_by_key)
        for key in list(pool.keys()):
            if key not in live_keys:
                del pool[key]  # 变量已删除：池条目随 doc 裁剪
        pool.setdefault(TICK_KEY, {"v": float(int(time.time())), "q": QUALITY_GOOD, "t": _now_ms()})

        self._vars[project_id] = vars_by_key
        self._stale_ms[project_id] = stale_ms
        self._dependents[project_id] = dependents
        self._topo[project_id] = ordered

        # 虚拟变量初始化求值（对齐前端 recomputeAllVirtuals）：Kahn 序逐个求值；
        # 求值失败（依赖缺失/环）= bad，不能以 good 写 0 或旧值：启动时数据源还没连上，
        # 报「0 且正常」比报「不可用」危险得多（历史会按 good 采样入库）。
        now = _now_ms()
        for key in ordered:
            var = vars_by_key[key]
            value = self._eval_virtual(project_id, var)
            if value is _EVAL_FAILED:
                old = self._pools.get(project_id, {}).get(key)
                self._apply(project_id, var, old["v"] if old is not None else None, QUALITY_BAD, now)
                continue
            self._apply(project_id, var, value, QUALITY_GOOD, now)

    @staticmethod
    def _effective_stale_ms(var: VariableDef, ds: Any) -> int:
        """stale 判定超时（02 §1.7）：显式 staleTimeoutMs 优先；缺省 3×采集周期、下限 STALE_MIN。

        两类变量不参与 stale 计时（返回 0 = 永不超时）：
        - 虚拟变量：值由依赖驱动重算，是否可信由依赖质量决定（坏值传导已覆盖），
          按时间判 stale 会让「依赖不变」的正常计算点无故失效。
        - mock hold：语义就是常量/反控回环，本来就不会周期性来帧。
        """
        from app.core.config import settings

        if var.expr:
            return 0
        if var.mock is not None and getattr(var.mock, "kind", None) == "hold":
            return 0

        cfg = getattr(ds, "config", None)
        explicit = getattr(cfg, "staleTimeoutMs", None)
        if explicit:
            return int(explicit)
        period = 0
        if getattr(cfg, "intervalMs", None):  # rest 轮询
            period = int(cfg.intervalMs)
        elif var.mock is not None:  # mock 波形
            spec = var.mock
            period = int(getattr(spec, "periodMs", 0) or getattr(spec, "intervalMs", 0) or 0)
        return max(settings.STALE_MIN_TIMEOUT_MS, 3 * period)

    def remove(self, project_id: uuidlib.UUID) -> None:
        """工程删除：池与索引全清（签名冻结）。"""
        self._pools.pop(project_id, None)
        self._vars.pop(project_id, None)
        self._stale_ms.pop(project_id, None)
        self._dependents.pop(project_id, None)
        self._topo.pop(project_id, None)

    # ---- 监听器（B 包 rules_engine / historian 在 background_jobs 注册）----

    def add_value_listener(self, fn: ValueListener) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_value_listener(self, fn: ValueListener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    # ---- 值入池 ----

    def ingest(self, project_id: uuidlib.UUID, variable: VariableDef, raw: Any, ts: int) -> None:
        """collector 唯一入口（签名冻结）：换算流水 → 入池 → 级联 → 通知。"""
        ev = convert.to_engineering(variable, raw)
        self._apply(project_id, variable, ev.value, ev.q, ts)
        self._propagate(project_id, variable.key, ts)

    def apply_engineering(self, project_id: uuidlib.UUID, variable: VariableDef, value: "float | bool | str | None", q: str, ts: int) -> None:
        """已换算值的入池通道（mock 反控回环沿用 convert 流水；本方法供虚拟变量级联内部使用）。"""
        self._apply(project_id, variable, value, q, ts)
        self._propagate(project_id, variable.key, ts)

    def _apply(self, project_id: uuidlib.UUID, variable: VariableDef, value: "float | bool | str | None", q: str, ts: int) -> None:
        """单变量入池：变化判定 + 监听器 + mark_dirty（不做级联）。"""
        pool = self._pools.setdefault(project_id, {})
        old = pool.get(variable.key)

        if q == QUALITY_GOOD and old is not None and old["q"] == QUALITY_GOOD:
            if old["v"] == value and isinstance(old["v"], type(value)):
                # 值无变化（变化抑制）：仅推进新鲜度时间戳
                old["t"] = ts
                return

        entry = {
            "v": value if q == QUALITY_GOOD else (old["v"] if old is not None else None),
            "q": q,
            "t": ts,
        }
        pool[variable.key] = entry

        for fn in list(self._listeners):
            try:
                fn(project_id, variable, entry["v"], q, ts)
            except Exception:  # noqa: BLE001 - 单个监听器异常不阻断值流
                logger.exception(f"hub 值监听器异常 project={project_id} key={variable.key}")

        try:  # 惰性引用 ws_manager（同包模块，仍走函数体 import 防装配顺序耦合）
            from app.services import ws_manager

            manager = ws_manager.manager
            if manager is not None:
                manager.mark_dirty(project_id, variable.key, dict(entry))
        except Exception:  # noqa: BLE001
            logger.debug("ws_manager 未装配，跳过 mark_dirty")

    def _propagate(self, project_id: uuidlib.UUID, changed_key: str, ts: int) -> None:
        """前向传播：BFS 重算依赖 changed_key 的虚拟变量（visited 防环，与前端 propagateVirtuals 同构）。"""
        dependents = self._dependents.get(project_id)
        if not dependents:
            return
        vars_by_key = self._vars.get(project_id, {})
        queue: deque[str] = deque([changed_key])
        visited = {changed_key}
        while queue:
            cur = queue.popleft()
            for vk in dependents.get(cur, []):
                if vk in visited:
                    continue  # 环/重复
                visited.add(vk)
                var = vars_by_key.get(vk)
                if var is None or not var.expr:
                    continue
                value = self._eval_virtual(project_id, var)
                if value is _EVAL_FAILED:
                    # 依赖坏值/缺失时，虚拟变量必须跟着变 bad；否则它会带着上一轮 GOOD
                    # 继续显示「停更旧值算出的正常值」——比单点坏值更隐蔽。
                    old = self._pools.get(project_id, {}).get(vk)
                    if old is not None and old.get("q") == QUALITY_BAD:
                        continue  # 已是 bad，不重复广播
                    self._apply(project_id, var, old["v"] if old is not None else None, QUALITY_BAD, ts)
                    queue.append(vk)  # 坏值继续向下游传导：依赖它的虚拟变量同样转 bad
                    continue
                self._apply(project_id, var, value, QUALITY_GOOD, ts)
                queue.append(vk)

    def _eval_virtual(self, project_id: uuidlib.UUID, var: VariableDef) -> Any:
        """虚拟变量求值：scope 只取【good 且非 None】的工程值（与前端 scope 同构）。

        坏值/停更值不得参与计算：宁可求值失败转 bad，也不能拿旧值算出看似正常的数。
        """
        pool = self._pools.get(project_id, {})
        scope: dict[str, Value] = {
            k: e["v"] for k, e in pool.items()
            if e.get("q") == QUALITY_GOOD and e.get("v") is not None
        }
        try:
            result = eval_expr(var.expr or "0", scope)
        except Exception as exc:  # noqa: BLE001
            warn_key = f"{project_id}:{var.key}"
            if warn_key not in self._warned:
                self._warned.add(warn_key)
                logger.warning(f"虚拟变量 {var.key} 求值失败（不再重复告警）：{exc}")
            return _EVAL_FAILED
        if isinstance(result, float):
            return result if math.isfinite(result) else 0.0  # 与前端 Number.isFinite 口径一致
        if isinstance(result, bool) or isinstance(result, str) or result is None:
            return 0.0 if result is None else result
        return 0.0

    # ---- stale ----

    def touch(self, project_id: uuidlib.UUID, variable: VariableDef, ts: int) -> None:
        """推进单点新鲜度但不改值（订阅型源用）：连接健康且值未变化 ≠ 数据停更。

        仅对当前 good 的条目生效；bad/stale 不因 touch 复活。
        """
        entry = self._pools.get(project_id, {}).get(variable.key)
        if entry is not None and entry.get("q") == QUALITY_GOOD:
            entry["t"] = ts

    def sweep_stale(self, project_id: uuidlib.UUID, now_ms: int | None = None) -> int:
        """单工程 stale 扫描：good 且超时 → stale（值保留）。返回翻转条数。仅 q 翻转时 mark_dirty。"""
        now = now_ms if now_ms is not None else _now_ms()
        pool = self._pools.get(project_id)
        stale_ms = self._stale_ms.get(project_id, {})
        if not pool:
            return 0
        flipped = 0
        flipped_keys: list[str] = []
        for key, entry in pool.items():
            timeout = stale_ms.get(key, 0)
            if entry["q"] == QUALITY_GOOD and timeout and now - entry["t"] > timeout:
                entry["q"] = QUALITY_STALE
                flipped += 1
                flipped_keys.append(key)
                try:
                    from app.services import ws_manager

                    ws_manager.manager.mark_dirty(project_id, key, dict(entry))
                except Exception:  # noqa: BLE001
                    pass
        # 停更同样要向下游传导：依赖它的虚拟变量转 bad，而不是继续用 stale 值计算
        for key in flipped_keys:
            self._propagate(project_id, key, now)
        return flipped

    def sweep_stale_all(self) -> int:
        return sum(self.sweep_stale(pid) for pid in list(self._pools.keys()))

    # ---- 内置秒节拍（M9 批次4） ----

    def tick_all(self) -> None:
        """全池推进 _tick（runtime_boot 每秒驱动）：值变化 → 广播 + 依赖它的虚拟变量级联重算。"""
        now = _now_ms()
        sec = float(int(time.time()))
        for pid in list(self._pools.keys()):
            var = self._vars.get(pid, {}).get(TICK_KEY)
            if var is None:
                continue
            self.apply_engineering(pid, var, sec, QUALITY_GOOD, now)

    # ---- 测试辅助 ----

    def reset(self) -> None:
        self._pools.clear()
        self._vars.clear()
        self._stale_ms.clear()
        self._dependents.clear()
        self._topo.clear()
        self._listeners.clear()
        self._warned.clear()


# 进程内单例（runtime_boot 挂 app.state；跨包一律惰性 import 本模块取用）
hub = Hub()
