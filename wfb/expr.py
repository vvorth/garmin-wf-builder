"""The expression language: parse, type-check, and compile to Monkey C.

ADR 0005: expressions are compiled, not interpreted.  ``heart_rate.current >
user.hr_zone4 ? palette.hot : palette.text`` becomes a Monkey C ternary over
locals the generator has already fetched; **no evaluator ships to the device**.

The language is deliberately small -- an *expression* language, not a
programming language.  Literals, references, arithmetic, comparison, boolean
operators, a ternary, and a fixed function set.  No loops, no user functions, no
assignment, no state.  Anything beyond this is a signal to use the escape hatch
(ADR 0007) rather than to grow the language, because growing it is how these
formats become unmaintainable.
"""

from __future__ import annotations

import difflib
import math
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import catalog
from .catalog import Type
from .diagnostics import did_you_mean

# --------------------------------------------------------------------------
# tokens


class ExprError(Exception):
    """A syntax or type error, with an offset into the expression text."""

    def __init__(self, message: str, offset: int = 0, notes: list[str] | None = None,
                 code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.notes = notes or []
        #: A diagnostic code more specific than the generic ``"expression"``
        #: :meth:`wfb.ir.Builder.expression` falls back to.  Only
        #: ``source-renamed`` uses this today -- a moved catalogue path wants
        #: its own code, so an author (or a lint suppression)
        #: can tell "you typed something unknown" apart from "the platform
        #: moved this on you".
        self.code = code


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+\.\d+|\.\d+|\d+)
  | (?P<string>'[^']*'|"[^"]*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<op><=|>=|==|!=|&&|\|\||[-+*/%<>?:(),!])
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "true", "false", "null"}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ExprError(f"unexpected character {text[pos]!r}", pos)
        pos = m.end()
        kind = m.lastgroup
        assert kind is not None, "every _TOKEN_RE alternative is a named group"
        if kind == "ws":
            continue
        value = m.group()
        if kind == "name" and value in _KEYWORDS:
            kind = "keyword"
        tokens.append(Token(kind, value, m.start()))
    tokens.append(Token("end", "", len(text)))
    return tokens


# --------------------------------------------------------------------------
# AST


class Node:
    offset: int = 0

    def children(self) -> tuple["Node", ...]:
        return ()


@dataclass
class Literal(Node):
    value: object
    type: Type
    offset: int = 0


@dataclass
class Ref(Node):
    path: str
    offset: int = 0


@dataclass
class Unary(Node):
    op: str
    operand: Node
    offset: int = 0

    def children(self) -> tuple[Node, ...]:
        return (self.operand,)


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node
    offset: int = 0

    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass
class Conditional(Node):
    cond: Node
    then: Node
    otherwise: Node
    offset: int = 0

    def children(self) -> tuple[Node, ...]:
        return (self.cond, self.then, self.otherwise)


@dataclass
class Call(Node):
    name: str
    args: list[Node]
    offset: int = 0

    def children(self) -> tuple[Node, ...]:
        return tuple(self.args)


# --------------------------------------------------------------------------
# parser

#: Binary operator precedence; higher binds tighter.  All left-associative.
_BINARY: dict[str, int] = {
    "or": 1, "||": 1,
    "and": 2, "&&": 2,
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}

@dataclass(frozen=True)
class Function:
    """One function of the language: its type rule and both implementations.

    `host` (constant folding, and `evaluate` for the preview) and `emit`
    (the Monkey C call) sit in one row so they can be checked against each
    other; `WfbMath.mc` holds the barrel half of `emit`.
    """

    arity: int
    description: str
    #: The result type, or ``None`` when it follows the arguments: Float if
    #: any argument is (for folding: if the folded value is a float).
    result: Type | None
    #: Host evaluation over argument values; ``None`` means "no value".
    host: Callable[[list[Any]], object]
    #: Toybox module the emitted call needs, or ``None`` for a barrel call
    #: (`WfbMath.<name>`, runtime-lib/WfbMath.mc).
    module: str | None = None
    #: Whether constant folding may bake `host`'s answer for these argument
    #: values into generated code; ``None`` means always. `evaluate` (the
    #: preview) ignores it: a best guess is fine for a picture, not for code.
    foldable: Callable[[list[Any]], bool] | None = None


def _round(args: list[Any]) -> int:
    """`Math.round`: "Decimal values >= .5 will be rounded up"
    ($CIQ_SDK/doc/Toybox/Math.html) -- not Python's half-to-even `round`.
    Computed from the fractional part, which is exact for a double, rather
    than as `floor(x + 0.5)`, which rounds 0.49999999999999994 up."""
    x = args[0]
    whole = math.floor(x)
    return int(whole) + (1 if x - whole >= 0.5 else 0)


def _round_foldable(args: list[Any]) -> bool:
    """A negative exact half is the one input the SDK's "rounded up" leaves
    open (-2.5 is -2 rounded up, -3 rounded away from zero), and no
    simulator runs here to observe it (docs/lore/monkeyc.md), so the call is
    left for the device to compute."""
    x = args[0]
    return not (x < 0 and x - math.floor(x) == 0.5)


def _clamp(args: list[Any]) -> object:
    """`WfbMath.clamp`, in its order: below `lo` first, then above `hi` --
    which differs from `max(lo, min(v, hi))` only when `lo > hi`."""
    value, lo, hi = args
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _percent(args: list[Any]) -> object:
    """`WfbMath.percent`: 0.0 for a goal <= 0 (an unset goal is a real
    reading, not an absent one), otherwise clamped to 0..100."""
    value, goal = args
    if goal <= 0:
        return 0.0
    return _clamp([100.0 * value / goal, 0.0, 100.0])


def _mod(a: object, b: object) -> object:
    """Monkey C's `%`: the remainder takes the dividend's sign (`-7 % 3` is
    -1; `monkeyc`'s own constant folder, docs/research/probes/math-parity/),
    where Python's floor modulo gives 2. Integers only -- `check` refuses a
    Float operand, as `monkeyc -l 3` does."""
    if not (isinstance(a, int) and isinstance(b, int)) or isinstance(a, bool) or isinstance(b, bool):
        raise TypeError("% needs integers")
    remainder = abs(a) % abs(b)
    return -remainder if a < 0 else remainder


FUNCTIONS: dict[str, Function] = {
    "min": Function(2, "smaller of two numbers", None, lambda a: min(a)),
    "max": Function(2, "larger of two numbers", None, lambda a: max(a)),
    "clamp": Function(3, "clamp(value, lo, hi)", None, _clamp),
    "round": Function(1, "round to the nearest whole number (.5 rounds up)", Type.NUMBER,
                      _round, module="Toybox.Math", foldable=_round_foldable),
    "floor": Function(1, "round down", Type.NUMBER,
                      lambda a: int(math.floor(a[0])), module="Toybox.Math"),
    "abs": Function(1, "absolute value", None, lambda a: abs(a[0])),
    "percent": Function(2, "percent(value, goal) -> 0..100", Type.FLOAT, _percent),
}

#: Toybox modules the emitted code needs, keyed by expression function name.
CALL_MODULES = {name: f.module for name, f in FUNCTIONS.items() if f.module is not None}
#: Expression functions that compile to a support-barrel call.
CALL_BARREL = frozenset(name for name, f in FUNCTIONS.items() if f.module is None)


class Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, text: str) -> Token:
        if self.current.text != text:
            got = self.current.text or "end of expression"
            raise ExprError(f"expected {text!r} but found {got!r}", self.current.offset)
        return self.advance()

    def parse(self) -> Node:
        node = self.parse_ternary()
        if self.current.kind != "end":
            raise ExprError(f"unexpected {self.current.text!r}", self.current.offset)
        return node

    def parse_ternary(self) -> Node:
        cond = self.parse_binary(0)
        if self.current.text == "?":
            offset = self.advance().offset
            then = self.parse_ternary()
            self.expect(":")
            otherwise = self.parse_ternary()
            return Conditional(cond, then, otherwise, offset)
        return cond

    def parse_binary(self, min_prec: int) -> Node:
        left = self.parse_unary()
        while True:
            op = self.current.text
            prec = _BINARY.get(op)
            if prec is None or prec < min_prec:
                return left
            offset = self.advance().offset
            right = self.parse_binary(prec + 1)
            left = Binary(_canonical_op(op), left, right, offset)

    def parse_unary(self) -> Node:
        token = self.current
        if token.text in ("-", "not", "!"):
            self.advance()
            return Unary("not" if token.text in ("not", "!") else "-", self.parse_unary(), token.offset)
        return self.parse_primary()

    def parse_primary(self) -> Node:
        token = self.advance()
        if token.text == "(":
            node = self.parse_ternary()
            self.expect(")")
            return node
        if token.kind == "number":
            if "." in token.text:
                return Literal(float(token.text), Type.FLOAT, token.offset)
            return Literal(int(token.text), Type.NUMBER, token.offset)
        if token.kind == "string":
            return Literal(token.text[1:-1], Type.STRING, token.offset)
        if token.kind == "keyword":
            if token.text in ("true", "false"):
                return Literal(token.text == "true", Type.BOOLEAN, token.offset)
            if token.text == "null":
                return Literal(None, Type.NUMBER, token.offset)
            raise ExprError(f"{token.text!r} cannot start an expression", token.offset)
        if token.kind == "name":
            if self.current.text == "(":
                return self.parse_call(token)
            return Ref(token.text, token.offset)
        got = token.text or "end of expression"
        raise ExprError(f"expected a value but found {got!r}", token.offset)

    def parse_call(self, name: Token) -> Node:
        if name.text not in FUNCTIONS:
            known = ", ".join(sorted(FUNCTIONS))
            raise ExprError(
                f"unknown function {name.text!r}",
                name.offset,
                [f"the expression language has exactly these functions: {known}"],
            )
        self.expect("(")
        args: list[Node] = []
        if self.current.text != ")":
            args.append(self.parse_ternary())
            while self.current.text == ",":
                self.advance()
                args.append(self.parse_ternary())
        self.expect(")")
        function = FUNCTIONS[name.text]
        if len(args) != function.arity:
            raise ExprError(
                f"{name.text}() takes {function.arity} argument(s), got {len(args)}",
                name.offset,
                [function.description],
            )
        return Call(name.text, args, name.offset)


def _canonical_op(op: str) -> str:
    return {"&&": "and", "||": "or"}.get(op, op)


def parse(text: str) -> Node:
    return Parser(text).parse()


# --------------------------------------------------------------------------
# types and scope


@dataclass(frozen=True)
class Value:
    """The static type of an expression, plus whether it may be absent."""

    type: Type
    nullable: bool = False

    def __str__(self) -> str:
        return f"{self.type.value}{'?' if self.nullable else ''}"


@dataclass
class Binding:
    """A name the expression may refer to, and how to read it in Monkey C."""

    value: Value
    #: The Monkey C expression producing it.  For a nullable binding this is the
    #: *guarded local* the generator has already narrowed, never the raw read.
    code: str
    #: Set when the value is known at build time, enabling constant folding.
    constant: object | None = None


@dataclass
class Scope:
    """The names in scope, and the sources an expression turned out to use."""

    bindings: dict[str, Binding] = field(default_factory=dict)
    used: set[str] = field(default_factory=set)

    def define(self, name: str, binding: Binding) -> None:
        self.bindings[name] = binding

    def lookup(self, name: str) -> Binding | None:
        binding = self.bindings.get(name)
        if binding is not None:
            self.used.add(name)
        return binding


#: The index of the copy being drawn, 0-based -- bound only while a `type:
#: pattern`'s colours, its parts' `visible:` and a text part's `value:` are
#: compiled (`wfb.kinds.pattern.PatternKind.build`), to the generated loop's own
#: `i`. Every other expression sees it unbound -- including the *element's
#: own* `visible:`, compiled before the pattern builder binds `copy` -- and
#: `check` gives that its own error rather than "unknown data source".
COPY = "copy"


def reads_copy(node: Node | None) -> bool:
    """Does this (folded) expression read :data:`COPY` -- so its value can
    differ from one copy of a pattern to the next?"""
    return node is not None and any(
        isinstance(n, Ref) and n.path == COPY for n in walk(node))


_NUMERIC_OPS = {"+", "-", "*", "/", "%"}
_COMPARISON_OPS = {"<", "<=", ">", ">="}
_EQUALITY_OPS = {"==", "!="}
_BOOLEAN_OPS = {"and", "or"}


def check(node: Node, scope: Scope) -> Value:
    """Infer the type of ``node``, raising :class:`ExprError` on a mismatch."""
    if isinstance(node, Literal):
        return Value(node.type)

    if isinstance(node, Ref):
        binding = scope.lookup(node.path)
        if binding is None:
            raise _unknown_ref(node, scope)
        return binding.value

    if isinstance(node, Unary):
        inner = check(node.operand, scope)
        if node.op == "-":
            _require_numeric(inner, "-", node.offset)
            return Value(inner.type, inner.nullable)
        _require(inner, Type.BOOLEAN, "not", node.offset)
        return Value(Type.BOOLEAN, inner.nullable)

    if isinstance(node, Binary):
        left, right = check(node.left, scope), check(node.right, scope)
        nullable = left.nullable or right.nullable
        if node.op in _NUMERIC_OPS:
            _require_numeric(left, node.op, node.offset)
            _require_numeric(right, node.op, node.offset)
            if node.op == "%" and Type.FLOAT in (left.type, right.type):
                raise ExprError(
                    f"% needs two whole numbers, got {left} % {right}", node.offset,
                    ["Monkey C has no remainder of a Float ('monkeyc' refuses it); "
                     "wrap the Float side in floor() or round() first"],
                )
            if node.op == "/" or Type.FLOAT in (left.type, right.type):
                return Value(Type.FLOAT, nullable)
            return Value(Type.NUMBER, nullable)
        if node.op in _COMPARISON_OPS:
            _require_numeric(left, node.op, node.offset)
            _require_numeric(right, node.op, node.offset)
            return Value(Type.BOOLEAN, nullable)
        if node.op in _EQUALITY_OPS:
            if left.type != right.type and not (left.type.is_numeric() and right.type.is_numeric()):
                raise ExprError(
                    f"cannot compare {left} with {right}", node.offset,
                    ["the two sides of == and != must have the same type"],
                )
            return Value(Type.BOOLEAN, nullable)
        if node.op in _BOOLEAN_OPS:
            _require(left, Type.BOOLEAN, node.op, node.offset)
            _require(right, Type.BOOLEAN, node.op, node.offset)
            return Value(Type.BOOLEAN, nullable)
        raise ExprError(f"unknown operator {node.op!r}", node.offset)

    if isinstance(node, Conditional):
        cond = check(node.cond, scope)
        _require(cond, Type.BOOLEAN, "?:", node.offset)
        then, otherwise = check(node.then, scope), check(node.otherwise, scope)
        if then.type != otherwise.type:
            if then.type.is_numeric() and otherwise.type.is_numeric():
                merged = Type.FLOAT if Type.FLOAT in (then.type, otherwise.type) else Type.NUMBER
            else:
                raise ExprError(
                    f"the two branches of ?: have different types: {then} and {otherwise}",
                    node.offset,
                )
        else:
            merged = then.type
        return Value(merged, cond.nullable or then.nullable or otherwise.nullable)

    if isinstance(node, Call):
        args = [check(a, scope) for a in node.args]
        nullable = any(a.nullable for a in args)
        for arg in args:
            _require_numeric(arg, f"{node.name}()", node.offset)
        result = FUNCTIONS[node.name].result
        if result is None:
            result = Type.FLOAT if any(a.type is Type.FLOAT for a in args) else Type.NUMBER
        return Value(result, nullable)

    raise ExprError(f"cannot type {type(node).__name__}")


def _unknown_ref(node: Ref, scope: Scope) -> ExprError:
    """The error for a reference nothing in ``scope`` binds."""
    if node.path == COPY:
        return ExprError(
            f"{COPY!r} is only defined in a 'type: pattern' element's colours, "
            "its parts' 'visible:' and a text part's 'value:'",
            node.offset,
            [f"{COPY!r} is the index of the copy being drawn, 0-based -- "
             "nothing but a pattern has copies",
             "to hide some copies, put 'visible:' on the parts, or use 'skip:'"],
        )
    renamed = catalog.renamed_to(node.path)
    if renamed is not None:
        return ExprError(
            f"{node.path!r} has been renamed to {renamed!r}",
            node.offset,
            ["complications now have their own namespace -- "
             "'complication.<type>' is always read through "
             "Toybox.Complications, and every other catalogue path is "
             "always a direct API read",
             "the value is unchanged; only the path moves",
             "run `wfb sources` for the current catalogue"],
            code="source-renamed",
        )
    # Prefer suggestions from the same namespace: a mistyped palette entry
    # wants the palette listed, not the data-source catalogue.
    namespace = node.path.split(".", 1)[0] if "." in node.path else ""
    siblings = sorted(name for name in scope.bindings if name.startswith(f"{namespace}."))
    near = difflib.get_close_matches(node.path, siblings, n=3, cutoff=0.4) or (
        [] if siblings else catalog.CATALOG.suggest(node.path))
    if near:
        note = did_you_mean(near)[0]
    elif siblings:
        note = f"{namespace} has: " + ", ".join(siblings)
    else:
        note = "known namespaces: " + ", ".join(sorted(catalog.namespaces())) + ", palette"
    return ExprError(f"unknown data source {node.path!r}", node.offset, [note])


def _require(value: Value, want: Type, op: str, offset: int) -> None:
    if value.type is not want:
        raise ExprError(f"{op} needs a {want.value}, got {value}", offset)


def _require_numeric(value: Value, op: str, offset: int) -> None:
    if not value.type.is_numeric():
        hint = (
            ["colours are not numbers here -- arithmetic on a palette entry is almost always a mistake"]
            if value.type is Type.COLOR
            else []
        )
        raise ExprError(f"{op} needs a number, got {value}", offset, hint)


# --------------------------------------------------------------------------
# constant folding and emission

_MONKEYC_BINARY = {
    "and": "&&",
    "or": "||",
}


def fold(node: Node, scope: Scope, *, fold_colors: bool = True) -> Node:
    """Replace any subtree whose value is known at build time with a literal.

    ``fold_colors=False`` leaves palette references as references so the emitted
    code says ``Palette.ACCENT`` rather than ``0xFF5500``.  A colour is already a
    Monkey C constant, so nothing is gained by inlining it here and the name --
    the whole point of having a palette -- would be lost.  Colours are still
    folded for the *linter*, which needs the value rather than the name.
    """
    if isinstance(node, Literal):
        return node
    if isinstance(node, Ref):
        binding = scope.bindings.get(node.path)
        if binding is None or binding.constant is None:
            return node
        if not fold_colors and binding.value.type is Type.COLOR:
            return node
        return Literal(binding.constant, binding.value.type, node.offset)
    if isinstance(node, Unary):
        operand = fold(node.operand, scope, fold_colors=fold_colors)
        if isinstance(operand, Literal) and operand.value is not None:
            if node.op == "-":
                return Literal(_negate(operand.value), operand.type, node.offset)
            return Literal(not operand.value, Type.BOOLEAN, node.offset)
        return Unary(node.op, operand, node.offset)
    if isinstance(node, Binary):
        left = fold(node.left, scope, fold_colors=fold_colors)
        right = fold(node.right, scope, fold_colors=fold_colors)
        if (
            isinstance(left, Literal)
            and isinstance(right, Literal)
            and left.value is not None
            and right.value is not None
            and left.type is not Type.COLOR
            and right.type is not Type.COLOR
        ):
            folded = _apply(node.op, left.value, right.value)
            if folded is not None:
                return Literal(*folded, node.offset)
        return Binary(node.op, left, right, node.offset)
    if isinstance(node, Conditional):
        cond = fold(node.cond, scope, fold_colors=fold_colors)
        then = fold(node.then, scope, fold_colors=fold_colors)
        otherwise = fold(node.otherwise, scope, fold_colors=fold_colors)
        if isinstance(cond, Literal) and isinstance(cond.value, bool):
            return then if cond.value else otherwise
        return Conditional(cond, then, otherwise, node.offset)
    if isinstance(node, Call):
        args = [fold(a, scope, fold_colors=fold_colors) for a in node.args]
        literals = [a for a in args if isinstance(a, Literal) and a.value is not None]
        if len(literals) == len(args):
            values = [a.value for a in literals]
            function = FUNCTIONS.get(node.name)
            if function is None or function.foldable is None or function.foldable(values):
                folded = _apply_call(node.name, values)
                if folded is not None:
                    return Literal(*folded, node.offset)
        return Call(node.name, args, node.offset)
    return node


def as_number(value: object) -> int | float:
    """``value`` as the number a numeric-typed literal or reading holds;
    `TypeError` for anything else, as Python's own arithmetic would raise."""
    if isinstance(value, (int, float)):
        return value
    raise TypeError(f"expected a number, got {value!r}")


def _negate(value: object) -> int | float:
    return -as_number(value)


#: Host implementations of the foldable binary operators.  Operands are
#: `Any`: a pair the operator does not take raises `TypeError`, which
#: `_apply` turns into "no value".
_HOST_BINARY: dict[str, Callable[[Any, Any], object]] = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "/": operator.truediv, "%": _mod,
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
    "and": lambda a, b: bool(a) and bool(b),
    "or": lambda a, b: bool(a) or bool(b),
}


def _numeric_type(value: object) -> Type:
    return Type.FLOAT if isinstance(value, float) else Type.NUMBER


def _apply(op: str, a: object, b: object) -> tuple[object, Type] | None:
    """``a op b`` on the host, typed; ``None`` when it has no value (an
    unknown operator, a zero divisor, mismatched operands)."""
    fn = _HOST_BINARY.get(op)
    if fn is None or (op in ("/", "%") and b == 0):
        return None
    try:
        result = fn(a, b)
    except TypeError:
        return None
    if op in _COMPARISON_OPS or op in _EQUALITY_OPS or op in _BOOLEAN_OPS:
        return (bool(result), Type.BOOLEAN)
    return (result, Type.FLOAT if op == "/" else _numeric_type(result))


def _apply_call(name: str, args: list[Any]) -> tuple[object, Type] | None:
    function = FUNCTIONS.get(name)
    if function is None:
        return None
    try:
        value = function.host(args)
    except (TypeError, ValueError):
        return None
    if value is None:
        return None
    return (value, function.result or _numeric_type(value))


def emit(node: Node, scope: Scope) -> str:
    """Compile to a Monkey C expression."""
    if isinstance(node, Literal):
        return _emit_literal(node)
    if isinstance(node, Ref):
        binding = scope.bindings[node.path]
        return binding.code
    if isinstance(node, Unary):
        inner = emit(node.operand, scope)
        return f"(-{inner})" if node.op == "-" else f"(!{inner})"
    if isinstance(node, Binary):
        op = _MONKEYC_BINARY.get(node.op, node.op)
        left_code = emit(node.left, scope)
        right_code = emit(node.right, scope)
        if node.op == "/" and not _has_float_operand(node.left, node.right, scope):
            # `check()` always types `/` as Float (see `check` above), but Monkey
            # C's own `Number / Number` truncates -- unlike `+`/`-`/`*`, where an
            # all-Number result matches what `check` assigns. Left un-coerced,
            # the preview renderer (host-side Python `/`) and the device
            # silently disagree, breaking the invariant ADR 0005 exists to
            # guarantee. Only needed when *neither* operand is already a Float:
            # Monkey C promotes a Number/Float mix to Float on its own.
            left_code = _as_float(node.left, left_code)
        return f"({left_code} {op} {right_code})"
    if isinstance(node, Conditional):
        return (
            f"({emit(node.cond, scope)} ? {emit(node.then, scope)} "
            f": {emit(node.otherwise, scope)})"
        )
    if isinstance(node, Call):
        args = [emit(a, scope) for a in node.args]
        return _emit_call(node.name, args)
    raise ExprError(f"cannot emit {type(node).__name__}")


def _has_float_operand(left: Node, right: Node, scope: Scope) -> bool:
    """Does either side of a `/` already type as Float?

    Re-runs `check` on the (already-folded) operands rather than threading a
    type through emission -- `emit` is only ever called on a tree `check` has
    already validated, so this recomputation cannot itself raise; it exists
    purely to answer "does Monkey C already do float division here", which
    `check`'s own Value isn't otherwise available at this point in `emit`.
    """
    return check(left, scope).type is Type.FLOAT or check(right, scope).type is Type.FLOAT


def _as_float(node: Node, code: str) -> str:
    """Force integer-typed Monkey C code to Float division by coercing it.

    A bare numeric literal needs parentheses first -- ``5.toFloat()`` parses as
    a malformed decimal (the ``.`` reads as starting a fraction), not a method
    call, so ``5`` becomes ``(5).toFloat()``. Every other operand `emit`
    produces is already an identifier, a parenthesized subexpression, or a
    function call, all of which take `.toFloat()` directly.
    """
    if isinstance(node, Literal):
        return f"({code}).toFloat()"
    return f"{code}.toFloat()"


def _emit_literal(node: Literal) -> str:
    if node.value is None:
        return "null"
    if node.type is Type.BOOLEAN:
        return "true" if node.value else "false"
    if node.type is Type.STRING:
        escaped = str(node.value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if node.type is Type.COLOR:
        return f"0x{int(as_number(node.value)):06X}"
    if node.type is Type.FLOAT:
        return f"{float(as_number(node.value))}f"
    return str(int(as_number(node.value)))


def _emit_call(name: str, args: list[str]) -> str:
    """Emit a call.

    A barrel function (``min``/``max``/``clamp``/``abs``/``percent``) is a
    `WfbMath` call rather than an inline ternary, which would evaluate an
    argument two or three times -- correct, since expressions are pure, but
    triple the generated text, which ADR 0003 does not allow.  ``round``/
    ``floor`` are `Toybox.Math` calls brought back to a Number.
    """
    if name in CALL_BARREL:
        return f"WfbMath.{name}({', '.join(args)})"
    return f"Math.{name}({args[0]}).toNumber()"


def compile_expression(text: str, scope: Scope, *,
                      fold_colors: bool = False) -> tuple[str, Value, Node]:
    """Parse, type-check, fold and emit in one step.

    ``fold_colors`` defaults to ``False`` to match what the compiler does: a
    palette reference is emitted as ``Palette.NAME``, not as its hex value.
    """
    node = parse(text)
    value = check(node, scope)
    folded = fold(node, scope, fold_colors=fold_colors)
    return emit(folded, scope), value, folded


def walk(node: Node) -> Iterator[Node]:
    """``node`` and every node under it, pre-order."""
    yield node
    for child in node.children():
        yield from walk(child)


# --------------------------------------------------------------------------
# host-side evaluation, for the preview renderer


def evaluate(node: Node, values: dict[str, object]) -> object | None:
    """Evaluate an expression on the host against sample readings.

    This exists only for the preview renderer.  ADR 0005's "no runtime
    evaluator" is a statement about the *device* -- the whole point of compiling
    expressions is that nothing interprets them on a watch.  Evaluating the same
    tree here is what lets the preview and the device agree.

    Returns ``None`` when any input is absent, mirroring the null guards the
    generated code emits.
    """
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Ref):
        return values.get(node.path)
    if isinstance(node, Unary):
        inner = evaluate(node.operand, values)
        if inner is None:
            return None
        return _negate(inner) if node.op == "-" else (not inner)
    if isinstance(node, Binary):
        left, right = evaluate(node.left, values), evaluate(node.right, values)
        if node.op == "and":
            return bool(left) and bool(right) if None not in (left, right) else None
        if node.op == "or":
            return bool(left) or bool(right) if None not in (left, right) else None
        if left is None or right is None:
            return None
        folded = _apply(node.op, left, right)
        return folded[0] if folded else None
    if isinstance(node, Conditional):
        cond = evaluate(node.cond, values)
        if cond is None:
            return None
        return evaluate(node.then if cond else node.otherwise, values)
    if isinstance(node, Call):
        args = [evaluate(a, values) for a in node.args]
        if any(a is None for a in args):
            return None
        folded = _apply_call(node.name, args)
        return folded[0] if folded else None
    return None
