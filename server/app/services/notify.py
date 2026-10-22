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
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.core import stats
from app.core.config import settings
from app.db.models import Project
from app.utils.encrypt import decrypt, looks_encrypted

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


async def _dispatch_channel(channel: dict, rec, rule: dict | None) -> bool:
    """按 kind 分发到对应 sender。"""
    kind = channel.get("kind")
    if kind == "webhook":
        return await _send_webhook(channel["url"], rec, rule)
    if kind == "dingtalk":
        return await _send_dingtalk(channel["url"], str(channel.get("secret") or ""), rec, rule)
    if kind == "wecom":
        return await _send_wecom(channel["url"], rec, rule)
    if kind == "email":
        return await _send_email(channel.get("recipients") or [], rec, rule)
    logger.warning("未知通知渠道 kind={}，跳过", kind)
    return False


async def send_alarm(rec, rule: dict | None) -> None:
    """触发外发入口（alarm_service 新行后调用；签名冻结 §6.2，禁止改名）。

    rec: AlarmRecord 行（project_id 即渠道解析上下文）；rule: 规则快照 dict（可 None）。
    渠道级级别过滤 / (project, rule) 节流不满足静默返回；全部渠道失败仅计数告警，
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
        if not any(results):
            logger.debug("alarm {} 全部渠道发送失败", rec.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_alarm 异常（不抛）：{}", exc)
