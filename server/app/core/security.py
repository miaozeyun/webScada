"""鉴权与安全：bcrypt 密码、PyJWT 签发校验、jti 黑名单（登出）、登录失败锁定。

口径（docs/design/03-接口清单 §1.2/§2.2）：
- JWT HS256，有效期默认 2h；登出 = 当前 token 的 jti 进入进程内黑名单（单 worker；重启黑名单清空，
  残留 token 寿命 ≤2h，可接受并已声明）
- 改密不做全局 token 作废：旧 token 有效至自然过期
- 登录同用户名连续失败 5 次锁 60s（内存计数，429）
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AppError

# ---------------- 密码 ----------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ---------------- JWT ----------------

def create_access_token(user_id: str) -> tuple[str, int]:
    """返回 (token, expires_in 秒)。jti 用于登出黑名单。"""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {"sub": user_id, "jti": uuid.uuid4().hex, "iat": now, "exp": exp}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return token, settings.JWT_EXPIRE_HOURS * 3600


def decode_access_token(token: str) -> dict:
    """校验签名/有效期/黑名单，失败抛 401。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AppError("TOKEN_EXPIRED", "登录已过期，请重新登录", 401)
    except jwt.InvalidTokenError:
        raise AppError("TOKEN_EXPIRED", "无效的登录凭证", 401)
    if is_jti_revoked(payload.get("jti", "")):
        raise AppError("TOKEN_EXPIRED", "登录已注销", 401)
    return payload


# ---------------- jti 黑名单（登出）----------------
# 进程内实现：jti -> exp（unix 秒）。过期条目在检查时顺手清理。

_revoked: dict[str, float] = {}


def revoke_jti(jti: str, exp: float | None = None) -> None:
    _prune_revoked()
    _revoked[jti] = exp if exp is not None else time.time() + settings.JWT_EXPIRE_HOURS * 3600


def is_jti_revoked(jti: str) -> bool:
    _prune_revoked()
    return jti in _revoked


def _prune_revoked() -> None:
    now = time.time()
    for k in [k for k, exp in _revoked.items() if exp <= now]:
        _revoked.pop(k, None)


# ---------------- 登录失败锁定 ----------------
# username -> {"count": int, "until": unix 秒（锁定截止）}

_login_state: dict[str, dict] = {}


def _prune_login_state() -> None:
    """惰性清理：只淘汰"超过一个锁定周期无新失败"的陈旧条目，
    防随机用户名刷接口无限增长（复查 minor 修复）。
    注意不能清掉累计到一半的条目（有 ts 活跃时间戳保护），否则锁定计数失效。"""
    now = time.time()
    stale = [
        k
        for k, st in _login_state.items()
        if st.get("until", 0) < now and now - st.get("ts", now) > settings.LOGIN_LOCKOUT_SECONDS
    ]
    for k in stale:
        _login_state.pop(k, None)


def check_login_lockout(username: str) -> int:
    """返回剩余锁定秒数；0 表示未锁定。"""
    _prune_login_state()
    st = _login_state.get(username)
    if not st:
        return 0
    if st.get("until", 0) > time.time():
        return int(st["until"] - time.time()) + 1
    return 0


def record_login_failure(username: str) -> None:
    _prune_login_state()
    st = _login_state.setdefault(username, {"count": 0, "until": 0, "ts": 0.0})
    if st.get("until", 0) > time.time():
        return  # 锁定期内不重复累计
    st["count"] += 1
    st["ts"] = time.time()
    if st["count"] >= settings.LOGIN_LOCKOUT_ATTEMPTS:
        st["until"] = time.time() + settings.LOGIN_LOCKOUT_SECONDS
        st["count"] = 0  # 解锁后重新计数


def clear_login_failure(username: str) -> None:
    _login_state.pop(username, None)


# ---------------- 登录时序对齐 ----------------
# 防用户名枚举的时序侧信道：用户不存在时也执行一次同代价的 bcrypt 比较。
# 模块加载时生成一次固定 dummy hash（复查 minor 修复）。
_DUMMY_HASH = hash_password("timing-equalizer-dummy")


def dummy_verify(plain: str) -> None:
    """与 verify_password 同代价但结果丢弃，用于对齐"用户不存在"分支的响应耗时。"""
    bcrypt.checkpw(plain.encode("utf-8"), _DUMMY_HASH.encode("utf-8"))
