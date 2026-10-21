"""限流中间件规则与容量测试（终审 #2/#5）：history IP 限流规则、空窗口回收、容量清扫。

纯单元口径：直接调 rate_limit.check（中间件本体另有 smoke 覆盖），不建 app。
"""
import os
import time as time_mod

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core import rate_limit  # noqa: E402
from app.core.config import settings  # noqa: E402


def _scope(method: str = "GET", ip: str = "203.0.113.9") -> dict:
    return {"type": "http", "method": method, "client": (ip, 12345)}


def setup_function(_):
    rate_limit.reset_for_tests()


def teardown_function(_):
    rate_limit.reset_for_tests()


def test_history_ip_rate_limited(monkeypatch):
    """GET /projects/{id}/history：同 IP ≤ REST_HISTORY_PER_MIN/min（终审 #2 分享通道兜底）。"""
    monkeypatch.setattr(settings, "REST_HISTORY_PER_MIN", 3)
    pid = "00000000-0000-0000-0000-000000000000"
    path = f"/api/v1/projects/{pid}/history"
    for _ in range(3):
        assert rate_limit.check(path, _scope())[0] is True
    allowed, retry = rate_limit.check(path, _scope())
    assert allowed is False and retry >= 1

    # 不同 IP 独立计数
    assert rate_limit.check(path, _scope(ip="198.51.100.7"))[0] is True
    # 后缀不符的同类端点（如 /export）不入 history 规则
    assert rate_limit.check(f"/api/v1/projects/{pid}/export", _scope())[0] is True
    assert rate_limit.check(f"/api/v1/projects/{pid}", _scope())[0] is True


def test_history_export_rate_limited(monkeypatch):
    """GET /projects/{id}/history/export 同 IP 同额限流（阶段二 Task 2：CSV 导出与 /history 共用
    REST_HISTORY_PER_MIN——后缀匹配只认 /history，不补规则导出端点将裸奔）。"""
    monkeypatch.setattr(settings, "REST_HISTORY_PER_MIN", 2)
    pid = "00000000-0000-0000-0000-000000000000"
    path = f"/api/v1/projects/{pid}/history/export"
    assert rate_limit.check(path, _scope())[0] is True
    assert rate_limit.check(path, _scope())[0] is True
    allowed, retry = rate_limit.check(path, _scope())
    assert allowed is False and retry >= 1


def test_empty_window_key_reclaimed(monkeypatch):
    """窗口整体过期后再次触达：空 key 即时回收（终审 #5：修复 _hits 清理永不执行）。"""
    monkeypatch.setattr(settings, "REST_LOGIN_PER_MIN", 10)
    path = "/api/v1/auth/login"
    scope = _scope(method="POST")
    assert rate_limit.check(path, scope)[0] is True
    key = next(iter(rate_limit._hits))
    assert len(rate_limit._hits) == 1

    # 手工把窗口内命中时间戳推到窗口外（模拟时间流逝）
    rate_limit._hits[key] = rate_limit.deque([time_mod.monotonic() - 3600.0])
    assert rate_limit.check(path, scope)[0] is True
    # 旧 key 被移除并重建：队列里只剩本次新命中（无过期残留）
    assert len(rate_limit._hits) == 1
    window = rate_limit._hits[key]
    assert len(window) == 1 and time_mod.monotonic() - window[0] < 5.0


def test_sweep_caps_growth(monkeypatch):
    """_hits 超阈值时全量清扫已过期 key（终审 #5 容量兜底）。"""
    for i in range(rate_limit._SWEEP_THRESHOLD + 10):
        rate_limit._hits[f"stale-{i}"] = rate_limit.deque([time_mod.monotonic() - 3600.0])
    # 下一次命中规则请求触发清扫
    assert rate_limit.check("/api/v1/auth/login", _scope(method="POST"))[0] is True
    assert len(rate_limit._hits) == 1  # 全部过期 key 被清空，仅剩本次请求
