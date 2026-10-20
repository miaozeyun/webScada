"""分享链接（M6）与报警记录（M5）接口：创建 → 匿名访问 → 撤销 / 上报 → 查询。"""
from tests.conftest import make_doc


async def _create(client, headers) -> str:
    resp = await client.post("/api/v1/projects", headers=headers, json={"name": "分享工程"})
    return resp.json()["id"]


async def test_share_lifecycle(client, auth_headers):
    project_id = await _create(client, auth_headers)

    # 创建（永久）
    resp = await client.post(f"/api/v1/projects/{project_id}/shares", headers=auth_headers, json={})
    assert resp.status_code == 201
    token = resp.json()["token"]
    assert len(token) >= 24

    # 匿名访问：拿到脱敏快照 doc
    resp = await client.get(f"/api/v1/shares/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["projectName"] == "分享工程"
    assert body["doc"]["project"]["id"] == project_id

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


async def test_alarm_records_roundtrip(client, auth_headers):
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
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["level"] == "warn" and rows[0]["status"] == "active"
    assert rows[0]["triggeredAt"] is not None
