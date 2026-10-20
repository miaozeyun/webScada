"""进程内滑动窗口限流中间件（M8：把 G16 死参数变为真实消费；自研零新增依赖）。

覆盖公开面四类热点入口（鉴权后的管理面内网受信，不在 HTTP 层限流）：
- POST /api/v1/auth/login            同 IP   ≤ REST_LOGIN_PER_MIN/min
- GET  /api/v1/shares/{token}        同 IP+token ≤ RATE_LIMIT_CONNECT_PER_MIN/min
- POST /api/v1/datasources/test      同 IP   ≤ REST_DATASOURCE_TEST_PER_MIN/min
- GET  /api/v1/projects/{id}/history 同 IP   ≤ REST_HISTORY_PER_MIN/min（终审 #2：
  分享 token 免登录通道可全量拉历史，加 IP 维度限流兜底）

口径声明（契约文档 §9）：
- 单 worker 基线（00-总览 §1.5）；多实例部署时限流退化为单实例粒度，届时换 Redis 后端（P1 预留）
- 超限统一 429 + {code:"TOO_MANY_REQUESTS"} 信封 + Retry-After 响应头（与 G20 信封同形）
- WS 限流（token/用户并发连接数）在 ws_manager 内实现，不经本中间件
"""
import time
from collections import deque

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import stats
from app.core.config import settings

_WINDOW_SECONDS = 60.0
_SWEEP_THRESHOLD = 512  # _hits 条目数阈值：达到即触发一次全量过期清扫（终审 #5 容量兜底）

# (method, path_prefix, key_kind, settings 参数名, path_suffix)；key_kind: ip | ip+token
# suffix 非空时还需 path 以其结尾（用于 /projects/{id}/history 这类带 id 前缀、无法单靠前缀区分的端点）
_RULES: tuple[tuple[str, str, str, str, str], ...] = (
    ("POST", "/api/v1/auth/login", "ip", "REST_LOGIN_PER_MIN", ""),
    ("GET", "/api/v1/shares/", "ip+token", "RATE_LIMIT_CONNECT_PER_MIN", ""),
    ("POST", "/api/v1/datasources/test", "ip", "REST_DATASOURCE_TEST_PER_MIN", ""),
    ("GET", "/api/v1/projects/", "ip", "REST_HISTORY_PER_MIN", "/history"),
)

# key -> 命中时间戳环形队列（窗口外时间戳出队；空队列随手删除防 key 无限增长）
_hits: dict[str, deque[float]] = {}


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


def _rule_key(rule: tuple[str, str, str, str, str], scope: Scope, path: str) -> str | None:
    kind = rule[2]
    ip = _client_ip(scope)
    if kind == "ip":
        return f"{rule[1]}|ip={ip}"
    # ip+token：路径段 /api/v1/shares/{token}
    parts = path.rstrip("/").split("/")
    if len(parts) < 5 or not parts[4]:
        return None
    return f"{rule[1]}|ip={ip}|token={parts[4]}"


def _sweep(now: float) -> None:
    """全量清扫：最新命中已出窗口的 key 整体移除（容量兜底，防 _hits 无限增长，终审 #5）。"""
    expired = [k for k, w in _hits.items() if not w or now - w[-1] >= _WINDOW_SECONDS]
    for k in expired:
        _hits.pop(k, None)


def check(path: str, scope: Scope) -> tuple[bool, int]:
    """返回 (放行, retry_after 秒)。仅对命中规则且超限的请求返回 False。"""
    if not settings.RATE_LIMIT_ENABLED:
        return True, 0
    method = scope.get("method", "")
    for rule in _RULES:
        if method != rule[0] or not path.startswith(rule[1]):
            continue
        suffix = rule[4]
        if suffix and not path.rstrip("/").endswith(suffix):
            continue  # 前缀命中但后缀不符（如 /projects/{id}/export 不入 history 规则）
        limit = getattr(settings, rule[3])
        key = _rule_key(rule, scope, path)
        if key is None:
            return True, 0
        now = time.monotonic()
        if len(_hits) >= _SWEEP_THRESHOLD:
            _sweep(now)
        window = _hits.get(key)
        if window is not None:
            while window and now - window[0] >= _WINDOW_SECONDS:
                window.popleft()
            if not window:
                _hits.pop(key, None)  # 空窗口即时回收（终审 #5：修复清理永不执行、_hits 无限增长）
                window = None
        if window is None:
            window = _hits.setdefault(key, deque())
        if len(window) >= limit:
            retry = int(_WINDOW_SECONDS - (now - window[0])) + 1
            stats.inc("rate_limited_total")
            return False, retry
        window.append(now)
        return True, 0
    return True, 0


class RateLimitMiddleware:
    """纯 ASGI 中间件（只作用于 http scope，WS scope 透传）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        allowed, retry = check(path, scope)
        if not allowed:
            body = '{"code":"TOO_MANY_REQUESTS","message":"请求过于频繁，请稍后重试"}'.encode("utf-8")
            headers = [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"retry-after", str(retry).encode("ascii")),
            ]
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def reset_for_tests() -> None:
    """测试辅助：清空窗口状态（conftest 每测试调用，防跨测试串计数）。"""
    _hits.clear()
