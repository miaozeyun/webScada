"""通知投递记录接口（2026-10-26）：outbox 可观测 + 渠道信息脱敏。"""
import uuid as uuidlib
from datetime import datetime, timezone

from app.db.models import NotificationOutbox


async def _project(client, headers) -> str:
    resp = await client.post("/api/v1/projects", headers=headers, json={"name": "通知工程"})
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_deliveries_list_and_redact(client, auth_headers, db_factory):
    project_id = await _project(client, auth_headers)
    now = datetime.now(timezone.utc)
    async with db_factory() as db:
        db.add(
            NotificationOutbox(
                project_id=uuidlib.UUID(project_id),
                alarm_id=7,
                event="trigger",
                channel_kind="dingtalk",
                channel_json={
                    "kind": "dingtalk",
                    "url": "https://oapi.dingtalk.com/robot/send?access_token=LEAK_ME",
                    "secret": "LEAK_ME_TOO",
                    "minLevel": "warn",
                },
                payload_json={"rec": {"message": "温度超限", "level": "critical"}, "rule": {}},
                status="sent",
                attempts=1,
                next_at=now,
                sent_at=now,
            )
        )
        await db.commit()

    resp = await client.get(
        f"/api/v1/projects/{project_id}/notifications/deliveries", headers=auth_headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["status"] == "sent" and row["event"] == "trigger"
    assert row["message"] == "温度超限" and row["level"] == "critical"
    # 渠道只回显类型 + host，不含 path/token/secret
    assert row["channelLabel"].startswith("钉钉")
    assert "oapi.dingtalk.com" in row["channelLabel"]
    assert "LEAK_ME" not in str(row)


async def test_deliveries_requires_operator(client, auth_headers, db_factory):
    """viewer 不可读投递记录（渠道信息属运维面）。"""
    from app.core.security import hash_password
    from app.db.models import User

    project_id = await _project(client, auth_headers)
    async with db_factory() as db:
        db.add(User(username="viewer1", password_hash=hash_password("viewer12345"), role="viewer"))
        await db.commit()
    login = await client.post(
        "/api/v1/auth/login", json={"username": "viewer1", "password": "viewer12345"}
    )
    token = login.json()["access_token"]
    resp = await client.get(
        f"/api/v1/projects/{project_id}/notifications/deliveries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
