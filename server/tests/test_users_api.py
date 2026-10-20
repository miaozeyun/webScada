"""用户管理 API 测试（契约 §4.3）：CRUD + 最后一个 admin 保护 + self_delete + 密码重置。

自建 mini app（契约 §8 集成说明，同 test_rbac.py 头注）：
- 独立运行：cd server && python -m pytest tests/test_users_api.py --noconftest -q
"""
import os

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("DATASOURCE_SECRET", Fernet.generate_key().decode())

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.errors import register_handlers  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db.base import Base, get_db  # noqa: E402
from app.db.models import User  # noqa: E402
from app.services import audit_service  # noqa: E402


# ---------------- mini app 与夹具（自包含，与 test_rbac.py 同构） ----------------

def build_mini_app(*routers) -> FastAPI:
    app = FastAPI()
    register_handlers(app)
    api = APIRouter(prefix="/api/v1")
    for r in routers:
        api.include_router(r)
    app.include_router(api)
    return app


@pytest.fixture(autouse=True)
async def c_env():
    from app.core import security

    security._login_state.clear()
    security._revoked.clear()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    prev = audit_service.session_factory
    audit_service.session_factory = factory
    yield factory
    audit_service.session_factory = prev

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def app(c_env):
    from app.api.v1 import auth as auth_api
    from app.api.v1 import users as users_api

    application = build_mini_app(auth_api.router, users_api.router)

    async def _override_get_db():
        async with c_env() as session:
            yield session

    application.dependency_overrides[get_db] = _override_get_db
    yield application
    application.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def make_user(factory, username: str, role: str, password: str = "pass12345") -> User:
    async with factory() as session:
        u = User(username=username, password_hash=hash_password(password), role=role)
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


def hdr(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))[0]}"}


@pytest.fixture
async def admin(c_env):
    return await make_user(c_env, "admin", "admin")


@pytest.fixture
def admin_h(admin):
    return hdr(admin)


# ---------------- 创建 ----------------

async def test_create_user_201_shape(client, admin_h):
    resp = await client.post("/api/v1/users", headers=admin_h,
                             json={"username": "op1", "password": "pass12345", "role": "operator"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "op1" and body["role"] == "operator"
    assert body["id"] and body["createdAt"]


async def test_create_user_conflict_409(client, admin_h):
    payload = {"username": "dup", "password": "pass12345", "role": "viewer"}
    assert (await client.post("/api/v1/users", headers=admin_h, json=payload)).status_code == 201
    resp = await client.post("/api/v1/users", headers=admin_h, json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == "USERNAME_EXISTS"


async def test_create_user_validation_422(client, admin_h):
    base = {"username": "x", "password": "pass12345", "role": "viewer"}
    assert (await client.post("/api/v1/users", headers=admin_h, json={**base, "password": "short7"})).status_code == 422
    assert (await client.post("/api/v1/users", headers=admin_h, json={**base, "role": "root"})).status_code == 422
    assert (await client.post("/api/v1/users", headers=admin_h, json={**base, "username": ""})).status_code == 422
    assert (await client.post("/api/v1/users", headers=admin_h, json={"username": "norole", "password": "pass12345"})).status_code == 422


async def test_create_user_requires_admin(client, c_env, admin_h):
    operator = await make_user(c_env, "o1", "operator")
    resp = await client.post("/api/v1/users", headers=hdr(operator),
                             json={"username": "n", "password": "pass12345", "role": "viewer"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
    assert (await client.post("/api/v1/users", json={"username": "n", "password": "pass12345", "role": "viewer"})).status_code == 401


# ---------------- 列表 ----------------

async def test_list_users_keyword_pagination(client, c_env, admin, admin_h):
    for i in range(3):
        await make_user(c_env, f"plc_{i}", "operator")
    resp = await client.get("/api/v1/users", headers=admin_h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4 and len(body["items"]) == 4

    resp = await client.get("/api/v1/users", headers=admin_h, params={"keyword": "plc_1"})
    body = resp.json()
    assert body["total"] == 1 and body["items"][0]["username"] == "plc_1"

    resp = await client.get("/api/v1/users", headers=admin_h, params={"page": 2, "size": 2})
    body = resp.json()
    assert body["total"] == 4 and body["page"] == 2 and len(body["items"]) == 2


# ---------------- 角色调整 ----------------

async def test_update_role_and_last_admin_protection(client, c_env, admin, admin_h):
    """唯一 admin 不可降级（409 last_admin）；存在第二个 admin 后可降级。"""
    resp = await client.put(f"/api/v1/users/{admin.id}", headers=admin_h, json={"role": "operator"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "last_admin"

    second = await make_user(c_env, "admin2", "admin")
    resp = await client.put(f"/api/v1/users/{admin.id}", headers=hdr(second), json={"role": "operator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "operator"

    # operator（已被降级的 admin）可被现任 admin 升回 admin
    resp = await client.put(f"/api/v1/users/{admin.id}", headers=hdr(second), json={"role": "admin"})
    assert resp.status_code == 200 and resp.json()["role"] == "admin"


async def test_update_role_404(client, admin_h):
    resp = await client.put("/api/v1/users/00000000-0000-0000-0000-00000000000f", headers=admin_h,
                            json={"role": "viewer"})
    assert resp.status_code == 404


async def test_update_role_invalid_enum_422(client, admin, admin_h):
    resp = await client.put(f"/api/v1/users/{admin.id}", headers=admin_h,
                            json={"role": "superuser"})
    assert resp.status_code == 422


# ---------------- 密码重置 ----------------

async def test_reset_password_flow(client, c_env, admin_h):
    target = await make_user(c_env, "bob", "operator", password="oldpass12345")

    resp = await client.put(f"/api/v1/users/{target.id}/password", headers=admin_h,
                            json={"newPassword": "short"})
    assert resp.status_code == 422
    resp = await client.put(f"/api/v1/users/{'0' * 8}-0000-0000-0000-00000000000e/password",
                            headers=admin_h, json={"newPassword": "newpass12345"})
    assert resp.status_code == 404

    # 无需旧密码（§4.3）
    assert (await client.put(f"/api/v1/users/{target.id}/password", headers=admin_h,
                             json={"newPassword": "newpass12345"})).status_code == 204
    # 新密码可登录，旧密码 401
    login = await client.post("/api/v1/auth/login", json={"username": "bob", "password": "newpass12345"})
    assert login.status_code == 200
    assert (await client.post("/api/v1/auth/login", json={"username": "bob", "password": "oldpass12345"})).status_code == 401


# ---------------- 删除 ----------------

async def test_delete_user_and_self_delete(client, c_env, admin, admin_h):
    target = await make_user(c_env, "gone", "viewer")
    assert (await client.delete(f"/api/v1/users/{target.id}", headers=admin_h)).status_code == 204
    # 库内已无该用户
    async with c_env() as session:
        assert await session.scalar(select(User.id).where(User.username == "gone")) is None

    assert (await client.delete(f"/api/v1/users/{'0' * 8}-0000-0000-0000-00000000000d", headers=admin_h)).status_code == 404

    # 不能删自己 → 422 self_delete；且优先级高于最后一个 admin 409（admin 恰为唯一 admin）
    resp = await client.delete(f"/api/v1/users/{admin.id}", headers=admin_h)
    assert resp.status_code == 422
    assert resp.json()["code"] == "self_delete"


async def test_delete_last_admin_protection(client, c_env, admin, admin_h):
    """删除唯一 admin 的路径被 self_delete 拦截；双 admin 场景下删除其一可行。"""
    second = await make_user(c_env, "admin2", "admin")
    assert (await client.delete(f"/api/v1/users/{second.id}", headers=admin_h)).status_code == 204
    # 剩 admin 自己，删除自己 → 422（不是 409：self_delete 先判）
    resp = await client.delete(f"/api/v1/users/{admin.id}", headers=admin_h)
    assert resp.status_code == 422


# ---------------- me 返回 role（契约 §4.3 me 增加 role 字段） ----------------

async def test_me_returns_role(client, c_env):
    operator = await make_user(c_env, "o1", "operator")
    resp = await client.get("/api/v1/auth/me", headers=hdr(operator))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "operator"
    assert body["username"] == "o1"
