"""MQTT 变量地址通配匹配测试：mqtt_topic_matches 纯函数 + MqttSource._dispatch 分发接入。

背景：订阅 topics 可含 +/#（broker 原生支持），但变量 address 此前按全等匹配，
导致通配订阅送达的具体 topic 无法命中变量。修复后 address 亦按订阅通配规则匹配。
"""
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8")

from app.schemas.doc import MqttConfig, MqttDataSource, VariableDef  # noqa: E402
from app.services.collector import MqttSource, mqtt_topic_matches  # noqa: E402


def test_exact_match():
    assert mqtt_topic_matches("factory/line1/temp", "factory/line1/temp")


def test_plus_single_level():
    assert mqtt_topic_matches("factory/+/temp", "factory/line1/temp")
    assert not mqtt_topic_matches("factory/+/temp", "factory/line1/area/temp")
    assert not mqtt_topic_matches("factory/+/temp", "factory/temp")


def test_hash_tail_multilevel():
    assert mqtt_topic_matches("factory/#", "factory/line1/temp")
    assert mqtt_topic_matches("factory/#", "factory")


def test_hash_not_tail_never_matches():
    assert not mqtt_topic_matches("factory/#/temp", "factory/line1/temp")


def test_address_and_topic_stripped():
    assert mqtt_topic_matches(" factory/+/temp ", "factory/line1/temp ")


def test_dispatch_wildcard_address(monkeypatch):
    """分发接入：订阅通配 factory/#，变量 address 通配 factory/+/run，送达 factory/line1/run 应命中。"""
    ds = MqttDataSource(
        id="ds_t",
        name="MQTT",
        type="mqtt",
        config=MqttConfig(brokerUrl="emqx:1883", topics=["factory/#"]),
    )
    var = VariableDef(
        id="var_1",
        key="run",
        label="运行",
        type="number",
        datasourceId="ds_t",
        address="factory/+/run",
        jsonPath="v",
    )
    source = MqttSource(uuid.uuid4(), ds, [var])
    calls: list = []
    monkeypatch.setattr(
        source, "_ingest", lambda variable, raw, ts=None: calls.append((variable, raw))
    )
    source._dispatch("factory/line1/run", b'{"v":1}', None)
    assert len(calls) == 1
    assert calls[0][0] is var
    assert calls[0][1] == 1
