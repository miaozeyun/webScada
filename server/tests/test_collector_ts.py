"""采集帧时间戳口径（G26 + 03 §2.7）：解析成功用载荷时间，偏差超限回落当前时间。"""
import time

from app.core.config import settings
from app.services.collector import _frame_ts

TOL_MS = 3_000


def test_frame_ts_accepts_recent_epoch_ms():
    now = int(time.time() * 1000)
    assert abs(_frame_ts({"ts": now}, "ts") - now) < TOL_MS


def test_frame_ts_accepts_recent_epoch_seconds():
    now_s = int(time.time())
    assert abs(_frame_ts({"ts": now_s}, "ts") - now_s * 1000) < TOL_MS


def test_frame_ts_accepts_iso8601():
    now = int(time.time() * 1000)
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000))
    assert abs(_frame_ts({"ts": iso}, "ts") - now) < 2_000


def test_frame_ts_falls_back_when_skew_too_large():
    """上游时钟未对时/retained 旧消息：偏差 > ±300s 时回落当前时间，不污染历史。"""
    now = int(time.time() * 1000)
    stale = now - settings.FRAME_TS_MAX_SKEW_MS - 60_000
    assert abs(_frame_ts({"ts": stale}, "ts") - now) < TOL_MS


def test_frame_ts_falls_back_when_missing_or_invalid():
    now = int(time.time() * 1000)
    assert abs(_frame_ts({"x": 1}, "ts") - now) < TOL_MS
    assert abs(_frame_ts({"ts": "not-a-date"}, "ts") - now) < TOL_MS
    assert abs(_frame_ts(None, "ts") - now) < TOL_MS
