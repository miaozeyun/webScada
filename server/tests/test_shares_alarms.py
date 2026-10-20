"""分享链接（M6 + M8 终审对齐 03 §2.6）与报警记录（M5）接口测试。

覆盖：创建/匿名访问/撤销生命周期、契约出参（url/revokedAt/expiresAt/refreshedAt/公开端收窄）、
列表端点、撤销与过期路径在线 WS 踢下线（终审 #3）、旧报警上报端点 RBAC（终审 #5）。
"""
import sys
import types
from datetime import datetime, timedelta, timezone

from tests.conftest import make_doc


async def _create(client, headers) -> str:
    resp = await client.post("/api/v1/projects", headers=headers, json={"name": "分享工程"})
    return resp.json()["id"]


def _install_ws_stub(monkeypatch) -> dict:
    """向 sys.modules/包属性注入 ws_manager stub（捕获 reload 与踢下线调用，模拟在线分享连接）。"""
    calls: dict = {"reload": [], "kick": []}

    async def broadcast_reload(token: str) -> None:
        calls["reload"].append(token)

    async def close_share_token(token: str, code: str, message: str) -> None:
        calls["kick"].append((token, code, message))

    stub = types.ModuleType("app.services.ws_manager")
    stub.broadcast_reload = broadcast_reload  # type: ignore[attr-defined]
    stub.close_share_token = close_share_token  # type: ignore[attr-defined]
    # 两处都要盖：shares.py 的惰性 import 是 `from app.services import ws_manager`，
    # 该语句优先经包属性 getattr 命中——只换 sys.modules 条目不会生效
    monkeypatch.setitem(sys.modules, "app.services.ws_manager", stub)
    import app.services as services_pkg

    monkeypatch.setattr(services_pkg, "ws_manager", stub, raising=False)
    return calls


def _parse_utc(value: str) -> datetime:
    """响应时间戳 → aware UTC（SQLite 读回 naive 时按 UTC 口径，与 ws/history 同语义）。"""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------- 生命周期（M6 基线 + M8 出参收窄） ----------------


async def test_share_lifecycle(client, auth_headers):
    project_id = await _create(client, auth_headers)

    # 创建（永久）
    resp = await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    assert resp.status_code == 201
    create_body = resp.json()
    assert set(create_body) == {"token", "url", "expiresAt", "revokedAt", "createdAt"}  # 03 §2.6 出参
    token = create_body["token"]
    assert len(token) >= 24
    assert create_body["url"].endswith(f"/s/{token}")
    assert create_body["revokedAt"] is None

    # 匿名访问：公开出参收窄到 {projectId, createdAt, doc}（03 §2.6，终审 #4）
    resp = await client.get(f"/api/v1/shares/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"projectId", "createdAt", "doc"}
    assert body["projectId"] == project_id
    assert body["doc"]["project"]["id"] == project_id
    assert body["doc"]["project"]["name"] == "分享工程"

    # 撤销后 404
    resp = await client.delete(f"/api/v1/shares/{token}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/shares/{token}")
    assert resp.status_code == 404


async def test_share_snapshot_frozen(client, auth_headers):
    """快照方案：保存后工程更新，分享内容仍为创建时冻结版本。"""
    project_id = await _create(client, auth_headers)
    resp = await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    token = resp.json()["token"]

    # 保存一个页名不同的新版本（project.id/name 需与库内一致，G9，故只改 pages）
    doc = make_doc("分享工程")
    doc["project"]["id"] = project_id
    doc["pages"][0]["name"] = "改名后的页面"
    resp = await client.put(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers,
        json={"doc": doc, "baseRevision": 1},
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/shares/{token}")
    assert resp.json()["doc"]["pages"][0]["name"] != "改名后的页面"


async def test_share_requires_auth(client):
    resp = await client.post("/api/v1/projects/00000000-0000-0000-0000-000000000000/shares", json={})
    assert resp.status_code == 401


# ---------------- 契约对齐（03 §2.6，终审 #4） ----------------


async def test_share_create_expires_at_and_compat(client, auth_headers):
    project_id = await _create(client, auth_headers)

    # 契约字段 expiresAt（ISO8601）
    resp = await client.post(
        f"/api/v1/projects/{project_id}/shares",
        headers=auth_headers,
        json={"expiresAt": "2027-01-01T00:00:00Z"},
    )
    assert resp.status_code == 201
    assert resp.json()["expiresAt"].startswith("2027-01-01T00:00:00")

    # 旧字段 expiresHours 兼容：≈ now + 1h
    resp = await client.post(
        f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={"expiresHours": 1}
    )
    assert resp.status_code == 201
    expires_at = _parse_utc(resp.json()["expiresAt"])
    delta = abs((expires_at - datetime.now(timezone.utc) - timedelta(hours=1)).total_seconds())
    assert delta < 10

    # 双字段同传：expiresAt 优先
    resp = await client.post(
        f"/api/v1/projects/{project_id}/shares",
        headers=auth_headers,
        json={"expiresAt": "2027-06-01T00:00:00Z", "expiresHours": 1},
    )
    assert resp.status_code == 201
    assert resp.json()["expiresAt"].startswith("2027-06-01T00:00:00")

    # 未知字段拒绝（extra=forbid，防拼写错误静默落空）
    resp = await client.post(
        f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={"expireAt": "2027-01-01T00:00:00Z"}
    )
    assert resp.status_code == 422


async def test_share_list_endpoint(client, auth_headers):
    project_id = await _create(client, auth_headers)
    token_a = (
        await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    ).json()["token"]
    token_b = (
        await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={"expiresHours": 2})
    ).json()["token"]
    await client.delete(f"/api/v1/shares/{token_b}", headers=auth_headers)

    resp = await client.get(f"/api/v1/projects/{project_id}/shares", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2  # 已撤销记录保留（revokedAt 供排查）
    by_token = {i["token"]: i for i in items}
    assert by_token[token_a]["revokedAt"] is None
    assert by_token[token_b]["revokedAt"] is not None
    for item in items:
        assert set(item) == {"token", "url", "expiresAt", "revokedAt", "createdAt", "lastAccessAt"}
        assert item["url"].endswith(f"/s/{item['token']}")

    # 未登录 401
    assert (await client.get(f"/api/v1/projects/{project_id}/shares")).status_code == 401


async def test_refresh_returns_refreshed_at(client, auth_headers):
    project_id = await _create(client, auth_headers)
    token = (
        await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    ).json()["token"]

    resp = await client.post(f"/api/v1/shares/{token}/refresh", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"token", "refreshedAt"}  # 03 §2.6：仅 token + refreshedAt
    assert body["token"] == token
    assert abs((_parse_utc(body["refreshedAt"]) - datetime.now(timezone.utc)).total_seconds()) < 10


# ---------------- 撤销/过期即时生效（终审 #3） ----------------


async def test_revoke_kicks_online_share_ws(client, auth_headers, monkeypatch):
    calls = _install_ws_stub(monkeypatch)
    project_id = await _create(client, auth_headers)
    token = (
        await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    ).json()["token"]

    resp = await client.delete(f"/api/v1/shares/{token}", headers=auth_headers)
    assert resp.status_code == 204
    assert calls["kick"] == [(token, "SHARE_REVOKED", "分享链接已撤销，连接即将关闭")]


async def test_expired_public_access_kicks_share_ws(client, auth_headers, monkeypatch):
    calls = _install_ws_stub(monkeypatch)
    project_id = await _create(client, auth_headers)
    token = (
        await client.post(
            f"/api/v1/projects/{project_id}/shares",
            headers=auth_headers,
            json={"expiresAt": "2020-01-01T00:00:00Z"},
        )
    ).json()["token"]

    resp = await client.get(f"/api/v1/shares/{token}")
    assert resp.status_code == 404  # 统一 404 防枚举
    assert calls["kick"] == [(token, "SHARE_EXPIRED", "分享链接已过期，连接即将关闭")]


async def test_revoke_degrades_without_ws_manager(client, auth_headers, monkeypatch):
    """A 包缺席（import 失败语义）：撤销本身成功，仅踢下线广播降级。"""
    monkeypatch.setitem(sys.modules, "app.services.ws_manager", None)  # 强制 import 失败语义
    project_id = await _create(client, auth_headers)
    token = (
        await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    ).json()["token"]
    resp = await client.delete(f"/api/v1/shares/{token}", headers=auth_headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/shares/{token}")).status_code == 404


# ---------------- 报警记录（终审 #5：旧上报端点收紧 operator/admin） ----------------


async def _make_role_user(client, auth_headers, username: str, role: str) -> dict:
    """经 users API 建号后登录，返回该角色的 Bearer headers。"""
    resp = await client.post(
        "/api/v1/users", headers=auth_headers, json={"username": username, "password": "pass12345", "role": role}
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": "pass12345"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_alarm_records_post_requires_operator(client, auth_headers):
    project_id = await _create(client, auth_headers)
    viewer_h = await _make_role_user(client, auth_headers, "viewer_rep", "viewer")
    operator_h = await _make_role_user(client, auth_headers, "operator_rep", "operator")
    payload = {
        "ruleId": "alm_1",
        "variableKey": "plant1.temp",
        "level": "warn",
        "message": "出口温度 超温：95.0℃（阈值 90）",
        "value": "95.0",
        "status": "active",
    }
    # viewer 不得伪造报警记录（终审 #5）
    resp = await client.post(f"/api/v1/projects/{project_id}/alarm-records", headers=viewer_h, json=payload)
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
    # operator/admin 放行（admin 走下方 roundtrip 用例，此处验证 operator）
    resp = await client.post(f"/api/v1/projects/{project_id}/alarm-records", headers=operator_h, json=payload)
    assert resp.status_code == 201


async def test_alarm_records_roundtrip(client, auth_headers):
    """M8 语义（契约 03 §2.7）：旧端点上报 active/recovered 映射状态机 trigger/clear，响应为信封分页。"""
    project_id = await _create(client, auth_headers)
    payload = {
        "ruleId": "alm_1",
        "variableKey": "plant1.temp",
        "level": "warn",
        "message": "出口温度 超温：95.0℃（阈值 90）",
        "value": "95.0",
        "status": "active",
    }
    resp = await client.post(f"/api/v1/projects/{project_id}/alarm-records", headers=auth_headers, json=payload)
    assert resp.status_code == 201

    resp = await client.get(f"/api/v1/projects/{project_id}/alarm-records", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and len(body["items"]) == 1
    row = body["items"][0]
    assert row["level"] == "warn" and row["status"] == "triggered"
    assert row["triggeredAt"] is not None

    # recovered → clear：单行状态机置 cleared（保留 triggeredAt），默认 status 过滤不再出现
    resp = await client.post(
        f"/api/v1/projects/{project_id}/alarm-records",
        headers=auth_headers,
        json={**payload, "status": "recovered"},
    )
    assert resp.status_code == 201
    resp = await client.get(f"/api/v1/projects/{project_id}/alarm-records", headers=auth_headers)
    assert resp.json()["total"] == 0  # 缺省 status=triggered,acked
    resp = await client.get(
        f"/api/v1/projects/{project_id}/alarm-records", headers=auth_headers, params={"status": "cleared"}
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "cleared"
    assert body["items"][0]["triggeredAt"] is not None
    assert body["items"][0]["clearedAt"] is not None
