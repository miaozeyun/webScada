"""datasources/test 凭证注回安全测试（终审 #1）：URL 一致性校验 + datasource_test 审计。

自建 mini app（契约 §8 集成说明，同 test_rbac.py 头注）：
- 独立运行：cd server && python -m pytest tests/test_datasources_security.py --noconftest -q
- 探测函数打桩（不真连外网）：捕获注回后的 config，校验凭证是否被注入
- 关键用例：本次 URL 与库内一致 → 注回 FER1: 密文解密凭证；不一致 → 不注回 + message 提示重填
"""
import json
import os
import uuid as uuidlib

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("DATASOURCE_SECRET", Fernet.generate_key().decode())

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.errors import register_handlers  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401  注册全部模型
from app.db.base import Base, get_db  # noqa: E402
from app.db.models import AuditLog, Project, User  # noqa: E402
from app.services import audit_service  # noqa: E402
from app.utils.encrypt import encrypt  # noqa: E402

PID = uuidlib.uuid4()
DS_ID = "ds_rest_01"
STORED_URL = "http://127.0.0.1:59999/api"
STORED_SECRET = "Bearer real-secret"


def build_mini_app() -> FastAPI:
    app = FastAPI()
    register_handlers(app)
    from app.api.v1 import datasources

    app.include_router(datasources.router, prefix="/api/v1")
    return app


@pytest.fixture(autouse=True)
async def c_env():
    """每测试：新测试库 + 审计短会话指向测试库 + 复位打桩捕获。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        session.add(admin)
        await session.flush()
        # 库内 doc：rest 数据源，Authorization 为 FER1: 密文（保存管线加密后的形态）
        session.add(
            Project(
                id=PID, name="注回测试工程", revision=1, owner_id=admin.id,
                doc={
                    "schemaVersion": 1,
                    "project": {"id": str(PID), "name": "注回测试工程"},
                    "datasources": [{
                        "id": DS_ID, "name": "上游 REST", "type": "rest", "enabled": True,
                        "config": {"url": STORED_URL, "method": "GET", "intervalMs": 1000,
                                   "headers": {"Authorization": encrypt(STORED_SECRET)}},
                    }],
                    "variables": [], "pages": [], "alarmRules": [],
                },
            )
        )
        await session.commit()

    prev = audit_service.session_factory
    audit_service.session_factory = factory
    yield factory
    audit_service.session_factory = prev

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(c_env):
    application = build_mini_app()

    async def _override_get_db():
        async with c_env() as session:
            yield session

    application.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
        yield c
    application.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def admin_h(c_env):
    async with c_env() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalars().one()
        return {"Authorization": f"Bearer {create_access_token(str(admin.id))[0]}"}


@pytest.fixture
def captured_probe(monkeypatch):
    """打桩 _probe_rest / _probe_websocket：捕获注回后的 config，恒返回成功。"""
    seen: list[dict] = []

    async def _fake_rest(config: dict) -> tuple[bool, str]:
        seen.append(dict(config))
        return True, "HTTP 200"

    async def _fake_ws(config: dict) -> tuple[bool, str]:
        seen.append(dict(config))
        return True, "已连接"

    from app.api.v1 import datasources

    monkeypatch.setattr(datasources, "_probe_rest", _fake_rest)
    monkeypatch.setattr(datasources, "_probe_websocket", _fake_ws)
    return seen


async def audit_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.scalars(select(AuditLog))).all())


async def test_url_match_refills_stored_credentials(client, admin_h, c_env, captured_probe):
    """本次 URL 与库内一致：FER1: 密文解密注回；落 datasource_test 审计（终审 #1）。"""
    assert "datasource_test" in audit_service.ALLOWED_ACTIONS  # 新 action 已入枚举

    resp = await client.post(
        "/api/v1/datasources/test", headers=admin_h,
        json={"type": "rest", "projectId": str(PID), "datasourceId": DS_ID,
              "config": {"url": STORED_URL, "method": "GET"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "重填凭证" not in body["message"]

    # 探测收到的是注回后的 config：敏感头为解密明文
    assert len(captured_probe) == 1
    assert captured_probe[0]["headers"]["Authorization"] == STORED_SECRET

    rows = await audit_rows(c_env)
    assert len(rows) == 1 and rows[0].action == "datasource_test"
    assert rows[0].target_type == "datasource" and rows[0].target_id == DS_ID
    assert rows[0].detail["refilled"] is True and rows[0].detail["urlMatched"] is True
    # 审计 detail 不含凭证明文
    assert STORED_SECRET not in json.dumps(rows[0].detail, default=str)


async def test_url_mismatch_skips_refill_and_hints(client, admin_h, c_env, captured_probe):
    """本次 URL 与库内不一致：不注回（防换 URL 窃取任意工程凭证）+ message 提示重填（终审 #1）。"""
    evil_url = "http://evil.example.com:8080/steal"
    resp = await client.post(
        "/api/v1/datasources/test", headers=admin_h,
        json={"type": "rest", "projectId": str(PID), "datasourceId": DS_ID,
              "config": {"url": evil_url, "method": "GET"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "重填凭证" in body["message"]

    # 探测收到的 config 不含任何注回凭证
    assert len(captured_probe) == 1
    assert not captured_probe[0].get("headers")

    rows = await audit_rows(c_env)
    assert len(rows) == 1 and rows[0].action == "datasource_test"
    assert rows[0].detail["refilled"] is False and rows[0].detail["urlMatched"] is False


async def test_mqtt_url_mismatch_no_password_refill(client, admin_h, c_env, monkeypatch):
    """mqtt 同口径：brokerUrl 不一致 → 不注回 password（修法覆盖四类源）。"""
    seen: list[dict] = []

    async def _fake_mqtt(config: dict) -> tuple[bool, str]:
        seen.append(dict(config))
        return False, "连接失败"

    from app.api.v1 import datasources

    monkeypatch.setattr(datasources, "_probe_mqtt", _fake_mqtt)

    # 库内仅 rest 源（无 mqtt 源）：datasourceId 指向 rest 源而本次 type=mqtt → stored 存在但
    # brokerUrl vs url 口径不一致，一律不注回
    resp = await client.post(
        "/api/v1/datasources/test", headers=admin_h,
        json={"type": "mqtt", "projectId": str(PID), "datasourceId": DS_ID,
              "config": {"brokerUrl": "mqtt://127.0.0.1:59999"}},
    )
    assert resp.status_code == 200
    assert not seen[0].get("password")
    rows = await audit_rows(c_env)
    assert rows[0].detail["refilled"] is False


async def test_refill_requires_matching_url_only_for_stored(client, admin_h, c_env, captured_probe):
    """无 projectId/datasourceId 的裸测试不触发注回，也照常落审计。"""
    resp = await client.post(
        "/api/v1/datasources/test", headers=admin_h,
        json={"type": "rest", "config": {"url": STORED_URL}},
    )
    assert resp.status_code == 200
    assert len(captured_probe) == 1 and not captured_probe[0].get("headers")
    rows = await audit_rows(c_env)
    assert len(rows) == 1
    assert rows[0].detail["refilled"] is False and rows[0].detail["projectId"] is None
