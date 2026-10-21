"""Modbus 16/32 位编解码纯函数测试：关键向量精确断言 + 全组合 roundtrip + 非法输入。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.services.modbus_codec import (  # noqa: E402
    decode_modbus_registers,
    encode_modbus_registers,
    modbus_word_count,
)


def test_decode_uint16_int16():
    assert decode_modbus_registers([0x0064], "uint16", "ABCD") == 100
    assert decode_modbus_registers([0xFFFF], "int16", "ABCD") == -1


def test_decode_float32_both_endians():
    assert decode_modbus_registers([0x42C8, 0x0000], "float32", "ABCD") == 100.0
    assert decode_modbus_registers([0x0000, 0x42C8], "float32", "CDAB") == 100.0


def test_decode_uint32_badc_dcba():
    # 0x000186A0 = 100000；BADC = 每字字节交换：0x0001→0x0100, 0x86A0→0xA086
    assert decode_modbus_registers([0x0100, 0xA086], "uint32", "BADC") == 100000
    assert decode_modbus_registers([0xA086, 0x0100], "uint32", "DCBA") == 100000


def test_word_count():
    assert modbus_word_count("int16") == 1 and modbus_word_count("float32") == 2


def test_encode_roundtrip_all_types():
    for dt, v in [("int16", -123), ("uint16", 65535), ("int32", -70000), ("uint32", 100000), ("float32", 23.5)]:
        for bo in ("ABCD", "CDAB", "BADC", "DCBA"):
            words = encode_modbus_registers(v, dt, bo)
            assert decode_modbus_registers(words, dt, bo) == v


def test_invalid_inputs_raise():
    import pytest
    with pytest.raises(ValueError): decode_modbus_registers([0x1234], "float32", "ABCD")
    with pytest.raises(ValueError): decode_modbus_registers([0x0001], "int9", "ABCD")
    with pytest.raises(ValueError): encode_modbus_registers(-1, "uint16", "ABCD")
