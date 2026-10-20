"""换算流水唯一实现点（M8 工作包 A）：原始值 → 工程值。

口径权威：docs/design/02-工程JSON数据结构.md §2.9「服务端换算流水」：
① address/jsonPath 定位帧取值（缺帧/解析失败 → q='bad'，由 collector 传 raw=MISSING/None 表达）
② bitIndex 位提取（与 scale/offset/precision 互斥，schema 校验保证；提取后仍按 type 规范化）
③ 按 type 规范化：number=×scale+offset；boolean 归一 true/1/'1'→true，其余→false；string 原样
   （string 判定用原始 raw：数值字符串预转换只服务 number/bitIndex 路径，"42" 不得被转丢）
④ number 且 precision 非空 → decimal.Decimal ROUND_HALF_UP 量化。
   禁用内置 round()（银行家舍入），防止服务端判定与前端显示在 x.5 边界分叉。
⑤ 结果类型与 type 不符 → (None, 'bad')，值保持上一有效由 hub 负责。
"""
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, NamedTuple

from app.schemas.doc import VariableDef

# 值质量位（03-接口清单 §3.4）；bad 时 v=null、值保持上一有效
QUALITY_GOOD = "good"
QUALITY_STALE = "stale"
QUALITY_BAD = "bad"

_MISSING = object()
MISSING = _MISSING  # collector「帧内无此字段」哨兵：与 None（显式 null）区分，二者均判 bad

_PATH_KEY_RE = re.compile(r"\[(\d+)\]")


class EngineeringValue(NamedTuple):
    """换算结果：value 为工程值（bad 时 None），q 为质量位。"""

    value: float | bool | str | None
    q: str  # good | stale | bad


def get_by_path(data: Any, path: str | None) -> Any:
    """载荷点路径取值（02 §1 第 4 条子集语法）：a.b.c / a[0].b；空路径返回原值。

    缺失返回 MISSING 哨兵（与值恰为 None 区分）。与前端 sources.getByPath 同构。
    """
    if not path:
        return data
    cur: Any = data
    for key in _PATH_KEY_RE.sub(r".\1", path).split("."):
        if not key:
            continue
        if isinstance(cur, dict):
            cur = cur.get(key, _MISSING)
        elif isinstance(cur, list) and key.isdigit():
            idx = int(key)
            cur = cur[idx] if idx < len(cur) else _MISSING
        else:
            return _MISSING
        if cur is _MISSING:
            return _MISSING
    return cur


def pick_value(message: Any, var: VariableDef) -> Any:
    """按变量 address 定位帧 + jsonPath 深取（rest/websocket 上游帧；mqtt 由 collector 先按 topic 路由）。"""
    base: Any = message
    if var.address and isinstance(message, dict):
        base = message.get(var.address, _MISSING)
    return get_by_path(base, var.jsonPath)


def _is_number_str(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _quantize(num: float, precision: int) -> float:
    """Decimal ROUND_HALF_UP 量化（02 §2.9 第 4 条：禁用内置 round 防银行家舍入分叉）。"""
    exp = Decimal(1).scaleb(-precision)
    try:
        return float(Decimal(str(num)).quantize(exp, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return num


def to_engineering(var: VariableDef, raw: Any) -> EngineeringValue:
    """换算流水入口（签名冻结，契约 §6.1）。raw 传 MISSING/None 表示缺帧/解析失败。"""
    if raw is None or raw is _MISSING:
        return EngineeringValue(None, QUALITY_BAD)

    value: Any = raw
    # 可解析数字的非空字符串先转数值（与前端 engine.toEngineering 同口径）
    if isinstance(value, str) and value != "" and _is_number_str(value):
        value = float(value)

    # ② 位提取（bitIndex 优先；schema 保证与 scale/offset/precision 互斥）
    if var.bitIndex is not None:
        if isinstance(value, bool):
            intval = int(value)
        elif isinstance(value, (int, float)):
            intval = int(value)  # 非整数输入先截断（02 §2.9 第 2 条）
        else:
            return EngineeringValue(None, QUALITY_BAD)  # ToInt 失败 → bad
        bit = (intval >> var.bitIndex) & 1
        # 位提取后继续按 type 规范化：boolean 归一 true/false；number 保留 0/1
        if var.type == "boolean":
            return EngineeringValue(bit == 1, QUALITY_GOOD)
        if var.type == "number":
            return EngineeringValue(float(bit), QUALITY_GOOD)
        return EngineeringValue(None, QUALITY_BAD)  # string×bitIndex 被 schema 拦截，双保险

    # ③ 按 type 规范化
    if var.type == "number":
        # 注意 bool 是 int 子类：JS typeof true === 'boolean'，number 变量收到布尔 → 类型不符 bad
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return EngineeringValue(None, QUALITY_BAD)
        num = float(value)
        scale = 1.0 if var.scale is None else float(var.scale)
        offset = 0.0 if var.offset is None else float(var.offset)
        num = num * scale + offset
        if not math.isfinite(num):
            return EngineeringValue(None, QUALITY_BAD)
        if var.precision is not None:  # ④ ROUND_HALF_UP 量化
            num = _quantize(num, var.precision)
        return EngineeringValue(num, QUALITY_GOOD)

    if var.type == "boolean":
        if isinstance(value, bool):
            return EngineeringValue(value, QUALITY_GOOD)
        if isinstance(value, (int, float)) and value == 1:
            return EngineeringValue(True, QUALITY_GOOD)
        if isinstance(value, str) and value == "1":
            return EngineeringValue(True, QUALITY_GOOD)
        # 其余（0 / '0' / false / '' 等）一律归一 false（02 §2.9 第 3 条）
        return EngineeringValue(False, QUALITY_GOOD)

    # string：原样（bitIndex 与 string 互斥，schema 拦截）。
    # 用原始 raw 判定：数值字符串预转换只服务 number/bitIndex 路径，
    # 否则 string 变量收到 "42" 会被预转成 42.0 后误判类型不符 → q=bad 值丢失
    if isinstance(raw, str):
        return EngineeringValue(raw, QUALITY_GOOD)
    return EngineeringValue(None, QUALITY_BAD)  # 结果类型与 type 不符 → bad（第 5 条）
