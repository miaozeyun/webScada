"""审计埋点与查询测试（契约 §9 C 包验收）：七类 action 各一例 + login 成败审计 +
SET NULL 后 username 快照可读 + X-Forwarded-For 首段 + refresh 触发 broadcast_reload（打桩）。

自建 mini app（契约 §8 集成说明，同 test_rbac.py 头注）：
- 独立运行：cd server && python -m pytest tests/test_audit.py --noconftest -q
- ws_manager 打桩：A 包未合入时向 sys.modules 注入 stub，验证 C→A 惰性 import 降级路径
"""
import os
import sys
import types

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("DATASOURCE_SECRET", Fernet.generate_key().decode())

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.errors import register_handlers  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db.base import Base, get_db  # noqa: E402
from app.db.models import AuditLog, User  # noqa: E402
from app.services import audit_service  # noqa: E402


# ---------------- mini app 与夹具（自包含；引擎开 FK 以验证 ondelete=SET NULL） ----------------

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

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # SQLite 默认关外键；开启后 ondelete=SET NULL 才生效
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

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
    from app.api.v1 import auth as auth_api
    from app.api.v1 import projects, shares, users

    application = build_mini_app(auth_api.router, projects.router, shares.router, users.router, audit_api.router)

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


def make_min_doc(project_id: str, name: str = "审计工程") -> dict:
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


async def all_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.scalars(select(AuditLog).order_by(AuditLog.id))).all())


def install_ws_stub(monkeypatch) -> list[str]:
    """向 sys.modules 注入 ws_manager stub（模拟 A 包交付前的降级路径）。"""
    calls: list[str] = []

    async def broadcast_reload(token: str) -> None:
        calls.append(token)

    stub = types.ModuleType("app.services.ws_manager")
    stub.broadcast_reload = broadcast_reload  # type: ignore[attr-defined]
    # 两处都要盖：shares.py 的惰性 import 是 `from app.services import ws_manager`，
    # 该语句优先经包属性 getattr 命中——只换 sys.modules 条目不会生效
    monkeypatch.setitem(sys.modules, "app.services.ws_manager", stub)
    import app.services as services_pkg
    monkeypatch.setattr(services_pkg, "ws_manager", stub, raising=False)
    return calls


# ---------------- audit_service 单元口径 ----------------

async def test_seven_actions_recorded(c_env):
    """七类 action 各落一例（契约 §9 C 包验收）；request=None → ip 为空。"""
    actor = await make_user(c_env, "actor", "admin")
    seven = ["login", "write_var", "alarm_ack", "project_save", "share_create", "share_revoke", "user_mgmt"]
    for i, action in enumerate(seven):
        await audit_service.audit(
            None, actor, action, target_type="project", target_id=f"t-{i}", detail={"i": i}
        )
    rows = await all_rows(c_env)
    assert [r.action for r in rows] == seven
    for r in rows:
        assert r.user_id == actor.id
        assert r.username == "actor"
        assert r.ip is None  # request=None 口径


async def test_unknown_action_still_records(c_env):
    await make_user(c_env, "actor", "admin")
    await audit_service.audit(None, None, "future_action", detail={})
    rows = await all_rows(c_env)
    assert len(rows) == 1 and rows[0].action == "future_action"
    assert rows[0].user_id is None and rows[0].username is None


class _BoomFactory:
    def __call__(self, *args, **kwargs):
        raise RuntimeError("boom")


async def test_audit_failure_does_not_raise(c_env, monkeypatch):
    """审计失败 log 不抛（业务主流程不受阻断）。"""
    actor = await make_user(c_env, "actor", "admin")
    monkeypatch.setattr(audit_service, "session_factory", _BoomFactory())
    await audit_service.audit(None, actor, "user_mgmt", detail={"op": "t"})  # 不抛即通过


async def test_xff_first_segment(client, c_env):
    """ip 取 X-Forwarded-For 首段；login 成功/失败均落审计（detail 含 success/ip）。"""
    admin = await make_user(c_env, "admin", "admin", password="adminpass12345")
    xff = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}

    ok = await client.post("/api/v1/auth/login", headers=xff, json={"username": "admin", "password": "adminpass12345"})
    assert ok.status_code == 200
    bad = await client.post("/api/v1/auth/login", headers=xff, json={"username": "admin", "password": "wrong-pass"})
    assert bad.status_code == 401
    ghost = await client.post("/api/v1/auth/login", headers=xff, json={"username": "ghost", "password": "whatever123"})
    assert ghost.status_code == 401

    rows = await all_rows(c_env)
    assert all(r.action == "login" for r in rows)
    assert all(r.ip == "203.0.113.7" for r in rows)  # 首段，非整串/末段
    success = [r for r in rows if r.detail and r.detail.get("success") is True]
    failed = [r for r in rows if r.detail and r.detail.get("success") is False]
    assert len(success) == 1 and success[0].username == "admin"
    assert {r.detail["reason"] for r in failed} == {"bad_password", "user_not_found"}
    # 用户名不存在 → user=None，username 快照进 detail
    assert any(r.user_id is None and r.detail.get("username") == "ghost" for r in failed)


async def test_username_snapshot_survives_actor_delete(client, c_env):
    """actor 被删 → audit.user_id 外键 SET NULL，username 快照仍可读（契约 §9）。"""
    admin = await make_user(c_env, "admin", "admin")
    operator = await make_user(c_env, "opx", "operator")
    pid = (await client.post("/api/v1/projects", headers=hdr(admin), json={"name": "t"})).json()["id"]
    # operator 触发一条审计（share_create，不产生 operator 名下工程，规避 projects.owner_id 外键限制）
    share = await client.post(f"/api/v1/projects/{pid}/shares", headers=hdr(operator), json={})
    assert share.status_code == 201

    resp = await client.delete(f"/api/v1/users/{operator.id}", headers=hdr(admin))
    assert resp.status_code == 204

    rows = await all_rows(c_env)
    share_rows = [r for r in rows if r.action == "share_create"]
    assert len(share_rows) == 1
    assert share_rows[0].user_id is None  # SET NULL 生效
    assert share_rows[0].username == "opx"  # 快照可读
    assert share_rows[0].target_id == share.json()["token"]


# ---------------- 业务端点埋点 ----------------

async def test_project_save_create_import_audited(client, c_env):
    admin = await make_user(c_env, "a1", "admin")
    operator = await make_user(c_env, "o1", "operator")
    admin_h, operator_h = hdr(admin), hdr(operator)

    pid = (await client.post("/api/v1/projects", headers=admin_h, json={"name": "新建"})).json()["id"]
    assert (await put_doc(client, operator_h, pid, make_min_doc(pid, name="改名"))).status_code == 200
    assert (await client.post("/api/v1/projects/import", headers=operator_h,
                              json={"doc": make_min_doc("00000000-0000-0000-0000-000000000000")})).status_code == 201

    rows = [r for r in await all_rows(c_env) if r.action == "project_save"]
    ops = {r.detail["op"]: r for r in rows}
    assert set(ops) == {"create", "save", "import"}
    assert ops["save"].user_id == operator.id and ops["save"].target_id == pid
    assert ops["save"].detail["revision"] == 2 and ops["save"].detail["name"] == "改名"
    assert ops["create"].user_id == admin.id


async def test_share_create_revoke_audited(client, c_env):
    operator = await make_user(c_env, "o1", "operator")
    operator_h = hdr(operator)
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "t"})).json()["id"]
    token = (await client.post(f"/api/v1/projects/{pid}/shares", headers=operator_h, json={})).json()["token"]

    assert (await client.delete(f"/api/v1/shares/{token}", headers=operator_h)).status_code == 204
    rows = [r for r in await all_rows(c_env) if r.target_type == "share"]
    assert [r.action for r in rows] == ["share_create", "share_revoke"]
    assert all(r.target_id == token for r in rows)
    assert rows[0].detail["projectId"] == pid


async def test_user_mgmt_audited(client, c_env):
    admin = await make_user(c_env, "a1", "admin")
    admin_h = hdr(admin)
    target_id = (await client.post("/api/v1/users", headers=admin_h,
                                   json={"username": "u9", "password": "pass12345", "role": "viewer"})).json()["id"]
    rows = [r for r in await all_rows(c_env) if r.action == "user_mgmt"]
    assert len(rows) == 1
    assert rows[0].target_type == "user" and rows[0].target_id == target_id
    assert rows[0].detail["op"] == "create" and rows[0].detail["role"] == "viewer"


# ---------------- refresh 与 broadcast_reload（C→A 惰性 import，打桩） ----------------

async def test_refresh_broadcasts_reload_and_updates_snapshot(client, c_env, monkeypatch):
    calls = install_ws_stub(monkeypatch)
    operator_h = hdr(await make_user(c_env, "o1", "operator"))
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "旧名"})).json()["id"]
    token = (await client.post(f"/api/v1/projects/{pid}/shares", headers=operator_h, json={})).json()["token"]

    assert (await put_doc(client, operator_h, pid, make_min_doc(pid, name="新名"))).status_code == 200
    resp = await client.post(f"/api/v1/shares/{token}/refresh", headers=operator_h)
    assert resp.status_code == 200
    assert calls == [token]  # refresh 成功后向该 token 全部连接广播 reload（契约 §5）

    # 公开访问读到刷新后的快照（出参收窄为 {projectId, createdAt, doc}，工程名在 doc 内）
    doc = (await client.get(f"/api/v1/shares/{token}")).json()
    assert doc["doc"]["project"]["name"] == "新名"


async def test_refresh_without_ws_manager_degrades(client, c_env, monkeypatch):
    """A 包缺席（模块不存在）：refresh 本身成功，仅广播降级。"""
    monkeypatch.setitem(sys.modules, "app.services.ws_manager", None)  # 强制 import 失败语义
    operator_h = hdr(await make_user(c_env, "o1", "operator"))
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "t"})).json()["id"]
    token = (await client.post(f"/api/v1/projects/{pid}/shares", headers=operator_h, json={})).json()["token"]
    resp = await client.post(f"/api/v1/shares/{token}/refresh", headers=operator_h)
    assert resp.status_code == 200
    # 快照仍被刷新（再次公开访问不报错）
    assert (await client.get(f"/api/v1/shares/{token}")).status_code == 200


async def test_refresh_not_found_and_revoked(client, c_env, monkeypatch):
    calls = install_ws_stub(monkeypatch)
    operator_h = hdr(await make_user(c_env, "o1", "operator"))
    pid = (await client.post("/api/v1/projects", headers=operator_h, json={"name": "t"})).json()["id"]
    token = (await client.post(f"/api/v1/projects/{pid}/shares", headers=operator_h, json={})).json()["token"]

    assert (await client.post("/api/v1/shares/unknown-token/refresh", headers=operator_h)).status_code == 404
    assert (await client.delete(f"/api/v1/shares/{token}", headers=operator_h)).status_code == 204
    assert (await client.post(f"/api/v1/shares/{token}/refresh", headers=operator_h)).status_code == 404
    assert calls == []  # 404 路径不广播


# ---------------- 审计查询 API ----------------

async def test_audit_api_filters_and_order(client, c_env):
    admin = await make_user(c_env, "a1", "admin")
    operator = await make_user(c_env, "o1", "operator")
    admin_h = hdr(admin)

    await audit_service.audit(None, operator, "login", target_type="session", target_id="s1")
    await audit_service.audit(None, operator, "user_mgmt", target_type="user", target_id="u1")
    await audit_service.audit(None, admin, "project_save", target_type="project", target_id="p1")

    resp = await client.get("/api/v1/audit-logs", headers=admin_h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [i["action"] for i in body["items"]] == ["project_save", "user_mgmt", "login"]  # createdAt 倒序

    # action 过滤
    resp = await client.get("/api/v1/audit-logs", headers=admin_h, params={"action": "login"})
    assert resp.json()["total"] == 1 and resp.json()["items"][0]["targetId"] == "s1"
    # userId 过滤
    resp = await client.get("/api/v1/audit-logs", headers=admin_h, params={"userId": str(operator.id)})
    assert resp.json()["total"] == 2
    # targetType/targetId 过滤
    resp = await client.get("/api/v1/audit-logs", headers=admin_h,
                            params={"targetType": "user", "targetId": "u1"})
    assert resp.json()["total"] == 1
    # from/to 窗口
    resp = await client.get("/api/v1/audit-logs", headers=admin_h, params={"from": "2099-01-01T00:00:00Z"})
    assert resp.json()["total"] == 0
    resp = await client.get("/api/v1/audit-logs", headers=admin_h,
                            params={"from": "2000-01-01T00:00:00Z", "to": "2099-01-01T00:00:00Z"})
    assert resp.json()["total"] == 3
    # 分页
    resp = await client.get("/api/v1/audit-logs", headers=admin_h, params={"page": 2, "size": 2})
    body = resp.json()
    assert body["total"] == 3 and len(body["items"]) == 1 and body["items"][0]["action"] == "login"
    # 出口字段形状（§4.4）
    item = body["items"][0]
    assert set(item) == {"id", "userId", "username", "action", "targetType", "targetId", "detail", "ip", "createdAt"}


async def test_audit_api_requires_admin(client, c_env):
    operator = await make_user(c_env, "o1", "operator")
    await audit_service.audit(None, operator, "login")
    assert (await client.get("/api/v1/audit-logs")).status_code == 401
    resp = await client.get("/api/v1/audit-logs", headers=hdr(operator))
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
