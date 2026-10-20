"""导入/导出流水线：凭证脱敏、库内加密、round-trip、multipart、版本拦截（验收项 5/6）。"""
import json
import uuid as uuidlib

from app.db.models import Project
from tests.conftest import make_doc, put_doc


async def _create(client, headers) -> dict:
    return (await client.post("/api/v1/projects", headers=headers, json={"name": "导入导出用"})).json()


async def test_export_sanitizes_credentials(client, auth_headers, db_factory):
    created = await _create(client, auth_headers)
    assert (await put_doc(client, auth_headers, created["id"], make_doc(password="Secret@123"))).status_code == 200

    # GET 详情：password 脱敏为空、username 保留（G6）
    detail = (await client.get(f"/api/v1/projects/{created['id']}", headers=auth_headers)).json()
    ds = detail["doc"]["datasources"][0]
    assert ds["config"]["password"] == ""
    assert ds["config"]["username"] == "factory"

    # 导出：同样脱敏（G6/G7）
    exported = (await client.get(f"/api/v1/projects/{created['id']}/export", headers=auth_headers)).json()
    assert exported["datasources"][0]["config"]["password"] == ""

    # 库内为 Fernet 密文（防拖库直读，G6）
    async with db_factory() as session:
        project = await session.get(Project, uuidlib.UUID(created["id"]))
        stored_pw = project.doc["datasources"][0]["config"]["password"]
        assert stored_pw.startswith("FER1:") and "Secret@123" not in stored_pw


async def test_import_export_roundtrip(client, auth_headers):
    created = await _create(client, auth_headers)
    assert (await put_doc(client, auth_headers, created["id"], make_doc())).status_code == 200
    exported = (await client.get(f"/api/v1/projects/{created['id']}/export", headers=auth_headers)).json()

    # 导出 → 导入 → 新工程（不覆盖原工程；id 重新生成，G9）
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, json={"doc": exported})
    assert resp.status_code == 201
    imported = resp.json()
    assert imported["id"] != created["id"] and imported["revision"] == 1

    # 导入凭证视为空（规则③）：详情中 password 为空串
    detail = (await client.get(f"/api/v1/projects/{imported['id']}", headers=auth_headers)).json()
    assert detail["doc"]["datasources"][0]["config"]["password"] == ""


async def test_import_multipart_file(client, auth_headers):
    doc = make_doc()
    files = {"file": ("demo.json", json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json")}
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, files=files)
    assert resp.status_code == 201


async def test_import_unsupported_schema_version(client, auth_headers):
    doc = make_doc()
    doc["schemaVersion"] = 99
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, json={"doc": doc})
    assert resp.status_code == 422
    assert resp.json()["code"] == "version_unsupported"


async def test_import_bad_reference_reports_path(client, auth_headers):
    doc = make_doc()
    doc["pages"][0]["components"][0]["bindings"][0]["variableId"] = "var_missing"
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, json={"doc": doc})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["path"] == "pages[0].components[0].bindings[0].variableId"


async def test_import_invalid_json_file(client, auth_headers):
    files = {"file": ("bad.json", b"not-json{", "application/json")}
    resp = await client.post("/api/v1/projects/import", headers=auth_headers, files=files)
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_json"


async def test_credential_merge_keep_and_clear_semantics(client, auth_headers, db_factory):
    """PUT 空值保留合并（02 §4.3 规则⑤）：空串=保留旧值；null=清除。"""
    created = await _create(client, auth_headers)
    # 第一次保存：带明文凭证（入库前加密）
    doc1 = make_doc(password="Secret@123")
    assert (await put_doc(client, auth_headers, created["id"], doc1, base_revision=1)).status_code == 200

    # 第二次保存：编辑器回显脱敏 doc（password=""），用户只改了别的字段 → 空串=保留库内凭证
    doc2 = make_doc(password="")  # 模拟编辑器回显（GET 已脱敏）
    doc2["project"]["name"] = "改名后"
    assert (await put_doc(client, auth_headers, created["id"], doc2, base_revision=2)).status_code == 200

    async with db_factory() as session:
        project = await session.get(Project, uuidlib.UUID(created["id"]))
        stored_pw = project.doc["datasources"][0]["config"]["password"]
        assert stored_pw.startswith("FER1:")  # 库内凭证未被空串抹掉（断数缺陷防护）

    # 第三次保存：显式 null → 清除（对应切到 allow_anonymous broker 的场景）
    doc3 = make_doc(password="")
    doc3["datasources"][0]["config"]["password"] = None
    assert (await put_doc(client, auth_headers, created["id"], doc3, base_revision=3)).status_code == 200

    async with db_factory() as session:
        project = await session.get(Project, uuidlib.UUID(created["id"]))
        config = project.doc["datasources"][0]["config"]
        assert "password" not in config  # 字段已删除
