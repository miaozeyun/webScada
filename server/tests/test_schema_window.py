"""schemaVersion N-1 兼容窗口测试（M8 契约 §7.2/§9-F 验收位）。

运行方式（--noconftest：共享 conftest 顶层 import app.main，六包合入前不可装配——
本文件为纯函数级测试，不依赖 db/app fixture）：
    cd server && python -m pytest tests/test_schema_window.py --noconftest -q

覆盖：
- v=CURRENT 接受；v=CURRENT-1 接受（默认窗口=1）；
- v=CURRENT-2 与 v=CURRENT+1（假想 v=2 拒绝路径）均 422 version_unsupported，文案区分过低/过高；
- 窗口参数模拟：SCHEMA_COMPAT_WINDOW=0 塌缩 / =2 放宽（N-2 接受路径）；
- 非法版本（缺失/字符串/浮点/bool 冒充整数）→ 422；
- round-trip 回归位：CURRENT 版 blank_doc 走 validate_full 全链路不破。
"""
import uuid

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.services import doc_service

CURRENT = settings.CURRENT_SCHEMA_VERSION


def test_current_version_accepted():
    doc_service.check_schema_version({"schemaVersion": CURRENT})


def test_n_minus_1_accepted_by_default_window():
    """默认窗口=1：N-1 直接通过（灰度缓冲，入库仍按 CURRENT 结构校验）。"""
    if settings.SCHEMA_COMPAT_WINDOW >= 1:
        doc_service.check_schema_version({"schemaVersion": CURRENT - 1})


def test_below_floor_rejected_with_migrate_hint():
    """v < CURRENT-窗口 → 422 version_unsupported，文案指引前端 migrateDoc 导入入口（过低）。"""
    floor = CURRENT - max(settings.SCHEMA_COMPAT_WINDOW, 0)
    with pytest.raises(AppError) as ei:
        doc_service.check_schema_version({"schemaVersion": floor - 1})
    err = ei.value
    assert err.code == "version_unsupported"
    assert err.status_code == 422
    assert "migrateDoc" in err.message  # 过低：指引前端迁移入口


def test_too_new_rejected_with_upgrade_hint():
    """v=CURRENT+1（本期即假想 v=2）→ 422 version_unsupported，文案提示升级服务端（过高）。"""
    with pytest.raises(AppError) as ei:
        doc_service.check_schema_version({"schemaVersion": CURRENT + 1})
    err = ei.value
    assert err.code == "version_unsupported"
    assert err.status_code == 422
    assert "升级服务端" in err.message  # 过高：禁止静默降级


def test_window_zero_collapses_to_current_only(monkeypatch):
    """窗口=0：塌缩为仅接受 CURRENT，N-1 也拒绝。"""
    monkeypatch.setattr(settings, "SCHEMA_COMPAT_WINDOW", 0)
    doc_service.check_schema_version({"schemaVersion": CURRENT})
    with pytest.raises(AppError):
        doc_service.check_schema_version({"schemaVersion": CURRENT - 1})


def test_window_widened_accepts_n_minus_2(monkeypatch):
    """窗口=2：模拟放宽后 N-2 接受（提版过渡期窗口参数语义）。"""
    monkeypatch.setattr(settings, "SCHEMA_COMPAT_WINDOW", 2)
    doc_service.check_schema_version({"schemaVersion": CURRENT - 2})
    with pytest.raises(AppError):
        doc_service.check_schema_version({"schemaVersion": CURRENT - 3})


@pytest.mark.parametrize(
    "raw",
    [
        {},                                  # 缺失
        {"schemaVersion": "1"},              # 字符串
        {"schemaVersion": 1.5},              # 浮点
        {"schemaVersion": None},             # null
        {"schemaVersion": True},             # bool 是 int 子类，True==1 不得冒充 CURRENT
    ],
)
def test_invalid_version_types_rejected(raw):
    with pytest.raises(AppError) as ei:
        doc_service.check_schema_version(raw)
    assert ei.value.code == "version_unsupported"
    assert ei.value.status_code == 422


def test_full_pipeline_roundtrip_current_doc():
    """round-trip 回归位：CURRENT 版 blank_doc 经 validate_full 全链路（版本→体积→结构→引用）不破。"""
    doc = doc_service.blank_doc(str(uuid.uuid4()), "窗口回归工程", author="tester")
    model = doc_service.validate_full(doc)  # 不抛即通过
    assert doc_service.collect_warnings(model) == []
