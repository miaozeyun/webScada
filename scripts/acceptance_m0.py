# -*- coding: utf-8 -*-
"""M0 容器化验收脚本（对齐 docs/design/04-分阶段任务拆解.md M0 验收标准）。
用法：python scripts/acceptance_m0.py [base_url]  （默认 http://localhost:8088）
"""
import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8088"
API = f"{BASE}/api/v1"
TOKEN = ""
PASS = 0
FAIL = 0

# 凭证一律从环境变量读取，不写入仓库（模板见 .env.example）
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
MQTT_USER = os.environ.get("MQTT_USER", "factory")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")

_missing = [n for n in ("ADMIN_PASSWORD", "MQTT_PASSWORD") if not os.environ.get(n)]
if _missing:
    sys.exit(f"缺少环境变量：{', '.join(_missing)}（示例：ADMIN_PASSWORD=*** MQTT_PASSWORD=*** python scripts/acceptance_m0.py）")


def req(method: str, path: str, body: dict | None = None, auth: bool = True, raw: bool = False):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            content = resp.read()
            return resp.status, (content if raw else (json.loads(content) if content else None))
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            return e.code, json.loads(content)
        except Exception:
            return e.code, content.decode(errors="replace")


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{mark}] {name}" + (f"  | {detail}" if detail and not cond else ""))


# 1. 管理员登录
st, body = req("POST", "/auth/login", {"username": ADMIN_USER, "password": ADMIN_PASSWORD}, auth=False)
check("登录 200", st == 200)
TOKEN = body["access_token"]

st, body = req("POST", "/auth/login", {"username": "admin", "password": "wrong"}, auth=False)
check("错误密码 401 + 统一信封", st == 401 and body.get("code") == "LOGIN_FAILED")

# 2. 建工程（不携带 doc，G7）
st, body = req("POST", "/projects", {"name": "一号车间产线", "description": "M0 验收"})
check("建工程 201 + revision=1", st == 201 and body["revision"] == 1)
pid = body["id"]

# 3. 列表不含 doc；详情含 doc 且 id 一致（G9）
st, body = req("GET", f"/projects?page=1&size=10")
check("列表 200 且条目不含 doc", st == 200 and all("doc" not in it for it in body["items"]))
st, body = req("GET", f"/projects/{pid}")
check("详情 doc.project.id 与库 id 一致", body["doc"]["project"]["id"] == pid and len(body["doc"]["pages"]) == 1)
doc = body["doc"]

# 4. 保存含凭证 doc（中文标签/绑定/报警规则全链）
doc["datasources"] = [{
    "id": "ds_mqtt_01", "name": "车间 EMQX", "type": "mqtt", "enabled": True,
    "config": {"brokerUrl": "mqtt://emqx:1883", "username": MQTT_USER, "password": MQTT_PASSWORD,
               "topics": ["factory/line1/#"], "qos": 0, "cleanSession": True},
}]
doc["variables"] = [
    {"id": "var_temp_01", "key": "reactor1_temp", "label": "1号反应釜温度", "type": "number",
     "unit": "°C", "datasourceId": "ds_mqtt_01", "address": "factory/line1/reactor1",
     "jsonPath": "data.temp", "scale": 0.1, "precision": 1},
    {"id": "var_pump_01", "key": "pump1_running", "label": "1号循环泵运行", "type": "boolean",
     "datasourceId": "ds_mqtt_01", "address": "factory/line1/pump1", "jsonPath": "data.running", "bitIndex": 0},
]
page = doc["pages"][0]
page["components"] = [
    {"id": "cmp_gauge_01", "type": "gauge", "name": "温度仪表盘", "x": 120, "y": 200, "w": 320, "h": 320,
     "z": 1, "props": {"value": 0}, "bindings": [
        {"id": "bnd_g01", "prop": "props.value", "variableId": "var_temp_01", "mode": "value"},
        {"id": "bnd_g02", "prop": "style.color", "variableId": "var_temp_01", "mode": "color",
         "mapping": {"kind": "range", "bands": [{"max": 80, "value": "#22c55e"}, {"min": 80, "value": "#ef4444"}]}}]},
    {"id": "cmp_pump_01", "type": "pump", "name": "1号循环泵", "x": 560, "y": 240, "w": 120, "h": 120,
     "z": 2, "props": {"state": 0}, "bindings": [
        {"id": "bnd_p01", "prop": "props.state", "variableId": "var_pump_01", "mode": "value"}]},
]
doc["alarmRules"] = [{"id": "alm_01", "name": "反应釜温度超高", "variableId": "var_temp_01", "op": ">",
                      "threshold": 110, "level": "warn", "message": "{label} 超高: {value}", "enabled": True}]
st, body = req("PUT", f"/projects/{pid}", {"doc": doc, "baseRevision": 1})
check("保存 doc 200 + revision=2", st == 200 and body["revision"] == 2, str(body)[:120])

# 5. GET 详情与导出均脱敏（G6）
st, body = req("GET", f"/projects/{pid}")
cfg = body["doc"]["datasources"][0]["config"]
check("详情脱敏：password 空、username 保留", cfg["password"] == "" and cfg["username"] == "factory")
st, exported = req("GET", f"/projects/{pid}/export")
check("导出脱敏", exported["datasources"][0]["config"]["password"] == "")

# 6. 导出文件可再次导入（凭证视为空，G6/G7）
st, body = req("POST", "/projects/import", {"doc": exported})
check("round-trip 导入 201 + 新 id", st == 201 and body["id"] != pid)
imported_id = body.get("id")

# 7. 乐观锁 409（G2）
st, body = req("PUT", f"/projects/{pid}", {"doc": doc, "baseRevision": 1})
check("乐观锁冲突 409 + currentRevision", st == 409 and body.get("code") == "REVISION_CONFLICT" and body.get("currentRevision") == 2)

# 8. 坏引用 422 + 字段路径（G20）
bad = json.loads(json.dumps(doc))
bad["pages"][0]["components"][0]["bindings"][0]["variableId"] = "var_missing"
st, body = req("PUT", f"/projects/{pid}", {"doc": bad, "baseRevision": 2})
check("坏引用 422 + errors 路径", st == 422 and body.get("errors", [{}])[0].get("path")
      == "pages[0].components[0].bindings[0].variableId", str(body)[:120])

# 9. 高版本 schemaVersion 422（G8）
bad2 = json.loads(json.dumps(doc))
bad2["schemaVersion"] = 99
st, body = req("POST", "/projects/import", {"doc": bad2})
check("version_unsupported 422", st == 422 and body.get("code") == "version_unsupported")

# 10. 删除 204 → 404（级联 share_links/alarm_records 由 FK 保证）
st, _ = req("DELETE", f"/projects/{imported_id}")
check("删除 204", st == 204)
st, _ = req("GET", f"/projects/{imported_id}")
check("删除后 404", st == 404)

# 11. 登出后旧 token 401
st, _ = req("POST", "/auth/logout")
check("登出 204", st == 204)
st, _ = req("GET", "/auth/me")
check("登出后旧 token 401", st == 401)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
