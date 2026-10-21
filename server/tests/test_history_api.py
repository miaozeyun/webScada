"""历史区间查询 API 测试（B 包，契约 §4.2 / 03 §2.10）：双通道鉴权、stepMs 聚合、maxPoints。"""
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.errors import register_handlers
from app.core.security import create_access_token, hash_password
from app.db.base import Base, get_db
from app.db.models import HistoryValue, Project, ShareLink, User

UTCD = timezone.utc
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTCD)
T0_MS = int(T0.timestamp() * 1000)


def ms(n: int) -> int:
    return T0_MS + n


@pytest.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SimpleNamespace(engine=engine, factory=factory)
    await engine.dispose()


@pytest.fixture
async def api(env):
    from fastapi import FastAPI

    from app.api.v1 import history as history_api

    app = FastAPI()
    register_handlers(app)
    app.include_router(history_api.router, prefix="/api/v1")

    async def _override():
        async with env.factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield SimpleNamespace(client=c, app=app, factory=env.factory)


async def make_user(env, role="viewer") -> User:
    async with env.factory() as s:
        u = User(username=f"u_{role}_{uuidlib.uuid4().hex[:6]}", password_hash=hash_password("pw12345678"), role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def make_project(env, owner_id) -> Project:
    async with env.factory() as s:
        p = Project(id=uuidlib.uuid4(), name="P", description=None, doc={}, revision=1, owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def make_share(env, project_id, token: str, revoked=False, expires_at=None) -> ShareLink:
    async with env.factory() as s:
        sh = ShareLink(id=uuidlib.uuid4(), project_id=project_id, token=token,
                       doc_snapshot={}, revoked_at=datetime.now(UTCD) if revoked else None,
                       expires_at=expires_at)
        s.add(sh)
        await s.commit()
        await s.refresh(sh)
        return sh


async def seed(env, pid: str, key: str, points: list[tuple[int, float]]):
    async with env.factory() as s:
        for off, v in points:
            s.add(HistoryValue(project_id=pid, variable_key=key, ts=datetime.fromtimestamp((T0_MS + off) / 1000, tz=UTCD), value=v))
        await s.commit()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------- 鉴权双通道 ----------------

async def test_no_auth_and_garbage_token_401(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={"keys": "a", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"})
    assert r.status_code == 401
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={"keys": "a"}, headers=auth("not-a-token"))
    assert r.status_code == 401
    r = await api.client.get(f"/api/v1/projects/{uuidlib.uuid4()}/history", headers=auth("x"))
    assert r.status_code == 404  # 工程不存在优先


async def test_jwt_any_role_ok(api, env):
    viewer = await make_user(env, role="viewer")
    pid = (await make_project(env, viewer.id)).id
    await seed(env, pid, "temp", [(0, 1.0)])
    token = create_access_token(str(viewer.id))[0]
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"}, headers=auth(token))
    assert r.status_code == 200
    assert r.json()["series"]["temp"] == [[ms(0), 1.0]]


async def test_share_token_channel_and_guards(api, env):
    owner = await make_user(env, role="admin")
    p1 = await make_project(env, owner.id)
    p2 = await make_project(env, owner.id)
    await seed(env, p1.id, "temp", [(0, 5.0)])
    await seed(env, p2.id, "temp", [(0, 6.0)])

    ok = await make_share(env, p1.id, "tok_ok_aaaaaaaaaaaaaaaaaaaaaaaaaa")
    revoked = await make_share(env, p1.id, "tok_revoked_aaaaaaaaaaaaaaaaaaaaaa", revoked=True)
    expired = await make_share(env, p1.id, "tok_expired_aaaaaaaaaaaaaaaaaaaaa",
                               expires_at=datetime.now(UTCD) - timedelta(days=1))
    other = await make_share(env, p2.id, "tok_other_aaaaaaaaaaaaaaaaaaaaaaa")

    q = {"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"}
    r = await api.client.get(f"/api/v1/projects/{p1.id}/history", params=q, headers=auth(ok.token))
    assert r.status_code == 200 and r.json()["series"]["temp"] == [[ms(0), 5.0]]

    r = await api.client.get(f"/api/v1/projects/{p1.id}/history", params=q, headers=auth(revoked.token))
    assert r.status_code == 403 and r.json()["code"] == "SHARE_REVOKED"
    r = await api.client.get(f"/api/v1/projects/{p1.id}/history", params=q, headers=auth(expired.token))
    assert r.status_code == 403 and r.json()["code"] == "SHARE_EXPIRED"
    r = await api.client.get(f"/api/v1/projects/{p1.id}/history", params=q, headers=auth(other.token))
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"  # 分享链接与工程不匹配


# ---------------- 参数校验 ----------------

async def test_param_validation(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    token = create_access_token(str(u.id))[0]
    h = auth(token)
    base = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"}

    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={**base, "keys": ",".join(f"k{i}" for i in range(21))}, headers=h)
    assert r.status_code == 422  # keys > 20
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"}, headers=h)
    assert r.status_code == 422  # from ≥ to
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={**base, "maxPoints": 20000}, headers=h)
    assert r.status_code == 422  # maxPoints ≤ 10000


async def test_span_limit_422(api, env, monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_RETENTION_DAYS", 1)
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"from": "2026-01-01T00:00:00Z", "to": "2026-01-09T00:00:00Z"},
        headers=auth(token),
    )
    assert r.status_code == 422


# ---------------- 聚合与降采样 ----------------

async def test_step_ms_window_mean(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 1.0), (300, 2.0), (600, 3.0), (900, 4.0), (1500, 10.0)])
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z", "stepMs": 1000},
        headers=auth(token),
    )
    assert r.status_code == 200
    assert r.json()["series"]["temp"] == [[ms(0), 2.5], [ms(1000), 10.0]]  # 窗口均值


async def test_step_ms_auto_coarsen_by_max_points(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 1.0), (500, 2.0), (1000, 3.0), (1500, 4.0), (2000, 5.0), (2500, 6.0)])
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:03Z",
                "stepMs": 1000, "maxPoints": 1},
        headers=auth(token),
    )
    assert r.status_code == 200
    pts = r.json()["series"]["temp"]
    assert len(pts) == 1  # 自动增大 stepMs 至只余 1 点


async def test_raw_decimation_by_max_points(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 1.0), (100, 2.0), (200, 3.0), (300, 4.0)])
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:01:00Z", "maxPoints": 2},
        headers=auth(token),
    )
    assert r.status_code == 200
    pts = r.json()["series"]["temp"]
    assert pts == [[ms(0), 1.0], [ms(200), 3.0]]  # 等距抽稀（stride=2）


# ---------------- 行数硬上限（终审 #2） ----------------

async def test_row_cap_forced_aggregation(api, env, monkeypatch):
    """逐 key 行数触顶：原始模式（stepMs=0）自动提升 stepMs 强制聚合，防全窗加载 OOM。

    仅保留最新 cap 行（倒序限量再回正），聚合后点数 ≤ maxPoints。
    """
    monkeypatch.setattr(settings, "HISTORY_MAX_ROWS_PER_KEY", 3)
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(o, float(o // 100)) for o in range(0, 5000, 100)])  # 50 点
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z"},
        headers=auth(token),
    )
    assert r.status_code == 200
    pts = r.json()["series"]["temp"]
    # 仅最新 3 行（4700/4800/4900ms），强制步长 = ceil(5000/2000) = 3ms，桶锚定窗口起点 from_ms
    assert pts == [[ms(4698), 47.0], [ms(4800), 48.0], [ms(4899), 49.0]]


async def test_row_cap_not_hit_raw_mode_unchanged(api, env, monkeypatch):
    """行数未触顶：原始模式行为不变（全窗原始点返回）。"""
    monkeypatch.setattr(settings, "HISTORY_MAX_ROWS_PER_KEY", 3)
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 1.0), (100, 2.0), (200, 3.0)])
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:01Z"},
        headers=auth(token),
    )
    assert r.status_code == 200
    assert r.json()["series"]["temp"] == [[ms(0), 1.0], [ms(100), 2.0], [ms(200), 3.0]]


async def test_keys_filter_and_default_all(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "a", [(0, 1.0)])
    await seed(env, pid, "b", [(0, 2.0), (100, 3.0)])
    await seed(env, pid, "c", [(0, 9.9), (100, 9.9), (200, 9.9)])
    token = create_access_token(str(u.id))[0]
    h = auth(token)
    q = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"}

    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={**q, "keys": "a,b"}, headers=h)
    body = r.json()["series"]
    assert sorted(body.keys()) == ["a", "b"] and body["a"] == [[ms(0), 1.0]]

    # 缺省 keys → 区间内有数据的全部 key（03 §2.10）；c 的 3 点全部落在 to 之内
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={
        "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:00.250Z"}, headers=h)
    body = r.json()["series"]
    assert sorted(body.keys()) == ["a", "b", "c"]
    assert body["c"] == [[ms(0), 9.9], [ms(100), 9.9], [ms(200), 9.9]]

    # 请求了但无数据的 key → 空数组
    r = await api.client.get(f"/api/v1/projects/{pid}/history", params={**q, "keys": "zz"}, headers=h)
    assert r.json()["series"] == {"zz": []}


# ---------------- 聚合扩展（阶段二 Task 1：agg=min/max/last/sum） ----------------

async def test_agg_modes_single_bucket(api, env):
    """六点同窗（1,5,3,7,9,2）→ 五种聚合精确值；last 取窗口内最后一个点（≠max，可区分实现）。"""
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 1.0), (100, 5.0), (200, 3.0), (300, 7.0), (400, 9.0), (500, 2.0)])
    token = create_access_token(str(u.id))[0]
    expect = {"mean": 4.5, "min": 1.0, "max": 9.0, "last": 2.0, "sum": 27.0}
    for agg, val in expect.items():
        r = await api.client.get(
            f"/api/v1/projects/{pid}/history",
            params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z",
                    "stepMs": 5000, "agg": agg},
            headers=auth(token),
        )
        assert r.status_code == 200, agg
        assert r.json()["series"]["temp"] == [[ms(0), val]], agg


async def test_agg_multi_bucket(api, env):
    """跨桶：last=各窗口内最后一点，max=各窗口内极值（桶锚定窗口起点，逐桶独立聚合）。"""
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(0, 5.0), (400, 3.0), (500, 8.0), (900, 6.0)])
    token = create_access_token(str(u.id))[0]
    for agg, expect in {
        "last": [[ms(0), 3.0], [ms(500), 6.0]],
        "max": [[ms(0), 5.0], [ms(500), 8.0]],
        "min": [[ms(0), 3.0], [ms(500), 6.0]],
    }.items():
        r = await api.client.get(
            f"/api/v1/projects/{pid}/history",
            params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z",
                    "stepMs": 500, "agg": agg},
            headers=auth(token),
        )
        assert r.status_code == 200, agg
        assert r.json()["series"]["temp"] == expect, agg


async def test_agg_invalid_422(api, env):
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:01Z", "agg": "avg"},
        headers=auth(token),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_agg_share_token_channel(api, env):
    """分享 token 免登录通道同样支持 agg（历史图分享页与编辑器同口径）。"""
    owner = await make_user(env, role="admin")
    p = await make_project(env, owner.id)
    await seed(env, p.id, "temp", [(0, 1.0), (100, 5.0), (200, 9.0)])
    share = await make_share(env, p.id, "tok_agg_aaaaaaaaaaaaaaaaaaaaaa")
    r = await api.client.get(
        f"/api/v1/projects/{p.id}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z",
                "stepMs": 5000, "agg": "max"},
        headers=auth(share.token),
    )
    assert r.status_code == 200
    assert r.json()["series"]["temp"] == [[ms(0), 9.0]]


async def test_row_cap_forced_agg_respects_agg(api, env, monkeypatch):
    """行数触顶强制聚合：同样走所选 agg（max 与 mean 结果不同，防止强制路径漏传参数）。"""
    monkeypatch.setattr(settings, "HISTORY_MAX_ROWS_PER_KEY", 6)
    u = await make_user(env)
    pid = (await make_project(env, u.id)).id
    await seed(env, pid, "temp", [(o, float(o // 100)) for o in range(0, 5000, 100)])  # 50 点
    token = create_access_token(str(u.id))[0]
    r = await api.client.get(
        f"/api/v1/projects/{pid}/history",
        params={"keys": "temp", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:05Z",
                "maxPoints": 10, "agg": "max"},
        headers=auth(token),
    )
    assert r.status_code == 200
    # 原始模式触顶 → 强制步长 ceil(5000/10)=500；仅留最新 6 行（4400~4900 → 44~49）
    # 桶 4000=[44]；桶 4500=[45,46,47,48,49] → max=49（mean=47，可区分）
    assert r.json()["series"]["temp"] == [[ms(4000), 44.0], [ms(4500), 49.0]]
