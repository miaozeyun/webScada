"""认证接口：登录/锁定/me/logout(jti 黑名单)/改密。"""

LOGIN = {"username": "admin", "password": "admin12345"}


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
    assert "role" not in body  # P0 无角色概念（users 表无 role 列，G10）


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
