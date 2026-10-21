"""图片上传：鉴权、魔数校验、体积上限、匿名读取、路径防护。"""
import base64

from app.core.config import settings

# 1×1 透明 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


async def test_upload_requires_auth(client):
    resp = await client.post("/api/v1/uploads", files={"file": ("a.png", _PNG, "image/png")})
    assert resp.status_code == 401


async def test_upload_and_public_read(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    resp = await client.post(
        "/api/v1/uploads", headers=auth_headers, files={"file": ("a.png", _PNG, "image/png")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == f"/api/v1/uploads/{body['name']}"
    assert body["size"] == len(_PNG)
    assert body["name"].endswith(".png")

    # 匿名读取（分享页无登录态）：内容与安全头
    got = await client.get(body["url"])
    assert got.status_code == 200
    assert got.content == _PNG
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"


async def test_upload_rejects_non_image(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    # 伪装 Content-Type 也拒绝（按魔数判定）
    resp = await client.post(
        "/api/v1/uploads", headers=auth_headers,
        files={"file": ("evil.png", b"<svg onload=alert(1)>", "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_file"


async def test_upload_rejects_oversize(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_MAX_BYTES", 8)
    resp = await client.post(
        "/api/v1/uploads", headers=auth_headers, files={"file": ("a.png", _PNG, "image/png")}
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == "file_too_large"


async def test_upload_read_rejects_bad_name(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    resp = await client.get("/api/v1/uploads/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404
    resp = await client.get("/api/v1/uploads/" + "a" * 32 + ".png")
    assert resp.status_code == 404
