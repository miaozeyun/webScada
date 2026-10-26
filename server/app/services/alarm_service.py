"""报警服务（M8 单行状态机唯一实现点，契约 §6.2；REST 与引擎共用）。

单行状态机（修复「恢复另插新行」缺陷）：triggered → (acked) → cleared
- trigger：同 (project_id, rule_id) 已有未恢复行 → 幂等返回既有 id（不插新行、不重复外发）
- ack：triggered→acked；acked 重复 ack 幂等返回当前态；cleared 迟到补确认只填 ack 字段不改 status
- clear：triggered/acked → cleared（cleared_at）；ack 字段保留
- 并发口径：ack/clear 状态迁移一律条件 UPDATE（WHERE 携带状态前态 + rowcount 判定），
  防读-改-写无条件 UPDATE 在与对方并发时互相覆写（丢更新）

事件外发（均函数体内惰性 import，跨包依赖规约 §6.4）：
- 新触发 → ws_manager.broadcast_alarm + notify.send_alarm（级别过滤/节流在 notify 内）
- 恢复 → ws_manager.broadcast_alarm_clear
- ack 状态变更 → ws_manager.broadcast_alarm_ack
A 包未合入时对应事件降级为 debug 日志，不影响入库主流程；审计由 REST 路由层落（需 request）。

通知外发经 _spawn 后台任务派发：webhook/SMTP 网络耗时不回传值流（§11.7）。
"""
import asyncio
import inspect
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core import stats
from app.core.errors import AppError
from app.db.models import AlarmRecord, User

# 活动报警集合（WS snapshot activeAlarms / 清理保护范围均以此为口径）
ACTIVE_STATUSES = ("triggered", "acked")

# 级别序：critical > warn > info（snapshot 截断与告警条优先级同源 02 §2.11）
_LEVEL_RANK = {"critical": 0, "warn": 1, "info": 2}

# 进程内活动报警数参考值（alarms_active gauge；启动时由 count_active 校准）
_active_hint = 0

# 后台任务强引用集（防 Task 被 GC；done 后自动移除）
_bg_tasks: set[asyncio.Task] = set()


def level_rank(level: str) -> int:
    return _LEVEL_RANK.get(level, 3)


def _norm_pid(project_id) -> uuid.UUID:
    if isinstance(project_id, uuid.UUID):
        return project_id
    try:
        return uuid.UUID(str(project_id))
    except ValueError:
        raise AppError("NOT_FOUND", "工程不存在", 404) from None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def epoch_ms(dt: datetime) -> int:
    return int(_aware(dt).timestamp() * 1000)


def _spawn(coro) -> asyncio.Task | None:
    """派发后台任务（无运行中事件循环时放弃并告警，值流不受阻）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("无事件循环，报警外发任务放弃：{!r}", coro)
        return None
    task = loop.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


def _bump_active(delta: int) -> None:
    global _active_hint
    _active_hint = max(0, _active_hint + delta)
    stats.set_gauge("alarms_active", _active_hint)


async def _broadcast_clear(pid: uuid.UUID, alarm_id: int, at_ms: int) -> None:
    """alarmClear 帧广播（A 包未合入时降级为 debug 日志，不影响主流程）。"""
    try:
        from app.services import ws_manager  # 惰性：跨包（A）
    except ImportError:
        logger.debug("ws_manager 未合入（A 包），alarmClear 帧广播降级为日志")
        return
    try:
        # 帧目录（03 §3.4）字段名沿用 recoveredAt（帧契约冻结）；此处传 cleared 时刻（epoch ms）
        result = ws_manager.broadcast_alarm_clear(pid, alarm_id, at_ms)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("alarmClear 帧广播失败（不抛）：{}", exc)


def set_active_hint(n: int) -> None:
    """启动/维护路径校准 gauge（background_jobs 调用）。"""
    global _active_hint
    _active_hint = max(0, n)
    stats.set_gauge("alarms_active", _active_hint)


def _alarm_payload(rec: AlarmRecord) -> dict:
    """WS 帧 / snapshot activeAlarms 条目（结构同 03 §2.7 REST 条目，时间为 epoch 毫秒；
    status 为 M8 值域 triggered/acked——前端 D 包对未知状态灰显兜底，见契约 §11.8）。"""
    return {
        "id": rec.id,
        "ruleId": rec.rule_id,
        "variableKey": rec.variable_key,
        "level": rec.level,
        "message": rec.message,
        "value": rec.value,
        "status": rec.status,
        "triggeredAt": epoch_ms(rec.triggered_at),
        "ackedAt": epoch_ms(rec.acked_at) if rec.acked_at else None,
    }


async def _fire_triggered(rec: AlarmRecord, rule: dict | None) -> None:
    """新行触发后外发：WS 即时帧 + 通知（notify 自行做级别过滤与节流）。"""
    from app.services import notify  # 惰性：同包跨模块，避免 import 环
    _spawn(notify.send_alarm(rec, rule))
    payload = _alarm_payload(rec)

    async def _do_broadcast():
        try:
            from app.services import ws_manager  # 惰性：跨包（A）
        except ImportError:
            logger.debug("ws_manager 未合入（A 包），alarm 帧广播降级为日志")
            return
        try:
            result = ws_manager.broadcast_alarm(rec.project_id, payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("alarm 帧广播失败（不抛）：{}", exc)

    _spawn(_do_broadcast())


async def trigger(db: AsyncSession, project_id, rule: dict, value_str: str | None, at: datetime) -> int | None:
    """触发：同规则存在未恢复行 → 返回既有 id（幂等）；否则插入新行并外发事件。

    rule 快照 dict：{id, variableKey, level, message}（兼容 variable_key 下划线键），
    id/variableKey/level/message 为触发时快照（规则/变量删除后历史仍可读）。
    """
    pid = _norm_pid(project_id)
    rule_id = str(rule.get("id") or rule.get("rule_id") or "")
    if not rule_id:
        logger.warning("trigger 缺少规则 id，忽略本次触发")
        return None
    existing = (
        await db.execute(
            select(AlarmRecord.id)
            .where(
                AlarmRecord.project_id == pid,
                AlarmRecord.rule_id == rule_id,
                AlarmRecord.status.in_(ACTIVE_STATUSES),
            )
            .order_by(AlarmRecord.triggered_at.desc())
            .limit(1)
        )
    ).scalar()
    if existing is not None:
        return int(existing)

    rec = AlarmRecord(
        project_id=pid,
        rule_id=rule_id,
        variable_key=str(rule.get("variableKey") or rule.get("variable_key") or ""),
        level=str(rule.get("level") or "warn"),
        message=str(rule.get("message") or rule_id),
        value=value_str,
        status="triggered",
        triggered_at=_aware(at),
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    _bump_active(1)
    await _fire_triggered(rec, rule)
    return int(rec.id)


async def clear(db: AsyncSession, project_id, rule_id: str, at: datetime) -> int | None:
    """恢复：triggered/acked → cleared（幂等：无未恢复行时返回 None 不动作）。

    条件 UPDATE（WHERE status IN ACTIVE，写法同 sweep_on_startup）：与 REST ack 的
    在途读-改-写并发时不会被覆写回 acked（丢更新会导致后续同规则触发被幂等早退
    静默吞掉）；rowcount==0 即该行已被并发方变更 → 按幂等返回 None 不动作不外发。
    """
    pid = _norm_pid(project_id)
    rec_id = (
        await db.execute(
            select(AlarmRecord.id)
            .where(
                AlarmRecord.project_id == pid,
                AlarmRecord.rule_id == str(rule_id),
                AlarmRecord.status.in_(ACTIVE_STATUSES),
            )
            .order_by(AlarmRecord.triggered_at.desc())
            .limit(1)
        )
    ).scalar()
    if rec_id is None:
        return None
    cleared_at = _aware(at)
    res = await db.execute(
        update(AlarmRecord)
        .where(AlarmRecord.id == rec_id, AlarmRecord.status.in_(ACTIVE_STATUSES))
        .values(status="cleared", cleared_at=cleared_at)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if not res.rowcount:
        return None
    _bump_active(-1)

    # 恢复通知（阶段三）：值班员必须知道「好了」，否则只会看到报警、永远不知道何时恢复
    rec = (
        await db.execute(select(AlarmRecord).where(AlarmRecord.id == rec_id))
    ).scalar_one_or_none()
    if rec is not None:
        from app.services import notify  # 惰性：同包跨模块

        _spawn(notify.send_recovery(rec))

    _spawn(_broadcast_clear(pid, int(rec_id), epoch_ms(cleared_at)))
    return int(rec_id)


async def reconcile_rules(db: AsyncSession, project_id, doc: dict) -> list[int]:
    """规则变更收口（保存 doc 后调用）：规则被删除或停用 → 其活动报警置 cleared。

    - 只收口「不在启用规则集合内」的行；仍在启用的规则报警保持原状。
    - **排除 sys_comm: 系统报警**（通讯中断由 comm_monitor 自管，保存任意工程不得误清）。
    - 配置变更不是现场恢复：广播 alarmClear 让界面同步，但**不**发外部恢复通知（避免客户群刷屏）。
    返回被清除的 alarm id 列表。
    """
    pid = _norm_pid(project_id)
    live: set[str] = set()
    rules = doc.get("alarmRules") if isinstance(doc, dict) else None
    for r in rules or []:
        if isinstance(r, dict) and r.get("enabled", True) and r.get("id"):
            live.add(str(r["id"]))

    rows = (
        await db.execute(
            select(AlarmRecord.id, AlarmRecord.rule_id).where(
                AlarmRecord.project_id == pid,
                AlarmRecord.status.in_(ACTIVE_STATUSES),
                ~AlarmRecord.rule_id.like("sys_comm:%"),
            )
        )
    ).all()
    stale = [(int(r.id), str(r.rule_id)) for r in rows if str(r.rule_id) not in live]
    if not stale:
        return []

    now = _now()
    ids = [i for i, _ in stale]
    res = await db.execute(
        update(AlarmRecord)
        .where(AlarmRecord.id.in_(ids), AlarmRecord.status.in_(ACTIVE_STATUSES))
        .values(status="cleared", cleared_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    n = res.rowcount or 0
    _bump_active(-n)
    for aid, rule_id in stale:
        logger.info("规则收口：project={} rule={} alarm={} → cleared", pid, rule_id, aid)
        _spawn(_broadcast_clear(pid, aid, epoch_ms(now)))
    return ids


async def force_clear(db: AsyncSession, project_id, alarm_id: int, at: datetime | None = None) -> AlarmRecord:
    """人工清除（operator/admin 运维动作）：triggered/acked → cleared，幂等。

    与引擎 clear 的区别：按 alarm id 直接收口，不要求规则仍在；用于清理规则已变更、
    设备已被拆除等「永远不会自动恢复」的残留报警。广播 alarmClear，不发恢复通知。
    """
    pid = _norm_pid(project_id)
    now = _aware(at) if at is not None else _now()
    res = await db.execute(
        update(AlarmRecord)
        .where(
            AlarmRecord.id == alarm_id,
            AlarmRecord.project_id == pid,
            AlarmRecord.status.in_(ACTIVE_STATUSES),
        )
        .values(status="cleared", cleared_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    changed = bool(res.rowcount)
    rec = (
        await db.execute(
            select(AlarmRecord).where(AlarmRecord.id == alarm_id, AlarmRecord.project_id == pid)
        )
    ).scalar_one_or_none()
    if rec is None:
        raise AppError("NOT_FOUND", "报警不存在或不属该工程", 404)
    if changed:
        _bump_active(-1)
        _spawn(_broadcast_clear(pid, alarm_id, epoch_ms(now)))
    return rec


async def ack(db: AsyncSession, project_id, alarm_id: int, user: User, note: str | None) -> AlarmRecord:
    """确认（幂等）：triggered→acked；acked 重复 ack 原样返回；
    cleared 且从未确认 → 补填 ack 字段（status 保持 cleared）；已确认的 cleared 原样返回。
    状态/字段发生变更时向工程在线连接广播 alarmAck 帧（A 未合入降级）。

    状态迁移一律条件 UPDATE（写法同 sweep_on_startup）：WHERE 携带状态前态，
    rowcount==0 说明该行已被并发方（引擎 clear / 并发 ack）变更 → 重读当前行走
    幂等/迟到补确认分支。杜绝读-改-写无条件 UPDATE 把并发 clear 覆写回 acked
    （读出态过期时 db.get 命中的是会话身份映射旧快照，正是竞态窗口所在）。
    """
    pid = _norm_pid(project_id)
    rec = await db.get(AlarmRecord, alarm_id)
    if rec is None or rec.project_id != pid:
        raise AppError("NOT_FOUND", "报警不存在或不属该工程", 404)

    now = _now()
    changed = False
    res = await db.execute(
        update(AlarmRecord)
        .where(AlarmRecord.id == alarm_id, AlarmRecord.status == "triggered")
        .values(status="acked", acked_at=now, acked_by=user.id, acked_note=note)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount:
        changed = True
    else:
        # 读出态已过期 → 重读当前行，幂等/冲突分支以当前行为准
        await db.refresh(rec)
        if rec.status == "cleared" and rec.acked_at is None:
            # 迟到补确认（03 §2.7）：只填 ack 字段，status 保持 cleared；
            # 同样条件化（ack_at 仍空才生效）防并发迟到 ack 重复填写
            res2 = await db.execute(
                update(AlarmRecord)
                .where(
                    AlarmRecord.id == alarm_id,
                    AlarmRecord.status == "cleared",
                    AlarmRecord.acked_at.is_(None),
                )
                .values(acked_at=now, acked_by=user.id, acked_note=note)
                .execution_options(synchronize_session=False)
            )
            changed = bool(res2.rowcount)
        # acked / 已确认的 cleared / 仍 triggered（极窄并发窗口，下次 ack 再生效）：
        # 幂等返回当前态，不重复广播

    if changed:
        await db.commit()
        await db.refresh(rec)

        async def _do_broadcast():
            try:
                from app.services import ws_manager  # 惰性：跨包（A）
            except ImportError:
                logger.debug("ws_manager 未合入（A 包），alarmAck 帧广播降级为日志")
                return
            try:
                result = ws_manager.broadcast_alarm_ack(
                    pid, rec.id, epoch_ms(rec.acked_at), user.username
                )
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning("alarmAck 帧广播失败（不抛）：{}", exc)

        _spawn(_do_broadcast())
    return rec


async def active_for_snapshot(db: AsyncSession, project_id, limit: int = 200) -> list[dict]:
    """WS snapshot activeAlarms（契约 §6.1 A 包调用）：未恢复集合按 critical>warn>info、
    同级按触发时间倒序截断；调用方据 len==limit 置 truncated=true（防风暴 02 §2.11）。"""
    pid = _norm_pid(project_id)
    rank = case({"critical": 0, "warn": 1, "info": 2}, value=AlarmRecord.level)
    rows = (
        await db.execute(
            select(AlarmRecord)
            .where(AlarmRecord.project_id == pid, AlarmRecord.status.in_(ACTIVE_STATUSES))
            .order_by(rank.asc(), AlarmRecord.triggered_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_alarm_payload(r) for r in rows]


async def count_active(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(AlarmRecord)
            .where(AlarmRecord.status.in_(ACTIVE_STATUSES))
        )
        or 0
    )


async def sweep_on_startup(db: AsyncSession) -> int:
    """启动收口（契约 §5）：遗留 triggered/acked 统一 cleared，防僵尸活动报警。返回收口条数。"""
    now = _now()
    res = await db.execute(
        update(AlarmRecord)
        .where(AlarmRecord.status.in_(ACTIVE_STATUSES))
        .values(status="cleared", cleared_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    n = res.rowcount or 0
    set_active_hint(0)
    return n


async def cleanup_expired(db: AsyncSession) -> int:
    """保留清理（02 §2.11 / 契约 §6.2）：超 ALARM_RETENTION_DAYS 的 cleared 行删除；
    单工程总量超 ALARM_MAX_ROWS_PER_PROJECT 时按 triggered_at 最旧截断 cleared 行
    （triggered/acked 活动记录一律不清理）。返回删除总条数。"""
    deleted = 0
    cutoff = _now() - timedelta(days=settings.ALARM_RETENTION_DAYS)
    res = await db.execute(
        delete(AlarmRecord)
        .where(AlarmRecord.status == "cleared", AlarmRecord.cleared_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    deleted += res.rowcount or 0

    cap = settings.ALARM_MAX_ROWS_PER_PROJECT
    counts = (
        await db.execute(select(AlarmRecord.project_id, func.count()).group_by(AlarmRecord.project_id))
    ).all()
    for pid, cnt in counts:
        if cnt <= cap:
            continue
        keep_ids = (
            select(AlarmRecord.id)
            .where(AlarmRecord.project_id == pid)
            .order_by(AlarmRecord.triggered_at.desc(), AlarmRecord.id.desc())
            .limit(cap)
        )
        res = await db.execute(
            delete(AlarmRecord)
            .where(
                AlarmRecord.project_id == pid,
                AlarmRecord.status == "cleared",
                AlarmRecord.id.not_in(keep_ids),
            )
            .execution_options(synchronize_session=False)
        )
        deleted += res.rowcount or 0
    await db.commit()
    return deleted
