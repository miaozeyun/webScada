"""工程 CRUD / 乐观锁 / 体积上限（验收项 3、9、7）。"""
from app.core.security import hash_password
from app.db.models import User
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


async def test_list_thumbnail_projection(client, auth_headers):
    """缩略图走 doc 路径投影读出：保存后列表能拿到，未保存工程为 None（列裁剪不丢字段）。"""
    created = await _create(client, auth_headers)
    doc = make_doc()
    doc["project"]["thumbnail"] = "/uploads/t_a1b2c3.png"
    assert (await put_doc(client, auth_headers, created["id"], doc, base_revision=1)).status_code == 200
    resp = await client.get("/api/v1/projects", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["thumbnail"] == "/uploads/t_a1b2c3.png"
    # 再建一个未保存缩略图的工程：投影缺省回落 None，不误读其他字段
    await _create(client, auth_headers, name="二号车间")
    resp2 = await client.get("/api/v1/projects", headers=auth_headers)
    by_name = {i["name"]: i["thumbnail"] for i in resp2.json()["items"]}
    assert by_name["演示工程"] == "/uploads/t_a1b2c3.png"
    assert by_name["二号车间"] is None


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


async def test_clone_project_copies_doc_with_new_identity(client, auth_headers):
    """模板克隆：新 id/名称，画面/变量/报警原样复制，源工程不受影响。"""
    created = await _create(client, auth_headers)
    doc = make_doc()
    assert (await put_doc(client, auth_headers, created["id"], doc, base_revision=1)).status_code == 200

    resp = await client.post(
        f"/api/v1/projects/{created['id']}/clone", headers=auth_headers, json={"name": "二号机组"}
    )
    assert resp.status_code == 201
    clone = resp.json()
    assert clone["id"] != created["id"] and clone["revision"] == 1

    clone_doc = (await client.get(f"/api/v1/projects/{clone['id']}", headers=auth_headers)).json()["doc"]
    assert clone_doc["project"]["id"] == clone["id"]
    assert clone_doc["project"]["name"] == "二号机组"
    assert [v["key"] for v in clone_doc["variables"]] == [v["key"] for v in doc["variables"]]
    assert len(clone_doc["pages"]) == len(doc["pages"])

    source_doc = (await client.get(f"/api/v1/projects/{created['id']}", headers=auth_headers)).json()["doc"]
    assert source_doc["project"]["id"] == created["id"]
    assert source_doc["project"]["name"] == "演示工程"


async def test_readonly_demo_rejects_save_but_clone_is_editable(client, auth_headers):
    """旗舰演示工程只读（2026-10-29）：导入时可标记 readonly，PUT 一律 403。

    客户演示要求「编辑器能改、但不落库」：前端禁用保存只是体验，服务端必须兜底；
    要定制走「复制工程」，克隆出的新工程必须可编辑。
    """
    doc = make_doc(name="海上风电集控（演示案例）")
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, json={"doc": doc, "readonly": True})
    assert resp.status_code == 201
    imported = resp.json()
    assert imported["readonly"] is True

    pid = imported["id"]
    detail = (await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)).json()
    assert detail["readonly"] is True
    listing = (await client.get("/api/v1/projects", headers=auth_headers)).json()["items"]
    assert next(i for i in listing if i["id"] == pid)["readonly"] is True

    # 保存被拒，且 revision / doc 均未变
    conflict = await put_doc(client, auth_headers, pid, make_doc(name="改坏演示"), base_revision=1)
    assert conflict.status_code == 403
    assert conflict.json()["code"] == "PROJECT_READONLY"
    after = (await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)).json()
    assert after["revision"] == 1 and after["name"] == "海上风电集控（演示案例）"

    # 克隆是定制入口：新工程 readonly=False，可正常保存
    clone = await client.post(f"/api/v1/projects/{pid}/clone", headers=auth_headers, json={"name": "我的风电"})
    assert clone.status_code == 201
    assert clone.json()["readonly"] is False
    saved = await put_doc(client, auth_headers, clone.json()["id"], make_doc(name="我的风电"), base_revision=1)
    assert saved.status_code == 200


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


async def test_pin_project_keeps_it_first(client, auth_headers):
    """置顶工程恒排最前：后创建的工程更新时间更新，也不会把置顶项挤下去。

    置顶不写 doc、不动 revision（避免 UI 操作触发别人的 409 乐观锁冲突）。
    """
    first = await _create(client, auth_headers, name="置顶目标")
    second = await _create(client, auth_headers, name="最新工程")

    # 默认按更新时间倒序：后创建的在最前
    listed = (await client.get("/api/v1/projects", headers=auth_headers)).json()["items"]
    assert [i["name"] for i in listed][:2] == ["最新工程", "置顶目标"]
    assert all(i["pinned"] is False for i in listed)

    before = (await client.get(f"/api/v1/projects/{first['id']}", headers=auth_headers)).json()
    resp = await client.patch(f"/api/v1/projects/{first['id']}/pin", headers=auth_headers, json={"pinned": True})
    assert resp.status_code == 200
    assert resp.json()["pinned"] is True
    assert resp.json()["revision"] == 1  # 置顶不改 revision
    # 也不改 updated_at：否则取消置顶后工程会错误地排到未置顶列表首位
    assert resp.json()["updatedAt"] == before["updatedAt"]

    listed = (await client.get("/api/v1/projects", headers=auth_headers)).json()["items"]
    assert [i["name"] for i in listed][:2] == ["置顶目标", "最新工程"]
    assert listed[0]["pinned"] is True and listed[1]["pinned"] is False

    # 取消置顶后恢复更新时间倒序
    resp = await client.patch(f"/api/v1/projects/{first['id']}/pin", headers=auth_headers, json={"pinned": False})
    assert resp.status_code == 200
    listed = (await client.get("/api/v1/projects", headers=auth_headers)).json()["items"]
    assert [i["name"] for i in listed][:2] == ["最新工程", "置顶目标"]

    # 详情出口同样带 pinned（前端卡片/表格状态回填）
    detail = (await client.get(f"/api/v1/projects/{first['id']}", headers=auth_headers)).json()
    assert detail["pinned"] is False


async def test_pin_viewer_forbidden(client, db_factory, admin_user):
    """viewer 只读：置顶属写操作，403。"""
    async with db_factory() as session:
        session.add(User(username="viewer1", password_hash=hash_password("viewer12345"), role="viewer"))
        await session.commit()

    login = await client.post("/api/v1/auth/login", json={"username": "viewer1", "password": "viewer12345"})
    assert login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # viewer 不能创建工程，用 admin 建好后由 viewer 尝试置顶
    admin_login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin12345"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    created = await _create(client, admin_headers)

    resp = await client.patch(
        f"/api/v1/projects/{created['id']}/pin", headers=viewer_headers, json={"pinned": True}
    )
    assert resp.status_code == 403
