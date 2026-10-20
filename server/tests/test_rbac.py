"""RBAC 角色矩阵测试（契约 §9 C 包验收）：viewer/operator/admin × 端点 → 401/403/2xx。

自建 mini app（契约 §8 集成说明）：不依赖 app.main 全量装配（main 顶部 import 的
A/B 包模块缺席时不可启动是预期中间态）。共享 conftest.py 禁改，本文件完全自包含：
- 独立运行：cd server && python -m pytest tests/test_rbac.py --noconftest -q
- 集成全量：python -m pytest（与共享 conftest 共存，本文件不使用其 fixture）
"""
import os

# ---- 测试环境（必须先于 app 模块导入设置；settings 在导入期读取）----
# setdefault：与 tests/conftest.py 共存（集成期全量跑）时让位给 conftest 的同值设置
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("DATASOURCE_SECRET", Fernet.generate_key().decode())

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.errors import register_handlers  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401  注册全部模型
from app.db.base import Base, get_db  # noqa: E402
from app.db.models import User  # noqa: E402
from app.services import audit_service  # noqa: E402


# ---------------- mini app 与夹具（自包含） ----------------

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
    """每测试：清安全状态 + 新测试库 + 审计短会话指向测试库。"""
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
    from app.api.v1 import audit as audit_api
    from app.api.v1 import projects, shares, users

    application = build_mini_app(projects.router, shares.router, users.router, audit_api.router)

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


# ---------------- 测试辅助 ----------------

async def make_user(factory, username: str, role: str, password: str = "pass12345") -> User:
    async with factory() as session:
        u = User(username=username, password_hash=hash_password(password), role=role)
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


def hdr(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))[0]}"}


def make_min_doc(project_id: str, name: str = "矩阵工程") -> dict:
    """最小合法 ProjectDoc（schemas/doc 缺省项走默认值；硬性下限仅 pages ≥1）。"""
    now = "2026-10-20T00:00:00.000Z"
    return {
        "schemaVersion": 1,
        "project": {"id": project_id, "name": name, "description": None,
                    "author": "tester", "createdAt": now, "updatedAt": now},
        "datasources": [],
        "variables": [],
        "pages": [{"id": "page_1", "name": "总览", "order": 0,
                   "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
                   "components": []}],
        "alarmRules": [],
    }


async def put_doc(client, headers, project_id: str, doc: dict, base_revision: int = 1):
    if doc["project"]["id"] != project_id:
        doc = {**doc, "project": {**doc["project"], "id": project_id}}
    return await client.put(
        f"/api/v1/projects/{project_id}", headers=headers, json={"doc": doc, "baseRevision": base_revision}
    )


# ---------------- 用例 ----------------

async def test_401_without_token(client, c_env):
    """未登录 → 401（先于角色判定）。"""
    assert (await client.get("/api/v1/users")).status_code == 401
    assert (await client.get("/api/v1/audit-logs")).status_code == 401
    pid = (await client.post("/api/v1/projects", headers=hdr(await make_user(c_env, "root", "admin")),
                             json={"name": "t"})).json()["id"]
    assert (await client.put(f"/api/v1/projects/{pid}", json={"doc": make_min_doc(pid), "baseRevision": 1})).status_code == 401


async def test_admin_only_endpoints(client, c_env):
    """users/audit 全端点：viewer/operator → 403，admin → 2xx。"""
    viewer = await make_user(c_env, "v1", "viewer")
    operator = await make_user(c_env, "o1", "operator")
    admin = await make_user(c_env, "a1", "admin")
    target = await make_user(c_env, "target", "viewer")

    viewer_h, operator_h, admin_h = hdr(viewer), hdr(operator), hdr(admin)
    # GET 列表
    assert (await client.get("/api/v1/users", headers=viewer_h)).status_code == 403
    assert (await client.get("/api/v1/users", headers=operator_h)).status_code == 403
    assert (await client.get("/api/v1/users", headers=admin_h)).status_code == 200
    assert (await client.get("/api/v1/audit-logs", headers=viewer_h)).status_code == 403
    assert (await client.get("/api/v1/audit-logs", headers=operator_h)).status_code == 403
    assert (await client.get("/api/v1/audit-logs", headers=admin_h)).status_code == 200
    # 写端点
    body = {"username": "n1", "password": "pass12345", "role": "viewer"}
    assert (await client.post("/api/v1/users", headers=viewer_h, json=body)).status_code == 403
    assert (await client.post("/api/v1/users", headers=operator_h, json=body)).status_code == 403
    assert (await client.post("/api/v1/users", headers=admin_h, json=body)).status_code == 201
    role_body = {"role": "operator"}
    assert (await client.put(f"/api/v1/users/{target.id}", headers=viewer_h, json=role_body)).status_code == 403
    assert (await client.put(f"/api/v1/users/{target.id}", headers=operator_h, json=role_body)).status_code == 403
    pw_body = {"newPassword": "pass12345"}
    assert (await client.put(f"/api/v1/users/{target.id}/password", headers=viewer_h, json=pw_body)).status_code == 403
    assert (await client.put(f"/api/v1/users/{target.id}/password", headers=operator_h, json=pw_body)).status_code == 403
    assert (await client.put(f"/api/v1/users/{target.id}", headers=admin_h, json=role_body)).status_code == 200
    assert (await client.put(f"/api/v1/users/{target.id}/password", headers=admin_h, json=pw_body)).status_code == 204
    assert (await client.delete(f"/api/v1/users/{target.id}", headers=operator_h)).status_code == 403
    assert (await client.delete(f"/api/v1/users/{target.id}", headers=admin_h)).status_code == 204


async def test_project_write_matrix(client, c_env):
    """PUT /projects：viewer 403；operator/admin 200（operator 全工程可编辑，§4.7）。"""
    viewer = await make_user(c_env, "v1", "viewer")
    operator = await make_user(c_env, "o1", "operator")
    admin = await make_user(c_env, "a1", "admin")
    pid = (await client.post("/api/v1/projects", headers=hdr(admin), json={"name": "t"})).json()["id"]

    resp_v = await put_doc(client, hdr(viewer), pid, make_min_doc(pid))
    assert resp_v.status_code == 403
    assert resp_v.json()["code"] == "FORBIDDEN"
    assert (await put_doc(client, hdr(operator), pid, make_min_doc(pid))).status_code == 200
    assert (await put_doc(client, hdr(admin), pid, make_min_doc(pid), base_revision=2)).status_code == 200


async def test_project_create_import_matrix(client, c_env):
    """POST /projects 与 /import：viewer 403；operator/admin 放行。"""
    viewer_h = hdr(await make_user(c_env, "v1", "viewer"))
    operator_h = hdr(await make_user(c_env, "o1", "operator"))

    assert (await client.post("/api/v1/projects", headers=viewer_h, json={"name": "t"})).status_code == 403
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "t"})).json()["id"]

    assert (await client.post("/api/v1/projects/import", headers=viewer_h,
                              json={"doc": make_min_doc("00000000-0000-0000-0000-000000000000")})).status_code == 403
    resp = await client.post("/api/v1/projects/import", headers=operator_h,
                             json={"doc": make_min_doc("00000000-0000-0000-0000-000000000000")})
    assert resp.status_code == 201
    assert resp.json()["id"] != pid  # 导入总是新建工程（G9 重写 id）


async def test_project_delete_matrix(client, c_env):
    """DELETE /projects（§4.7）：admin 恒可删；operator 仅 owner；viewer 恒 403（含 owner）。"""
    viewer = await make_user(c_env, "v1", "viewer")
    operator = await make_user(c_env, "o1", "operator")
    admin = await make_user(c_env, "a1", "admin")

    # operator 自建自删 → 204
    own = (await client.post("/api/v1/projects", headers=hdr(operator), json={"name": "own"})).json()
    assert (await client.delete(f"/api/v1/projects/{own['id']}", headers=hdr(operator))).status_code == 204

    # admin 建：operator 非 owner 403；viewer 403；admin 204
    admin_pid = (await client.post("/api/v1/projects", headers=hdr(admin), json={"name": "adm"})).json()["id"]
    assert (await client.delete(f"/api/v1/projects/{admin_pid}", headers=hdr(operator))).status_code == 403
    assert (await client.delete(f"/api/v1/projects/{admin_pid}", headers=hdr(viewer))).status_code == 403

    # viewer 名下工程（直插库，viewer 无创建权）：owner 也不可删 → 403
    from app.services import project_service

    async with c_env() as session:
        project = await project_service.create_project(session, viewer, "viewer-owned", None)
        viewer_pid = str(project.id)
    assert (await client.delete(f"/api/v1/projects/{viewer_pid}", headers=hdr(viewer))).status_code == 403
    assert (await client.delete(f"/api/v1/projects/{viewer_pid}", headers=hdr(admin))).status_code == 204


async def test_share_write_matrix(client, c_env):
    """POST/DELETE shares：operator/admin 放行（§4.7）；viewer 403。"""
    viewer_h = hdr(await make_user(c_env, "v1", "viewer"))
    operator_h = hdr(await make_user(c_env, "o1", "operator"))
    admin_h = hdr(await make_user(c_env, "a1", "admin"))
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "t"})).json()["id"]

    assert (await client.post(f"/api/v1/projects/{pid}/shares", headers=viewer_h, json={})).status_code == 403
    assert (await client.post(f"/api/v1/projects/{pid}/shares", headers=operator_h, json={})).status_code == 201
    token = (await client.post(f"/api/v1/projects/{pid}/shares", headers=admin_h, json={})).json()["token"]
    assert (await client.delete(f"/api/v1/shares/{token}", headers=viewer_h)).status_code == 403
    assert (await client.delete(f"/api/v1/shares/{token}", headers=operator_h)).status_code == 204


async def test_viewer_can_read_projects(client, c_env):
    """viewer 只读口径：GET 工程/列表/导出 200。"""
    viewer_h = hdr(await make_user(c_env, "v1", "viewer"))
    admin_h = hdr(await make_user(c_env, "a1", "admin"))
    pid = (await client.post("/api/v1/projects", headers=admin_h, json={"name": "t"})).json()["id"]
    assert (await client.get("/api/v1/projects", headers=viewer_h)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{pid}", headers=viewer_h)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{pid}/export", headers=viewer_h)).status_code == 200
