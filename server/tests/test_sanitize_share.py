"""分享快照投影单测（2026-10-26）：连接配置/通知/地址/演示说明一律不出现在匿名可见 doc。"""
from app.utils.sanitize import sanitize_doc_for_share


def _doc() -> dict:
    return {
        "project": {"id": "p1", "name": "P", "thumbnail": "data:image/jpeg;base64,xxx"},
        "settings": {
            "alarm": {"levelColors": {}, "soundEnabled": True, "soundThrottleSec": 60},
            "notify": {"channels": [{"kind": "webhook", "url": "https://hook.example.com/?token=SECRET"}]},
        },
        "datasources": [
            {
                "id": "ds1",
                "name": "PLC",
                "type": "modbus",
                "enabled": True,
                "config": {"host": "192.168.1.10", "port": 502},
            }
        ],
        "variables": [
            {
                "id": "v1",
                "key": "temp",
                "label": "温度",
                "type": "number",
                "address": "40001",
                "writeAddress": "40002",
                "unitId": 2,
                "range": {"min": 0, "max": 100},
                "datasourceId": "ds1",
            }
        ],
        "pages": [
            {
                "id": "pg1",
                "components": [
                    {"id": "c1", "type": "text", "props": {"text": "说明", "demoNote": True}},
                    {
                        "id": "g1",
                        "type": "group",
                        "props": {},
                        "children": [
                            {"id": "c2", "type": "text", "props": {"text": "组内说明", "demoNote": True}},
                            {"id": "c3", "type": "text", "props": {"text": "正常"}},
                        ],
                    },
                ],
            }
        ],
    }


def test_share_projection_strips_secrets_and_demo_notes():
    out = sanitize_doc_for_share(_doc())

    assert "thumbnail" not in out["project"]
    assert "notify" not in out["settings"]
    assert "config" not in out["datasources"][0]
    var = out["variables"][0]
    for key in ("address", "writeAddress", "unitId", "range"):
        assert key not in var
    # 渲染必需字段保留
    assert var["key"] == "temp" and var["datasourceId"] == "ds1"

    comps = out["pages"][0]["components"]
    assert [c["id"] for c in comps] == ["g1"]
    assert [c["id"] for c in comps[0]["children"]] == ["c3"]


def test_share_projection_does_not_mutate_source():
    doc = _doc()
    sanitize_doc_for_share(doc)
    assert "config" in doc["datasources"][0]
    assert doc["pages"][0]["components"][0]["id"] == "c1"
