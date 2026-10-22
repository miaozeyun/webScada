"""演示工程种子脚本（工厂可用阶段一 Task 8，阶段二 Task 9 扩展）。

宿主机运行（server venv 已含 httpx），按 API 建立名为「仿真演示工程」的演示 doc：
- modbus 数据源 → sim-modbus:502（compose sim profile 的 sim-modbus 服务）
- mqtt 数据源 → emqx:1883（订阅 sim-mqtt-gateway 发布的 factory/ 主题）
- 报警规则 line1_temp > 75 warn（网关 line1 温度正弦每 60s 扫过 80，必触发）
- 页面 1：标题栏 + 4 个 var-display（双字节序 float32 / int32 / MQTT 温度各一）
  + 实时表格（line1/2/3_temp 三列，列内显式 precision/unit——分享页无变量定义回落时仍可读，
  Task 6 边界）+ 历史表格（1线温度近 24h 小时末值，variableKey 存变量 id，Task 7 语义）
- 可选 --notify-webhook URL：写入 doc.settings.notify 的 webhook 渠道（报警外发）。
  服务端 schema 强制 https://（防明文出口），脚本先行校验；本地明文接收器无法入库，
  阶段验收的实测做法见 docs/经验教训.md（TLS 接收器 + 容器 CA 注入）

前置：`docker compose --profile sim up -d` 已启动（nginx 入口经 BASE 访问）。
幂等：按工程名查找，已存在且与目标一致（变量数 = 基础 9 个 + --points N、两表格组件齐、
notify 渠道与本次参数一致）即跳过并打印工程 id；任一不符（如从 --points 500 回退/首次
追加/切换 --notify-webhook）则全量 PUT 同一工程（凭证空值合并语义，password 每次按
环境变量明文重提，服务端自动重加密）。

用法：
    set -a; source .env; set +a        # 注入 ADMIN_USER/ADMIN_PASSWORD（bash）
    server/.venv/Scripts/python scripts/seed_demo.py            # 基础演示工程（9 变量）
    server/.venv/Scripts/python scripts/seed_demo.py --points 500   # 追加 500 点批量读验证
    server/.venv/Scripts/python scripts/seed_demo.py --notify-webhook https://hooks.example.com/scada   # 报警外发渠道

环境变量：
    BASE               缺省 http://localhost:8088（compose nginx 入口）
    ADMIN_USER         缺省 admin
    ADMIN_PASSWORD     必填（仓库根 .env）
    EMQX_DEFAULT_USERNAME / EMQX_DEFAULT_PASSWORD
                       MQTT 凭证缺省 webscada_mqtt / webscada_mqtt123（与 compose 同口径）

doc 与仿真台对照（scripts/sim/modbus_slave.py、scripts/sim/mqtt_gateway.py docstring）：
    HR 40001 秒计数（int16）→ m_counter；40101 float32=23.5 ABCD → m_temp；
    40103 float32=88.0 CDAB → m_temp_swap；40111 int32=-123456 ABCD → m_int32；
    COIL 00001=True → m_coil；factory/lineN/temp → line1/2/3_temp；
    factory/+/run（通配地址）→ any_run。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid as uuidlib
from datetime import datetime, timezone

import httpx

PROJECT_NAME = "仿真演示工程"
BASE = os.environ.get("BASE", "http://localhost:8088")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MQTT_USERNAME = os.environ.get("EMQX_DEFAULT_USERNAME", "webscada_mqtt")
MQTT_PASSWORD = os.environ.get("EMQX_DEFAULT_PASSWORD", "webscada_mqtt123")


def _nid(prefix: str) -> str:
    """doc 内对象 id：`<前缀>_` + uuid4().hex（Global Constraints 约定）。"""
    return f"{prefix}_{uuidlib.uuid4().hex}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_doc(project_id: str, name: str, points: int, notify_webhook: str | None = None) -> dict:
    """构造演示 doc（寄存器表/主题表一一对照；points>0 时在 modbus 源追加连续 int16 批量点位）。"""
    ds_modbus = {"id": _nid("ds"), "name": "Modbus 仿真从站", "type": "modbus", "enabled": True,
                 "config": {"host": "sim-modbus", "port": 502, "unitId": 1, "intervalMs": 500}}
    ds_mqtt = {"id": _nid("ds"), "name": "车间 MQTT 网关", "type": "mqtt", "enabled": True,
               "config": {"brokerUrl": "mqtt://emqx:1883", "username": MQTT_USERNAME, "password": MQTT_PASSWORD,
                          "topics": ["factory/+/temp", "factory/#"]}}

    def var(key: str, label: str, vtype: str, ds_id: str, **extra) -> dict:
        return {"id": _nid("var"), "key": key, "label": label, "type": vtype, "datasourceId": ds_id, **extra}

    variables = [
        var("m_counter", "秒计数 HR40001", "number", ds_modbus["id"], address="40001"),
        var("m_temp", "温度 ABCD HR40101", "number", ds_modbus["id"], address="40101", unit="°C",
            modbusDataType="float32", modbusByteOrder="ABCD"),
        var("m_temp_swap", "温度 CDAB HR40103", "number", ds_modbus["id"], address="40103", unit="°C",
            modbusDataType="float32", modbusByteOrder="CDAB"),
        var("m_int32", "有符号整数 HR40111", "number", ds_modbus["id"], address="40111",
            modbusDataType="int32", modbusByteOrder="ABCD"),
        var("m_coil", "线圈状态 00001", "boolean", ds_modbus["id"], address="00001"),
        var("line1_temp", "1线温度", "number", ds_mqtt["id"], address="factory/line1/temp", unit="°C", jsonPath="v"),
        var("line2_temp", "2线温度", "number", ds_mqtt["id"], address="factory/line2/temp", unit="°C", jsonPath="v"),
        var("line3_temp", "3线温度", "number", ds_mqtt["id"], address="factory/line3/temp", unit="°C", jsonPath="v"),
        var("any_run", "任意设备运行（通配）", "boolean", ds_mqtt["id"], address="factory/+/run", jsonPath="v"),
    ]
    # 批量点位（--points N）：40001 起连续 int16（sim 从站 HR 偏移 0~511 预置零值区支撑）
    for i in range(1, points + 1):
        variables.append(var(f"m_p{i}", f"批量点位 {i}", "number", ds_modbus["id"], address=f"{40000 + i}"))

    var_id = {v["key"]: v["id"] for v in variables}

    def display(x: float, label: str, unit: str, precision: int, key: str, z: int) -> dict:
        return {"id": _nid("cmp"), "name": label, "type": "var-display",
                "x": x, "y": 200.0, "w": 220.0, "h": 64.0, "z": z,
                "props": {"prefix": label, "unit": unit, "precision": precision},
                "bindings": [{"id": _nid("bnd"), "prop": "props.value",
                              "variableId": var_id[key], "mode": "value"}]}

    page = {"id": _nid("page"), "name": "总览", "order": 0,
            "background": {"color": "#0b1220"},
            "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
            "components": [
                {"id": _nid("cmp"), "name": "标题栏", "type": "title-bar",
                 "x": 560.0, "y": 24.0, "w": 800.0, "h": 64.0, "z": 0,
                 "props": {"text": name, "align": "center"}},
                display(160.0, "温度 ABCD", "°C", 1, "m_temp", 1),
                display(400.0, "温度 CDAB", "°C", 1, "m_temp_swap", 2),
                display(640.0, "int32 读数", "", 0, "m_int32", 3),
                display(880.0, "1线温度", "°C", 1, "line1_temp", 4),
                # 实时表格（阶段二 Task 6）：三温度列；precision/unit 显式进列定义——
                # 分享页无变量定义回落时格式化仍可读（Task 6 分享页边界）
                {"id": _nid("cmp"), "name": "产线温度（实时）", "type": "realtime-table",
                 "x": 160.0, "y": 320.0, "w": 460.0, "h": 240.0, "z": 5,
                 "props": {"columns": json.dumps(
                     [{"key": "line1_temp", "label": "1线温度", "precision": 1, "unit": "°C"},
                      {"key": "line2_temp", "label": "2线温度", "precision": 1, "unit": "°C"},
                      {"key": "line3_temp", "label": "3线温度", "precision": 1, "unit": "°C"}],
                     ensure_ascii=False),
                     "showQuality": True, "showUnit": True}},
                # 历史表格（阶段二 Task 7）：variableKey 按属性面板「变量」选择器口径存变量 id
                # （组件内经 doc.variables/runtime 反查 key），rangeMs 24h × 24 桶 = 小时末值快照
                {"id": _nid("cmp"), "name": "1线温度近 24h（小时末值）", "type": "history-table",
                 "x": 700.0, "y": 320.0, "w": 460.0, "h": 440.0, "z": 6,
                 "props": {"variableKey": var_id["line1_temp"], "rangeMs": 86400000, "bucketCount": 24}},
            ]}

    alarm = {"id": _nid("alm"), "name": "1线温度超高", "variableId": var_id["line1_temp"],
             "op": ">", "threshold": 75, "level": "warn",
             "message": "{label}={value}℃ 超过阈值 {threshold}℃", "enabled": True}

    now = _now_iso()
    settings = {
        "designSize": {"width": 1920, "height": 1080},
        "adaptive": "fit-contain", "theme": "blue-dark", "primaryColor": "#2563eb",
        "alarm": {"levelColors": {"info": "#3b82f6", "warn": "#f59e0b", "critical": "#ef4444"},
                  "soundEnabled": True, "soundThrottleSec": 60},
    }
    if notify_webhook:  # 报警外发渠道（阶段二 Task 4：doc.settings.notify，服务端强制 https）
        settings["notify"] = {"channels": [{"kind": "webhook", "url": notify_webhook, "minLevel": "warn"}]}
    return {
        "schemaVersion": 1,
        "project": {"id": project_id, "name": name, "description": "仿真演示工程（scripts/seed_demo.py 生成）",
                    "author": ADMIN_USER, "createdAt": now, "updatedAt": now},
        "settings": settings,
        "datasources": [ds_modbus, ds_mqtt],
        "variables": variables,
        "pages": [page],
        "alarmRules": [alarm],
    }


def _doc_matches_target(doc: dict, target_vars: int, notify_webhook: str | None) -> bool:
    """幂等判定：变量数 / 两表格组件 / notify 渠道三者都与本次目标一致才跳过全量 PUT。

    组件判定按「类型 + 关键 props」而非新生成的随机 id（每次 build_doc 的 var_/cmp_ id 都会重生成）：
    实时表格看列 key 集合，历史表格看 variableKey 引用的变量在库内 doc 里解析为 line1_temp。
    """
    if len(doc.get("variables") or []) != target_vars:
        return False
    pages = doc.get("pages") or []
    comps = [c for p in pages for c in (p.get("components") or [])]
    var_key_by_id = {v.get("id"): v.get("key") for v in doc.get("variables") or []}

    rt = next((c for c in comps if c.get("type") == "realtime-table"), None)
    if rt is None:
        return False
    try:
        cols = json.loads((rt.get("props") or {}).get("columns") or "[]")
    except (TypeError, ValueError):
        return False
    if {c.get("key") for c in cols} != {"line1_temp", "line2_temp", "line3_temp"}:
        return False

    ht = next((c for c in comps if c.get("type") == "history-table"), None)
    if ht is None or var_key_by_id.get((ht.get("props") or {}).get("variableKey")) != "line1_temp":
        return False

    notify = (doc.get("settings") or {}).get("notify") or {}
    urls = [ch.get("url") for ch in notify.get("channels") or [] if ch.get("kind") == "webhook"]
    return urls == ([notify_webhook] if notify_webhook else [])


def _die(msg: str, resp: httpx.Response | None = None) -> None:
    if resp is not None:
        print(f"[seed] 失败：{msg} HTTP {resp.status_code} {resp.text[:500]}", file=sys.stderr)
    else:
        print(f"[seed] 失败：{msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="建立/更新「仿真演示工程」演示 doc（幂等）")
    parser.add_argument("--points", type=int, default=0,
                        help="在 modbus 源追加 N 个连续地址 int16 变量（40001 起，key m_p{i}），如 --points 500")
    parser.add_argument("--notify-webhook", default=None,
                        help="报警外发 webhook 渠道 URL（写入 doc.settings.notify；服务端强制 https://，"
                             "明文 http:// 会被 422 拒绝）。缺省不配置（回落服务端 env）")
    args = parser.parse_args()
    if not ADMIN_PASSWORD:
        _die("缺少环境变量 ADMIN_PASSWORD（先 source 仓库根 .env）")
    if args.points < 0:
        _die("--points 不允许负数")
    if args.notify_webhook is not None and not args.notify_webhook.startswith("https://"):
        _die(f"--notify-webhook 须为 https:// URL（服务端 schema 强制，收到 {args.notify_webhook!r}）；"
             "本地明文接收器的验收做法见 docs/经验教训.md")

    target_vars = 9 + args.points
    with httpx.Client(base_url=BASE, timeout=20.0) as c:
        r = c.post("/api/v1/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
        if r.status_code != 200:
            _die("登录失败", r)
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 按工程名查找（幂等锚点）
        r = c.get("/api/v1/projects", params={"page": 1, "size": 100}, headers=headers)
        if r.status_code != 200:
            _die("工程列表查询失败", r)
        existing = next((it for it in r.json().get("items", []) if it["name"] == PROJECT_NAME), None)

        if existing is not None:
            pid = existing["id"]
            r = c.get(f"/api/v1/projects/{pid}", headers=headers)
            if r.status_code != 200:
                _die("工程详情查询失败", r)
            revision = r.json()["revision"]
            if _doc_matches_target(r.json().get("doc") or {}, target_vars, args.notify_webhook):
                print(f"[seed] 跳过：工程「{PROJECT_NAME}」已存在且与目标一致 id={pid} 变量数={target_vars}")
                return
            print(f"[seed] 工程已存在 id={pid}，与目标不一致（变量数/表格组件/通知渠道），全量更新 doc")
        else:
            r = c.post("/api/v1/projects", headers=headers,
                       json={"name": PROJECT_NAME, "description": "仿真演示工程（scripts/seed_demo.py 生成）"})
            if r.status_code != 201:
                _die("建工程失败", r)
            pid = r.json()["id"]
            revision = r.json()["revision"]  # 空白模板 revision=1
            print(f"[seed] 工程已创建 id={pid} revision={revision}")

        body = {"doc": build_doc(pid, PROJECT_NAME, args.points, args.notify_webhook), "baseRevision": revision}
        r = c.put(f"/api/v1/projects/{pid}", headers=headers, json=body)
        if r.status_code == 409:  # 乐观锁冲突：刷新 revision 重试一次
            revision = r.json().get("currentRevision") or (c.get(f"/api/v1/projects/{pid}", headers=headers).json()["revision"])
            body["baseRevision"] = revision
            r = c.put(f"/api/v1/projects/{pid}", headers=headers, json=body)
        if r.status_code != 200:
            _die("保存 doc 失败", r)
        print(f"[seed] 完成：id={pid} revision={r.json()['revision']} "
              f"变量={target_vars}（modbus 5+{args.points} / mqtt 4）报警规则=1 页面=1 "
              f"组件=7（含实时/历史表格）notify={'webhook' if args.notify_webhook else '无'}")


if __name__ == "__main__":
    main()
