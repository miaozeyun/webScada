"""工程 CRUD / 乐观锁 / 体积上限（验收项 3、9、7）。"""
from tests.conftest import make_doc, put_doc


async def _create(client, headers, name="一号车间") -> dict:
    resp = await client.post("/api/v1/projects", headers=headers, json={"name": name, "description": "测试工程"})
    assert resp.status_code == 201
    return resp.json()


async def test_create_project_with_blank_doc(client, auth_headers):
    body = await _create(client, auth_headers)
    assert body["revision"] == 1
    # 创建不携带 doc（G7），创建响应无 doc 内容
    detail = await client.get(f"/api/v1/projects/{body['id']}", headers=auth_headers)
    assert detail.status_code == 200
    doc = detail.json()["doc"]
    # 空白模板：1 个默认页面、蓝色主题；doc.project.id 与 DB UUID 一致（G9）
    assert doc["project"]["id"] == body["id"]
    assert len(doc["pages"]) == 1 and doc["pages"][0]["screen"]["designWidth"] == 1920
    assert doc["settings"]["theme"] == "blue-dark"


async def test_list_has_no_doc(client, auth_headers):
    created = await _create(client, auth_headers)
    resp = await client.get("/api/v1/projects", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1 and data["page"] == 1
    item = data["items"][0]
    assert item["id"] == created["id"] and "doc" not in item


async def test_update_doc_revision_and_name_sync(client, auth_headers):
    created = await _create(client, auth_headers)
    doc = make_doc()
    resp = await put_doc(client, auth_headers, created["id"], doc, base_revision=1)
    assert resp.status_code == 200
    assert resp.json()["revision"] == 2

    # doc.project.name 同步到列表列（列表不含 doc，名字以 doc 为准）
    listing = await client.get("/api/v1/projects", headers=auth_headers)
    assert listing.json()["items"][0]["name"] == "演示工程"


async def test_revision_conflict_409(client, auth_headers):
    created = await _create(client, auth_headers)
    doc = make_doc()
    # 第一次保存成功（revision 1 → 2）
    assert (await put_doc(client, auth_headers, created["id"], doc, base_revision=1)).status_code == 200
    # 另一客户端仍持旧 revision 1 提交 → 409 + currentRevision（G2）
    resp = await put_doc(client, auth_headers, created["id"], make_doc(name="冲突版"), base_revision=1)
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "REVISION_CONFLICT" and body["currentRevision"] == 2


async def test_delete_project_cascade(client, auth_headers):
    created = await _create(client, auth_headers)
    resp = await client.delete(f"/api/v1/projects/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/projects/{created['id']}", headers=auth_headers)).status_code == 404


async def test_doc_too_large_422(client, auth_headers):
    created = await _create(client, auth_headers)
    doc = make_doc()
    doc["padding"] = "a" * (2 * 1024 * 1024)  # > 2MB（G21；体积校验先于结构校验）
    resp = await put_doc(client, auth_headers, created["id"], doc)
    assert resp.status_code == 422
    assert resp.json()["code"] == "doc_too_large"


async def test_create_name_too_long_422(client, auth_headers):
    resp = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "x" * 129})
    assert resp.status_code == 422
