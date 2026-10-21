"""认证接口：登录/锁定/me/logout(jti 黑名单)/改密 + refresh token（阶段二 Task 3）。"""

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import RefreshToken, User

LOGIN = {"username": "admin", "password": "admin12345"}


async def _login_remember(client, username: str = "admin", password: str = "admin12345") -> str:
    """rememberMe 登录并返回 refresh 明文（仅响应体出现一次）。"""
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password, "rememberMe": True}
    )
    assert resp.status_code == 200
    refresh = resp.json()["refresh_token"]
    assert refresh
    return refresh


async def test_login_ok(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["access_token"] and body["expires_in"] > 0


async def test_login_wrong_password_envelope(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={**LOGIN, "password": "wrong"})
    assert resp.status_code == 401
    # 统一错误信封 {code,message}，文案统一防枚举（G20/接口清单 §2.2）
    assert resp.json()["code"] == "LOGIN_FAILED"
    assert resp.json()["message"] == "用户名或密码错误"


async def test_login_lockout_after_5_failures(client, admin_user):
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={**LOGIN, "password": "wrong"})
    # 第 6 次即使密码正确也应 429（同用户名锁定 60s）
    resp = await client.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 429
    assert resp.json()["code"] == "LOGIN_LOCKED"


async def test_me_ok(client, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"  # M8：me 返回角色（契约 §4.3；存量用户经 0002 迁移全量 admin）


async def test_me_without_token_401(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


async def test_logout_revokes_token(client, admin_user):
    login = await client.post("/api/v1/auth/login", json=LOGIN)
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 登出前可用
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    # 登出：jti 进黑名单
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    # 登出后同 token 401
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


async def test_change_password_flow(client, admin_user):
    login = await client.post("/api/v1/auth/login", json=LOGIN)
    old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 旧密码错误 → 422 invalid_old_password（统一 422 口径，G20）
    resp = await client.put(
        "/api/v1/auth/password",
        headers=old_headers,
        json={"oldPassword": "wrong-old", "newPassword": "newPass12345"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_old_password"

    # 新密码强度不足 → 422（参数校验）
    resp = await client.put(
        "/api/v1/auth/password",
        headers=old_headers,
        json={"oldPassword": "admin12345", "newPassword": "short"},
    )
    assert resp.status_code == 422

    # 改密成功 → 204；旧 token 至自然过期仍有效（P0 不做全局作废）
    resp = await client.put(
        "/api/v1/auth/password",
        headers=old_headers,
        json={"oldPassword": "admin12345", "newPassword": "newPass12345"},
    )
    assert resp.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 200

    # 新密码可登录，旧密码 401
    assert (await client.post("/api/v1/auth/login", json={**LOGIN, "password": "newPass12345"})).status_code == 200
    assert (await client.post("/api/v1/auth/login", json=LOGIN)).status_code == 401


# ---------------- refresh token（阶段二 Task 3：操作员免重登）----------------


async def test_login_rememberme_issues_refresh(client, admin_user, db_factory):
    """用例 1：rememberMe=True 才签发 refresh；库内只存 sha256、有效期 7 天、明文不落库。"""
    resp = await client.post("/api/v1/auth/login", json={**LOGIN, "rememberMe": True})
    assert resp.status_code == 200
    refresh = resp.json()["refresh_token"]
    assert refresh  # 明文仅响应体返回一次

    async with db_factory() as session:
        rows = (await session.execute(select(RefreshToken))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        # 库内是 sha256(token) 而非明文
        assert row.token_hash == hashlib.sha256(refresh.encode("utf-8")).hexdigest()
        assert row.revoked_at is None
        # 有效期 7 天（created_at 为 CURRENT_TIMESTAMP 秒精度，上界放宽 1s）
        ttl = row.expires_at - row.created_at
        assert timedelta(days=6, hours=23) < ttl <= timedelta(days=7, seconds=1)


async def test_login_without_rememberme_no_refresh(client, admin_user, db_factory):
    """用例 4：不勾选（缺省 False）不签发 refresh，库内零记录。"""
    resp = await client.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] is None
    async with db_factory() as session:
        assert (await session.execute(select(RefreshToken))).scalars().first() is None


async def test_refresh_rotates_old_invalid_new_usable(client, admin_user):
    """用例 2：轮换后新对可用；旧 token 一次性消费，复放 401。"""
    rt1 = await _login_remember(client)

    # 轮换：返回全新 access + refresh（与旧 refresh 不同）
    r2 = await client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert r2.status_code == 200
    pair = r2.json()
    assert pair["access_token"] and pair["refresh_token"]
    assert pair["refresh_token"] != rt1

    # 新 access 立即可用（免重登语义）
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["username"] == "admin"

    # 新 refresh 可继续轮换（链式续期）
    r3 = await client.post("/api/v1/auth/refresh", json={"refreshToken": pair["refresh_token"]})
    assert r3.status_code == 200

    # 旧 token 复放 → 401（已一次性消费）
    replay = await client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert replay.status_code == 401


async def test_refresh_reuse_revokes_all_for_user(client, admin_user, db_factory):
    """用例 3：复用已轮换 token → 401 且同 user 全部 refresh 吊销；其他 user 不受波及。"""
    # admin 两枚 refresh：一枚已轮换（rt1→rt2），一枚仍有效（rt3，模拟另一终端）
    rt1 = await _login_remember(client)
    r2 = await client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert r2.status_code == 200
    rt2 = r2.json()["refresh_token"]
    rt3 = await _login_remember(client)

    # 另一用户的 refresh（吊销范围对照）
    async with db_factory() as session:
        session.add(User(username="operator1", password_hash=hash_password("op12345678")))
        await session.commit()
    rt_other = await _login_remember(client, username="operator1", password="op12345678")

    # 复用已轮换的 rt1 → 401，且 admin 名下 rt2/rt3 全部吊销
    replay = await client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert replay.status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": rt2})).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": rt3})).status_code == 401
    # 其他 user 的 refresh 不在吊销范围内
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": rt_other})).status_code == 200


async def test_logout_revokes_refresh_token(client, admin_user):
    """用例 5：logout 带 refreshToken 则一并吊销（access jti 黑名单语义保持）。"""
    login = await client.post("/api/v1/auth/login", json={**LOGIN, "rememberMe": True})
    refresh = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # 登出带 refreshToken → 204
    resp = await client.post("/api/v1/auth/logout", headers=headers, json={"refreshToken": refresh})
    assert resp.status_code == 204
    # refresh 立即失效；同 access 亦 401（jti 黑名单保持）
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": refresh})).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_refresh_expired_token_401_without_family_revocation(client, admin_user, db_factory):
    """过期 ≠ 复用：过期 refresh 401，但不触发该 user 全吊销（新签的 refresh 仍可用）。"""
    rt_old = await _login_remember(client)
    async with db_factory() as session:
        row = (await session.execute(select(RefreshToken))).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)  # SQLite 落库时取 UTC 墙钟
        await session.commit()

    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": rt_old})).status_code == 401

    # 过期不牵连：此后新签的 refresh 正常可用
    rt_new = await _login_remember(client)
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": rt_new})).status_code == 200
