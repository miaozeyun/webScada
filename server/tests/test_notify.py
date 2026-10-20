"""notify 测试（B 包，契约 §6.2）：级别过滤、节流、webhook(httpx MockTransport)、SMTP 线程池。"""
import uuid as uuidlib
from datetime import datetime, timezone

import httpx
import pytest
import smtplib

from app.core import stats
from app.core.config import settings
from app.db.models import AlarmRecord
from app.services import notify

UTCD = timezone.utc


def counters() -> dict[str, float]:
    out: dict[str, float] = {}
    for line in stats.render().splitlines():
        if line and not line.startswith("#"):
            name, _, val = line.partition(" ")
            out[name] = float(val)
    return out


def make_rec(level: str = "critical", rule_id: str = "r1") -> AlarmRecord:
    return AlarmRecord(
        id=1,
        project_id=uuidlib.uuid4(),
        rule_id=rule_id,
        variable_key="temp_01",
        level=level,
        message="1号反应釜温度超高: 111.2",
        value="111.2",
        status="triggered",
        triggered_at=datetime(2026, 1, 1, 8, 30, 0, tzinfo=UTCD),
    )


RULE = {"id": "r1", "name": "温度超高"}


@pytest.fixture(autouse=True)
def _clean():
    notify.reset_notify_state()
    yield
    notify.reset_notify_state()


# ---------------- 级别过滤与节流 ----------------

async def test_level_filter_suppresses_below_min(monkeypatch):
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200)

    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "http://hook.local/alarm")
    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1))

    await notify.send_alarm(make_rec(level="info"), RULE)  # info < warn(缺省阈值) → 不外发
    assert calls == []
    await notify.send_alarm(make_rec(level="critical"), RULE)
    assert len(calls) == 1


async def test_throttle_same_rule_and_reset(monkeypatch):
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    monkeypatch.setattr(settings, "ALARM_NOTIFY_THROTTLE_SEC", 300)
    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "http://hook.local/alarm")
    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1))

    rec = make_rec()  # 固定 project_id：节流键为 (project_id, rule_id)
    await notify.send_alarm(rec, RULE)
    await notify.send_alarm(rec, RULE)  # 同规则节流窗口内 → 跳过
    same_project = make_rec(rule_id="r2")
    object.__setattr__(same_project, "project_id", rec.project_id)
    await notify.send_alarm(same_project, {"id": "r2", "name": "x"})  # 不同规则 → 放行
    assert len(calls) == 2

    notify.reset_notify_state()
    await notify.send_alarm(rec, RULE)  # 重置后再发
    assert len(calls) == 3


# ---------------- webhook（httpx MockTransport） ----------------

def _patch_hook(monkeypatch, handler) -> list[dict]:
    calls: list[dict] = []

    def rec(request: httpx.Request) -> httpx.Response:
        import json

        calls.append({"path": request.url.path,
                      "body": json.loads(request.content.decode("utf-8"))})
        return handler(request)

    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "http://hook.local/alarm")
    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(rec), timeout=1))
    return calls


async def test_webhook_payload_shape_and_sent_counter(monkeypatch):
    calls = _patch_hook(monkeypatch, lambda r: httpx.Response(200))
    before = counters()
    rec = make_rec()
    await notify.send_alarm(rec, RULE)
    after = counters()

    assert len(calls) == 1 and calls[0]["path"] == "/alarm"
    body = calls[0]["body"]
    assert body["alarmId"] == 1 and body["ruleId"] == "r1" and body["ruleName"] == "温度超高"
    assert body["variableKey"] == "temp_01" and body["level"] == "critical"
    assert body["message"] == rec.message and body["value"] == "111.2"
    assert body["status"] == "triggered" and body["triggeredAt"] == "2026-01-01T08:30:00+00:00"
    assert body["projectId"] == str(rec.project_id)
    assert after.get("webscada_notify_sent_total", 0) - before.get("webscada_notify_sent_total", 0) == 1
    assert after.get("webscada_notify_failed_total", 0) == before.get("webscada_notify_failed_total", 0)


async def test_webhook_non_2xx_counts_failed(monkeypatch):
    _patch_hook(monkeypatch, lambda r: httpx.Response(500))
    before = counters()
    await notify.send_alarm(make_rec(), RULE)  # 失败不抛
    after = counters()
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1
    assert after.get("webscada_notify_sent_total", 0) == before.get("webscada_notify_sent_total", 0)


async def test_webhook_transport_error_counts_failed(monkeypatch):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _patch_hook(monkeypatch, boom)
    before = counters()
    await notify.send_alarm(make_rec(), RULE)
    after = counters()
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1


# ---------------- 邮件（标准库 smtplib + asyncio.to_thread） ----------------

class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None
        self.sent: list = []
        self.fail_send = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        if self.fail_send:
            raise RuntimeError("smtp down")
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    yield


def _email_env(monkeypatch, use_tls=True):
    monkeypatch.setattr(settings, "NOTIFY_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_PORT", 465)
    monkeypatch.setattr(settings, "NOTIFY_SMTP_USERNAME", "ops@test")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_PASSWORD", "pw")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_FROM", "ops@test")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_USE_TLS", use_tls)


async def test_email_via_thread_pool(monkeypatch):
    _email_env(monkeypatch, use_tls=True)
    before = counters()
    await notify.send_alarm(make_rec(), RULE)
    after = counters()

    assert len(FakeSMTP.instances) == 1
    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.test" and smtp.port == 465
    assert smtp.logged_in == ("ops@test", "pw")
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["Subject"] == "[webScada][critical] 1号反应釜温度超高: 111.2"
    assert msg["From"] == "ops@test" and msg["To"] == "ops@test"  # 收件人=FROM（自发自收，见 deviations）
    assert "temp_01" in msg.get_content()
    assert after["webscada_notify_sent_total"] - before.get("webscada_notify_sent_total", 0) == 1


async def test_email_starttls_mode_uses_smtp_class(monkeypatch):
    _email_env(monkeypatch, use_tls=False)
    await notify.send_alarm(make_rec(), RULE)
    assert len(FakeSMTP.instances) == 1  # FakeSMTP 同时顶替 SMTP/SMTP_SSL，走非 SSL 分支即成功


async def test_email_failure_counts_failed_no_raise(monkeypatch):
    _email_env(monkeypatch)
    orig_init = FakeSMTP.__init__

    def failing_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.fail_send = True

    monkeypatch.setattr(FakeSMTP, "__init__", failing_init)
    before = counters()
    await notify.send_alarm(make_rec(), RULE)  # 不抛
    after = counters()
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1


async def test_both_channels_send_once_each(monkeypatch):
    calls = _patch_hook(monkeypatch, lambda r: httpx.Response(200))
    _email_env(monkeypatch)
    before = counters()
    await notify.send_alarm(make_rec(), RULE)
    after = counters()
    assert len(calls) == 1 and len(FakeSMTP.instances) == 1
    assert after["webscada_notify_sent_total"] - before.get("webscada_notify_sent_total", 0) == 2
