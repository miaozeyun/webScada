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


# ================= M7：反控 / 虚拟变量 / 事件 / 弹框 / 动效通道 =================


async def test_m7_widgets_and_anim_binding_accepted(client, auth_headers):
    """新组件类型 + anim.* 绑定路径 + lockPan + move 动画 + 事件/悬停/弹框（合法形态全通过）"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["pages"][0]["screen"]["lockPan"] = True
    comp = doc["pages"][0]["components"][0]
    comp["type"] = "var-display"
    comp["props"] = {"prefix": "", "unit": "", "precision": 2}
    comp["bindings"] = [
        {"id": "bnd_m7_a", "prop": "anim.rotateOn", "variableId": doc["variables"][1]["id"], "mode": "value", "mapping": None},
        {"id": "bnd_m7_b", "prop": "anim.rotatePeriod", "variableId": doc["variables"][0]["id"], "mode": "value", "mapping": None},
    ]
    comp["animations"] = {"move": {"enabled": True, "path": "M 0 0 L 300 0", "periodMs": 8000, "mode": "pingpong"}}
    comp["tooltip"] = {"enabled": True, "template": "温度 {reactor1_temp} ℃"}
    doc["pages"][0]["components"].append({
        "id": "grp_m7", "name": "弹框组", "type": "group", "x": 0, "y": 0, "w": 100, "h": 100, "z": 1,
        "props": {}, "bindings": [], "children": [],
        "popup": {"style": "menu", "title": "操作", "triggerExpr": "reactor1_temp > 80"},
    })
    comp["events"] = [
        {"id": "evt_m7", "trigger": "contextmenu", "actions": [{"type": "showPopup", "targetId": "grp_m7"}]},
    ]
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_anim_binding_requires_value_mode(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    _binding(doc, 0)["prop"] = "anim.rotateOn"
    _binding(doc, 0)["mode"] = "color"
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any("anim" in e["message"] or "value" in e["message"] for e in resp.json().get("errors", []))


async def test_virtual_variable_datasource_sentinel(client, auth_headers):
    """expr 变量：datasourceId='virtual' 通过；expr 配真实数据源被拒"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"].append({
        "id": "var_m7_virtual", "key": "avg_temp", "label": "平均温度", "type": "number",
        "datasourceId": "virtual", "expr": "reactor1_temp * 2",
    })
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200

    bad = make_doc()
    bad["variables"].append({
        "id": "var_m7_virtual", "key": "avg_temp", "label": "平均温度", "type": "number",
        "datasourceId": doc["variables"][0]["datasourceId"],  # expr 配了真实数据源 → 422
        "expr": "reactor1_temp * 2",
    })
    resp = await put_doc(client, auth_headers, pid, bad, base_revision=2)
    assert resp.status_code == 422


async def test_write_var_event_requires_writable_variable(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    comp = doc["pages"][0]["components"][0]
    comp["events"] = [
        {"id": "evt_m7_w", "trigger": "click", "actions": [
            {"type": "writeVar", "variableId": doc["variables"][0]["id"], "value": "1"},  # 未开启 writable → 422
        ]},
    ]
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any(e["path"].endswith("actions[0].variableId") for e in resp.json()["errors"])

    doc["variables"][0]["writable"] = True  # 开启后通过
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_event_target_references_validated(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    comp = doc["pages"][0]["components"][0]
    comp["events"] = [
        {"id": "evt_m7_p", "trigger": "click", "actions": [{"type": "switchPage", "pageId": "page_missing"}]},
    ]
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any(e["path"].endswith("actions[0].pageId") for e in resp.json()["errors"])

    comp["events"][0]["actions"][0] = {"type": "showPopup", "targetId": "node_missing"}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422


async def test_popup_only_on_group(client, auth_headers):
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["pages"][0]["components"][0]["popup"] = {"style": "dialog"}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422


async def test_mock_hold_and_anim_move_on_accepted(client, auth_headers):
    """M7 案例：hold 波形（反控回环）+ anim.moveOn 轨迹启停通道，合法形态通过"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"].append({
        "id": "var_m7_hold", "key": "ctl.run", "label": "运行开关", "type": "number",
        "datasourceId": doc["variables"][0]["datasourceId"], "writable": True,
        "defaultValue": 1, "mock": {"kind": "hold"},
    })
    comp = doc["pages"][0]["components"][0]
    comp["bindings"].append({
        "id": "bnd_m7_move", "prop": "anim.moveOn", "variableId": "var_m7_hold", "mode": "value", "mapping": None,
    })
    comp["animations"] = {"move": {"enabled": False, "path": "M 0 0 L 300 0", "periodMs": 8000, "mode": "loop"}}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


# ================= 工厂可用阶段一 Task 3：Modbus 增量字段 + 跨检 =================


async def test_modbus_variable_with_modbus_fields_accepted(client, auth_headers):
    """modbus 数据源变量携带 modbusDataType/modbusByteOrder/unitId → 合法通过"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["datasources"] = [{
        "id": "ds_modbus_01", "name": "车间 PLC", "type": "modbus", "enabled": True,
        "config": {"host": "192.168.1.10", "port": 502, "unitId": 1, "intervalMs": 1000},
    }]
    doc["variables"][0].update({
        "datasourceId": "ds_modbus_01", "address": "40101", "jsonPath": None,
        "modbusDataType": "float32", "modbusByteOrder": "CDAB", "unitId": 2,
    })
    doc["variables"][1].update({"datasourceId": "ds_modbus_01", "address": "00001"})
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_modbus_fields_rejected_on_non_modbus_source(client, auth_headers):
    """mqtt 变量携带 modbusDataType → 422 reference_error，errors 指向具体字段路径"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["variables"][0]["modbusDataType"] = "float32"  # 所属 ds_mqtt_01 非 modbus → 422
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "reference_error"
    assert any(e["path"] == "variables[0].modbusDataType" for e in body["errors"])


# ================= 工厂可用阶段二 Task 4：settings.notify 通知渠道契约 =================


async def test_notify_channels_all_kinds_accepted(client, auth_headers):
    """四种渠道合法形态全通过（缺省 minLevel=warn 可省略）"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": [
        {"kind": "webhook", "url": "https://hook.local/alarm"},
        {"kind": "dingtalk", "url": "https://oapi.dingtalk.com/robot/send?access_token=t", "secret": "SECxx"},
        {"kind": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k", "minLevel": "critical"},
        {"kind": "email", "recipients": ["a@t.test", "b@t.test"], "minLevel": "info"},
    ]}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_notify_unknown_kind_rejected(client, auth_headers):
    """非法 kind → 422 doc_invalid（discriminated union 分发失败）"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": [{"kind": "sms", "url": "https://x.test/hook"}]}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "doc_invalid"
    assert any("channels[0]" in e["path"] for e in body["errors"])


async def test_notify_webhook_url_must_be_https(client, auth_headers):
    """webhook/钉钉/企微 URL 必须以 https:// 开头（http 拒绝）"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": [{"kind": "webhook", "url": "http://hook.local/alarm"}]}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    # 判别联合错误路径带 kind 段：settings.notify.channels[0].webhook.url
    assert any("channels[0].webhook.url" in e["path"] for e in resp.json()["errors"])

    doc["settings"]["notify"]["channels"][0]["url"] = "https://hook.local/alarm"
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_notify_email_recipients_bounds_and_format(client, auth_headers):
    """收件人 1~20 个且每个含 @：空列表/超限/缺 @ → 422，errors 带字段路径"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": [{"kind": "email", "recipients": []}]}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any("channels[0].email.recipients" in e["path"] for e in resp.json()["errors"])

    doc["settings"]["notify"]["channels"][0]["recipients"] = [f"u{i}@t.test" for i in range(21)]  # 超限
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422

    doc["settings"]["notify"]["channels"][0]["recipients"] = ["not-an-email"]  # 缺 @
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any(e["path"].endswith("channels[0].email.recipients") for e in resp.json()["errors"])

    doc["settings"]["notify"]["channels"][0]["recipients"] = ["ops@t.test"]
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200


async def test_notify_bad_min_level_rejected(client, auth_headers):
    """minLevel 仅 info/warn/critical"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["settings"]["notify"] = {"channels": [
        {"kind": "webhook", "url": "https://hook.local/a", "minLevel": "fatal"},
    ]}
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 422
    assert any(e["path"].endswith("channels[0].webhook.minLevel") for e in resp.json()["errors"])


async def test_realtime_table_widget_type_accepted(client, auth_headers):
    """工厂可用阶段二 Task 6：WidgetType 纯增量 +realtime-table（schemaVersion 冻结 1，旧 doc 不受影响）。"""
    pid = await _create(client, auth_headers)
    doc = make_doc()
    doc["pages"][0]["components"].append({
        "id": "cmp_rt_table_01", "type": "realtime-table", "name": "产线实时表",
        "x": 40, "y": 40, "w": 360, "h": 260, "z": 3,
        "props": {
            "columns": '[{"key":"reactor1_temp","label":"1号反应釜温度","precision":1,"unit":"°C"}]',
            "showQuality": True, "showUnit": True,
        },
        "bindings": [],
    })
    resp = await put_doc(client, auth_headers, pid, doc)
    assert resp.status_code == 200
