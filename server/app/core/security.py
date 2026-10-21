"""鉴权与安全：bcrypt 密码、PyJWT 签发校验、jti 黑名单（登出）、登录失败锁定、refresh token。

口径（docs/design/03-接口清单 §1.2/§2.2）：
- JWT HS256，有效期默认 2h；登出 = 当前 token 的 jti 进入进程内黑名单（单 worker；重启黑名单清空，
  残留 token 寿命 ≤2h，可接受并已声明）
- 改密不做全局 token 作废：旧 token 有效至自然过期
- 登录同用户名连续失败 5 次锁 60s（内存计数，429）
- refresh token（阶段二 Task 3）：明文 = secrets.token_urlsafe(48)，库内只存 sha256，有效期 7 天；
  轮换一次性消费、复用已吊销 token 即判定泄露重放并吊销该 user 全部 refresh；状态全落库
"""
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.db.models import RefreshToken

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


# ---------------- refresh token（阶段二 Task 3：操作员免重登）----------------
# access JWT 语义零改动；refresh 只在 rememberMe=true 时签发，access 过期后由前端
# 401 单飞刷新（POST /auth/refresh）轮换取新对。状态全落库（无进程内 dict，
# conftest 的安全态重置口径不受影响）。

REFRESH_TOKEN_DAYS = 7


def hash_refresh_token(raw: str) -> str:
    """库内存储口径：sha256 十六进制（64 字符）。明文不落库、不进日志。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    """签发一枚 refresh token（hash 落库，返回明文——仅在响应体出现一次）。"""
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        )
    )
    await db.commit()
    return raw


async def revoke_refresh_token(db: AsyncSession, raw: str) -> bool:
    """吊销一枚 refresh（登出携带 refreshToken 时调用）。返回是否命中未吊销记录。"""
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return result.rowcount == 1


async def revoke_all_user_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    """吊销该 user 全部未过期未吊销的 refresh，返回命中条数。

    两个调用方口径一致（只吊未过期，避免无谓写放大）：
    - 复用检测的家族吊销（rotate_refresh_token）
    - 改密自救（/auth/password）：「改密不做全局作废」既有口径只覆盖旧 access（≤2h
      自然失效）；refresh 轮换链会把泄露窗口延长到 7 天，改密时必须一并切断
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
    )
    await db.commit()
    return result.rowcount


async def rotate_refresh_token(db: AsyncSession, raw: str) -> tuple[uuid.UUID, str] | None:
    """一次性轮换：合法（存在 / 未吊销 / 未过期）→ 旧记录置 revoked + 签发新对。

    返回 (user_id, 新明文)；None = 拒绝。失败三态：
    - hash 不存在：普通 401（无 user 可吊销）
    - 未吊销但已过期：普通 401（过期 ≠ 复用，不作家族吊销）
    - 已吊销仍复用：疑似泄露重放 → 先吊销该 user 全部未过期 refresh 再 401

    并发双花防护：条件 UPDATE（revoked_at NULL → now）保证同一 token 只有一个赢家
    （rowcount==1）；输家随后读到已置位的 revoked_at，落入复用分支被全吊销——
    这正是「检测到复用即视为泄露」的既定安全语义，前端单飞刷新把正常流量挡在前置。
    """
    token_hash = hash_refresh_token(raw)
    now = datetime.now(timezone.utc)
    won = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
    )
    if won.rowcount == 1:
        record = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        new_raw = await issue_refresh_token(db, record.user_id)
        return record.user_id, new_raw

    record = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if record is None or record.revoked_at is None:
        # 不存在 / 未吊销但已过期（未吊销且未过期不可能走到这——条件 UPDATE 已赢）
        return None
    # 复用已吊销 token：吊销该 user 全部未过期 refresh（防已泄露令牌重放）
    await revoke_all_user_refresh_tokens(db, record.user_id)
    return None
