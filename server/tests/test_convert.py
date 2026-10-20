"""convert 换算流水验收（契约 §9 A 包）：bitIndex/scale/offset/precision（ROUND_HALF_UP 边界 x.5）、
boolean 归一、string 原样、bad/stale 语义、点路径取值。

口径权威：docs/design/02-工程JSON数据结构.md §2.9「服务端换算流水」。
"""
import uuid as uuidlib

from app.schemas.doc import VariableDef
from app.services import convert
from app.services.convert import MISSING, EngineeringValue, get_by_path, to_engineering


def var(**kw) -> VariableDef:
    base = dict(
        id="v1", key="k1", label="变量1", type="number",
        datasourceId="ds1",
    )
    base.update(kw)
    return VariableDef(**base)


# ---------------- 点路径 ----------------


def test_get_by_path_basic():
    data = {"a": {"b": [1, {"c": 7}]}}
    assert get_by_path(data, "a.b[1].c") == 7
    assert get_by_path(data, "a.b.0") == 1
    assert get_by_path(data, None) is data
    assert get_by_path(data, "a.x.y") is MISSING
    assert get_by_path(None, "a") is MISSING


def test_pick_value_uses_address():
    v = var(address="node1", jsonPath="temp")
    assert convert.pick_value({"node1": {"temp": 3}}, v) == 3
    assert convert.pick_value({"node2": {}}, v) is MISSING


# ---------------- number：scale/offset/precision ----------------


def test_number_scale_offset():
    v = var(scale=0.1, offset=1)
    assert to_engineering(v, 725) == EngineeringValue(73.5, "good")


def test_number_precision_round_half_up():
    """x.5 边界必须 ROUND_HALF_UP：内置 round 为银行家舍入（round(0.25,1)=0.2），服务端禁用。"""
    v = var(precision=1)
    assert to_engineering(v, 0.25).value == 0.3
    assert to_engineering(v, 0.24).value == 0.2
    assert to_engineering(v, -0.25).value == -0.3  # HALF_UP 对负数远离零

    v0 = var(precision=0)
    assert to_engineering(v0, 2.5).value == 3.0
    assert to_engineering(v0, -2.5).value == -3.0
    assert to_engineering(v0, 2.4).value == 2.0


def test_number_string_raw_coerced():
    v = var(scale=2)
    assert to_engineering(v, "3.5") == EngineeringValue(7.0, "good")


def test_number_bad_cases():
    v = var()
    assert to_engineering(v, None) == EngineeringValue(None, "bad")
    assert to_engineering(v, MISSING) == EngineeringValue(None, "bad")
    assert to_engineering(v, "abc") == EngineeringValue(None, "bad")
    # 布尔原始值落 number 变量：JS typeof true === 'boolean' → 类型不符 bad
    assert to_engineering(v, True).q == "bad"
    assert to_engineering(v, float("inf")).q == "bad"
    # string 类型变量收到数值 → 类型不符 bad
    assert to_engineering(var(type="string"), 42).q == "bad"


# ---------------- bitIndex（优先于 scale；提取后仍按 type 规范化）----------------


def test_bit_index_boolean_var():
    v = var(type="boolean", bitIndex=0)
    assert to_engineering(v, 5) == EngineeringValue(True, "good")  # 5=101 → 第0位 1
    v1 = var(type="boolean", bitIndex=1)
    assert to_engineering(v1, 5) == EngineeringValue(False, "good")
    assert to_engineering(v1, "2") == EngineeringValue(True, "good")  # 字符串先转数值再取位


def test_bit_index_number_var():
    v = var(type="number", bitIndex=2)
    assert to_engineering(v, 4) == EngineeringValue(1.0, "good")
    # 非整数输入先截断
    assert to_engineering(v, 7.9) == EngineeringValue(1.0, "good")


def test_bit_index_bad_input():
    v = var(type="boolean", bitIndex=0)
    assert to_engineering(v, "on").q == "bad"


# ---------------- boolean 归一 ----------------


def test_boolean_normalize():
    v = var(type="boolean")
    assert to_engineering(v, True).value is True
    assert to_engineering(v, False).value is False
    assert to_engineering(v, 1).value is True
    assert to_engineering(v, 1.0).value is True
    assert to_engineering(v, "1").value is True
    # 其余一律 false：0 / '0' / '' / 'true' / 0.5（02 §2.9 第 3 条白名单口径）
    for raw in (0, "0", "", "true", 0.5, False):
        assert to_engineering(v, raw).value is False, raw
    assert to_engineering(v, None).q == "bad"


# ---------------- string ----------------


def test_string_passthrough():
    v = var(type="string")
    assert to_engineering(v, "运行中") == EngineeringValue("运行中", "good")
    assert to_engineering(v, "") == EngineeringValue("", "good")  # 显式空串是合法字符串值
    # 缺帧（None/MISSING）才是 bad，值保持由 hub 负责
    assert to_engineering(v, None).q == "bad"
    assert to_engineering(v, MISSING).q == "bad"


def test_string_numeric_raw_passthrough():
    """修复回归：数值字符串预转换只服务 number/bitIndex 路径；
    string 变量收到 "42" 必须原样输出（不再被预转成 42.0 后误判类型不符 → q=bad 丢值）。"""
    v = var(type="string")
    assert to_engineering(v, "42") == EngineeringValue("42", "good")
    assert to_engineering(v, "3.14") == EngineeringValue("3.14", "good")
    assert to_engineering(v, "-7").value == "-7"
    # 非字符串数值类型落 string 变量仍是类型不符 bad（口径不变）
    assert to_engineering(v, 42).q == "bad"


# ---------------- 质量位汇总 ----------------


def test_quality_values_only_good_or_bad_from_convert():
    """convert 只产出 good/bad；stale 由 hub 超时翻转（collect 侧无新鲜度概念）。"""
    for raw in (1, "1", True, None, "x", MISSING):
        ev = to_engineering(var(), raw)
        assert ev.q in ("good", "bad")
