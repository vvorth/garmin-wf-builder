"""Check what the schema cannot in a format 2 document, before the builder.

The builder reads the author's keys as written; this pass, between the
schema and :mod:`wfb.desugar`, checks the format 2 semantics a JSON Schema
cannot express:

* every ``color.<name>``: unknown, a name that is both a swatch and a role,
  a role where a build-time colour is needed, a format 1 spelling;
* every ``text:`` template: it parses, a ternary inside a placeholder is
  parenthesised, ``{unit}`` has a reading to label, several placeholders
  only where several are drawn, and an ``aod: {text:}`` restyle reads the
  element's own expression.

It changes one thing: a compass alias (``align: NE``, ``anchor: SW``) is
spelled out.  And it records, for a nested key the builder compiles
(``outline.color``, ``absent.value``), the dotted name a diagnostic gives
it (:class:`~wfb.yamlsrc.Origin`).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Iterator

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .diagnostics import Bag, Span
from .expr import ExprError, tokenize
from .template import (
    Placeholder, TemplateError, Template, Unit, aod_format, parse_template, segments,
    strip_template_parens, to_value_format,
)
from .yamlsrc import Origin, YamlDocument

#: A compass alias -> the anchor name it stands for (`align:` and `anchor:`).
COMPASS = {"N": "top", "NE": "top_right", "E": "right", "SE": "bottom_right",
           "S": "bottom", "SW": "bottom_left", "W": "left", "NW": "top_left"}



@dataclass
class _Colors:
    """The names a ``color.<name>`` may take."""

    swatches: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)

    def names(self) -> list[str]:
        return sorted(self.swatches | self.roles)


class _Lowering:
    def __init__(self, doc: YamlDocument, bag: Bag) -> None:
        self.doc = doc
        self.bag = bag
        self.colors = _Colors()
        self.ok = True
        # One YAML node aliased under two keys is lowered once; `wfb.desugar`
        # reports the alias itself.
        self.lowered: set[int] = set()

    # -- spans and origins -------------------------------------------------

    def span(self, node: Any, key: Any = None, *, of: str = "value") -> Span | None:
        return self.doc.span(node, key, of=of)

    def error(self, code: str, message: str, span: Span | None, *notes: str) -> None:
        self.bag.error(code, message, span, notes=list(notes))
        self.ok = False

    # -- colours -----------------------------------------------------------

    def gather_colors(self, data: CommentedMap) -> None:
        resources = data.get("resources")
        palette = resources.get("palette") if isinstance(resources, dict) else None
        if isinstance(palette, dict):
            self.colors.swatches = set(palette)
        declared: dict[str, tuple[Any, Any]] = {}  # role -> (node, key) that declared it
        theme = data.get("theme")
        schemes = theme.get("schemes") if isinstance(theme, dict) else None
        if isinstance(schemes, dict):
            for scheme in schemes.values():
                colors = scheme.get("colors") if isinstance(scheme, dict) else None
                if isinstance(colors, dict):
                    for role in colors:
                        declared.setdefault(role, (colors, role))
                        self.colors.roles.add(role)
        config = data.get("config")
        if isinstance(config, dict):
            for axis, default in (("accent_color", "accent"), ("data_color", "data")):
                body = config.get(axis)
                if not isinstance(body, dict):
                    continue
                role = body.get("role", default)
                where = (body, "role") if "role" in body else (config, axis)
                if role in declared and declared[role][0] is not config:
                    self.error("color",
                               f"the role {role!r} is both a 'theme:' scheme role and the "
                               f"role 'config: {axis}:' binds",
                               self.span(*where, of="key"),
                               f"'color.{role}' would mean two different colours",
                               "rename the scheme role, or give the axis another with "
                               "'role:'")
                    continue
                declared[role] = where
                self.colors.roles.add(role)
        for name in sorted(self.colors.swatches & self.colors.roles):
            node, key = declared[name]
            for span in (self.span(palette, name, of="key"), self.span(node, key, of="key")):
                self.error("color",
                           f"'color.{name}' is both a palette swatch and a colour role",
                           span,
                           "format 2 has one colour namespace: a role is looked up "
                           "first, then a swatch, and a name that is both is refused "
                           "rather than shadowed",
                           "rename the palette swatch or the role")

    def unknown_color(self, name: str, span: Span | None) -> None:
        near = difflib.get_close_matches(name, self.colors.names(), n=3, cutoff=0.5)
        notes = ([f"did you mean {', '.join(f'color.{n}' for n in near)}?"] if near else
                 [f"declared colours: {', '.join(f'color.{n}' for n in self.colors.names())}"
                  if self.colors.names() else
                  "declare it under 'resources: palette:', or as a 'theme: schemes:' role"])
        self.error("color", f"unknown colour 'color.{name}'", span, *notes)

    def check_refs(self, node: Any, key: Any, *, author: str | None = None,
                   swatch_only: bool = False, text: str | None = None) -> bool:
        """Whether every ``color.<name>`` in ``node[key]`` (or ``text``) names
        a declared colour -- a palette swatch where ``swatch_only`` -- and no
        format 1 colour reference is left; each mistake reported."""
        raw = node[key] if text is None else text
        if not isinstance(raw, str):
            return True
        try:
            tokens = tokenize(raw)
        except ExprError:
            return True  # the builder reports the syntax error
        ok = True
        for token in tokens:
            if token.kind != "name":
                continue
            v1 = _format_1_ref(token.text)
            if v1 is not None:
                self.error("color", f"{token.text!r} is format 1's spelling of a colour",
                           self.span(node, key), f"format 2 writes {v1!r}",
                           "'wfb migrate' rewrites a whole file")
                ok = False
                continue
            if not token.text.startswith("color."):
                continue
            parts = token.text.split(".")
            if len(parts) != 2:
                continue
            name = parts[1]
            span = self.span(node, key)
            if name not in self.colors.swatches and name not in self.colors.roles:
                self.unknown_color(name, span)
                ok = False
                continue
            if swatch_only and name not in self.colors.swatches:
                self.error("color",
                           f"'color.{name}' is a colour role, but {author or key!r} needs a "
                           "build-time colour",
                           span,
                           "a role follows the active style's scheme or the wearer's "
                           "pick, so it has no single value when the face is built",
                           "name a palette swatch, or write the colour as '#RRGGBB'")
                ok = False
        return ok

    def expr_key(self, node: CommentedMap, key: str, *, author: str | None = None) -> None:
        """Check the colour references in ``node[key]``, and record the key's
        author name (``author``, a dotted path for a nested key) for the
        builder's diagnostics."""
        if key not in node or not isinstance(node[key], str):
            return
        if self.check_refs(node, key, author=author):
            self.doc.set_origin(node, key, Origin(author or key, str(node[key])))

    def swatch(self, node: Any, key: Any, author: str) -> None:
        """A colour that must be a build-time literal: a hex literal, or a
        ``color.<swatch>``."""
        value = node[key]
        if isinstance(value, str) and value.startswith("color."):
            self.check_refs(node, key, author=author, swatch_only=True)

    # -- the document --------------------------------------------------------

    def document(self, data: CommentedMap) -> None:
        self.gather_colors(data)
        if not self.ok:
            return
        self.top_level(data)
        for holder in self.scopes(data):
            for block in ("static", "elements"):
                mapping = holder.get(block)
                if isinstance(mapping, CommentedMap):
                    for body in mapping.values():
                        if isinstance(body, CommentedMap):
                            self.element(body)

    def scopes(self, data: CommentedMap) -> Iterator[CommentedMap]:
        yield data
        layouts = data.get("layouts")
        if isinstance(layouts, CommentedMap):
            for body in layouts.values():
                if isinstance(body, CommentedMap):
                    yield body

    def top_level(self, data: CommentedMap) -> None:
        resources = data.get("resources")
        if isinstance(resources, CommentedMap):
            hand_sets = resources.get("hand_sets")
            if isinstance(hand_sets, CommentedMap):
                for hand_set in hand_sets.values():
                    if not isinstance(hand_set, CommentedMap):
                        continue
                    for hand in hand_set.values():
                        if isinstance(hand, CommentedMap):
                            self.expr_key(hand, "color")
                            self.parts(hand.get("parts"))
        theme = data.get("theme")
        if isinstance(theme, CommentedMap):
            schemes = theme.get("schemes")
            if isinstance(schemes, CommentedMap):
                for scheme in schemes.values():
                    colors = scheme.get("colors") if isinstance(scheme, dict) else None
                    if isinstance(colors, CommentedMap):
                        for role in list(colors):
                            self.swatch(colors, role, f"theme.schemes: {role}")
        config = data.get("config")
        if isinstance(config, CommentedMap):
            self.config(config)

    def config(self, config: CommentedMap) -> None:
        for axis in ("accent_color", "data_color"):
            body = config.get(axis)
            if not isinstance(body, CommentedMap):
                continue
            if "default" in body:
                self.swatch(body, "default", f"config.{axis}.default")
            choices = body.get("choices")
            if isinstance(choices, CommentedSeq):
                for index, choice in enumerate(choices):
                    if isinstance(choice, str):
                        self.swatch(choices, index, f"config.{axis}.choices")

    # -- elements ------------------------------------------------------------

    def element(self, node: CommentedMap) -> None:
        if id(node) in self.lowered:
            return
        self.lowered.add(id(node))
        kind = node.get("type")
        self.common(node, kind)
        if kind == "text":
            self.text(node, several=True)
        elif kind == "gauge":
            self.expr_key(node, "value")
            self.expr_key(node, "max")
            bands = node.get("bands")
            if isinstance(bands, CommentedSeq):
                for band in bands:
                    if isinstance(band, CommentedMap):
                        self.expr_key(band, "color")
            self.parts(node.get("needle"))
        elif kind == "icon":
            self.icon(node)
        elif kind == "data":
            self.data(node)
        elif kind == "pattern":
            self.parts(node.get("parts"), pattern=True)
        elif kind == "graph":
            self.expr_key(node, "min")
            self.expr_key(node, "max")
        elif kind == "group":
            children = node.get("children")
            if isinstance(children, CommentedMap):
                for child in children.values():
                    if isinstance(child, CommentedMap):
                        self.element(child)
        self.absent(node)
        self.aod(node)

    def common(self, node: CommentedMap, kind: Any) -> None:
        self.align(node)
        for key in ("color", "track_color", "visible"):
            self.expr_key(node, key)
        if "outline" in node:
            self.outline(node)
        for key in ("at", "to"):
            _anchor(node.get(key))
        overrides = node.get("overrides")
        if isinstance(overrides, CommentedMap):
            for patch in overrides.values():
                if isinstance(patch, CommentedMap):
                    self.align(patch)
                    _anchor(patch.get("at"))
        points = node.get("points")
        if isinstance(points, list):
            for point in points:
                _anchor(point)

    def align(self, node: CommentedMap) -> None:
        value = node.get("align")
        if isinstance(value, str) and value in COMPASS:
            node["align"] = COMPASS[value]

    def outline(self, node: CommentedMap) -> None:
        outline = node["outline"]
        if isinstance(outline, CommentedMap):
            self.expr_key(outline, "color", author="outline.color")
        elif outline != "none":
            self.expr_key(node, "outline")

    def text(self, node: CommentedMap, *, several: bool = False) -> None:
        """Check a ``text:`` template: it parses, and each placeholder's
        expression reads declared colours.  With ``several``, a template
        with more than one placeholder is accepted."""
        raw = node.get("text")
        if not isinstance(raw, str):
            return
        template = self.template(node, "text", several=several)
        if template is None or template.placeholder is None:
            return
        for segment in segments(template):
            try:
                expr, _ = to_value_format(segment)
            except TemplateError as exc:
                self.error("format", f"text: {exc.message}", self.span(node, "text"))
                return
            assert expr is not None
            if not self.check_refs(node, "text", text=strip_template_parens(expr)[0]):
                return

    def template(self, node: CommentedMap, key: str, *, aod: bool = False,
                 several: bool = False) -> Template | None:
        raw = node[key]
        try:
            template = parse_template(raw)
        except TemplateError as exc:
            self.error("format", f"{key}: {exc.message}", self.span(node, key),
                       "'{{' and '}}' are a literal brace; a placeholder is '{expr}' or "
                       "'{expr:spec}'")
            return None
        if len(template.placeholders) > 1 and not several:
            self.error("format",
                       f"{key}: only a 'text' element's own 'text:' takes several "
                       "placeholders; this one reads one",
                       self.span(node, key),
                       "a pattern's text part, and an element's 'aod: {text:}', "
                       "draw a single reading",
                       "docs/limitations.md, \"Not implemented yet\"")
            return None
        if len(template.placeholders) > 1 and any(isinstance(p, Unit) for p in template.pieces):
            self.error("format", f"{key}: '{{unit}}' labels the reading of a 'units:' "
                       "conversion, and this text has several readings",
                       self.span(node, key),
                       "'units:' converts a text with one placeholder")
            return None
        if template.placeholder is None and any(isinstance(p, Unit) for p in template.pieces):
            self.error("format", f"{key}: '{{unit}}' needs a placeholder to be the unit of",
                       self.span(node, key))
            return None
        if not aod and any(not p.expr for p in template.placeholders):
            self.error("format", f"{key}: the placeholder has no expression",
                       self.span(node, key), "write the reading inside the braces: "
                       "\"{time.hour:02d}\"")
            return None
        if any(_open_ternary(p) for p in template.placeholders):
            self.error("format",
                       f"{key}: a ternary inside a placeholder must be parenthesised",
                       self.span(node, key),
                       "the expression ends at the first ':' outside parentheses, so "
                       "\"{a ? b : c}\" reads as the expression 'a ? b' with the format "
                       "spec ' c'",
                       "write \"{(a ? b : c)}\"")
            return None
        return template

    def icon(self, node: CommentedMap) -> None:
        icon = node.get("icon")
        if isinstance(icon, CommentedMap):
            self.expr_key(icon, "for", author="icon.for")

    def data(self, node: CommentedMap) -> None:
        icon = node.get("icon")
        if isinstance(icon, CommentedMap):
            self.expr_key(icon, "color", author="icon.color")

    def absent(self, node: CommentedMap) -> None:
        value = node.get("absent")
        if isinstance(value, CommentedMap):
            self.expr_key(value, "value", author="absent.value")

    def aod(self, node: CommentedMap) -> None:
        aod = node.get("aod")
        if not isinstance(aod, CommentedMap):
            return
        for key in ("color", "track_color", "visible"):
            self.expr_key(aod, key, author=f"aod.{key}")
        if "outline" in aod:
            self.outline(aod)
        icon = aod.get("icon")
        if isinstance(icon, CommentedMap):
            self.expr_key(icon, "color", author="aod.icon.color")
        if isinstance(aod.get("text"), str):
            self.aod_text(node, aod)

    def aod_text(self, node: CommentedMap, aod: CommentedMap) -> None:
        own = node.get("text") if node.get("type") == "text" else None
        own_template = _template_of(own) if isinstance(own, str) else None
        if own_template is not None and len(own_template.placeholders) > 1:
            self.error("format",
                       "aod.text: restyling a text with several placeholders is not "
                       "implemented yet",
                       self.span(aod, "text"),
                       "the always-on frame draws the same template; its other "
                       "'aod:' overrides (colour, font, outline) still apply",
                       "docs/limitations.md, \"Not implemented yet\"")
            return
        template = self.template(aod, "text", aod=True)
        if template is None:
            return
        placeholder = template.placeholder
        if placeholder is not None and placeholder.expr:
            parsed = own_template.placeholder if own_template is not None else None
            expected = parsed.expr if parsed is not None else None
            if expected is None or _normalise(placeholder.expr) != _normalise(expected):
                self.error("format",
                           "aod.text: the placeholder must read the element's own "
                           "expression" + (f" ({expected})" if expected else ""),
                           self.span(aod, "text"),
                           "the always-on frame may restyle the reading -- its literal "
                           "text and format spec -- but not change what is read",
                           "write the same expression, or leave the braces empty: "
                           "\"{:%H %M}\"")
                return
        if placeholder is None:
            self.error("format", "aod.text: needs the element's placeholder",
                       self.span(aod, "text"),
                       "the always-on frame restyles the reading; it cannot replace it "
                       "with fixed text")
            return
        try:
            aod_format(str(aod["text"]))
        except TemplateError as exc:
            self.error("format", f"aod.text: {exc.message}", self.span(aod, "text"))

    def parts(self, parts: Any, *, pattern: bool = False) -> None:
        if not isinstance(parts, CommentedSeq):
            return
        for part in parts:
            if not isinstance(part, CommentedMap):
                continue
            self.align(part)
            for key in ("color", "visible"):
                self.expr_key(part, key)
            if "outline" in part:
                self.outline(part)
            if pattern and part.get("type") == "text":
                self.text(part)


# --------------------------------------------------------------------------


def lower(doc: YamlDocument, bag: Bag) -> bool:
    """Rewrite the format 2 ``doc`` into the internal shape in place.  False
    (with diagnostics) when it cannot be."""
    doc.format = 2
    lowering = _Lowering(doc, bag)
    if isinstance(doc.data, CommentedMap):
        lowering.document(doc.data)
    return lowering.ok




def _format_1_ref(name: str) -> str | None:
    """The format 2 spelling of a format 1 colour reference (any name under
    `palette.` or `config.`), or ``None``."""
    parts = name.split(".")
    if parts[0] == "palette":
        return f"color.{parts[1]}" if len(parts) == 2 else "color.<name>"
    if parts[0] != "config":
        return None
    if len(parts) == 3 and parts[1] == "colors":
        return f"color.{parts[2]}"
    if name == "config.accent_color":
        return "color.accent"
    if name == "config.data_color":
        return "color.data"
    return "color.<role>"


def _anchor(position: Any) -> None:
    if isinstance(position, CommentedMap) and position.get("anchor") in COMPASS:
        position["anchor"] = COMPASS[position["anchor"]]




def _open_ternary(placeholder: Placeholder) -> bool:
    """``{a ? b : c}``: the expression stopped at a ternary's ':'."""
    if placeholder.spec is None:
        return False
    try:
        tokens = tokenize(placeholder.expr)
    except ExprError:
        return False
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.kind == "op" and token.text == "?" and depth == 0:
            return True
    return False



def _template_of(raw: str) -> Template | None:
    try:
        return parse_template(raw)
    except TemplateError:
        return None


def _normalise(expr: str) -> str:
    try:
        return " ".join(t.text for t in tokenize(expr))
    except ExprError:
        return expr.strip()
