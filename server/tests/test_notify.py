"""notify 测试（B 包，契约 §6.2）：级别过滤、节流、webhook(httpx MockTransport)、SMTP 线程池。
工厂可用阶段二 Task 4：通知渠道落工程 doc（工程配置优先/env 回落/缓存失效/重试/凭证管线）。"""
import uuid as uuidlib
from datetime import datetime, timezone

import httpx
import pytest
import smtplib

from app.core import stats
from app.core.config import settings
from app.db.models import AlarmRecord, Project
from app.services import notify
from tests.conftest import make_doc, put_doc

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
def _clean(db_factory, monkeypatch):
    """每测试清空节流表 + 渠道缓存；渠道读取的会话工厂指向当前测试库（rules_engine 同款测试缝）。"""
    monkeypatch.setattr(notify, "session_factory", db_factory)
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

    monkeypatch.setattr(notify, "RETRY_BACKOFF_SEC", (0, 0, 0))  # 网络类异常会重试：退避归零保测试速度
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


# ---------------- 通知渠道落工程 doc（工厂可用阶段二 Task 4） ----------------


def make_rec_for(pid, level: str = "critical", rule_id: str = "r1") -> AlarmRecord:
    """指定工程的报警行（渠道解析依赖 rec.project_id）。"""
    return AlarmRecord(
        id=99,
        project_id=pid if isinstance(pid, uuidlib.UUID) else uuidlib.UUID(str(pid)),
        rule_id=rule_id,
        variable_key="temp_01",
        level=level,
        message="1号反应釜温度超高: 111.2",
        value="111.2",
        status="triggered",
        triggered_at=datetime(2026, 1, 1, 8, 30, 0, tzinfo=UTCD),
    )


async def _mk_project(client, auth_headers, doc: dict | None = None) -> tuple[str, int]:
    """新建工程（可选先 PUT doc），返回 (pid, revision)。"""
    resp = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "通知测试工程"})
    assert resp.status_code == 201
    pid = resp.json()["id"]
    rev = 1
    if doc is not None:
        r = await put_doc(client, auth_headers, pid, doc)
        assert r.status_code == 200, r.text
        rev = r.json()["revision"]
    return pid, rev


def _notify_doc(channels: list[dict]) -> dict:
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": channels}
    return doc


def _patch_webhook_urls(monkeypatch) -> list[str]:
    """捕获外发完整 URL（MockTransport）。"""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200)

    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1))
    return urls


async def test_project_channels_webhook_and_email_both_send(client, auth_headers, monkeypatch):
    """工程 doc 配 2 渠道（webhook+email）→ 两路都发；渠道来自 doc 而非 env。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/alarm"},
        {"kind": "email", "recipients": ["a@ops.test", "b@ops.test"]},
    ]))

    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "")  # env 留空：证明渠道取自工程 doc
    monkeypatch.setattr(settings, "NOTIFY_SMTP_HOST", "")    # SMTP 参数仍走 env → 邮件渠道依赖 _email_env
    _email_env(monkeypatch)
    urls = _patch_webhook_urls(monkeypatch)

    before = counters()
    await notify.send_alarm(make_rec_for(pid), RULE)
    after = counters()

    assert urls == ["https://hook.local/alarm"]
    assert len(FakeSMTP.instances) == 1
    assert FakeSMTP.instances[0].sent[0]["To"] == "a@ops.test, b@ops.test"  # 收件人取自 doc 渠道
    assert after["webscada_notify_sent_total"] - before.get("webscada_notify_sent_total", 0) == 2


async def test_project_channel_min_level_filters_per_channel(client, auth_headers, monkeypatch):
    """minLevel 为渠道级：warn 报警只发 warn 渠道，critical 两路都发。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/crit-only", "minLevel": "critical"},
        {"kind": "email", "recipients": ["ops@ops.test"], "minLevel": "warn"},
    ]))
    _email_env(monkeypatch)
    urls = _patch_webhook_urls(monkeypatch)

    await notify.send_alarm(make_rec_for(pid, level="warn"), RULE)
    assert urls == []                              # warn 低于 critical 渠道阈值 → 不发
    assert len(FakeSMTP.instances) == 1            # email 渠道阈值 warn → 发

    await notify.send_alarm(make_rec_for(pid, level="critical", rule_id="r2"), RULE)
    assert urls == ["https://hook.local/crit-only"]
    assert len(FakeSMTP.instances) == 2


async def test_no_doc_config_falls_back_to_env(client, auth_headers, monkeypatch):
    """工程无 notify 配置 → env 回落：NOTIFY_WEBHOOK_URL 映射为 webhook 渠道。"""
    pid, _ = await _mk_project(client, auth_headers, make_doc())
    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "http://hook.local/env")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_HOST", "")
    urls = _patch_webhook_urls(monkeypatch)

    await notify.send_alarm(make_rec_for(pid), RULE)
    assert urls == ["http://hook.local/env"]


async def test_no_channels_anywhere_sends_nothing(client, auth_headers, monkeypatch):
    """工程无配置 + env 全空 → 空列表 = 站内 only，无任何外发。"""
    pid, _ = await _mk_project(client, auth_headers, make_doc())
    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_HOST", "")
    urls = _patch_webhook_urls(monkeypatch)

    before = counters()
    await notify.send_alarm(make_rec_for(pid), RULE)
    after = counters()
    assert urls == [] and FakeSMTP.instances == []
    assert after.get("webscada_notify_sent_total", 0) == before.get("webscada_notify_sent_total", 0)


async def test_doc_empty_channels_disables_env_fallback(client, auth_headers, monkeypatch):
    """显式空 channels（工程已配置通知）→ 不回落 env，站内 only。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([]))
    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "http://hook.local/env")
    urls = _patch_webhook_urls(monkeypatch)

    await notify.send_alarm(make_rec_for(pid), RULE)
    assert urls == []


async def test_channel_cache_invalidation_on_save_and_direct(client, auth_headers, db_factory, monkeypatch):
    """缓存双保险：API 保存经热更新钩子失效（Review Focus #4）；直改库 + invalidate 直测立即生效。"""
    pid, rev = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/a"},
    ]))
    urls = _patch_webhook_urls(monkeypatch)

    await notify.send_alarm(make_rec_for(pid, rule_id="r1"), RULE)
    assert urls == ["https://hook.local/a"]        # 首发已填充渠道缓存

    # API 保存新 URL（保存热更新钩子失效缓存，TTL 内也用新渠道）
    resp = await put_doc(client, auth_headers, pid, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/b"},
    ]), base_revision=rev)
    assert resp.status_code == 200
    await notify.send_alarm(make_rec_for(pid, rule_id="r2"), RULE)
    assert urls == ["https://hook.local/a", "https://hook.local/b"]

    # 直改库 + invalidate_project_channels 直测（不经保存流水线）
    from sqlalchemy.orm.attributes import flag_modified

    async with db_factory() as session:
        project = await session.get(Project, uuidlib.UUID(pid))
        project.doc["settings"]["notify"]["channels"][0]["url"] = "https://hook.local/c"
        flag_modified(project, "doc")              # dict 重赋值 == 原值不会标脏，须显式 flag
        await session.commit()
    notify.invalidate_project_channels(pid)
    await notify.send_alarm(make_rec_for(pid, rule_id="r3"), RULE)
    assert urls == ["https://hook.local/a", "https://hook.local/b", "https://hook.local/c"]


async def test_retry_exactly_three_times_on_network_error(client, auth_headers, monkeypatch):
    """网络类异常重试恰 3 次（初次+3=4 次尝试）；失败计数只记一次。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/flaky"},
    ]))
    attempts = {"n": 0}

    def boom(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(notify, "RETRY_BACKOFF_SEC", (0, 0, 0))  # 退避归零保测试速度
    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom), timeout=1))
    before = counters()
    await notify.send_alarm(make_rec_for(pid), RULE)
    after = counters()
    assert attempts["n"] == 4
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1
    assert after.get("webscada_notify_sent_total", 0) == before.get("webscada_notify_sent_total", 0)


async def test_http_4xx_business_rejection_no_retry(client, auth_headers, monkeypatch):
    """HTTP 4xx 业务拒绝不重试（仅 1 次尝试即放弃）。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "webhook", "url": "https://hook.local/reject"},
    ]))
    attempts = {"n": 0}

    def reject(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400)

    monkeypatch.setattr(notify, "RETRY_BACKOFF_SEC", (0, 0, 0))
    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(reject), timeout=1))
    before = counters()
    await notify.send_alarm(make_rec_for(pid), RULE)
    after = counters()
    assert attempts["n"] == 1
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1


async def test_dingtalk_secret_sanitized_out_and_encrypted_in_db(client, auth_headers, db_factory):
    """钉钉 secret：GET 详情/导出一律空串；库内为 FER1: 密文（分享快照走同一脱敏出口）。"""
    from app.utils.encrypt import decrypt

    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "dingtalk", "url": "https://oapi.dingtalk.com/robot/send?access_token=tok",
         "secret": "SECxxx"},
    ]))

    body = (await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)).json()
    ch_out = body["doc"]["settings"]["notify"]["channels"][0]
    assert ch_out["secret"] == ""
    assert ch_out["url"] == "https://oapi.dingtalk.com/robot/send?access_token=tok"

    export = (await client.get(f"/api/v1/projects/{pid}/export", headers=auth_headers)).json()
    assert export["settings"]["notify"]["channels"][0]["secret"] == ""

    async with db_factory() as session:
        stored = (await session.get(Project, uuidlib.UUID(pid))).doc
    stored_secret = stored["settings"]["notify"]["channels"][0]["secret"]
    assert stored_secret.startswith("FER1:")
    assert decrypt(stored_secret) == "SECxxx"


async def test_email_channel_without_smtp_env_counts_failed_with_warning(client, auth_headers, monkeypatch):
    """工程配了邮件渠道但服务端未配 NOTIFY_SMTP_HOST：显式失败计数 + warning（不静默吞）。"""
    from loguru import logger as loguru_logger

    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "email", "recipients": ["ops@ops.test"]},
    ]))
    monkeypatch.setattr(settings, "NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "NOTIFY_SMTP_HOST", "")  # 服务端 SMTP 未配置
    urls = _patch_webhook_urls(monkeypatch)

    messages: list[str] = []
    sink_id = loguru_logger.add(lambda m: messages.append(m), level="WARNING")
    try:
        before = counters()
        await notify.send_alarm(make_rec_for(pid), RULE)
        after = counters()
    finally:
        loguru_logger.remove(sink_id)

    assert urls == [] and FakeSMTP.instances == []
    assert after["webscada_notify_failed_total"] - before.get("webscada_notify_failed_total", 0) == 1
    assert any("NOTIFY_SMTP_HOST" in str(m) for m in messages)


async def test_secret_put_merge_empty_keeps_null_clears(client, auth_headers, db_factory):
    """PUT 空值合并（沿数据源规则⑤）：空串=保留库内密文；显式 null=清除。"""
    from app.utils.encrypt import decrypt

    pid, rev = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "dingtalk", "url": "https://oapi.dingtalk.com/robot/send?access_token=tok",
         "secret": "S1"},
    ]))

    async def stored_secret():
        async with db_factory() as session:
            stored = (await session.get(Project, uuidlib.UUID(pid))).doc
        return stored["settings"]["notify"]["channels"][0].get("secret")

    # 编辑器回读（脱敏 secret=""）→ 用户改无关项 → 原样 PUT → 空串保留库内值
    doc2 = (await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)).json()["doc"]
    assert doc2["settings"]["notify"]["channels"][0]["secret"] == ""
    resp = await put_doc(client, auth_headers, pid, doc2, base_revision=rev)
    assert resp.status_code == 200
    kept = await stored_secret()
    assert kept is not None and kept.startswith("FER1:")
    assert decrypt(kept) == "S1"

    # 显式 null → 清除（库内键删除）
    doc3 = (await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)).json()["doc"]
    doc3["settings"]["notify"]["channels"][0]["secret"] = None
    resp = await put_doc(client, auth_headers, pid, doc3, base_revision=resp.json()["revision"])
    assert resp.status_code == 200
    assert await stored_secret() is None


# ---------------- 钉钉/企微专属发送（工厂可用阶段二 Task 5） ----------------


def _capture_posts(monkeypatch) -> list[dict]:
    """捕获外发完整 URL + 请求体（沿 _patch_webhook_urls 的 MockTransport 模式扩展 body）。"""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append({"url": str(request.url), "body": json.loads(request.content.decode("utf-8"))})
        return httpx.Response(200)

    monkeypatch.setattr(notify, "_build_webhook_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1))
    return seen


def test_dingtalk_sign_fixed_vector():
    """sign 固定向量防时序/编码回归（Review Focus #1：毫秒时间戳 + HMAC-SHA256 + base64 + urlencode）。

    期望值由标准实现独立手算后写死：digest hex=784b2732d1819d54ab53bf7654fc2cdc260e2c752f0891f546b7e00a81c7acb7
    （hmac.new 与 hmac.digest 双实现交叉验证一致；quote_plus 与 urlencode({"sign":...}) 一致）。
    """
    assert notify._dingtalk_sign("1719000000000", "SECxxxxxxxx") == \
        "eEsnMtGBnVSrU792VPws3CYOLHUvCJH1RrfgCoHHrLc%3D"


async def test_dingtalk_signed_url_and_text_payload(client, auth_headers, monkeypatch):
    """钉钉：URL 追加 &timestamp=<毫秒>&sign=<urlencode(HMAC)>；payload 为 text 消息形状。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "dingtalk", "url": "https://oapi.dingtalk.com/robot/send?access_token=tok",
         "secret": "SECxxxxxxxx"},
    ]))
    seen = _capture_posts(monkeypatch)

    await notify.send_alarm(make_rec_for(pid), RULE)

    assert len(seen) == 1
    base, _, query = seen[0]["url"].partition("?")
    assert base == "https://oapi.dingtalk.com/robot/send"
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert params["access_token"] == "tok"          # 原有 query 参数原样保留
    ts = params["timestamp"]
    assert ts.isdigit() and len(ts) == 13           # 毫秒时间戳原样（纯数字，无编码）
    assert params["sign"] == notify._dingtalk_sign(ts, "SECxxxxxxxx")  # 算法级一致性断言
    assert seen[0]["body"] == {"msgtype": "text",
                               "text": {"content": f"[webScada] {pid} temp_01 critical: 1号反应釜温度超高: 111.2"}}


async def test_dingtalk_without_secret_sends_unsigned(client, auth_headers, monkeypatch):
    """secret 空（未配置/解密失败降级空串）→ 不追加签名参数，按原 URL 发送（_decrypt_secret 口径）。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "dingtalk", "url": "https://oapi.dingtalk.com/robot/send?access_token=tok"},
    ]))
    seen = _capture_posts(monkeypatch)

    await notify.send_alarm(make_rec_for(pid), RULE)

    assert len(seen) == 1
    assert seen[0]["url"] == "https://oapi.dingtalk.com/robot/send?access_token=tok"
    assert seen[0]["body"]["msgtype"] == "text"


async def test_wecom_markdown_payload_no_sign(client, auth_headers, monkeypatch):
    """企微：URL 原样无追加（无签名）；payload 为 markdown 消息形状（内容口径同钉钉）。"""
    pid, _ = await _mk_project(client, auth_headers, _notify_doc([
        {"kind": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY"},
    ]))
    seen = _capture_posts(monkeypatch)

    await notify.send_alarm(make_rec_for(pid), RULE)

    assert len(seen) == 1
    assert seen[0]["url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY"
    assert seen[0]["body"] == {"msgtype": "markdown",
                               "markdown": {"content": f"[webScada] {pid} temp_01 critical: 1号反应釜温度超高: 111.2"}}
