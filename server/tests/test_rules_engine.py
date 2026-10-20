"""服务端报警判定引擎测试（B 包，契约 §6.2）：迟滞表逐 op + durationMs 持续窗（02 §2.11）。

事件经 on_value 同步入口进入，入库派发为后台任务 → async 轮询测试库断言
（wait_rows/wait_status 内部以独立会话快照读，与派发任务的短会话互不干扰）。
"""
import asyncio
import time
import uuid as uuidlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AlarmRecord, Project, User
from app.services import rules_engine
from app.services.rules_engine import RulesEngine, _to_number, _ts_to_epoch_sec

UTCD = timezone.utc


# ---------------- 轮询助手 ----------------

async def rows_of(env, pid) -> list[AlarmRecord]:
    async with env.factory() as s:
        return list((await s.execute(select(AlarmRecord).order_by(AlarmRecord.id))).scalars())


async def wait_rows(env, pid, n=1, what="触发") -> list[AlarmRecord]:
    deadline = time.monotonic() + 2.0
    rows: list[AlarmRecord] = []
    while time.monotonic() < deadline:
        rows = await rows_of(env, pid)
        if len(rows) >= n:
            return rows
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待超时：{what}（当前 {len(rows)} 行）")


async def last_status(env, pid) -> str | None:
    rows = await rows_of(env, pid)
    return rows[-1].status if rows else None


async def wait_status(env, pid, status, what="状态"):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if await last_status(env, pid) == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待超时：{what}（当前 {await last_status(env, pid)}）")


@pytest.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SimpleNamespace(engine=engine, factory=factory)
    await engine.dispose()


@pytest.fixture
def seam(env):
    """rules_engine 会话缝指向测试库。"""
    rules_engine.session_factory = env.factory
    yield
    rules_engine.session_factory = None


def var_def(**over) -> dict:
    d = {"id": "v1", "key": "temp_01", "label": "1号反应釜温度", "type": "number", "precision": 1}
    d.update(over)
    return d


def rule_def(**over) -> dict:
    d = {"id": "alm_1", "name": "温度超高", "variableId": "v1", "op": ">", "threshold": 110,
         "level": "warn", "message": "{label} 超高: {value}（阈值 {threshold}）", "enabled": True}
    d.update(over)
    return d


def make_engine(pid: str, rules: list[dict], variable: dict | None = None) -> RulesEngine:
    eng = RulesEngine()
    eng.sync(pid, {"variables": [variable or var_def()], "alarmRules": rules})
    return eng


def _naive_ms(dt: datetime) -> int:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTCD)
    return int(dt.timestamp() * 1000)


# ---------------- 工具函数口径 ----------------

def test_to_number_and_ts_norm():
    assert _to_number(True) == 1.0 and _to_number(False) == 0.0
    assert _to_number(3) == 3.0 and _to_number("abc") is None
    assert _to_number(float("nan")) is None and _to_number(float("inf")) is None
    assert _ts_to_epoch_sec(1759999000000) == 1759999000.0   # epoch 毫秒
    assert _ts_to_epoch_sec(1759999000.5) == 1759999000.5    # epoch 秒
    dt = datetime(2026, 1, 1, tzinfo=UTCD)
    assert _ts_to_epoch_sec(dt) == dt.timestamp()
    assert _ts_to_epoch_sec(datetime(2026, 1, 1)) == dt.timestamp()  # naive 按 UTC


# ---------------- 迟滞表逐 op（02 §2.11 恢复判定表） ----------------

@pytest.mark.parametrize(
    "op,th,H,trigger_v,band_v,recover_v",
    [
        (">", 110, 2, 110.1, 108.1, 108.0),   # 触发 v>th；band >th−H 不恢复；恢复 v≤th−H
        (">=", 110, 2, 110.0, 108.0, 107.9),  # 触发 v≥th；band ≥th−H 不恢复；恢复 v<th−H
        ("<", 110, 2, 109.9, 111.9, 112.0),   # 触发 v<th；band <th+H 不恢复；恢复 v≥th+H
        ("<=", 110, 2, 110.0, 112.0, 112.1),  # 触发 v≤th；band ≤th+H 不恢复；恢复 v>th+H
    ],
)
async def test_hysteresis_table_per_op(env, seam, op, th, H, trigger_v, band_v, recover_v):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def(op=op, threshold=th, hysteresis=H)])

    eng.on_value(pid, var_def(), trigger_v, "good", 1000)
    rows = await wait_rows(env, pid, 1, what=f"{op} 触发")
    assert rows[0].status == "triggered"

    eng.on_value(pid, var_def(), band_v, "good", 2000)  # 回差带内：不恢复
    await asyncio.sleep(0.05)
    assert await last_status(env, pid) == "triggered"

    eng.on_value(pid, var_def(), recover_v, "good", 3000)  # 越过回差带：恢复
    await wait_status(env, pid, "cleared", what=f"{op} 恢复")
    rows = await rows_of(env, pid)
    assert rows[0].cleared_at is not None and rows[0].value == str(trigger_v)


async def test_eq_ne_reverse_recovery(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def(op="==", threshold=100)])
    eng.on_value(pid, var_def(), 100, "good", 1000)
    await wait_rows(env, pid, 1, what="== 触发")
    eng.on_value(pid, var_def(), 100.5, "good", 2000)  # 反向判定即恢复（H 不适用）
    await wait_status(env, pid, "cleared", what="== 恢复")

    pid2 = str(uuidlib.uuid4())
    eng2 = make_engine(pid2, [rule_def(op="!=", threshold=100)])
    eng2.on_value(pid2, var_def(), 101, "good", 1000)
    await wait_rows(env, pid2, 1, what="!= 触发")
    eng2.on_value(pid2, var_def(), 100, "good", 2000)  # 回到等值 → 恢复
    await wait_status(env, pid2, "cleared", what="!= 恢复")


# ---------------- durationMs 持续窗（ts 用真实 epoch 毫秒口径） ----------------

T0_MS = 1760000000000


async def test_duration_ms_requires_continuous_window(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def(op=">", threshold=110, durationMs=5000)])
    eng.on_value(pid, var_def(), 111, "good", T0_MS + 1000)   # 开始满足（pending）
    eng.on_value(pid, var_def(), 112, "good", T0_MS + 4000)   # 持续 3s：未到 5s
    await asyncio.sleep(0.05)
    assert await rows_of(env, pid) == []
    eng.on_value(pid, var_def(), 113, "good", T0_MS + 6000)   # 持续 5s：触发
    rows = await wait_rows(env, pid, 1, what="durationMs 触发")
    assert rows[0].status == "triggered"


async def test_duration_ms_resets_on_breach(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def(op=">", threshold=110, durationMs=5000)])
    eng.on_value(pid, var_def(), 111, "good", T0_MS + 1000)
    eng.on_value(pid, var_def(), 109, "good", T0_MS + 2000)   # 跌回（不满足触发条件）→ since 重置
    eng.on_value(pid, var_def(), 111, "good", T0_MS + 4000)   # 重新计时
    eng.on_value(pid, var_def(), 112, "good", T0_MS + 7000)   # 距重置 3s：不触发
    await asyncio.sleep(0.05)
    assert await rows_of(env, pid) == []
    eng.on_value(pid, var_def(), 113, "good", T0_MS + 9000)   # 距重置 5s：触发
    rows = await wait_rows(env, pid, 1, what="重置后触发")
    assert len(rows) == 1 and _naive_ms(rows[0].triggered_at) == T0_MS + 9000


# ---------------- 质量位 / 类型 / 快照口径 ----------------

async def test_bad_quality_not_evaluated(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def()])
    eng.on_value(pid, var_def(), 999, "stale", 1000)
    eng.on_value(pid, var_def(), 999, "bad", 2000)
    await asyncio.sleep(0.05)
    assert await rows_of(env, pid) == []


async def test_boolean_as_1_0_and_string_skipped(env, seam):
    pid = str(uuidlib.uuid4())
    bvar = var_def(id="vb", key="pump1_running", label="循环泵", type="boolean", precision=None)
    eng = make_engine(pid, [rule_def(id="alm_b", variableId="vb", op="==", threshold=1,
                                     message="{label} 启动异常: {value}")], variable=bvar)
    eng.on_value(pid, bvar, True, "good", 1000)   # True→1 == 1 → 触发
    rows = await wait_rows(env, pid, 1, what="boolean 触发")
    assert rows[0].value == "1.00" and "循环泵" in rows[0].message  # precision 缺省 2 位
    eng.on_value(pid, bvar, False, "good", 2000)  # False→0 != 1 → 恢复
    await wait_status(env, pid, "cleared", what="boolean 恢复")

    # string 变量值跳过（doc 校验已禁 string 规则，此处兜底）
    eng.on_value(pid, var_def(), "hot", "good", 3000)
    await asyncio.sleep(0.05)
    assert len(await rows_of(env, pid)) == 1


async def test_message_placeholders_and_value_precision(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def(message="{key}|{label}|{value}|{threshold}")])
    eng.on_value(pid, var_def(), 111.23, "good", 1000)  # precision=1 → 111.2
    row = (await wait_rows(env, pid, 1, what="触发"))[0]
    assert row.message == "temp_01|1号反应釜温度|111.2|110.0"
    assert row.value == "111.2" and row.variable_key == "temp_01" and row.level == "warn"


async def test_retrigger_after_clear_new_row(env, seam):
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def()])
    eng.on_value(pid, var_def(), 111, "good", 1000)
    await wait_rows(env, pid, 1, what="第一次触发")
    eng.on_value(pid, var_def(), 100, "good", 2000)  # v ≤ 110-0 → 恢复
    await wait_status(env, pid, "cleared", what="恢复")
    eng.on_value(pid, var_def(), 111, "good", 3000)  # 再次触发 → 新行
    rows = await wait_rows(env, pid, 2, what="第二次触发")
    assert rows[0].status == "cleared" and rows[1].status == "triggered"


async def test_trigger_recover_retrigger_fast_sequence(env, seam):
    """竞态回归：触发→恢复→再触发快速连续翻转（任务尚未运行即全部派发），
    per-rule 锁内按 spawn 序逐条落库——中间的 clear 不得被「复核 current active」
    吞掉（否则首行滞留 triggered、恢复帧丢失、再触发被幂等并入首行）。"""
    pid = str(uuidlib.uuid4())
    eng = make_engine(pid, [rule_def()])
    eng.on_value(pid, var_def(), 111, "good", 1000)  # 触发翻转
    eng.on_value(pid, var_def(), 100, "good", 2000)  # 恢复翻转（v ≤ 110-0）
    eng.on_value(pid, var_def(), 112, "good", 3000)  # 再触发翻转
    rows = await wait_rows(env, pid, 2, what="快速序列两行")
    assert rows[0].status == "cleared" and rows[0].value == "111.0"
    assert rows[1].status == "triggered" and rows[1].value == "112.0"


# ---------------- 规则注册与 TTL 刷新 ----------------

def test_sync_filters_and_state_cleanup():
    eng = RulesEngine()
    pid = str(uuidlib.uuid4())
    n = eng.sync(pid, {"variables": [var_def()], "alarmRules": [rule_def(), rule_def(id="r2", enabled=False)]})
    assert n == 1
    eng._states[(pid, "alm_1")] = rules_engine._RuleState(active=True)
    eng.sync(pid, {"variables": [var_def()], "alarmRules": [rule_def(id="r9")]})  # 规则 id 变更 → 旧状态清理
    assert (pid, "alm_1") not in eng._states
    eng.remove(pid)
    assert eng._entries.get(pid) is None


async def test_ttl_refresh_picks_up_doc_change(env, seam):
    """值事件路径 TTL 后台刷新：库内 doc 更新后 ≤TTL 生效（deviation：规则来源自治方案）。"""
    import app.services.rules_engine as re_mod

    async with env.factory() as s:
        u = User(username="u1", password_hash="x")
        s.add(u)
        await s.flush()
        p = Project(id=uuidlib.uuid4(), name="P", description=None, revision=1, owner_id=u.id,
                    doc={"variables": [var_def()], "alarmRules": [rule_def()]})
        s.add(p)
        await s.commit()
        pid = str(p.id)

    eng = RulesEngine()
    # 工程未 sync：首个事件触发后台刷新（本事件不判定，防阻塞）
    eng.on_value(pid, var_def(), 111, "good", 1000)
    await asyncio.sleep(0.05)
    assert await rows_of(env, pid) == []
    eng.on_value(pid, var_def(), 111, "good", 2000)  # 规则已加载 → 触发
    rows = await wait_rows(env, pid, 1, what="TTL 后触发")
    assert rows[0].status == "triggered"

    # 库内规则改为 threshold=-1（任何正数都满足触发且不满足恢复）：模拟保存后 TTL 刷新不丢状态
    async with env.factory() as s:
        p = await s.get(Project, uuidlib.UUID(pid))
        p.doc = {"variables": [var_def()], "alarmRules": [rule_def(threshold=-1)]}
        await s.commit()
    eng._loaded_at[pid] = time.monotonic() - re_mod.RULES_TTL_SEC - 1  # 强制缓存过期
    eng.on_value(pid, var_def(), 111, "good", 3000)  # 旧规则：已激活、v 不越带 → 无动作
    await asyncio.sleep(0.1)  # 等后台刷新完成
    eng.on_value(pid, var_def(), 111, "good", 4000)  # 新规则 op='>' th=-1：恢复需 v≤-1 → 仍激活
    assert await last_status(env, pid) == "triggered"
