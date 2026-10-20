"""License key 骨架测试（M8 阶段 2）：签发/校验往返、篡改拒绝、过期降级、开源核心模式。"""
import sys

import pytest

sys.stdout.reconfigure(encoding="utf-8")

from app.core import license as lic  # noqa: E402


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(lic.settings, "LICENSE_SIGNING_SECRET", "unit-test-secret")
    return "unit-test-secret"


def test_issue_parse_roundtrip(secret):
    key = lic.issue_license("acme 工厂", days=30, max_variables=999, max_connections=9)
    info = lic.parse_license(key)
    assert info is not None
    assert info.licensee == "acme 工厂"
    assert info.max_variables == 999
    assert info.max_connections == 9
    assert not info.expired


def test_tampered_signature_rejected(secret):
    key = lic.issue_license("acme", days=30)
    assert lic.parse_license(key[:-3] + "AAA") is None      # 签名被改
    assert lic.parse_license("WS1." + key.split(".")[1]) is None  # 缺段
    assert lic.parse_license("XXXX" + key) is None          # 版本头错


def test_expired_license_degrades(secret, monkeypatch):
    info = lic.LicenseInfo("old", expires_at=1, max_variables=999, max_connections=9)
    assert info.expired
    # 过期授权不收敛上限（回落 settings 基线）
    ws_cap, var_cap = lic.effective_limits(info)
    assert ws_cap == lic.settings.WS_MAX_CONNECTIONS
    assert var_cap == lic.settings.COLLECTOR_MAX_VARIABLES_PER_PROJECT


def test_effective_limits_converge(secret):
    info = lic.parse_license(lic.issue_license("acme", days=30, max_variables=10, max_connections=5))
    ws_cap, var_cap = lic.effective_limits(info)
    assert ws_cap == 5
    assert var_cap == 10


def test_open_source_mode_no_key(monkeypatch):
    monkeypatch.setattr(lic.settings, "LICENSE_KEY", "")
    info, status = lic.load_runtime_license()
    assert info is None and status == "open-source"
    # 开源核心：settings 基线即上限，无收敛
    assert lic.effective_limits(None) == (
        lic.settings.WS_MAX_CONNECTIONS, lic.settings.COLLECTOR_MAX_VARIABLES_PER_PROJECT
    )


def test_invalid_key_reported(monkeypatch, secret):
    monkeypatch.setattr(lic.settings, "LICENSE_KEY", "WS1.bad.bad")
    info, status = lic.load_runtime_license()
    assert info is None and status == "invalid"
