"""健康检查（compose healthcheck 依赖）。"""


async def test_health_ok(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "version" in body and "uptimeSec" in body
