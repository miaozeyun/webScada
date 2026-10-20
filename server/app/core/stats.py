"""进程内指标注册表（M8 共享基础设施，各模块禁止自行另建）。

设计约束：
- 零第三方依赖：/metrics 输出 Prometheus exposition 文本子集（HELP/TYPE + 样本行）
- 线程安全（Lock 保护）；单 worker 部署基线下量级极小，直接 dict
- 各工作包只通过 inc()/set_gauge() 埋点，禁止直接读写内部 dict：
  - A 包：ws_connections / collector_tasks（gauge）、ws_frames_total{type}（counter）
  - B 包：alarms_active（gauge）、notify_sent_total / notify_failed_total（counter）
  - rate_limit 中间件：rate_limited_total（counter）
"""
import time

_started_at = time.time()
_lock = __import__("threading").Lock()
_counters: dict[str, float] = {}
_gauges: dict[str, float] = {}


def inc(name: str, n: float = 1.0) -> None:
    """计数器累加（如 ws_frames_values_total、rate_limited_total）。"""
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + n


def set_gauge(name: str, value: float) -> None:
    """仪表盘置值（如 ws_connections、collector_tasks、alarms_active）。"""
    with _lock:
        _gauges[name] = value


def uptime_seconds() -> float:
    return time.time() - _started_at


def render() -> str:
    """渲染 Prometheus 文本格式（webscada_ 前缀；counter/gauge 自动声明类型）。"""
    with _lock:
        counters = dict(_counters)
        gauges = dict(_gauges)
    lines: list[str] = [
        "# HELP webscada_uptime_seconds Process uptime in seconds",
        "# TYPE webscada_uptime_seconds gauge",
        f"webscada_uptime_seconds {uptime_seconds():.3f}",
    ]
    for name, v in sorted(counters.items()):
        lines.append(f"# TYPE webscada_{name} counter")
        lines.append(f"webscada_{name} {v}")
    for name, v in sorted(gauges.items()):
        lines.append(f"# TYPE webscada_{name} gauge")
        lines.append(f"webscada_{name} {v}")
    return "\n".join(lines) + "\n"
