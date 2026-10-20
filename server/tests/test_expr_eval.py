"""expr_eval 与前端 web/src/utils/expr.ts 同构用例（契约 §9 A 包：文法逐一对应，最易漂移点）。

每条用例对齐 TS 实现行为本身（而非直觉 JS/Python 语义），分叉点见 expr_eval 模块注释。
"""
import math

import pytest

from app.services.expr_eval import eval_expr, expr_idents, to_num


def ev(src: str, scope=None):
    return eval_expr(src, scope or {})


# ---------------- 四则与优先级 ----------------


def test_arithmetic_precedence():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("10 / 4") == 2.5
    assert ev("2 - 3 - 4") == -5  # 左结合
    assert ev("2 * 3 % 4") == 2


def test_division_by_zero_is_zero():
    """TS 实现：零除/零模得 0，不抛异常。"""
    assert ev("1 / 0") == 0
    assert ev("0 / 0") == 0
    assert ev("5 % 0") == 0


def test_modulo_js_sign():
    """JS 余号符号随被除数：-5 % 3 = -2（Python 原生 % 得 1，必须 fmod）。"""
    assert ev("-5 % 3") == -2
    assert ev("5 % -3") == 2


def test_unary():
    assert ev("-3 + 5") == 2
    assert ev("+4") == 4
    assert ev("!0") is True
    assert ev("!1") is False
    assert ev("- '3'") == -3.0  # 操作数经 toNum 强转


def test_number_tokens():
    assert ev(".5 + 1") == 1.5
    assert ev("1.25 * 2") == 2.5
    # 科学计数法不在文法内（TS 逐条镜像）：按「数字+未知标识符」报尾部多余
    with pytest.raises(SyntaxError):
        ev("1e3")


# ---------------- 比较 / 相等 / 逻辑 / 三元 ----------------


def test_comparisons():
    assert ev("3 > 2") is True
    assert ev("2 >= 2") is True
    assert ev("'10' < 9") is False  # 操作数 toNum：'10'→10
    assert ev("1 != 2") is True


def test_equality_semantics():
    """镜像 TS 实现本身：eq = (l === r) || looseEq(l, r) 对 ==/=== 一并生效——
    即严格等并不真正「严格」，宽等不命中时才回落到类型严格的直接比较。"""
    assert ev("1 == '1'") is True  # 宽等
    assert ev("1 === '1'") is True  # TS 实现下 === 亦走 looseEq（1 == '1' 宽等成立）
    assert ev("1 === 1.0") is True
    assert ev("true === 1") is True  # 宽等 toNum 归一同样作用于 ===
    assert ev("true === 'true'") is True  # 宽等 js_str('true') 命中
    assert ev("1 === 2") is False
    assert ev("true === 2") is False
    assert ev("null == null") is True
    assert ev("null == 0") is False
    assert ev("'a' != 'b'") is True
    assert ev("1 !== '1'") is False  # !== 同理镜像：宽等成立则取反为 False


def test_logical_and_ternary():
    assert ev("true && false") is False
    assert ev("false || 2") is True  # or/and 返回布尔（非操作数，TS 实现口径）
    assert ev("0 || ''") is False
    assert ev("1 > 0 ? 'yes' : 'no'") == "yes"
    assert ev("0 ? 1 : 2") == 2
    assert ev("true ? 1 : unknown_var") == 1  # 三元惰性：未选分支不求值


def test_scope_lookup():
    assert ev("a + b", {"a": 1.5, "b": 2}) == 3.5
    assert ev("tank.level > 5", {"tank.level": 6}) is True  # 点形式 key
    with pytest.raises(ReferenceError):
        ev("nope + 1", {})


def test_truthy_table():
    """TS truthy：true/非零数值（含 NaN）/非空且非 'false'/'0' 字符串。"""
    assert ev("a ? 1 : 0", {"a": "x"}) == 1
    assert ev("a ? 1 : 0", {"a": "0"}) == 0
    assert ev("a ? 1 : 0", {"a": "false"}) == 0
    assert ev("a ? 1 : 0", {"a": ""}) == 0
    assert ev("a ? 1 : 0", {"a": 0.0}) == 0
    assert ev("a ? 1 : 0", {"a": True}) == 1


# ---------------- 字符串拼接（js_str 口径）----------------


def test_string_concat():
    assert ev("'T=' + a", {"a": 1.5}) == "T=1.5"
    assert ev("'T=' + a", {"a": 2.0}) == "T=2"  # 1.0 → '1'（js_str 整数省小数）
    assert ev("'T=' + a", {"a": True}) == "T=true"
    assert ev("'T=' + a", {"a": None}) == "T="


def test_concat_vs_add():
    assert ev("1 + 2") == 3
    assert ev("'1' + 2") == "12"


# ---------------- 内置函数 ----------------


def test_builtins_math():
    assert ev("abs(-3)") == 3
    assert ev("min(3, 1, 2)") == 1
    assert ev("max(3, 1, 2)") == 3
    assert ev("floor(1.9)") == 1
    assert ev("ceil(1.1)") == 2
    assert ev("pow(2, 10)") == 1024
    assert ev("sqrt(9)") == 3
    assert ev("sqrt(4) + abs(0 - 1)") == 3


def test_builtin_round_js_half_up():
    """TS round：Math.round 为 half-up（towards +∞），非 Python 银行家舍入。"""
    assert ev("round(2.5)") == 3
    assert ev("round(-2.5)") == -2  # Math.round(-2.5) = -2
    assert ev("round(2.456, 2)") == 2.46
    assert ev("round(0.25, 1)") == 0.3
    assert ev("round(7)") == 7


def test_builtin_args_coerced():
    """TS 实现：全部实参先 toNum（字符串数字可参与）。"""
    assert ev("min('3', 2)") == 2
    assert ev("abs('-4')") == 4


def test_unknown_function_and_syntax():
    with pytest.raises(SyntaxError):
        ev("foo(1)")
    with pytest.raises(SyntaxError):
        ev("1 +")
    with pytest.raises(SyntaxError):
        ev("(1 + 2")
    with pytest.raises(SyntaxError):
        ev("'未闭合")
    with pytest.raises(SyntaxError):
        ev("1 2")  # 尾部多余


# ---------------- NaN 传播 ----------------


def test_nan_semantics():
    assert math.isnan(ev("1.2.3"))  # 非法数字串 → NaN 常量
    assert ev("1.2.3 == 1.2.3") is False  # NaN 宽等恒假（JS）


def test_to_num_helper():
    assert to_num(True) == 1.0
    assert to_num(False) == 0.0
    assert to_num("2.5") == 2.5
    assert to_num("x") == 0.0
    assert to_num(None) == 0.0


# ---------------- expr_idents ----------------


def test_expr_idents_extraction():
    assert expr_idents("min(a, b) + c.d + a") == ["a", "b", "c.d"]  # 保序去重
    assert expr_idents("true ? x : null") == ["x"]  # 排除常量
    assert expr_idents("round(x, 1) + y") == ["x", "y"]  # 排除内置函数
    assert expr_idents("'lit' + 1") == []


def test_compile_cache():
    """同一表达式串重复求值使用缓存（虚拟变量每 tick 求值的性能前提）。"""
    scope = {"a": 1}
    assert eval_expr("a + 1", scope) == 2
    scope["a"] = 41
    assert eval_expr("a + 1", scope) == 42
