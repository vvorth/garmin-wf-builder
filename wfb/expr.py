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

import re
from dataclasses import dataclass, field

from .catalog import Type

# --------------------------------------------------------------------------
# tokens


class ExprError(Exception):
    """A syntax or type error, with an offset into the expression text."""

    def __init__(self, message: str, offset: int = 0, notes: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.notes = notes or []


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


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node
    offset: int = 0


@dataclass
class Conditional(Node):
    cond: Node
    then: Node
    otherwise: Node
    offset: int = 0


@dataclass
class Call(Node):
    name: str
    args: list[Node]
    offset: int = 0


# --------------------------------------------------------------------------
# parser

#: (precedence, right-associative).  Higher binds tighter.
_BINARY: dict[str, int] = {
    "or": 1, "||": 1,
    "and": 2, "&&": 2,
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}

#: name -> (arity or None for variadic-min, description)
FUNCTIONS: dict[str, tuple[tuple[int, ...], str]] = {
    "min": ((2,), "smaller of two numbers"),
    "max": ((2,), "larger of two numbers"),
    "clamp": ((3,), "clamp(value, lo, hi)"),
    "round": ((1,), "round to the nearest whole number"),
    "floor": ((1,), "round down"),
    "abs": ((1,), "absolute value"),
    "percent": ((2,), "percent(value, goal) -> 0..100"),
}


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
        arities, description = FUNCTIONS[name.text]
        if len(args) not in arities:
            want = " or ".join(str(a) for a in arities)
            raise ExprError(
                f"{name.text}() takes {want} argument(s), got {len(args)}",
                name.offset,
                [description],
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
    kind: str = "source"  # source | palette | config


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
            from . import catalog

            notes = []
            near = catalog.suggest(node.path)
            if near:
                notes.append("did you mean: " + ", ".join(near) + "?")
            else:
                notes.append(
                    "known namespaces: " + ", ".join(sorted(catalog.namespaces())) + ", palette, config"
                )
            raise ExprError(f"unknown data source {node.path!r}", node.offset, notes)
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
        if node.name in ("round", "floor"):
            return Value(Type.NUMBER, nullable)
        if node.name == "percent":
            return Value(Type.FLOAT, nullable)
        if any(a.type is Type.FLOAT for a in args):
            return Value(Type.FLOAT, nullable)
        return Value(Type.NUMBER, nullable)

    raise ExprError(f"cannot type {type(node).__name__}")


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
                return Literal(-operand.value, operand.type, node.offset)
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
        if all(isinstance(a, Literal) and a.value is not None for a in args):
            folded = _apply_call(node.name, [a.value for a in args])  # type: ignore[union-attr]
            if folded is not None:
                return Literal(*folded, node.offset)
        return Call(node.name, args, node.offset)
    return node


def _apply(op: str, a: object, b: object) -> tuple[object, Type] | None:
    try:
        if op == "+":
            result = a + b  # type: ignore[operator]
        elif op == "-":
            result = a - b  # type: ignore[operator]
        elif op == "*":
            result = a * b  # type: ignore[operator]
        elif op == "/":
            if b == 0:
                return None
            result = a / b  # type: ignore[operator]
            return (result, Type.FLOAT)
        elif op == "%":
            if b == 0:
                return None
            result = a % b  # type: ignore[operator]
        elif op in ("<", "<=", ">", ">=", "==", "!="):
            import operator

            fn = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
                  ">=": operator.ge, "==": operator.eq, "!=": operator.ne}[op]
            return (bool(fn(a, b)), Type.BOOLEAN)
        elif op == "and":
            return (bool(a) and bool(b), Type.BOOLEAN)
        elif op == "or":
            return (bool(a) or bool(b), Type.BOOLEAN)
        else:
            return None
    except TypeError:
        return None
    return (result, Type.FLOAT if isinstance(result, float) else Type.NUMBER)


def _apply_call(name: str, args: list) -> tuple[object, Type] | None:
    import math

    try:
        if name == "min":
            value = min(args)
        elif name == "max":
            value = max(args)
        elif name == "clamp":
            value = max(args[1], min(args[0], args[2]))
        elif name == "round":
            return (int(round(args[0])), Type.NUMBER)
        elif name == "floor":
            return (int(math.floor(args[0])), Type.NUMBER)
        elif name == "abs":
            value = abs(args[0])
        elif name == "percent":
            if args[1] == 0:
                return None
            return (100.0 * args[0] / args[1], Type.FLOAT)
        else:
            return None
    except (TypeError, ValueError):
        return None
    return (value, Type.FLOAT if isinstance(value, float) else Type.NUMBER)


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
        return f"({emit(node.left, scope)} {op} {emit(node.right, scope)})"
    if isinstance(node, Conditional):
        return (
            f"({emit(node.cond, scope)} ? {emit(node.then, scope)} "
            f": {emit(node.otherwise, scope)})"
        )
    if isinstance(node, Call):
        args = [emit(a, scope) for a in node.args]
        return _emit_call(node.name, args)
    raise ExprError(f"cannot emit {type(node).__name__}")


def _emit_literal(node: Literal) -> str:
    if node.value is None:
        return "null"
    if node.type is Type.BOOLEAN:
        return "true" if node.value else "false"
    if node.type is Type.STRING:
        escaped = str(node.value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if node.type is Type.COLOR:
        return f"0x{int(node.value):06X}"
    if node.type is Type.FLOAT:
        return f"{float(node.value)}f"
    return str(int(node.value))


def _emit_call(name: str, args: list[str]) -> str:
    """Emit a call.

    ``min``/``max``/``clamp``/``abs`` go through the support barrel rather than
    being expanded inline as ternaries.  Inlining would evaluate the argument
    expression two or three times -- correct, since expressions are pure, but it
    triples the generated text for no gain and makes the output hard to read,
    which ADR 0003 does not allow.
    """
    if name in ("min", "max", "clamp", "abs", "percent"):
        return f"WfbMath.{name}({', '.join(args)})"
    if name == "round":
        return f"Math.round({args[0]}).toNumber()"
    if name == "floor":
        return f"Math.floor({args[0]}).toNumber()"
    raise ExprError(f"no emitter for {name}()")


#: Toybox modules the emitted code needs, keyed by expression function name.
CALL_MODULES = {"round": "Toybox.Math", "floor": "Toybox.Math"}
#: Expression functions that compile to a support-barrel call.
CALL_BARREL = frozenset({"min", "max", "clamp", "abs", "percent"})


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


def walk(node: Node):
    yield node
    if isinstance(node, Unary):
        yield from walk(node.operand)
    elif isinstance(node, Binary):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, Conditional):
        yield from walk(node.cond)
        yield from walk(node.then)
        yield from walk(node.otherwise)
    elif isinstance(node, Call):
        for arg in node.args:
            yield from walk(arg)


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
        return -inner if node.op == "-" else (not inner)
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
