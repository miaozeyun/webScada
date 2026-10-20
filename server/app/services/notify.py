"""报警通知外发（M8，契约 §6.2）：webhook(httpx) + 邮件（标准库 smtplib 线程池包装）。

依赖约束：不新增第三方依赖；SMTP 用 asyncio.to_thread 包装阻塞 smtplib（§11.7：
外发阻塞不回传值流；webhook 失败仅计数+节流，不做重试/死信队列，P1 预留）。
- 级别过滤：低于 ALARM_NOTIFY_MIN_LEVEL（info<warn<critical）不外发
- 节流：同 (project_id, rule_id) 在 ALARM_NOTIFY_THROTTLE_SEC 内只发首条
- 失败计数 stats.notify_failed_total / 成功计数 notify_sent_total（/metrics 消费）
- 收件人口径：config 未设独立收件人（共享骨架禁改），以 NOTIFY_SMTP_FROM 作为收件人
  （运维告警信箱自发自收模式），已记入交付 deviations
"""
import asyncio
import time
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.core import stats
from app.core.config import settings

_LEVEL_RANK = {"info": 0, "warn": 1, "critical": 2}

# 同规则节流表：[(project_id, rule_id)] -> 上次外发 monotonic 时刻
_throttle: dict[tuple[str, str], float] = {}


def reset_notify_state() -> None:
    """清空节流表（测试用）。"""
    _throttle.clear()


def _level_allowed(level: str) -> bool:
    min_rank = _LEVEL_RANK.get(settings.ALARM_NOTIFY_MIN_LEVEL, _LEVEL_RANK["warn"])
    return _LEVEL_RANK.get(level, 1) >= min_rank


def _should_send(project_id: str, rule_id: str) -> bool:
    """节流闸门：通过即占位（按尝试口径，避免失败渠道高频重放）。"""
    key = (project_id, rule_id)
    now = time.monotonic()
    last = _throttle.get(key)
    if last is not None and now - last < settings.ALARM_NOTIFY_THROTTLE_SEC:
        return False
    _throttle[key] = now
    return True


def _iso(dt: datetime) -> str:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _webhook_payload(rec, rule: dict | None) -> dict:
    """外发帧（03 §2.7 字段口径 + 工程/规则标识；triggeredAt 为 ISO8601 UTC）。"""
    return {
        "alarmId": rec.id,
        "projectId": str(rec.project_id),
        "ruleId": rec.rule_id,
        "ruleName": (rule or {}).get("name"),
        "variableKey": rec.variable_key,
        "level": rec.level,
        "message": rec.message,
        "value": rec.value,
        "status": rec.status,
        "triggeredAt": _iso(rec.triggered_at),
    }


def _build_webhook_client() -> httpx.AsyncClient:
    """客户端工厂（测试注入点：替换为 MockTransport 客户端）。"""
    return httpx.AsyncClient(timeout=settings.NOTIFY_WEBHOOK_TIMEOUT_MS / 1000)


async def _send_webhook(rec, rule: dict | None) -> bool:
    url = settings.NOTIFY_WEBHOOK_URL
    if not url:
        return False
    try:
        async with _build_webhook_client() as client:
            resp = await client.post(url, json=_webhook_payload(rec, rule))
        if not (200 <= resp.status_code < 300):
            stats.inc("notify_failed_total")
            logger.warning("webhook 外发失败（alarm={}）：HTTP {}", rec.id, resp.status_code)
            return False
        stats.inc("notify_sent_total")
        return True
    except Exception as exc:
        stats.inc("notify_failed_total")
        logger.warning("webhook 外发异常（alarm={}，不抛）：{}", rec.id, exc)
        return False


def _smtp_send_sync(rec, rule: dict | None) -> None:
    """阻塞 SMTP 发送（仅在线程池中执行）。收件人=NOTIFY_SMTP_FROM（自发自收）。"""
    import smtplib
    from email.message import EmailMessage

    rule_name = (rule or {}).get("name") or rec.rule_id
    msg = EmailMessage()
    msg["Subject"] = f"[webScada][{rec.level}] {rec.message}"
    msg["From"] = settings.NOTIFY_SMTP_FROM
    msg["To"] = settings.NOTIFY_SMTP_FROM
    msg.set_content(
        "\n".join(
            [
                f"工程：{rec.project_id}",
                f"规则：{rule_name}（{rec.rule_id}）",
                f"变量：{rec.variable_key}",
                f"级别：{rec.level}",
                f"值：{rec.value}",
                f"消息：{rec.message}",
                f"触发时间：{_iso(rec.triggered_at)}",
            ]
        )
    )
    if settings.NOTIFY_SMTP_USE_TLS:
        with smtplib.SMTP_SSL(settings.NOTIFY_SMTP_HOST, settings.NOTIFY_SMTP_PORT, timeout=10) as smtp:
            _smtp_login(smtp)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.NOTIFY_SMTP_HOST, settings.NOTIFY_SMTP_PORT, timeout=10) as smtp:
            _smtp_login(smtp)
            smtp.send_message(msg)


def _smtp_login(smtp) -> None:
    if settings.NOTIFY_SMTP_USERNAME:
        smtp.login(settings.NOTIFY_SMTP_USERNAME, settings.NOTIFY_SMTP_PASSWORD)


async def _send_email(rec, rule: dict | None) -> bool:
    if not settings.NOTIFY_SMTP_HOST:
        return False
    try:
        await asyncio.to_thread(_smtp_send_sync, rec, rule)
        stats.inc("notify_sent_total")
        return True
    except Exception as exc:
        stats.inc("notify_failed_total")
        logger.warning("邮件外发异常（alarm={}，不抛）：{}", rec.id, exc)
        return False


async def send_alarm(rec, rule: dict | None) -> None:
    """触发外发入口（alarm_service 新行后调用；签名冻结 §6.2，禁止改名）。

    rec: AlarmRecord 行；rule: 规则快照 dict（可 None）。级别/节流不满足静默返回；
    全部渠道失败仅计数告警，不抛（通知故障不阻断报警主流程）。
    """
    try:
        if not _level_allowed(rec.level):
            logger.debug("alarm {} 级别 {} 低于下发阈值 {}，不外发",
                         rec.id, rec.level, settings.ALARM_NOTIFY_MIN_LEVEL)
            return
        if not _should_send(str(rec.project_id), rec.rule_id):
            logger.debug("alarm {} 命中节流窗口（{}s），不外发",
                         rec.id, settings.ALARM_NOTIFY_THROTTLE_SEC)
            return
        results = await asyncio.gather(_send_webhook(rec, rule), _send_email(rec, rule))
        if not any(results):
            logger.debug("alarm {} 未配置任何通知渠道，跳过外发", rec.id)
    except Exception as exc:
        logger.warning("send_alarm 异常（不抛）：{}", exc)
