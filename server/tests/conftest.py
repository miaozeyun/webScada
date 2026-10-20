"""测试基座：SQLite 内存库 + 依赖覆盖。

注意：
- 环境变量必须在导入 app 模块**之前**设置（settings 在导入时读取）
- pytest-asyncio 每个测试一个事件循环，因此引擎/会话工厂必须**每个测试重建**
  （StaticPool 的单连接绑定首次使用的循环，跨测试复用会串库）
"""
import os

from cryptography.fernet import Fernet

# ---- 测试环境（先设环境，再导入 app）----
os.environ["JWT_SECRET"] = "test-jwt-secret-not-for-production"
os.environ["DATASOURCE_SECRET"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin12345"

import uuid as uuidlib  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401  # 注册全部模型
from app.db.base import Base, get_db  # noqa: E402
from app.db.models import User  # noqa: E402

# M8 集成中间态（契约 §8）：六包未合齐时 app.main 顶部 import 缺模块、服务不可启动——预期状态。
# 此处降级为 app=None，各包自有测试用 mini FastAPI app 不受影响；集成门禁合齐后恢复全量装配。
try:
    from app.main import app  # noqa: E402
except Exception:  # noqa: BLE001
    app = None

# 当前测试的会话工厂（由 db_env fixture 每测试重建，供 admin_user 与测试直接访库）
_CTX: dict = {}


def _new_engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture(autouse=True)
async def db_env():
    """每测试：新引擎 + 建表 + 覆盖 get_db；结束后销毁。"""
    # 清空进程内安全状态（登录锁定/jti 黑名单/限流计数为模块级内存，跨测试必须重置）
    from app.core import security
    security._login_state.clear()
    security._revoked.clear()
    from app.core import rate_limit
    rate_limit.reset_for_tests()

    engine = _new_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with factory() as session:
            yield session

    if app is not None:  # 中间态 app.main 未合齐时跳过（各包 mini app 自行装配）
        app.dependency_overrides[get_db] = _override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    _CTX["factory"] = factory
    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    if app is not None:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def db_factory():
    """直接访库用（校验库内密文等场景）。"""
    return _CTX["factory"]


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_user(db_factory):
    async with db_factory() as session:
        user = User(username="admin", password_hash=hash_password("admin12345"))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def auth_headers(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin12345"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------- 测试用 doc 构造（覆盖数值/颜色/显隐三类绑定的最小契约样例）----------------

def make_doc(name: str = "演示工程", password: str | None = "Secret@123") -> dict:
    """最小但完整合法的 ProjectDoc（对齐 docs/design/02 §3 最小示例）。"""
    now = "2026-10-20T00:00:00.000Z"
    doc: dict = {
        "schemaVersion": 1,
        "project": {"id": str(uuidlib.uuid4()), "name": name, "description": None,
                    "author": "admin", "createdAt": now, "updatedAt": now},
        "settings": {
            "designSize": {"width": 1920, "height": 1080},
            "adaptive": "fit-contain",
            "theme": "blue-dark",
            "primaryColor": "#2563eb",
            "alarm": {"levelColors": {"info": "#3b82f6", "warn": "#f59e0b", "critical": "#ef4444"},
                      "soundEnabled": True, "soundThrottleSec": 60},
        },
        "datasources": [{
            "id": "ds_mqtt_01", "name": "车间 EMQX", "type": "mqtt", "enabled": True,
            "config": {
                "brokerUrl": "mqtt://emqx:1883", "username": "factory",
                "password": password, "topics": ["factory/line1/#"],
                "qos": 0, "cleanSession": True,
            },
        }],
        "variables": [
            {"id": "var_temp_01", "key": "reactor1_temp", "label": "1号反应釜温度", "type": "number",
             "unit": "°C", "datasourceId": "ds_mqtt_01", "address": "factory/line1/reactor1",
             "jsonPath": "data.temp", "scale": 0.1, "precision": 1},
            {"id": "var_pump_01", "key": "pump1_running", "label": "1号循环泵运行", "type": "boolean",
             "datasourceId": "ds_mqtt_01", "address": "factory/line1/pump1",
             "jsonPath": "data.running", "bitIndex": 0},
        ],
        "pages": [{
            "id": "page_1", "name": "产线总览", "order": 0,
            "background": {"color": "#0b1220"},
            "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
            "components": [
                {"id": "cmp_gauge_01", "type": "gauge", "name": "温度仪表盘",
                 "x": 120, "y": 200, "w": 320, "h": 320, "rotate": 0, "z": 1,
                 "props": {"value": 0, "min": 0, "max": 150},
                 "bindings": [
                     {"id": "bnd_g01", "prop": "props.value", "variableId": "var_temp_01", "mode": "value"},
                     {"id": "bnd_g02", "prop": "style.color", "variableId": "var_temp_01", "mode": "color",
                      "mapping": {"kind": "range", "bands": [
                          {"max": 80, "value": "#22c55e"},
                          {"min": 80, "max": 110, "value": "#f59e0b"},
                          {"min": 110, "value": "#ef4444"},
                      ]}},
                 ]},
                {"id": "cmp_pump_01", "type": "pump", "name": "1号循环泵",
                 "x": 560, "y": 240, "w": 120, "h": 120, "z": 2,
                 "props": {"state": 0},
                 "bindings": [
                     {"id": "bnd_p01", "prop": "props.state", "variableId": "var_pump_01", "mode": "value"},
                     {"id": "bnd_p02", "prop": "visible", "variableId": "var_pump_01", "mode": "visibility",
                      "mapping": {"kind": "enum", "map": {"true": True, "false": False}}},
                 ]},
            ],
        }],
        "alarmRules": [{
            "id": "alm_temp_01", "name": "反应釜温度超高", "variableId": "var_temp_01",
            "op": ">", "threshold": 110, "level": "warn",
            "message": "{label} 超高: {value}", "enabled": True,
            "hysteresis": 2, "durationMs": 5000, "sound": True,
        }],
    }
    return doc


async def put_doc(client, headers, project_id: str, doc: dict, base_revision: int = 1):
    """把 doc 的 project.id 对齐工程后 PUT（测试辅助）。"""
    doc = doc if doc.get("project", {}).get("id") == project_id else {**doc, "project": {**doc["project"], "id": project_id}}
    return await client.put(
        f"/api/v1/projects/{project_id}", headers=headers, json={"doc": doc, "baseRevision": base_revision}
    )
