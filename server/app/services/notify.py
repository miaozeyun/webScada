"""报警通知外发（M8 契约 §6.2 → 工厂可用阶段二 Task 4 重构）。

渠道模型（doc.settings.notify.channels，按 kind 判别）：
- 工程 doc 渠道优先：get_project_channels(project_id) 按工程缓存（TTL 5s 兜底），
  保存/导入/删除经 project_service 热更新钩子调 invalidate_project_channels 即时失效
- 工程无 notify 配置 → env 回落：NOTIFY_WEBHOOK_URL 映射 webhook 渠道、
  NOTIFY_SMTP_HOST(+FROM) 映射 email 渠道（收件人沿 FROM 自发自收，M8 既有口径）；
  显式空 channels = 站内 only，不回落
- 级别过滤为渠道级：报警 level ≥ 渠道 minLevel（缺省 warn）才向该渠道外发
- 节流沿既有 (project_id, rule_id) 口径（工程级一次判定，与渠道数无关）

发送与重试：
- webhook(httpx 通用 JSON 帧) + 钉钉（毫秒时间戳加签 URL + text 消息）+
  企微（markdown 消息，无签名）+ 邮件（smtplib 线程池包装）
- 每渠道失败重试 3 次指数退避（1s/2s/4s）；仅网络类异常（httpx.TransportError/
  连接/超时）重试，HTTP 非 2xx（含 4xx 业务拒绝）不重试
- 全部渠道失败仅计数 stats.notify_failed_total / 成功计数 notify_sent_total（/metrics
  消费），不抛（通知故障不阻断报警主流程）；外发经 alarm_service._spawn 后台任务派发
"""
import asyncio
import base64
import hashlib
import hmac
import time
import urllib.parse
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from loguru import logger
from sqlalchemy import delete, select, update

from app.core import stats
from app.core.config import settings
from app.db.models import NotificationOutbox, Project
from app.utils.encrypt import decrypt, encrypt, looks_encrypted

_LEVEL_RANK = {"info": 0, "warn": 1, "critical": 2}

# 同规则节流表：[(project_id, rule_id)] -> 上次外发 monotonic 时刻
_throttle: dict[tuple[str, str], float] = {}

# 渠道缓存：project_id -> (monotonic 加载时刻, 已解析渠道列表)。
# 失效双保险：保存/导入/删除钩子 invalidate_project_channels 即时失效 + TTL 兜底
# （沿 rules_engine.RULES_TTL_SEC 先例：钩子遗漏时新渠道最迟 TTL 后生效）
CHANNELS_TTL_SEC = 5.0
_channel_cache: dict[str, tuple[float, list[dict]]] = {}

# 网络类异常重试退避序列（1s/2s/4s，共 3 次重试；测试缝：monkeypatch 归零保速度）
RETRY_BACKOFF_SEC: tuple[float, ...] = (1.0, 2.0, 4.0)

# 会话工厂注入点（与 rules_engine/audit_service 同款测试缝）：None 时惰性取 app.db.base.SessionLocal
session_factory = None


def _get_session_factory():
    if session_factory is not None:
        return session_factory
    from app.db.base import SessionLocal  # 惰性：避免导入期连库副作用

    return SessionLocal


def reset_notify_state() -> None:
    """清空节流表与渠道缓存（测试用）。"""
    _throttle.clear()
    _channel_cache.clear()


# ---------------- 渠道解析（doc 优先 / env 回落） ----------------


async def get_project_channels(project_id) -> list[dict]:
    """取工程外发渠道（缓存 + TTL）。

    返回运行时形状（勿就地修改，缓存共享列表）：
    {"kind": str, "minLevel": str, "url": str(非 email), "secret": str(仅 dingtalk),
     "recipients": list[str](仅 email)}
    """
    pid = str(project_id)
    hit = _channel_cache.get(pid)
    if hit is not None and time.monotonic() - hit[0] < CHANNELS_TTL_SEC:
        return hit[1]
    channels = await _resolve_project_channels(pid)
    _channel_cache[pid] = (time.monotonic(), channels)
    return channels


def invalidate_project_channels(project_id) -> None:
    """失效单工程渠道缓存（project_service 保存/导入/删除热更新钩子调用）。"""
    _channel_cache.pop(str(project_id), None)


async def _resolve_project_channels(pid: str) -> list[dict]:
    doc = await _load_project_doc(pid)
    if doc is not None:
        channels = _channels_from_doc(doc)
        if channels is not None:  # notify 已配置（含显式空列表）→ doc 为准
            return channels
    return _env_fallback_channels()


async def _load_project_doc(pid: str) -> dict | None:
    """读库内工程 doc；不存在/读取失败返回 None（失败回落 env，不阻断外发）。"""
    try:
        key = uuidlib.UUID(pid)
    except ValueError:
        return None
    try:
        async with _get_session_factory()() as db:
            row = await db.get(Project, key)
    except Exception as exc:  # noqa: BLE001 - 库不可用不拖垮报警外发
        logger.warning("通知渠道读取工程 doc 失败（project={}，回落 env 渠道）：{}", pid, exc)
        return None
    return row.doc if row is not None and isinstance(row.doc, dict) else None


def _channels_from_doc(doc: dict) -> list[dict] | None:
    """解析 doc.settings.notify.channels；未配置（无 notify 键）返回 None 表示回落 env。"""
    notify_cfg = (doc.get("settings") or {}).get("notify")
    if not isinstance(notify_cfg, dict):
        return None
    out: list[dict] = []
    for ch in notify_cfg.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        kind = str(ch.get("kind", ""))
        entry: dict = {"kind": kind, "minLevel": str(ch.get("minLevel") or "warn")}
        if kind == "email":
            entry["recipients"] = [str(r) for r in (ch.get("recipients") or []) if r]
        else:
            url = ch.get("url")
            if not url:
                logger.warning("通知渠道 {} 缺 url，跳过", kind)
                continue
            entry["url"] = str(url)
            if kind == "dingtalk":
                entry["secret"] = _decrypt_secret(ch.get("secret"))
        out.append(entry)
    return out


def _decrypt_secret(value) -> str:
    """钉钉加签密钥解密（库内 FER1: 密文）；解密失败降级为空串并告警（签名依赖此值）。"""
    if not isinstance(value, str) or not value:
        return ""
    if looks_encrypted(value):
        try:
            return decrypt(value)
        except ValueError as exc:
            logger.warning("钉钉 secret 解密失败（按无签名发送，可重填密钥恢复）：{}", exc)
            return ""
    return value


def _env_fallback_channels() -> list[dict]:
    """工程无 notify 配置时的 env 回落渠道（M8 单渠道行为的等价映射）。"""
    channels: list[dict] = []
    min_level = settings.ALARM_NOTIFY_MIN_LEVEL
    if settings.NOTIFY_WEBHOOK_URL:
        channels.append({"kind": "webhook", "url": settings.NOTIFY_WEBHOOK_URL, "minLevel": min_level})
    if settings.NOTIFY_SMTP_HOST and settings.NOTIFY_SMTP_FROM:
        channels.append({"kind": "email", "recipients": [settings.NOTIFY_SMTP_FROM], "minLevel": min_level})
    return channels


# ---------------- 节流与渠道级过滤 ----------------


def _channel_allows(channel: dict, level: str) -> bool:
    """渠道级级别过滤：报警级别 ≥ 渠道 minLevel（缺省/未知按 warn）。"""
    min_rank = _LEVEL_RANK.get(str(channel.get("minLevel", "warn")), _LEVEL_RANK["warn"])
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


# ---------------- 发送（重试包装 + 各渠道 sender） ----------------


class _HttpRejected(Exception):
    """HTTP 非 2xx 响应（业务拒绝，不重试）。"""


def _is_retryable(exc: BaseException) -> bool:
    """网络类异常才重试：httpx 传输层（连接拒绝/超时等）与连接/超时类（SMTP 侧）。"""
    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError, OSError))


async def _send_with_retry(label: str, rec, send) -> bool:
    """单渠道发送包装：网络类异常重试 3 次（1s/2s/4s 退避）；HTTP 非 2xx 不重试。
    成败各计一次 stats，异常不外抛。"""
    attempt = 0
    while True:
        try:
            await send()
            stats.inc("notify_sent_total")
            return True
        except _HttpRejected as exc:
            stats.inc("notify_failed_total")
            logger.warning("{} 外发失败（alarm={}）：{}", label, rec.id, exc)
            return False
        except Exception as exc:  # noqa: BLE001 - 单渠道故障不拖垮其他渠道
            if attempt < len(RETRY_BACKOFF_SEC) and _is_retryable(exc):
                delay = RETRY_BACKOFF_SEC[attempt]
                logger.warning("{} 外发网络异常（alarm={}，{}s 后第 {}/3 次重试）：{}",
                               label, rec.id, delay, attempt + 1, exc)
                await asyncio.sleep(delay)
                attempt += 1
                continue
            stats.inc("notify_failed_total")
            logger.warning("{} 外发异常（alarm={}，不抛）：{}", label, rec.id, exc)
            return False


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


def _url_label(url: str) -> str:
    """日志用渠道标识：只取 host（钉钉/企微 URL 内嵌 access_token/key，不得进日志）。"""
    try:
        return httpx.URL(url).host or url
    except Exception:  # noqa: BLE001
        return "webhook"


async def _post_webhook_json(url: str, payload: dict) -> None:
    """POST JSON；非 2xx 抛 _HttpRejected（不重试），传输异常原样上抛（可重试）。"""
    async with _build_webhook_client() as client:
        resp = await client.post(url, json=payload)
    if not (200 <= resp.status_code < 300):
        raise _HttpRejected(f"HTTP {resp.status_code}")


async def _send_webhook(url: str, rec, rule: dict | None) -> bool:
    payload = _webhook_payload(rec, rule)
    label = f"webhook 渠道（{_url_label(url)}）"
    return await _send_with_retry(label, rec, lambda: _post_webhook_json(url, payload))


def _im_content(rec) -> str:
    """钉钉/企微消息内容（字段拼装口径同 _webhook_payload：工程/变量/级别/消息）。"""
    return f"[webScada] {rec.project_id} {rec.variable_key} {rec.level}: {rec.message}"


def _dingtalk_sign(timestamp_ms: str, secret: str) -> str:
    """钉钉加签（官方算法）：HMAC-SHA256(key=secret, msg="{ts}\\n{secret}") → base64 → urlencode。

    timestamp_ms 为毫秒字符串、原样进 URL；sign 值整体 percent-encode（base64 含 + / =）。
    固定向量（tests/test_notify.py::test_dingtalk_sign_fixed_vector）钉死时序与编码：
    ts="1719000000000"、secret="SECxxxxxxxx" → "eEsnMtGBnVSrU792VPws3CYOLHUvCJH1RrfgCoHHrLc%3D"
    """
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


async def _send_dingtalk(url: str, secret: str, rec, rule: dict | None) -> bool:
    """钉钉渠道：URL 追加 timestamp/sign 加签参数 + text 消息。

    secret 为空（未配置/解密失败降级）→ 不加签按原 URL 发送（_decrypt_secret 口径）。
    """
    label = f"钉钉渠道（{_url_label(url)}）"

    def _signed_url() -> str:
        # 每次尝试现算时间戳与签名：重试退避后再发须用新时刻；URL 已含 ?access_token=... 故追加用 &
        if not secret:
            return url
        ts = str(int(time.time() * 1000))
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}timestamp={ts}&sign={_dingtalk_sign(ts, secret)}"

    payload = {"msgtype": "text", "text": {"content": _im_content(rec)}}
    return await _send_with_retry(label, rec, lambda: _post_webhook_json(_signed_url(), payload))


async def _send_wecom(url: str, rec, rule: dict | None) -> bool:
    """企微渠道：markdown 消息、无签名，URL 原样。"""
    payload = {"msgtype": "markdown", "markdown": {"content": _im_content(rec)}}
    label = f"企微渠道（{_url_label(url)}）"
    return await _send_with_retry(label, rec, lambda: _post_webhook_json(url, payload))


def _smtp_send_sync(rec, rule: dict | None, recipients: list[str]) -> None:
    """阻塞 SMTP 发送（仅在线程池中执行）。From/账号走 env；To 取渠道收件人。"""
    import smtplib
    from email.message import EmailMessage

    rule_name = (rule or {}).get("name") or rec.rule_id
    msg = EmailMessage()
    msg["Subject"] = f"[webScada][{rec.level}] {rec.message}"
    msg["From"] = settings.NOTIFY_SMTP_FROM
    msg["To"] = ", ".join(recipients)
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


async def _send_email(recipients: list[str], rec, rule: dict | None) -> bool:
    """邮件渠道：收件人来自 doc 渠道（env 回落时为 NOTIFY_SMTP_FROM）；SMTP 服务参数为 env。"""
    if not settings.NOTIFY_SMTP_HOST or not recipients:
        # 显式失败而非静默吞：工程配了邮件渠道但服务端 SMTP 未配置/收件人空——
        # 「配了收件人却收不到信」必须可发现（计数进 /metrics + 日志指出解法）
        reason = (
            "服务端未配置 SMTP（NOTIFY_SMTP_HOST 为空），请在服务端 .env 配置 NOTIFY_SMTP_HOST/NOTIFY_SMTP_FROM"
            if not settings.NOTIFY_SMTP_HOST
            else "渠道收件人列表为空"
        )
        stats.inc("notify_failed_total")
        logger.warning("邮件渠道未发送（alarm={}）：{}", rec.id, reason)
        return False
    return await _send_with_retry(
        "邮件渠道", rec, lambda: asyncio.to_thread(_smtp_send_sync, rec, rule, recipients)
    )


async def _dispatch_channel(channel: dict, rec, rule: dict | None) -> tuple[bool, str | None]:
    """按 kind 分发到对应 sender；返回 (是否成功, 失败原因)。"""
    kind = channel.get("kind")
    try:
        if kind == "webhook":
            ok = await _send_webhook(channel["url"], rec, rule)
        elif kind == "dingtalk":
            ok = await _send_dingtalk(channel["url"], str(channel.get("secret") or ""), rec, rule)
        elif kind == "wecom":
            ok = await _send_wecom(channel["url"], rec, rule)
        elif kind == "email":
            ok = await _send_email(channel.get("recipients") or [], rec, rule)
        else:
            logger.warning("未知通知渠道 kind={}，跳过", kind)
            return False, f"未知渠道 kind={kind}"
    except Exception as exc:  # noqa: BLE001 - 单渠道异常不影响其他渠道
        return False, f"{type(exc).__name__}: {exc}"
    return (True, None) if ok else (False, "发送失败（渠道返回非成功）")


# ---------------- 补发队列（outbox） ----------------


def _rec_snapshot(rec, *, status: str | None = None, message: str | None = None) -> dict:
    return {
        "id": rec.id,
        "project_id": str(rec.project_id),
        "rule_id": rec.rule_id,
        "variable_key": rec.variable_key,
        "level": rec.level,
        "message": message if message is not None else rec.message,
        "value": rec.value,
        "status": status if status is not None else rec.status,
        "triggered_at": _iso(rec.triggered_at),
    }


def _rec_from_snapshot(data: dict):
    triggered = data.get("triggered_at")
    try:
        dt = datetime.fromisoformat(str(triggered)) if triggered else datetime.now(timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=data.get("id"),
        project_id=uuidlib.UUID(str(data.get("project_id"))),
        rule_id=str(data.get("rule_id") or ""),
        variable_key=str(data.get("variable_key") or ""),
        level=str(data.get("level") or "warn"),
        message=str(data.get("message") or ""),
        value=data.get("value"),
        status=str(data.get("status") or "triggered"),
        triggered_at=dt,
    )


_SEALED_CHANNEL_KEYS = ("url", "secret")


def _seal_channel(channel: dict) -> dict:
    """入库前加密渠道 URL/签名密钥：URL 内嵌 access_token，不得明文落库（K11 同口径）。"""
    out = dict(channel)
    for key in _SEALED_CHANNEL_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val and not looks_encrypted(val):
            out[key] = encrypt(val)
    return out


def _open_channel(channel: dict) -> dict:
    out = dict(channel)
    for key in _SEALED_CHANNEL_KEYS:
        val = out.get(key)
        if isinstance(val, str) and looks_encrypted(val):
            out[key] = decrypt(val)
    return out


def _outbox_delay_sec(attempts: int) -> float:
    """指数退避：30s → 1m → 2m → 4m … 封顶 30min。"""
    base = 30.0
    return min(base * (2 ** max(attempts - 1, 0)), 1800.0)


async def _enqueue(channel: dict, rec, rule: dict | None, event: str, error: str | None) -> None:
    """发送失败的渠道落 pending 行（同一 alarm+渠道+事件去重，避免重试风暴叠加）。"""
    try:
        now = datetime.now(timezone.utc)
        async with _get_session_factory()() as db:
            # 去重按「同一 alarm + 事件 + 同一渠道（解密后全等）」，不是只比 kind：
            # 一个工程可以配两个 webhook，按 kind 去重会吞掉第二条。
            pending_rows = (
                await db.execute(
                    select(NotificationOutbox).where(
                        NotificationOutbox.project_id == rec.project_id,
                        NotificationOutbox.alarm_id == rec.id,
                        NotificationOutbox.event == event,
                        NotificationOutbox.status.in_(("pending", "sending")),
                    )
                )
            ).scalars().all()
            for row in pending_rows:
                try:
                    if _open_channel(row.channel_json) == channel:
                        return
                except Exception:  # noqa: BLE001 - 坏行不阻断新入队
                    continue
            db.add(
                NotificationOutbox(
                    project_id=rec.project_id,
                    alarm_id=rec.id,
                    event=event,
                    channel_kind=str(channel.get("kind")),
                    channel_json=_seal_channel(channel),
                    payload_json={"rec": _rec_snapshot(rec), "rule": rule or {}},
                    status="pending",
                    attempts=0,
                    next_at=now + timedelta(seconds=_outbox_delay_sec(0)),
                    last_error=error,
                )
            )
            await db.commit()
        stats.inc("notify_queued_total")
    except Exception as exc:  # noqa: BLE001 - 入队失败不阻断报警主流程
        logger.warning("通知入队失败（alarm={} kind={}）：{}", getattr(rec, "id", "?"), channel.get("kind"), exc)


async def _record_sent(channel: dict, rec, rule: dict | None, event: str) -> None:
    """即时发送成功也留一条 sent 记录（2026-10-26）：否则管理端无法回答
    「这条报警到底发出去没有」——outbox 此前只存失败行。"""
    try:
        now = datetime.now(timezone.utc)
        async with _get_session_factory()() as db:
            db.add(
                NotificationOutbox(
                    project_id=rec.project_id,
                    alarm_id=rec.id,
                    event=event,
                    channel_kind=str(channel.get("kind")),
                    channel_json=_seal_channel(channel),
                    payload_json={"rec": _rec_snapshot(rec), "rule": rule or {}},
                    status="sent",
                    attempts=1,
                    next_at=now,
                    sent_at=now,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - 记录失败不影响通知已送达的事实
        logger.warning("通知成功记录失败（alarm={} kind={}）：{}", getattr(rec, "id", "?"), channel.get("kind"), exc)


async def send_alarm(rec, rule: dict | None) -> None:
    """触发外发入口（alarm_service 新行后调用；签名冻结 §6.2，禁止改名）。

    rec: AlarmRecord 行（project_id 即渠道解析上下文）；rule: 规则快照 dict（可 None）。
    渠道级级别过滤 / (project, rule) 节流不满足静默返回；单渠道失败落 outbox 由后台补发，
    不抛（通知故障不阻断报警主流程）。
    """
    try:
        pid = str(rec.project_id)
        channels = [ch for ch in await get_project_channels(pid) if _channel_allows(ch, rec.level)]
        if not channels:
            logger.debug("alarm {} 无可发渠道（级别 {} 被全部渠道阈值过滤或工程/env 均未配置）",
                         rec.id, rec.level)
            return
        if not _should_send(pid, rec.rule_id):
            logger.debug("alarm {} 命中节流窗口（{}s），不外发",
                         rec.id, settings.ALARM_NOTIFY_THROTTLE_SEC)
            return
        results = await asyncio.gather(*(_dispatch_channel(ch, rec, rule) for ch in channels))
        for channel, (ok, error) in zip(channels, results, strict=False):
            if ok:
                await _record_sent(channel, rec, rule, "trigger")
            else:
                await _enqueue(channel, rec, rule, "trigger", error)
        if not any(ok for ok, _ in results):
            logger.debug("alarm {} 全部渠道发送失败（已入补发队列）", rec.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_alarm 异常（不抛）：{}", exc)


async def send_recovery(rec) -> None:
    """恢复通知（报警 clear 后调用）：不受触发节流限制；失败同样进补发队列。"""
    try:
        pid = str(rec.project_id)
        channels = [ch for ch in await get_project_channels(pid) if _channel_allows(ch, rec.level)]
        if not channels:
            return
        snap = SimpleNamespace(
            id=rec.id,
            project_id=rec.project_id,
            rule_id=rec.rule_id,
            variable_key=rec.variable_key,
            level=rec.level,
            message=f"报警恢复：{rec.message}",
            value=rec.value,
            status="cleared",
            triggered_at=rec.triggered_at,
        )
        results = await asyncio.gather(*(_dispatch_channel(ch, snap, None) for ch in channels))
        for channel, (ok, error) in zip(channels, results, strict=False):
            if ok:
                await _record_sent(channel, snap, None, "recovery")
            else:
                await _enqueue(channel, snap, None, "recovery", error)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_recovery 异常（不抛）：{}", exc)


async def cleanup_outbox(db) -> int:
    """清理已发送/死信历史行（每日维护调用）；pending/sending 一律保留。"""
    now = datetime.now(timezone.utc)
    sent_cut = now - timedelta(days=settings.OUTBOX_SENT_KEEP_DAYS)
    dead_cut = now - timedelta(days=settings.OUTBOX_DEAD_KEEP_DAYS)
    res1 = await db.execute(
        delete(NotificationOutbox)
        .where(NotificationOutbox.status == "sent", NotificationOutbox.sent_at < sent_cut)
        .execution_options(synchronize_session=False)
    )
    res2 = await db.execute(
        delete(NotificationOutbox)
        .where(NotificationOutbox.status == "dead", NotificationOutbox.created_at < dead_cut)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return int(res1.rowcount or 0) + int(res2.rowcount or 0)


async def process_outbox(limit: int = 20) -> int:
    """补发到期行：claim → 发送 → sent / 退避重排 / dead。返回本轮处理条数。"""
    now = datetime.now(timezone.utc)
    processed = 0
    try:
        async with _get_session_factory()() as db:
            # 崩溃恢复：claimed 后进程被杀会留下 sending 僵尸，超过 5 分钟回收
            await db.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.status == "sending",
                    NotificationOutbox.next_at <= now - timedelta(minutes=5),
                )
                .values(status="pending")
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            rows = (
                await db.execute(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.status == "pending",
                        NotificationOutbox.next_at <= now,
                    )
                    .order_by(NotificationOutbox.next_at.asc())
                    .limit(limit)
                )
            ).scalars().all()
            for row in rows:
                claimed = await db.execute(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.id == row.id, NotificationOutbox.status == "pending")
                    .values(status="sending")
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                if not claimed.rowcount:
                    continue
                processed += 1
                # 单行解密/解析/发送异常不得中断整轮：否则该行永远停在 sending，
                # 同轮其余到期行被跳过，队列也永远清不空。
                try:
                    rec = _rec_from_snapshot(row.payload_json.get("rec") or {})
                    rule = row.payload_json.get("rule") or None
                    ok, error = await _dispatch_channel(_open_channel(row.channel_json), rec, rule)
                except Exception as exc:  # noqa: BLE001
                    ok, error = False, f"{type(exc).__name__}: {exc}"
                done_at = datetime.now(timezone.utc)
                if ok:
                    await db.execute(
                        update(NotificationOutbox)
                        .where(NotificationOutbox.id == row.id)
                        .values(status="sent", sent_at=done_at, last_error=None)
                        .execution_options(synchronize_session=False)
                    )
                    stats.inc("notify_outbox_sent_total")
                else:
                    attempts = int(row.attempts or 0) + 1
                    dead = attempts >= 8
                    await db.execute(
                        update(NotificationOutbox)
                        .where(NotificationOutbox.id == row.id)
                        .values(
                            status="dead" if dead else "pending",
                            attempts=attempts,
                            next_at=done_at + timedelta(seconds=_outbox_delay_sec(attempts)),
                            last_error=(error or "发送失败")[:1000],
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if dead:
                        stats.inc("notify_outbox_dead_total")
                        logger.warning("通知补发超过上限，转死信（alarm={} kind={}）：{}",
                                       row.alarm_id, row.channel_kind, error)
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox 补发轮次异常（不抛）：{}", exc)
    return processed
