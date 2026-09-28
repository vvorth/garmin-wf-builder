"""``wfb migrate``: rewrite a format 1 design as format 2, once.

Format 2 (``docs/guide/format-2-migration.md``) renames and regroups format
1's keys; it adds no meaning. This module is the one place that knows both
spellings. It works on ruamel's round-trip tree, so comments, key order and
quoting survive, and it is an ordered list of small rules, one per row group
of the migration table:

* top level: ``targets:`` into ``build:``; ``fonts:``/``palette:``/``hands:``
  into ``resources:``; ``color_scheme:`` into ``theme: {schemes:}``;
  ``antialias:``/``min_1px:``/``aod: {default:}`` into ``defaults:``;
* ``config:``: colour references, ``style`` entries' ``colors:`` ->
  ``scheme:``, ``data:`` -> ``slots:`` with bare complication names;
* every element list into the mapping form, and a ``static: true`` element
  into its scope's ``static:`` block;
* every element's own keys, then each kind's.

Expression references (``palette.x``, ``config.colors.x``,
``config.accent_color``, ``config.data_color``) are rewritten token by token
through :func:`wfb.expr.tokenize`, never with a regular expression, so a
string literal or a longer identifier is never touched.

A v2 file (``format: 2``) passes through unchanged. A file the migrator
cannot rewrite faithfully is refused, with the line, the reason and what to
do by hand, and nothing is written. The migrator is not a validator: an
invalid v1 file gives a v2 file that the compiler rejects.

A *fragment* -- a YAML document with no ``format:`` key, which is how most
test inputs are written -- is migrated as format 1. It may be a whole design
without its header, a list or mapping of elements (``fragment="elements"``),
or one element (``fragment="element"``).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.emitter import Emitter
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.events import MappingEndEvent
from ruamel.yaml.scalarstring import (DoubleQuotedScalarString, FoldedScalarString,
                                      SingleQuotedScalarString)

from .diagnostics import Bag, Span
from .expr import ExprError, tokenize

#: The one format this module writes.
TARGET_FORMAT = 2

#: v1 reference -> v2 reference, for the fixed names.  ``palette.<x>`` and
#: ``config.colors.<x>`` are prefix rules (:func:`rewrite_refs`).
_FIXED_REFS = {
    "config.accent_color": "color.accent",
    "config.data_color": "color.data",
}

#: Element keys whose value is an expression (or a colour expression).
_EXPR_KEYS = ("color", "track_color", "icon_color", "visible", "value",
              "fallback", "max", "min", "icon_for")

#: The nine anchor names ``align:`` takes in format 2, built from v1's
#: ``vertical_align`` x ``align`` pair.
_H = ("left", "center", "right")
_V = ("top", "center", "bottom")

#: format 1's format-string field grammar (``wfb.formatting._FIELD_RE``),
#: repeated here so the migrator keeps its own knowledge of format 1 after
#: the compiler stops reading it.
_V1_FIELD_RE = re.compile(r"\{(?:(?P<unit>unit)|:(?P<spec>[^}]*))?\}")

_COMPLICATION_RE = re.compile(r"^complication\.([A-Za-z_][A-Za-z0-9_]*)$")
_SLOT_RE = re.compile(r"^config\.data\.([A-Za-z_][A-Za-z0-9_]*)$")
#: A yaml-language-server modeline naming the v1 schema.
_SCHEMA_COMMENT_RE = re.compile(
    r"^(#\s*yaml-language-server:\s*\$schema=\S*wfb-face-)1(\.schema\.json)", re.M)


class Refused(Exception):
    """Raised by a rule that cannot rewrite what it found faithfully."""

    def __init__(self, message: str, span: Span | None, notes: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.span = span
        self.notes = notes


@dataclass
class _Context:
    path: Path
    refusals: list[Refused] = field(default_factory=list)
    #: Multi-line quoted scalars' source text, by ``id()`` of the scalar
    #: (:func:`_capture_multiline`).
    captured: dict[int, tuple[Any, str, int]] = field(default_factory=dict)
    #: The comment lines above each top-level key, by the key's current name:
    #: ``(blank lines above them, lines)`` (:func:`_take_leading`).
    leading: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    #: The block-sequence indent the output is written with.
    seq_indent: int = 2

    def span(self, node: Any, key: Any = None) -> Span | None:
        lc = getattr(node, "lc", None)
        if lc is None:
            return None
        try:
            if key is None:
                pos = (lc.line, lc.col)
            elif isinstance(key, int) and not isinstance(node, dict):
                pos = lc.item(key)
            else:
                pos = lc.key(key)
        except (KeyError, IndexError, AttributeError, TypeError):
            pos = (lc.line, lc.col)
        if pos is None or pos[0] is None:
            return None
        return Span(self.path, pos[0] + 1, pos[1] + 1)

    def refuse(self, message: str, node: Any, key: Any, *notes: str) -> None:
        self.refusals.append(Refused(message, self.span(node, key), list(notes)))


# --------------------------------------------------------------------------
# entry points


@dataclass
class Migrated:
    """The outcome of migrating one document."""

    text: str
    changed: bool


def migrate_text(text: str, path: Path, bag: Bag, *, fragment: str | None = None,
                 ) -> Migrated | None:
    """Migrate ``text``.  ``None`` (with diagnostics in ``bag``) when the
    document cannot be parsed or a rule refused it."""
    bag.register_source(path, text)
    indent, offset = _guess_sequence_indent(text)
    yaml = _yaml(indent, offset, spaced_braces=_spaced_braces(text))
    try:
        data = yaml.load(io.StringIO(text))
    except MarkedYAMLError as exc:
        mark = exc.problem_mark
        span = Span(path, mark.line + 1, mark.column + 1) if mark else None
        bag.error("yaml", (exc.problem or "invalid YAML").strip(), span)
        return None
    if data is None:
        return Migrated(text, False)

    ctx = _Context(path, captured=_capture_multiline(data, text), seq_indent=indent or 2)
    if fragment == "element":
        if isinstance(data, CommentedMap):
            _element(ctx, data)
    elif fragment == "elements":
        data = _elements_fragment(ctx, data)
    else:
        if not isinstance(data, CommentedMap):
            return Migrated(text, False)
        if data.get("format") == TARGET_FORMAT:
            return Migrated(text, False)
        if "format" in data and data["format"] != 1:
            return Migrated(text, False)  # not ours to judge; the compiler says why
        _document(ctx, data)

    for refusal in ctx.refusals:
        bag.error("migrate", refusal.message, refusal.span,
                  notes=refusal.notes + ["nothing was written; fix this by hand, "
                                         "then run 'wfb migrate' again"])
    if ctx.refusals:
        return None
    sentinels = _swap_multiline(data, ctx.captured)
    out = io.StringIO()
    yaml.dump(data, out)
    new = _match_layout(text, _restore_multiline(out.getvalue(), sentinels))
    return Migrated(new, new != text)


# -- multi-line quoted scalars ------------------------------------------------
#
# ruamel keeps a quoted scalar's quotes but not where the author broke its
# lines, and re-emits a long lint `reason:` as one line.  So every quoted
# scalar that spans several lines in the source, and that no rule replaced,
# is swapped for a sentinel before dumping and its original text put back
# afterwards, re-indented to wherever its key now sits.

_SENTINEL = "__wfb_migrate_scalar_{}__"


def _children(node: Any) -> Iterator[tuple[Any, Any, Any]]:
    if isinstance(node, CommentedMap):
        for key, value in node.items():
            yield node, key, value
    elif isinstance(node, CommentedSeq):
        for index, value in enumerate(node):
            yield node, index, value


def _capture_multiline(data: Any, text: str) -> dict[int, tuple[Any, str, int]]:
    lines = text.split("\n")
    found: dict[int, tuple[Any, str, int]] = {}

    def walk(node: Any) -> None:
        for parent, key, value in _children(node):
            if isinstance(value, (DoubleQuotedScalarString, SingleQuotedScalarString)):
                try:
                    pos = (parent.lc.value(key) if isinstance(parent, CommentedMap)
                           else parent.lc.item(key))
                except (KeyError, IndexError, AttributeError, TypeError):
                    continue
                raw = _quoted_source(lines, pos[0], pos[1])
                if raw is not None and "\n" in raw:
                    source = lines[pos[0]]
                    found[id(value)] = (value, raw, len(source) - len(source.lstrip(" ")))
            else:
                walk(value)

    walk(data)
    return found


def _quoted_source(lines: list[str], line: int, col: int) -> str | None:
    """The source text of the quoted scalar opening at ``(line, col)``."""
    if line >= len(lines) or col >= len(lines[line]):
        return None
    quote = lines[line][col]
    if quote not in "'\"":
        return None
    out: list[str] = []
    row, i = line, col + 1
    while row < len(lines):
        src = lines[row]
        while i < len(src):
            ch = src[i]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and src[i + 1:i + 2] == "'":
                    i += 2
                    continue
                out.append(src[col if row == line else 0:i + 1])
                return "\n".join(out)
            i += 1
        out.append(src[col if row == line else 0:])
        row, i = row + 1, 0
    return None


def _swap_multiline(data: Any, captured: dict[int, tuple[Any, str, int]],
                    ) -> dict[str, tuple[str, int]]:
    sentinels: dict[str, tuple[str, int]] = {}

    def walk(node: Any) -> None:
        for parent, key, value in list(_children(node)):
            entry = captured.get(id(value))
            if entry is not None and entry[0] is value:
                sentinel = _SENTINEL.format(len(sentinels))
                sentinels[sentinel] = (entry[1], entry[2])
                parent[key] = sentinel
            elif isinstance(value, (CommentedMap, CommentedSeq)):
                walk(value)

    walk(data)
    return sentinels


def _restore_multiline(dumped: str, sentinels: dict[str, tuple[str, int]]) -> str:
    """Put each sentinel's source text back, its continuation lines moved
    by as much as the line holding it moved."""
    if not sentinels:
        return dumped
    lines = dumped.split("\n")
    for index, line in enumerate(lines):
        if "__wfb_migrate_scalar_" not in line:
            continue
        for sentinel, (raw, old_col) in sentinels.items():
            col = line.find(sentinel)
            if col < 0:
                continue
            end = col + len(sentinel)
            if col > 0 and line[col - 1] in "'\"" and line[end:end + 1] == line[col - 1]:
                col, end = col - 1, end + 1  # ruamel re-quotes a key it saw quoted
            delta = (len(line) - len(line.lstrip(" "))) - old_col
            first, *rest = raw.split("\n")
            moved = [_shift(r, delta) for r in rest]
            line = line[:col] + "\n".join([first] + moved) + line[end:]
        lines[index] = line
    return "\n".join(lines)


def _shift(line: str, delta: int) -> str:
    if delta >= 0:
        return " " * delta + line
    strip = min(-delta, len(line) - len(line.lstrip(" ")))
    return line[strip:]


def _match_layout(original: str, dumped: str) -> str:
    """Undo what ruamel's dumper changes that the author wrote on purpose:
    the blank lines at either end of the file, and the spaces just inside a
    flow mapping's braces (``{ anchor: center }``) when the file uses them."""
    body = dumped.strip("\n")
    lead = original[:len(original) - len(original.lstrip("\n"))]
    trail = original[len(original.rstrip("\n")):]
    body = _SCHEMA_COMMENT_RE.sub(r"\g<1>2\g<2>", body)
    return lead + body + trail


def _code_spans(line: str) -> Iterator[tuple[int, str]]:
    """``(index, char)`` for each character of ``line`` outside quotes and
    before a comment."""
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return
        yield i, ch


def _spaced_braces(text: str) -> bool:
    spaced = tight = 0
    for line in text.split("\n"):
        for i, ch in _code_spans(line):
            if ch == "{" and i + 1 < len(line) and line[i + 1] != "}":
                if line[i + 1] == " ":
                    spaced += 1
                else:
                    tight += 1
    return spaced > tight


class _SpacedBraceEmitter(Emitter):
    """ruamel's emitter, writing a non-empty flow mapping as ``{ a: 1 }``."""

    def expect_first_flow_mapping_key(self) -> None:
        if not isinstance(self.event, MappingEndEvent):
            self.whitespace = False  # the key's own writer adds the space
        super().expect_first_flow_mapping_key()

    def expect_flow_mapping_key(self) -> None:
        if isinstance(self.event, MappingEndEvent) and self.flow_context[-1] == "{":
            self.flow_map_end = " }"
            try:
                super().expect_flow_mapping_key()
            finally:
                del self.flow_map_end
            return
        super().expect_flow_mapping_key()


def migrate_file(path: Path, bag: Bag) -> Migrated | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        bag.error("io", f"cannot read {path}: {exc.strerror}")
        return None
    return migrate_text(text, path, bag)


_KEY_LINE_RE = re.compile(r"^(\s*)[^\s#-][^#]*:\s*(#.*)?$")
_DASH_LINE_RE = re.compile(r"^(\s*)- ")


def _guess_sequence_indent(text: str) -> tuple[int | None, int | None]:
    """``(sequence indent, dash offset)`` for ruamel's dumper, from the first
    block sequence under a key: how far its ``-`` sits inside the key."""
    previous: str | None = None
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        dash = _DASH_LINE_RE.match(line)
        if dash and previous is not None:
            key = _KEY_LINE_RE.match(previous)
            if key:
                offset = len(dash.group(1)) - len(key.group(1))
                if offset >= 0:
                    return offset + 2, offset
        previous = line
    return None, None


def _yaml(indent: int | None, offset: int | None, *, spaced_braces: bool = False) -> YAML:
    yaml = YAML()
    if spaced_braces:
        yaml.Emitter = _SpacedBraceEmitter
    yaml.preserve_quotes = True
    yaml.width = 4096
    if indent is not None:
        yaml.indent(mapping=2, sequence=indent, offset=offset or 0)
    return yaml


# --------------------------------------------------------------------------
# ruamel helpers


def _rename(mapping: CommentedMap, old: str, new: str, value: Any = None, *,
            keep_value: bool = True) -> None:
    """Rename ``old`` to ``new`` in place, keeping its position and its
    comments, and optionally replacing its value."""
    keys = list(mapping)
    index = keys.index(old)
    val = mapping[old] if keep_value else value
    comment = mapping.ca.items.pop(old, None)
    del mapping[old]
    mapping.insert(index, new, val)
    if comment is not None:
        mapping.ca.items[new] = comment


def _replace(mapping: CommentedMap, key: str, value: Any) -> None:
    """Replace ``mapping[key]``'s value, keeping its comment."""
    comment = mapping.ca.items.get(key)
    mapping[key] = value
    if comment is not None:
        mapping.ca.items[key] = comment


def _pop(mapping: CommentedMap, key: str) -> Any:
    """Delete ``key``, handing any comment it carried to the key before it,
    so a comment line that follows it is not lost."""
    keys = list(mapping)
    index = keys.index(key)
    value = mapping[key]
    comment = mapping.ca.items.pop(key, None)
    del mapping[key]
    if comment is not None and comment[2] is not None and index > 0:
        _carry_comment(mapping, keys[index - 1], comment[2])
    return value


def _carry_comment(mapping: CommentedMap, key: str, token: Any) -> None:
    """Keep the *lines* of a dropped key's end-of-line comment -- the comment
    lines and blank lines below it -- attaching them after ``key``'s value.
    The dropped key's own end-of-line text goes with it."""
    text = token.value
    newline = text.find("\n")
    rest = text[newline + 1:] if newline >= 0 else ""
    if not rest:
        return
    found = _tail_slot(mapping, key)
    if found is not None:
        slot, pos = found
        slot[pos].value += rest
        return
    value = mapping[key]
    if isinstance(value, (CommentedMap, CommentedSeq)) and value and not _is_flow(value):
        if isinstance(value, CommentedMap):
            _carry_comment(value, list(value)[-1], token)
        return
    token.value = "\n" + rest
    slot = mapping.ca.items.setdefault(key, [None, None, None, None])
    slot[2] = token


def _tail_slot(mapping: CommentedMap, key: Any) -> tuple[list[Any], int] | None:
    """The comment slot ruamel files whatever follows ``mapping[key]``'s last
    line in -- the comment lines *above the next key* live there."""
    value = mapping[key]
    if isinstance(value, (CommentedMap, CommentedSeq)) and value and not _is_flow(value):
        last = list(value)[-1] if isinstance(value, CommentedMap) else len(value) - 1
        if isinstance(value, CommentedMap):
            deeper = _tail_slot(value, last)
        else:
            item = value[last]
            deeper = None
            if isinstance(item, CommentedMap) and item and not _is_flow(item):
                deeper = _tail_slot(item, list(item)[-1])
            if deeper is None:
                slot = value.ca.items.get(last)
                if slot and slot[0] is not None:
                    return slot, 0
        if deeper is not None:
            return deeper
    slot = mapping.ca.items.get(key)
    if slot and slot[2] is not None:
        return slot, 2
    return None


def _take_leading(mapping: CommentedMap, key: Any) -> tuple[int, list[str]]:
    """Detach the full-line comments written just above ``key`` and return
    ``(blank lines above them, the comment lines)``, so they can travel with
    ``key``.  ruamel files them after the previous key's value -- there the
    blank lines stay put -- or, after a flow collection, as ``key``'s own
    pre-comments, which go whole; a negative count says the blank lines
    went too."""
    own = mapping.ca.items.get(key)
    if own is not None and own[1]:
        texts = [token.value for token in own[1]]
        own[1] = None
        lines = "".join(texts).split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        blanks = 0
        while blanks < len(lines) and not lines[blanks].strip():
            blanks += 1
        return -blanks, [line.strip() for line in lines[blanks:]]
    keys = list(mapping)
    index = keys.index(key)
    if index == 0:
        return 0, []
    found = _tail_slot(mapping, keys[index - 1])
    if found is None:
        return 0, []
    slot, pos = found
    token = slot[pos]
    eol, _, rest = token.value.partition("\n")
    lines = rest.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    blanks = 0
    while blanks < len(lines) and not lines[blanks].strip():
        blanks += 1
    moved = [line.strip() for line in lines[blanks:]]
    if not any(moved):
        return 0, []
    token.value = eol + "\n" + "\n" * blanks
    return blanks, moved


def _put_leading(mapping: CommentedMap, key: Any, lines: list[str], indent: int) -> None:
    """Write ``lines`` (from :func:`_take_leading`) above ``mapping[key]``."""
    if not lines:
        return
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    slot = mapping.ca.items.setdefault(key, [None, [], None, None])
    if slot[1] is None:
        slot[1] = []
    for line in lines:
        slot[1].append(CommentToken(line + "\n", CommentMark(indent if line else 0)))


def _indent_comments(node: Any, delta: int, slot: Any = None,
                     seen: set[int] | None = None) -> None:
    """Move every comment inside ``node`` (and in its own ``slot`` in its
    parent) ``delta`` columns, for a subtree that now sits that much deeper
    or shallower.  ruamel keeps a comment's absolute column, and the lines
    of a multi-line comment carry their indentation in the text."""
    if delta == 0:
        return
    seen = set() if seen is None else seen

    def tokens(value: Any) -> Iterator[Any]:
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                yield from tokens(item)
        elif hasattr(value, "value"):
            yield value

    def shift(token: Any) -> None:
        if id(token) in seen:
            return
        seen.add(id(token))
        first, *rest = token.value.split("\n")
        token.value = "\n".join([first] + [
            _shift(line, delta) if line.lstrip().startswith("#") else line
            for line in rest])
        mark = getattr(token, "start_mark", None)
        if mark is not None and hasattr(mark, "column"):
            mark.column = max(0, mark.column + delta)

    for token in tokens(slot):
        shift(token)
    ca = getattr(node, "ca", None)
    if ca is None:
        return
    for token in tokens(ca.comment):
        shift(token)
    for value in ca.items.values():
        for token in tokens(value):
            shift(token)
    for _, _, child in _children(node):
        _indent_comments(child, delta, None, seen)


def _insert_before(mapping: CommentedMap, anchor: str | None, key: str, value: Any) -> None:
    """Insert ``key`` just before ``anchor`` (or at the end)."""
    if anchor is not None and anchor in mapping:
        mapping.insert(list(mapping).index(anchor), key, value)
    else:
        mapping[key] = value


def _flow(mapping: CommentedMap) -> CommentedMap:
    mapping.fa.set_flow_style()
    return mapping


def _is_flow(node: Any) -> bool:
    fa = getattr(node, "fa", None)
    return bool(fa is not None and fa.flow_style())


def _same_style(original: Any, text: str) -> Any:
    """``text`` as a scalar quoted the way ``original`` was."""
    if isinstance(original, SingleQuotedScalarString) and "'" not in text:
        return SingleQuotedScalarString(text)
    return DoubleQuotedScalarString(text)


def _group(ctx: _Context, data: CommentedMap, name: str,
           members: list[tuple[str, str]]) -> None:
    """Move each present ``(old, new)`` top-level key under one new mapping
    ``name``, placed where the first of them was."""
    present = [(old, new) for old, new in members if old in data]
    if not present:
        return
    group = CommentedMap()
    first = min(list(data).index(old) for old, _ in present)
    first_key = min((old for old, _ in present), key=list(data).index)
    for old, new in present:
        _move_key(ctx, data, old, group, new, first=old == first_key, group_name=name)
    data.insert(first, name, group)


def _move_key(ctx: _Context, data: CommentedMap, old: str, group: CommentedMap,
              new: str, *, first: bool, group_name: str) -> None:
    """Move ``data[old]`` to ``group[new]`` with its comments: the one after
    its value, and the ones above it (:attr:`_Context.leading`) -- above the
    group itself when this is the group's first key."""
    blanks, leading = ctx.leading.pop(old, (0, []))
    comment = data.ca.items.pop(old, None)
    _indent_comments(data[old], 2, comment)
    group[new] = data[old]
    if comment is not None:
        group.ca.items[new] = comment
    del data[old]
    if first:
        if leading:
            ctx.leading[group_name] = (blanks, leading)
    elif leading:
        _put_leading(group, new, [""] * min(abs(blanks), 1) + leading, 2)


# --------------------------------------------------------------------------
# expressions and templates


def rewrite_refs(text: Any) -> Any:
    """``text`` with every v1 colour reference rewritten to ``color.<x>``;
    anything that is not a string, or does not tokenize, unchanged."""
    if not isinstance(text, str):
        return text
    try:
        tokens = tokenize(text)
    except ExprError:
        return text
    out, pos = [], 0
    for token in tokens:
        if token.kind != "name":
            continue
        new = _ref(token.text)
        if new is None:
            continue
        out.append(text[pos:token.offset])
        out.append(new)
        pos = token.offset + len(token.text)
    if not out:
        return text
    result = "".join(out) + text[pos:]
    return _same_style(text, result) if _quoted(text) else result


def _quoted(value: Any) -> bool:
    return isinstance(value, (DoubleQuotedScalarString, SingleQuotedScalarString))


def _ref(name: str) -> str | None:
    if name in _FIXED_REFS:
        return _FIXED_REFS[name]
    parts = name.split(".")
    if len(parts) == 2 and parts[0] == "palette":
        return f"color.{parts[1]}"
    if len(parts) == 3 and parts[:2] == ["config", "colors"]:
        return f"color.{parts[2]}"
    return None


def _has_top_level_colon(expr: str) -> bool:
    """Does ``expr`` hold a ``:`` outside parentheses (a ternary), which
    would end a template placeholder's expression early?"""
    try:
        tokens = tokenize(expr)
    except ExprError:
        return ":" in expr
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.text == ":" and depth == 0 and token.kind == "op":
            return True
    return False


def _placeholder(expr: str, spec: str | None) -> str:
    expr = str(expr).strip()
    if _has_top_level_colon(expr):
        expr = f"({expr})"
    return "{" + expr + (f":{spec}" if spec else "") + "}"


def double_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


class _TemplateError(Exception):
    pass


def build_template(expr: str, fmt: Any) -> str:
    """A v2 ``text:`` template from a v1 ``value:`` expression and its
    ``format:`` (or none).  Raises :class:`_TemplateError` for a format
    string the migrator cannot turn into exactly one placeholder."""
    if fmt is None:
        return _placeholder(expr, None)
    if not isinstance(fmt, str):
        raise _TemplateError("'format:' is not a string")
    out, pos, fields = [], 0, 0
    for match in _V1_FIELD_RE.finditer(fmt):
        out.append(double_braces(fmt[pos:match.start()]))
        if match.group("unit"):
            out.append("{unit}")
        else:
            fields += 1
            out.append(_placeholder(expr, match.group("spec") or None))
        pos = match.end()
    out.append(double_braces(fmt[pos:]))
    if fields == 0:
        raise _TemplateError(f"format {fmt!r} has no '{{}}' field, which format 1 "
                             "already rejects")
    if fields > 1:
        raise _TemplateError(f"format {fmt!r} has {fields} value fields; format 2.0 "
                             "accepts one placeholder per text")
    return "".join(out)


# --------------------------------------------------------------------------
# the document


def _document(ctx: _Context, data: CommentedMap) -> None:
    if "format" in data:
        _replace(data, "format", TARGET_FORMAT)
    # The comment lines above each top-level key travel with that key, even
    # into a group; ruamel files them after the previous key's value.
    for key in list(data):
        blanks, lines = _take_leading(data, key)
        if lines or blanks < 0:
            ctx.leading[key] = (blanks, lines)
    _check_collisions(ctx, data)
    _config(ctx, data)
    _color_scheme(ctx, data)
    _group(ctx, data, "build", [("targets", "targets")])
    _defaults(ctx, data)
    _hands(ctx, data)
    _fonts(ctx, data)
    _group(ctx, data, "resources", [("fonts", "fonts"), ("palette", "palette"),
                                    ("hands", "hand_sets")])
    _scope(ctx, data)
    layouts = data.get("layouts")
    if isinstance(layouts, CommentedMap):
        for body in layouts.values():
            if isinstance(body, CommentedMap):
                _scope(ctx, body)
    for key, (blanks, lines) in ctx.leading.items():
        if key in data:
            _put_leading(data, key, [""] * max(0, -blanks) + lines, 0)


def _elements_fragment(ctx: _Context, data: Any) -> Any:
    holder = CommentedMap()
    holder["elements"] = data
    _scope(ctx, holder)
    if "static" in holder:
        ctx.refuse("a 'static: true' element in an elements fragment has no "
                   "enclosing design to hoist it into", data, None,
                   "migrate the whole design instead")
    return holder.get("elements", data)


def _check_collisions(ctx: _Context, data: CommentedMap) -> None:
    """Refuse a name that format 2's one ``color.`` namespace would make
    ambiguous: a palette swatch that is also a scheme role or a colour
    axis's role."""
    palette = data.get("palette")
    swatches = set(palette) if isinstance(palette, dict) else set()
    roles: dict[str, str] = {}
    schemes = data.get("color_scheme")
    if isinstance(schemes, dict):
        for scheme in schemes.values():
            colors = scheme.get("colors") if isinstance(scheme, dict) else None
            if isinstance(colors, dict):
                for role in colors:
                    roles.setdefault(role, "a 'color_scheme:' role")
    config = data.get("config")
    axes: dict[str, str] = {}
    if isinstance(config, dict):
        for axis, role in (("accent_color", "accent"), ("data_color", "data")):
            if axis in config:
                axes[role] = axis
    for role, axis in axes.items():
        if role in roles:
            ctx.refuse(f"the 'color_scheme:' role {role!r} collides with the role "
                       f"'config: {axis}:' binds in format 2", schemes, None,
                       f"format 2 reads 'config: {axis}:' as 'color.{role}'",
                       "rename the scheme role (and every 'config.colors."
                       f"{role}' reference to it)")
        roles.setdefault(role, f"the role 'config: {axis}:' binds")
    for name in sorted(swatches & set(roles)):
        ctx.refuse(f"the palette entry {name!r} has the same name as {roles[name]}",
                   palette, name,
                   f"format 2 reads both as 'color.{name}', and refuses the ambiguity",
                   "rename the palette entry (and every 'palette."
                   f"{name}' reference to it)")


def _defaults(ctx: _Context, data: CommentedMap) -> None:
    members = [("antialias", "antialias"), ("min_1px", "min_1px")]
    aod = data.get("aod")
    aod_default = None
    if isinstance(aod, CommentedMap) and "default" in aod:
        aod_default = aod["default"]
    present = [old for old, _ in members if old in data]
    if not present and aod_default is None:
        return
    first_key = present[0] if present else "aod"
    first = min([list(data).index(k) for k in present]
                + ([list(data).index("aod")] if aod_default is not None else []))
    group = CommentedMap()
    for old, new in members:
        if old in data:
            _move_key(ctx, data, old, group, new, first=old == first_key,
                      group_name="defaults")
    if aod_default is not None:
        assert isinstance(aod, CommentedMap)
        comment = aod.ca.items.pop("default", None)
        group["aod"] = aod_default
        if comment is not None:
            group.ca.items["aod"] = comment
        del aod["default"]
        if not aod:
            comment = data.ca.items.pop("aod", None)
            del data["aod"]
            if comment is not None:
                group.ca.items.setdefault("aod", comment)
            if first_key == "aod" and "aod" in ctx.leading:
                ctx.leading["defaults"] = ctx.leading.pop("aod")
    data.insert(min(first, len(data)), "defaults", group)


def _color_scheme(ctx: _Context, data: CommentedMap) -> None:
    schemes = data.get("color_scheme")
    if isinstance(schemes, CommentedMap):
        for scheme in schemes.values():
            colors = scheme.get("colors") if isinstance(scheme, dict) else None
            if isinstance(colors, CommentedMap):
                for role in list(colors):
                    _replace(colors, role, rewrite_refs(colors[role]))
    if "color_scheme" in data:
        wrapper = CommentedMap()
        comment = data.ca.items.pop("color_scheme", None)
        wrapper["schemes"] = schemes
        index = list(data).index("color_scheme")
        del data["color_scheme"]
        data.insert(index, "theme", wrapper)
        if comment is not None:
            data.ca.items["theme"] = comment
        if "color_scheme" in ctx.leading:
            ctx.leading["theme"] = ctx.leading.pop("color_scheme")


def _config(ctx: _Context, data: CommentedMap) -> None:
    config = data.get("config")
    if not isinstance(config, CommentedMap):
        return
    for axis in ("accent_color", "data_color"):
        body = config.get(axis)
        if not isinstance(body, CommentedMap):
            continue
        if "default" in body:
            _replace(body, "default", rewrite_refs(body["default"]))
        choices = body.get("choices")
        if isinstance(choices, CommentedSeq):
            for i, choice in enumerate(choices):
                if isinstance(choice, str):
                    choices[i] = rewrite_refs(choice)
    style = config.get("style")
    if isinstance(style, CommentedMap) and isinstance(style.get("choices"), CommentedMap):
        for entry in style["choices"].values():
            if isinstance(entry, CommentedMap) and "colors" in entry:
                _rename(entry, "colors", "scheme")
    if "data" in config:
        slots = config["data"]
        _rename(config, "data", "slots")
        if isinstance(slots, CommentedMap):
            for slot in slots.values():
                if isinstance(slot, CommentedMap):
                    _slot(ctx, slot)


def _bare_complication(value: Any) -> Any:
    if isinstance(value, str):
        match = _COMPLICATION_RE.match(value)
        if match:
            return type(value)(match.group(1)) if _quoted(value) else match.group(1)
    return value


def _slot(ctx: _Context, slot: CommentedMap) -> None:
    if "default" in slot:
        _replace(slot, "default", _bare_complication(slot["default"]))
    choices = slot.get("choices")
    if not isinstance(choices, CommentedSeq):
        return
    for i, choice in enumerate(choices):
        if isinstance(choice, str):
            choices[i] = _bare_complication(choice)
        elif isinstance(choice, CommentedMap):
            if "type" in choice:
                _replace(choice, "type", _bare_complication(choice["type"]))
            if "glyph" in choice:
                if "icon" in choice:
                    ctx.refuse("a data choice sets both 'icon:' and 'glyph:', which "
                               "format 2 writes as one 'icon:'", choice, "glyph",
                               "keep one of them")
                    continue
                _rename(choice, "glyph", "icon")


def _hands(ctx: _Context, data: CommentedMap) -> None:
    hands = data.get("hands")
    if not isinstance(hands, CommentedMap):
        return
    for hand_set in hands.values():
        if not isinstance(hand_set, CommentedMap):
            continue
        for hand in hand_set.values():
            if not isinstance(hand, CommentedMap):
                continue
            if "color" in hand:
                _replace(hand, "color", rewrite_refs(hand["color"]))
            _parts(ctx, hand.get("parts"))


def _fonts(ctx: _Context, data: CommentedMap) -> None:
    fonts = data.get("fonts")
    if isinstance(fonts, CommentedMap):
        for font in fonts.values():
            if isinstance(font, CommentedMap) and "if_unavailable" in font:
                _rename(font, "if_unavailable", "unsupported")


# --------------------------------------------------------------------------
# element scopes: the mapping form, and the `static: true` flag


def _scope(ctx: _Context, holder: CommentedMap) -> None:
    """One scope -- the document, or one ``layouts:`` body: both its element
    lists into the mapping form, every element rewritten, and each flagged
    element moved into the scope's ``static:`` block."""
    for key in ("static", "elements"):
        if key in holder:
            converted = _to_mapping(ctx, holder[key])
            if converted is not holder[key]:
                _replace(holder, key, converted)
    static = holder.get("static")
    elements = holder.get("elements")
    moved: list[tuple[str, CommentedMap]] = []
    if isinstance(elements, CommentedMap):
        for name in list(elements):
            body = elements[name]
            if isinstance(body, CommentedMap) and "static" in body:
                flag = body["static"]
                _pop(body, "static")
                if flag is True:
                    moved.append((name, body))
                    comment = elements.ca.items.pop(name, None)
                    del elements[name]
                    if comment is not None:
                        elements.ca.items.setdefault(name, comment)
                        elements.ca.items.pop(name, None)
    if moved:
        if not isinstance(static, CommentedMap):
            if static is not None:
                ctx.refuse("the 'static:' block is not a mapping of elements, so a "
                           "'static: true' element cannot join it", holder, "static",
                           "fix the 'static:' block first")
                return
            static = CommentedMap()
            _insert_before(holder, "elements", "static", static)
        for name, body in moved:
            static[name] = body
    if isinstance(elements, CommentedMap) and not elements and moved:
        _pop(holder, "elements")
    for block, in_static in ((holder.get("static"), True), (holder.get("elements"), False)):
        if isinstance(block, CommentedMap):
            for body in block.values():
                if isinstance(body, CommentedMap):
                    _element(ctx, body, static_scope=in_static, root=True)


def _to_mapping(ctx: _Context, node: Any) -> Any:
    """The mapping form of an element list: ``- id: x`` items become ``x:``
    entries.  A mapping (or anything else) comes back as it is."""
    if not isinstance(node, CommentedSeq):
        return node
    out = CommentedMap()
    if node.ca.comment is not None:
        out.ca.comment = node.ca.comment
    if _is_flow(node):
        out.fa.set_flow_style()
    for index, body in enumerate(node):
        if not isinstance(body, CommentedMap) or not isinstance(body.get("id"), str):
            ctx.refuse("an element list item has no 'id:', so it has no key in the "
                       "mapping form", node, index, "give it an 'id:' first")
            return node
        name = body["id"]
        if name in out:
            ctx.refuse(f"the id {name!r} is used twice in one list, and a mapping "
                       "key cannot be", body, "id", "rename one of them")
            return node
        comment = body.ca.items.pop("id", None)
        del body["id"]
        # An item's keys sit `seq_indent` inside the list's parent key; an
        # entry's keys sit 4 inside it (the id key 2, its body 2 more).
        _indent_comments(body, 4 - ctx.seq_indent, comment)
        out[name] = body
        if comment is not None and comment[2] is not None:
            # The `- id: x` line's comment (and any comment lines under it)
            # now follows `x:`, which ruamel keeps on the parent's key.
            out.ca.items[name] = [None, None, comment[2], None]
        _move_ca_items_into_body(node, index, body)
    return out


def _move_ca_items_into_body(seq: CommentedSeq, index: int, body: CommentedMap) -> None:
    """A comment ruamel filed against the sequence item itself goes on the
    body's last key instead."""
    item = seq.ca.items.get(index)
    if not item or not body:
        return
    last = list(body)[-1]
    for token in item:
        if token is None or isinstance(token, list):
            continue
        body.ca.items.setdefault(last, [None, None, None, None])
        if body.ca.items[last][2] is None:
            body.ca.items[last][2] = token


# --------------------------------------------------------------------------
# one element


def _element(ctx: _Context, body: CommentedMap, *, static_scope: bool = False,
             root: bool = False) -> None:
    kind = body.get("type")
    if "static" in body:
        flag = body["static"]
        if flag is True:
            where = ("inside a 'static:' block, which is static already"
                     if static_scope else "nested inside a group")
            ctx.refuse(f"a 'static: true' element {where} has no place in format 2",
                       body, "static",
                       "format 2 has no 'static: true' flag; an element is static "
                       "by being a direct entry of a 'static:' block",
                       "move this element (or its whole top-level group) into the "
                       "'static:' block by hand")
            return
        _pop(body, "static")
    _modes(ctx, body)
    _align(ctx, body)
    if "if_unavailable" in body:
        _rename(body, "if_unavailable", "unsupported")
    for key in _EXPR_KEYS:
        if key in body and not (kind == "text" and key == "value"):
            _replace(body, key, rewrite_refs(body[key]))
    if "outline" in body:
        _outline(body)
    if kind == "shape":
        _shape(body)
    elif kind == "text":
        _text(ctx, body)
    elif kind == "progress":
        _rename(body, "type", "type", "gauge", keep_value=False)
        _bands(body)
        _parts(ctx, body.get("needle"))
    elif kind == "icon":
        _icon(ctx, body)
    elif kind == "complication_slot":
        _slot_element(ctx, body)
    elif kind == "hands" and "hands" in body:
        _rename(body, "hands", "set")
    elif kind == "pattern":
        _parts(ctx, body.get("parts"))
    elif kind == "group":
        children = body.get("children")
        converted = _to_mapping(ctx, children)
        if converted is not children:
            _replace(body, "children", converted)
        if isinstance(converted, CommentedMap):
            for child in converted.values():
                if isinstance(child, CommentedMap):
                    _element(ctx, child, static_scope=static_scope)
    _absent(ctx, body)
    _aod(ctx, body, kind)


def _modes(ctx: _Context, body: CommentedMap) -> None:
    if "modes" not in body:
        return
    modes = body["modes"]
    values = set(modes) if isinstance(modes, list) else None
    if values == {"active"} and len(modes) == 1:
        _pop(body, "modes")
    elif values == {"active", "low_power"} and len(modes) == 2:
        _rename(body, "modes", "sleep_update", True, keep_value=False)
    else:
        ctx.refuse(f"'modes: {list(modes) if isinstance(modes, list) else modes}' has "
                   "no format 2 spelling", body, "modes",
                   "format 2 keeps '[active]' (the default, written as nothing) and "
                   "'[active, low_power]' ('sleep_update: true') only",
                   "choose one of those two by hand")


def _align(ctx: _Context, body: CommentedMap) -> None:
    if "vertical_align" not in body:
        return
    v = body["vertical_align"]
    h = body.get("align", "center")
    if v not in _V or h not in _H:
        return  # left as written; the compiler names the bad value
    if v == "center":
        merged = h
    elif h == "center":
        merged = v
    else:
        merged = f"{v}_{h}"
    if "align" in body:
        _replace(body, "align", merged)
        _pop(body, "vertical_align")
    else:
        _rename(body, "vertical_align", "align", merged, keep_value=False)


def _outline(body: CommentedMap) -> None:
    outline = body["outline"]
    if isinstance(outline, CommentedMap):
        if "color" in outline:
            _replace(outline, "color", rewrite_refs(outline["color"]))
    else:
        _replace(body, "outline", rewrite_refs(outline))


def _bands(body: CommentedMap) -> None:
    bands = body.get("bands")
    if isinstance(bands, CommentedSeq):
        for band in bands:
            if isinstance(band, CommentedMap) and "color" in band:
                _replace(band, "color", rewrite_refs(band["color"]))


def _shape(body: CommentedMap) -> None:
    shape = body.get("shape")
    if not isinstance(shape, str):
        return
    new = "rectangle" if shape == "rounded_rectangle" else shape
    _replace(body, "type", new)
    _pop(body, "shape")


def _text(ctx: _Context, body: CommentedMap) -> None:
    """``text:``/``value:``/``format:`` into one ``text:`` template."""
    if "value" in body:
        original = body["value"]
        expr = rewrite_refs(original)
        try:
            template = build_template(str(expr), body.get("format"))
        except _TemplateError as exc:
            ctx.refuse(f"cannot write this 'value:'/'format:' as one 'text:' "
                       f"template: {exc}", body, "format" if "format" in body else "value",
                       "rewrite the format by hand")
            return
        _rename(body, "value", "text",
                _template_scalar(ctx, original, str(expr), template), keep_value=False)
        if "format" in body:
            comment = body.ca.items.get("format")
            if comment is not None and comment[2] is not None:
                slot = body.ca.items.setdefault("text", [None, None, None, None])
                if slot[2] is None:
                    slot[2] = comment[2]
                    body.ca.items.pop("format")
            _pop(body, "format")
    elif isinstance(body.get("text"), str):
        literal = body["text"]
        doubled = double_braces(literal)
        if doubled != literal:
            _replace(body, "text", _same_style(literal, doubled))


def _template_scalar(ctx: _Context, original: Any, expr: str, template: str) -> Any:
    """``template`` as a scalar, keeping the author's line breaks when the
    expression was written over several lines and is otherwise unchanged:
    folded (``>-``) stays folded, and a multi-line quoted scalar keeps its
    source lines with the template's braces added round them."""
    unchanged = expr == str(original)
    shift = template.find(expr.strip()) if unchanged else -1
    if isinstance(original, FoldedScalarString) and shift >= 0:
        folded = FoldedScalarString(template)
        positions = getattr(original, "fold_pos", None) or []
        folded.fold_pos = [p + shift for p in positions]
        return folded
    entry = ctx.captured.get(id(original))
    if entry is not None and entry[0] is original and shift >= 0:
        raw, col = entry[1], entry[2]
        quote = raw[0]
        prefix, suffix = template[:shift], template[shift + len(expr.strip()):]
        inner = raw[1:-1]
        lead = len(inner) - len(inner.lstrip())
        trail = len(inner) - len(inner.rstrip())
        inner = inner.strip()
        new_raw = (quote + " " * lead + _escape(prefix, quote) + inner
                   + _escape(suffix, quote) + " " * trail + quote)
        scalar = (SingleQuotedScalarString(template) if quote == "'"
                  else DoubleQuotedScalarString(template))
        ctx.captured[id(scalar)] = (scalar, new_raw, col)
        return scalar
    return DoubleQuotedScalarString(template)


def _escape(text: str, quote: str) -> str:
    if quote == "'":
        return text.replace("'", "''")
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _icon(ctx: _Context, body: CommentedMap) -> None:
    if "glyph" in body:
        _rename(body, "glyph", "icon")
    elif "icon_for" in body:
        mapping = _flow(CommentedMap())
        mapping["for"] = body["icon_for"]
        _rename(body, "icon_for", "icon", mapping, keep_value=False)


_SLOT_ICON_KEYS = (("icon_size", "size"), ("icon_position", "position"),
                   ("icon_gap", "gap"), ("icon_color", "color"))


def _slot_element(ctx: _Context, body: CommentedMap) -> None:
    _replace(body, "type", "data")
    slot = body.get("slot")
    if isinstance(slot, str):
        match = _SLOT_RE.match(slot)
        if match:
            _replace(body, "slot", match.group(1))
    present = [(old, new) for old, new in _SLOT_ICON_KEYS if old in body]
    if not present:
        return
    icon = _flow(CommentedMap())
    first = present[0][0]
    for old, new in present:
        icon[new] = body[old]
    for old, _ in present[1:]:
        _pop(body, old)
    _rename(body, first, "icon", icon, keep_value=False)


def _parts(ctx: _Context, parts: Any) -> None:
    """Hand, needle and pattern parts: ``shape:`` -> ``type:``, and a text
    part's template."""
    if not isinstance(parts, CommentedSeq):
        return
    for part in parts:
        if not isinstance(part, CommentedMap):
            continue
        if "shape" in part:
            _rename(part, "shape", "type")
        _align(ctx, part)
        if "if_unavailable" in part:
            _rename(part, "if_unavailable", "unsupported")
        for key in ("color", "visible"):
            if key in part:
                _replace(part, key, rewrite_refs(part[key]))
        if "outline" in part:
            _outline(part)
        if part.get("type") == "text":
            _text(ctx, part)


def _absent(ctx: _Context, body: CommentedMap) -> None:
    """``when_absent:`` + ``placeholder:``/``fallback:`` -> ``absent:``."""
    if "when_absent" not in body:
        return
    policy = body["when_absent"]
    if policy == "hide":
        _replace(body, "when_absent", "hide")
        _rename(body, "when_absent", "absent")
    elif policy == "placeholder" and isinstance(body.get("placeholder"), str):
        text = body["placeholder"]
        if text == "hide":
            ctx.refuse("the placeholder text 'hide' would read as 'absent: hide' in "
                       "format 2", body, "placeholder",
                       "choose a different placeholder text")
            return
        _rename(body, "when_absent", "absent", body["placeholder"], keep_value=False)
        _pop(body, "placeholder")
    elif policy == "fallback" and "fallback" in body:
        mapping = _flow(CommentedMap())
        mapping["value"] = rewrite_refs(body["fallback"])
        _rename(body, "when_absent", "absent", mapping, keep_value=False)
        _pop(body, "fallback")


def _aod(ctx: _Context, body: CommentedMap, kind: Any) -> None:
    aod = body.get("aod")
    if not isinstance(aod, CommentedMap):
        return
    for key in ("color", "track_color", "icon_color", "visible"):
        if key in aod:
            _replace(aod, key, rewrite_refs(aod[key]))
    if "outline" in aod:
        _outline(aod)
    if "icon_color" in aod:
        icon = _flow(CommentedMap())
        icon["color"] = aod["icon_color"]
        _rename(aod, "icon_color", "icon", icon, keep_value=False)
    if "format" in aod:
        fmt = aod["format"]
        own = ""
        if kind == "text":
            text = body.get("text")
            own = _template_expr(text) if isinstance(text, str) else ""
        try:
            template = build_template(own, fmt) if own else _empty_template(fmt)
        except _TemplateError as exc:
            ctx.refuse(f"cannot write this 'aod: {{format:}}' as a 'text:' template: "
                       f"{exc}", aod, "format", "rewrite the format by hand")
            return
        _rename(aod, "format", "text", DoubleQuotedScalarString(template),
                keep_value=False)


def _empty_template(fmt: Any) -> str:
    """A group's ``aod: {format:}`` has no expression of its own: its
    placeholder stays empty, standing for each descendant's."""
    return build_template("", fmt)


def _template_expr(template: str) -> str:
    """The expression inside an already-migrated one-placeholder template
    (``_text`` ran first), or ``""`` for a literal."""
    from .template import parse_template, TemplateError

    try:
        parsed = parse_template(template)
    except TemplateError:
        return ""
    return parsed.placeholder.expr if parsed.placeholder else ""


# --------------------------------------------------------------------------


def iter_files(paths: list[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(path.rglob("*.yaml"))
        else:
            yield path

