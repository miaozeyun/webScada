"""doc 契约校验：结构（Pydantic）与引用完整性（02 §2.13 规则 1~5）。"""
from tests.conftest import make_doc, put_doc


async def _create(client, headers) -> str:
    resp = await client.post("/api/v1/projects", headers=headers, json={"name": "校验用工程"})
    return resp.json()["id"]


def _binding(doc, idx: int = 0) -> dict:
    return doc["pages"][0]["components"][0]["bindings"][idx]


async def test_color_binding_requires_mapping(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    _binding(doc, 1).pop("mapping")  # 第二条是 color 绑定：去 mapping → 422
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert resp.json()["code"] == "doc_invalid"


async def test_color_binding_target_must_be_color_path(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    _binding(doc, 1)["prop"] = "props.text"  # color 绑定指向非颜色路径 → 422
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422


async def test_visibility_binding_target_must_be_visible(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    # pump 组件的 visibility 绑定（components[1].bindings[1]）指向非 visible 路径 → 422
    doc["pages"][0]["components"][1]["bindings"][1]["prop"] = "style.fill"
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422


async def test_binding_reference_not_found_with_path(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    _binding(doc, 0)["variableId"] = "var_missing"
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "reference_error"
    # G20：errors 指出具体字段路径
    assert body["errors"][0]["path"] == "pages[0].components[0].bindings[0].variableId"


async def test_duplicate_variable_key(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"][1]["key"] = doc["variables"][0]["key"]  # key 重复
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any(e["path"] == "variables[1].key" for e in resp.json()["errors"])


async def test_bit_index_mutually_exclusive_with_scale(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"][1]["scale"] = 2  # bitIndex 与 scale 同配 → 422（规则 5）
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422


async def test_alarm_rule_on_string_variable_rejected(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"][0]["type"] = "string"  # 报警规则挂在 string 变量上 → 422（02 §2.11）
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any("string" in e["message"] for e in resp.json()["errors"])


async def test_boolean_variable_only_eq_ne(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["alarmRules"][0]["variableId"] = "var_pump_01"  # boolean 变量
    doc["alarmRules"][0]["op"] = ">"
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422

    # 合法形态：== 且 threshold 1/0
    doc["alarmRules"][0]["op"] = "=="
    doc["alarmRules"][0]["threshold"] = 1
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_project_id_mismatch_rejected(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    # project.id 与库内不一致（put_doc 会自动对齐，这里手动破坏）
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200  # 对齐后正常
    doc2 = make_doc(name="伪造")
    doc2["project"]["id"] = "3fa85f64-5717-4562-b3fc-2c963f66afa6"  # 合法 UUID 但非本工程
    resp = await client.put(
        f"/api/v1/projects/{pid}",
        headers=auth_headers,
        json={"doc": doc2, "baseRevision": 2},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "project_id_mismatch"


async def test_non_uuid_project_id_rejected(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["project"]["id"] = "nanoid_style_id"  # 拦截 nanoid 风格 id（规则 4）
    resp = await client.put(
        f"/api/v1/projects/{pid}", headers=auth_headers, json={"doc": doc, "baseRevision": 1}
    )
    assert resp.status_code == 422
    assert any(e["path"] == "project.id" for e in resp.json()["errors"])
