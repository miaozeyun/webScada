"""Modbus 16/32 位寄存器编解码纯函数（供 collector Modbus 源读写与测试共用）。

字节序语义表（32 位取字 ``[hi, lo]``，hi 为链路上第一个寄存器）：

    ABCD : (hi<<16) | lo            —— 大端，不交换
    CDAB : (lo<<16) | hi            —— 字交换
    BADC : ABCD 结果按字内字节交换
    DCBA : CDAB 结果按字内字节交换

16 位：ABCD / CDAB 不交换；BADC / DCBA 按字内字节交换。

非法字数、非法枚举（data_type / byte_order）、越界值一律 ``raise ValueError``。

本模块零 app 内依赖（仅标准库 struct/typing），保证可独立单测与前后端逻辑对照。
整型换算按上表位运算直做（字节序已在字层面归一）；float32 借 struct 做
IEEE 754 二进制浮点映射（``>f`` / ``>I`` 同为 4 字节大端，往返无损）。
"""
import struct
from typing import Literal, Sequence

ModbusDataType = Literal["int16", "uint16", "int32", "uint32", "float32"]
ModbusByteOrder = Literal["ABCD", "CDAB", "BADC", "DCBA"]

# 合法枚举（单点定义，校验与查表共用）
_DT_16 = ("int16", "uint16")
_DT_32 = ("int32", "uint32", "float32")

# 32 位字节序 → (hi 取自第几字, lo 取自第几字, 组合前是否字内字节交换)
# BADC = ABCD 结果字内交换 → 等价于先交换再按 (hi, lo) 组合；DCBA = CDAB 同理
_ORDER_32 = {
    "ABCD": (0, 1, False),
    "CDAB": (1, 0, False),
    "BADC": (0, 1, True),
    "DCBA": (1, 0, True),
}
# 16 位字节序 → 是否字内字节交换（ABCD/CDAB 对单字无差别）
_ORDER_16 = {"ABCD": False, "CDAB": False, "BADC": True, "DCBA": True}

# 各整型编码取值域（越界即 ValueError）
_INT_RANGE = {
    "int16": (-0x8000, 0x7FFF),
    "uint16": (0x0000, 0xFFFF),
    "int32": (-0x80000000, 0x7FFFFFFF),
    "uint32": (0x00000000, 0xFFFFFFFF),
}


def _swap16(word: int) -> int:
    """字内字节交换（位运算一次写对，编码解码共用）。"""
    return ((word & 0xFF) << 8) | (word >> 8)


def _check_word(word: int) -> int:
    """校验单个寄存器字为 0~0xFFFF 的 int。"""
    if not isinstance(word, int) or isinstance(word, bool) or not (0 <= word <= 0xFFFF):
        raise ValueError(f"非法寄存器字: {word!r}（须为 0~0xFFFF 的 int）")
    return word


def _check_enums(data_type: str, byte_order: str) -> None:
    """校验数据类型与字节序枚举。"""
    if data_type not in _DT_16 and data_type not in _DT_32:
        raise ValueError(f"未知 Modbus 数据类型: {data_type!r}")
    if byte_order not in _ORDER_32:
        raise ValueError(f"未知 Modbus 字节序: {byte_order!r}")


def modbus_word_count(data_type: str) -> int:
    """返回数据类型占用寄存器字数：int16/uint16 → 1，int32/uint32/float32 → 2。"""
    if data_type in _DT_16:
        return 1
    if data_type in _DT_32:
        return 2
    raise ValueError(f"未知 Modbus 数据类型: {data_type!r}")


def decode_modbus_registers(
    words: Sequence[int], data_type: str, byte_order: str
) -> int | float:
    """按数据类型与字节序把寄存器字序列解为数值（语义表见模块 docstring）。"""
    _check_enums(data_type, byte_order)
    if data_type in _DT_16:
        if len(words) != 1:
            raise ValueError(f"{data_type} 需要 1 个寄存器字，实得 {len(words)} 个")
        value = _check_word(words[0])
        if _ORDER_16[byte_order]:
            value = _swap16(value)
        if data_type == "int16":
            return value - 0x10000 if value >= 0x8000 else value  # 符号位还原
        return value
    # 32 位
    if len(words) != 2:
        raise ValueError(f"{data_type} 需要 2 个寄存器字，实得 {len(words)} 个")
    hi_idx, lo_idx, swapped = _ORDER_32[byte_order]
    hi = _check_word(words[hi_idx])
    lo = _check_word(words[lo_idx])
    if swapped:
        hi, lo = _swap16(hi), _swap16(lo)
    combined = (hi << 16) | lo
    if data_type == "uint32":
        return combined
    if data_type == "int32":
        return combined - 0x100000000 if combined >= 0x80000000 else combined  # 符号位还原
    return struct.unpack(">f", struct.pack(">I", combined))[0]


def encode_modbus_registers(
    value: int | float, data_type: str, byte_order: str
) -> list[int]:
    """按数据类型与字节序把数值编为寄存器字序列（与 decode 严格互逆）。"""
    _check_enums(data_type, byte_order)
    if data_type in _DT_16:
        low, high = _INT_RANGE[data_type]
        if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
            raise ValueError(f"{data_type} 越界或非法值: {value!r}（须为 {low}~{high} 的 int）")
        word = value & 0xFFFF
        if _ORDER_16[byte_order]:
            word = _swap16(word)
        return [word]
    # 32 位：先归一为大端 32 位组合值
    if data_type == "float32":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"float32 非法值: {value!r}（须为 int/float）")
        try:
            combined = struct.unpack(">I", struct.pack(">f", value))[0]
        except OverflowError as exc:  # 超出 float32 表示域 → 统一按越界 ValueError
            raise ValueError(f"float32 越界值: {value!r}") from exc
    else:
        low, high = _INT_RANGE[data_type]
        if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
            raise ValueError(f"{data_type} 越界或非法值: {value!r}（须为 {low}~{high} 的 int）")
        combined = value & 0xFFFFFFFF
    hi_idx, lo_idx, swapped = _ORDER_32[byte_order]
    hi, lo = combined >> 16, combined & 0xFFFF
    if swapped:
        hi, lo = _swap16(hi), _swap16(lo)
    out = [0, 0]
    out[hi_idx], out[lo_idx] = hi, lo
    return out
