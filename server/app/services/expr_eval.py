"""Python 白名单表达式求值器（M8 工作包 A）：服务端虚拟变量求值。

文法与前端 web/src/utils/expr.ts 逐一对应（契约 §11.2：最易漂移点，用例必须同构）：
- 记号：十进制数字（含 .5 形式，不支持科学计数法）/ 单双引号字符串（无转义）/ 标识符
  （字母或下划线开头，可含 . _ 数字）/ 运算符长者优先
- 文法（优先级低→高）：ternary > or > and > equality > relational > additive > multiplicative > unary > primary
- 语义分叉点（与 TS 实现逐条对齐，而非直觉 Python）：
  * 四则操作数经 to_num 强转；除/模 零除得 0；模为 JS 语义 fmod（符号随被除数）
  * + 任一侧为字符串 → JS 风格字符串拼接（js_str：true/'1.0'→'1'/None→''）
  * 宽等 loose_eq 镜像 TS 实现本身（true=='1' → False），严格等区分 bool/数值/字符串
  * 三元惰性求值；or/and 返回布尔（非操作数）
  * 未知标识符在求值期抛 ReferenceError（解析期不查作用域）
- 语法错误抛 SyntaxError；编译结果按表达式串缓存（每 tick 求值，解析开销必须摊销）
"""
import json
import math
import re
from typing import Any, Callable

# 求值器值域（与 hub 池内工程值一致）
Value = float | bool | str | None
Scope = dict[str, Value]

_OPS = ["===", "!==", "==", "!=", ">=", "<=", "&&", "||", "+", "-", "*", "/", "%", ">", "<", "!", "?", ":", "(", ")", ","]
_IDENT_HEAD_RE = re.compile(r"[A-Za-z_]")
_IDENT_RE = re.compile(r"[A-Za-z0-9_.]")
_WS_RE = re.compile(r"\s")
_DIGIT_RE = re.compile(r"[0-9]")


class _Token:
    __slots__ = ("type", "value")

    def __init__(self, type_: str, value: str) -> None:
        self.type = type_
        self.value = value

    def __repr__(self) -> str:  # 调试友好
        return f"{self.type}:{self.value}"


def _tokenize(src: str) -> list[_Token]:
    tokens: list[_Token] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if _WS_RE.match(ch):
            i += 1
            continue
        # 数字（十进制；与 TS 一致不支持科学计数法——1e3 会按「数字+未知标识符」报尾部多余）
        if _DIGIT_RE.match(ch) or (ch == "." and i + 1 < n and _DIGIT_RE.match(src[i + 1])):
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            tokens.append(_Token("num", src[i:j]))
            i = j
            continue
        # 字符串（单/双引号，无转义；未闭合报错）
        if ch in ("'", '"'):
            j = i + 1
            while j < n and src[j] != ch:
                j += 1
            if j >= n:
                raise SyntaxError(f"表达式字符串未闭合：{src[i:]}")
            tokens.append(_Token("str", src[i + 1 : j]))
            i = j + 1
            continue
        # 标识符（字母/下划线开头，可含 . _ 数字——覆盖 a.b 形式的变量 key）
        if _IDENT_HEAD_RE.match(ch):
            j = i
            while j < n and _IDENT_RE.match(src[j]):
                j += 1
            tokens.append(_Token("ident", src[i:j]))
            i = j
            continue
        # 运算符（长者优先）
        for op in _OPS:
            if src.startswith(op, i):
                tokens.append(_Token("op", op))
                i += len(op)
                break
        else:
            raise SyntaxError(f"表达式非法字符：{ch}（位置 {i}）")
    return tokens


def _js_num(value: str) -> float:
    """TS Number(token)：非法数字串得 NaN（如 '1.2.3'），NaN 沿算术传播。"""
    try:
        return float(value)
    except ValueError:
        return math.nan


def to_num(v: Value) -> float:
    """TS toNum：number→自身；boolean→1/0；可解析数字字符串→数值；其余→0。"""
    if isinstance(v, bool):  # bool 是 int 子类，必须先判
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v != "":
        try:
            return float(v)
        except ValueError:
            return 0.0
    return 0.0


def js_str(v: Value) -> str:
    """TS String()/模板拼接语义：None→''；true→'true'；1.0→'1'；对象→JSON。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _truthy(v: Value) -> bool:
    """TS truthy：true / 非零数值（含 NaN）/ 非空且非 'false'/'0' 的字符串。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0  # NaN != 0 → True，与 JS 一致
    if isinstance(v, str):
        return v != "" and v != "false" and v != "0"
    return False


def _strict_eq(l: Value, r: Value) -> bool:
    """TS ===：类型与值同真。bool 与数值互不等异（JS 1 === true 为 false）。"""
    if isinstance(l, bool) or isinstance(r, bool):
        return isinstance(l, bool) and isinstance(r, bool) and l == r
    if l is None or r is None:
        return l is None and r is None
    if isinstance(l, str) and isinstance(r, str):
        return l == r
    if isinstance(l, (int, float)) and isinstance(r, (int, float)):
        return float(l) == float(r)
    return False


def _loose_eq(l: Value, r: Value) -> bool:
    """TS looseEq（镜像前端实现本身）：null 对 null；双侧数值/布尔按 to_num；否则 String() 比较。"""
    if l is None or r is None:
        return l is None and r is None
    ln = isinstance(l, (bool, int, float))
    rn = isinstance(r, (bool, int, float))
    if ln and rn:
        return to_num(l) == to_num(r)
    return js_str(l) == js_str(r)


def _js_round(x: float, n: float) -> float:
    """镜像 TS BUILTINS.round：Number(Math.round(Number(`${x}e${n}`)) + `e-${n}`)。
    Math.round 为 half-up（towards +∞）：round(2.5)=3、round(-2.5)=-2。"""
    if math.isnan(x) or math.isinf(x):
        return x
    m = int(n)
    try:
        scaled = float(f"{x!r}e{m}")
    except (ValueError, OverflowError):
        return math.nan
    rounded = math.floor(scaled + 0.5)  # JS Math.round = floor(x + 0.5)
    try:
        return float(f"{rounded!r}e-{m}")
    except (ValueError, OverflowError):
        return math.nan


def _builtin_abs(*args: float) -> float:
    return abs(args[0]) if args else math.nan


def _builtin_min(*args: float) -> float:
    return float(min(args)) if args else math.inf  # JS Math.min() = Infinity


def _builtin_max(*args: float) -> float:
    return float(max(args)) if args else -math.inf


def _builtin_floor(*args: float) -> float:
    return float(math.floor(args[0])) if args else math.nan


def _builtin_ceil(*args: float) -> float:
    return float(math.ceil(args[0])) if args else math.nan


def _builtin_round(*args: float) -> float:
    return _js_round(args[0], args[1] if len(args) > 1 else 0)


def _builtin_pow(*args: float) -> float:
    if len(args) < 2:
        return math.nan
    try:
        r = math.pow(args[0], args[1])
    except (ValueError, OverflowError):
        return math.nan
    return r


def _builtin_sqrt(*args: float) -> float:
    if not args or args[0] < 0:
        return math.nan  # JS Math.sqrt(-1) = NaN
    return math.sqrt(args[0])


def _nan_if_not_finite(x: float) -> float:
    """JS Math.sin/cos/tan/asin/acos/atan 对非有限入参一律 NaN（含 ±Infinity）。"""
    return x if math.isfinite(x) else math.nan


def _builtin_sin(*args: float) -> float:
    return _nan_if_not_finite(math.sin(args[0])) if args else math.nan


def _builtin_cos(*args: float) -> float:
    return _nan_if_not_finite(math.cos(args[0])) if args else math.nan


def _builtin_tan(*args: float) -> float:
    return _nan_if_not_finite(math.tan(args[0])) if args else math.nan


def _builtin_asin(*args: float) -> float:
    if not args:
        return math.nan
    x = args[0]
    if not math.isfinite(x):
        return math.nan
    try:
        return _nan_if_not_finite(math.asin(x))  # 域外 |x|>1：JS NaN，Python ValueError
    except ValueError:
        return math.nan


def _builtin_acos(*args: float) -> float:
    if not args:
        return math.nan
    x = args[0]
    if not math.isfinite(x):
        return math.nan
    try:
        return _nan_if_not_finite(math.acos(x))
    except ValueError:
        return math.nan


def _builtin_atan(*args: float) -> float:
    return _nan_if_not_finite(math.atan(args[0])) if args else math.nan


def _builtin_atan2(*args: float) -> float:
    if len(args) < 2 or math.isnan(args[0]) or math.isnan(args[1]):
        return math.nan  # JS atan2(NaN,*) = NaN；±Inf 组合双端一致（均为数学定义值）
    return math.atan2(args[0], args[1])


def _builtin_exp(*args: float) -> float:
    if not args:
        return math.nan
    x = args[0]
    if math.isnan(x):
        return math.nan
    try:
        return math.exp(x)  # exp(+Inf)=Inf / exp(-Inf)=0 双端一致
    except OverflowError:
        return math.inf  # JS Math.exp(1000) = Infinity


def _builtin_log(*args: float) -> float:
    if not args:
        return math.nan
    x = args[0]
    if math.isnan(x):
        return math.nan
    if x == 0:
        return -math.inf  # JS Math.log(0) = -Infinity
    if x < 0:
        return math.nan  # JS Math.log(-1) = NaN
    return math.log(x)


def _builtin_clamp(*args: float) -> float:
    """镜像 TS clamp(x, lo=0, hi=1)：NaN 经比较链原样返回（比较恒 False → 返回 x）。"""
    if not args:
        return math.nan
    x = args[0]
    lo = args[1] if len(args) > 1 else 0.0
    hi = args[2] if len(args) > 2 else 1.0
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _builtin_sign(*args: float) -> float:
    """JS Math.sign：NaN→NaN；正→1；负→-1；±0→0/±0（统一 0.0，弱类型场景无差）。"""
    if not args:
        return math.nan
    x = args[0]
    if math.isnan(x):
        return math.nan
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return 0.0


# 内置函数（标识符命中函数名且后随 '(' 时按调用求值；与前端 BUILTINS 表一一对应）
BUILTINS: dict[str, Callable[..., float]] = {
    "abs": _builtin_abs,
    "min": _builtin_min,
    "max": _builtin_max,
    "floor": _builtin_floor,
    "ceil": _builtin_ceil,
    "round": _builtin_round,
    "pow": _builtin_pow,
    "sqrt": _builtin_sqrt,
    "sin": _builtin_sin,
    "cos": _builtin_cos,
    "tan": _builtin_tan,
    "asin": _builtin_asin,
    "acos": _builtin_acos,
    "atan": _builtin_atan,
    "atan2": _builtin_atan2,
    "exp": _builtin_exp,
    "log": _builtin_log,
    "clamp": _builtin_clamp,
    "sign": _builtin_sign,
}

_CONSTANTS = {"true", "false", "null"}

EvalFn = Callable[[Scope], Value]


def _parse(tokens: list[_Token]) -> EvalFn:
    pos = 0

    def peek() -> _Token | None:
        return tokens[pos] if pos < len(tokens) else None

    def next() -> _Token | None:
        nonlocal pos
        t = tokens[pos] if pos < len(tokens) else None
        pos += 1
        return t

    def eat(op: str) -> None:
        t = next()
        if t is None or t.type != "op" or t.value != op:
            raise SyntaxError(f"期望 '{op}'，得到 '{t.value if t else 'EOF'}'")

    def is_op(op: str) -> bool:
        t = peek()
        return t is not None and t.type == "op" and t.value == op

    def primary() -> EvalFn:
        t = next()
        if t is None:
            raise SyntaxError("表达式意外结束")
        if t.type == "num":
            n = _js_num(t.value)
            return lambda s: n
        if t.type == "str":
            sv: str = t.value
            return lambda s: sv
        if t.type == "ident":
            if t.value == "true":
                return lambda s: True
            if t.value == "false":
                return lambda s: False
            if t.value == "null":
                return lambda s: None
            if is_op("("):
                fn = BUILTINS.get(t.value)
                if fn is None:
                    raise SyntaxError(f"未知函数：{t.value}（可用：{'/'.join(BUILTINS)}）")
                nonlocal_pos_skip()  # 消耗 '('
                args: list[EvalFn] = []
                if not is_op(")"):
                    args.append(ternary())
                    while is_op(","):
                        nonlocal_pos_skip()
                        args.append(ternary())
                eat(")")
                return lambda s, _fn=fn, _args=tuple(args): _fn(*[to_num(a(s)) for a in _args])
            name = t.value

            def ident(s: Scope, _name: str = name) -> Value:
                if _name not in s:
                    raise ReferenceError(f"表达式引用了未知变量：{_name}")
                return s[_name]

            return ident
        if t.type == "op" and t.value == "(":
            inner = ternary()
            eat(")")
            return inner
        raise SyntaxError(f"意外的记号：{t.value}")

    def nonlocal_pos_skip() -> None:
        nonlocal pos
        pos += 1

    def unary() -> EvalFn:
        if is_op("!"):
            nonlocal_pos_skip()
            a = unary()
            return lambda s: not _truthy(a(s))
        if is_op("-"):
            nonlocal_pos_skip()
            a = unary()
            return lambda s: -to_num(a(s))
        if is_op("+"):
            nonlocal_pos_skip()
            a = unary()
            return lambda s: to_num(a(s))
        return primary()

    def binary(next_level: Callable[[], EvalFn], ops: list[str], apply: Callable[[Value, Value, str], Value]) -> EvalFn:
        left = next_level()
        while True:
            t = peek()
            if t is None or t.type != "op" or t.value not in ops:
                break
            op = next().value  # type: ignore[union-attr]
            right = next_level()

            def chained(s: Scope, _l: EvalFn = left, _r: EvalFn = right, _op: str = op) -> Value:
                return apply(_l(s), _r(s), _op)

            left = chained
        return left

    def multiplicative() -> EvalFn:
        def apply(l: Value, r: Value, op: str) -> Value:
            a, b = to_num(l), to_num(r)
            if op == "*":
                return a * b
            if b == 0:
                return 0.0  # 除/模零得 0（与前端一致）
            return a / b if op == "/" else math.fmod(a, b)  # fmod：JS 余号语义（符号随被除数）

        return binary(unary, ["*", "/", "%"], apply)

    def additive() -> EvalFn:
        def apply(l: Value, r: Value, op: str) -> Value:
            # 字符串拼接语义（+ 任一侧为字符串）
            if op == "+" and (isinstance(l, str) or isinstance(r, str)):
                return f"{js_str(l)}{js_str(r)}"
            a, b = to_num(l), to_num(r)
            return a + b if op == "+" else a - b

        return binary(multiplicative, ["+", "-"], apply)

    def relational() -> EvalFn:
        def apply(l: Value, r: Value, op: str) -> Value:
            a, b = to_num(l), to_num(r)
            if op == ">":
                return a > b
            if op == "<":
                return a < b
            if op == ">=":
                return a >= b
            return a <= b

        return binary(additive, [">", "<", ">=", "<="], apply)

    def equality() -> EvalFn:
        def apply(l: Value, r: Value, op: str) -> Value:
            eq = _strict_eq(l, r) or _loose_eq(l, r)
            return (not eq) if op.startswith("!") else eq

        return binary(relational, ["==", "!=", "===", "!=="], apply)

    def and_expr() -> EvalFn:
        return binary(equality, ["&&"], lambda l, r, op: _truthy(r) if _truthy(l) else False)

    def or_expr() -> EvalFn:
        return binary(and_expr, ["||"], lambda l, r, op: True if _truthy(l) else _truthy(r))

    def ternary() -> EvalFn:
        cond = or_expr()
        if is_op("?"):
            nonlocal_pos_skip()
            then = ternary()
            eat(":")
            els = ternary()
            return lambda s: then(s) if _truthy(cond(s)) else els(s)
        return cond

    result = ternary()
    if pos < len(tokens):
        raise SyntaxError(f"表达式尾部存在多余内容：'{tokens[pos].value}'")
    return result


# 编译缓存：同一表达式串只解析一次（与前端一致；表达式来自 doc，规模有限）
_cache: dict[str, EvalFn] = {}


def eval_expr(src: str, scope: Scope) -> Value:
    """求值入口（签名冻结，契约 §6.1）；语法/引用错误抛 SyntaxError/ReferenceError，调用方决定回落策略。"""
    fn = _cache.get(src)
    if fn is None:
        fn = _parse(_tokenize(src))
        _cache[src] = fn
    return fn(scope)


def expr_idents(src: str) -> list[str]:
    """提取表达式引用的标识符（排除内置函数与常量，保序去重）；供 hub 构建虚拟变量依赖图。"""
    idents: list[str] = []
    for t in _tokenize(src):
        if (
            t.type == "ident"
            and t.value not in BUILTINS
            and t.value not in _CONSTANTS
            and t.value not in idents
        ):
            idents.append(t.value)
    return idents
