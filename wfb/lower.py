"""Lower a format 2 document into the shape the rest of the compiler reads.

Format 2 (``docs/guide/format-2-migration.md``) is a front-end change: its
names and grouping are the author's, and the IR builder still reads the
internal shape it always has.  This pass rewrites a schema-valid format 2
document into that shape, in place, before :mod:`wfb.desugar` runs:

* the top level ungrouped (``build:``, ``defaults:``, ``resources:``,
  ``theme:``), ``config:``'s ``slots:``, ``scheme:`` and colour references;
* each element's own keys (``absent:``, ``align:``, ``unsupported:``,
  ``sleep_update:``) and each kind's (``type: rectangle`` is a ``shape``,
  a ``text:`` template becomes ``value:`` + ``format:``, ...);
* every ``color.<name>`` into the reference the builder binds: a scheme role
  is ``config.colors.<name>``, an axis role ``config.accent_color`` or
  ``config.data_color``, a swatch ``palette.<name>``.  Expressions are
  rewritten token by token (:func:`wfb.expr.tokenize`).

Each moved key keeps the author's source position, and each renamed or
rewritten one records an :class:`~wfb.yamlsrc.Origin` naming the key the
author wrote, so a diagnostic points at, names and quotes the author's own
text.  The rewritten document is what the same design said in format 1,
which is why moving a face to format 2 (``wfb migrate``) changed no
generated project.

The format 2 semantics the schema cannot check are checked here: a colour
name that is unknown, ambiguous, or a role where a build-time colour is
needed; a malformed template; and several placeholders where only one
reading is drawn.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .diagnostics import Bag, Span
from .expr import ExprError, tokenize
from .template import (
    Placeholder, TemplateError, Template, Unit, parse_template, segments, to_value_format,
)
from .yamlsrc import Origin, YamlDocument

#: A compass alias -> the anchor name it stands for (`align:` and `anchor:`).
COMPASS = {"N": "top", "NE": "top_right", "E": "right", "SE": "bottom_right",
           "S": "bottom", "SW": "bottom_left", "W": "left", "NW": "top_left"}

_V = ("top", "bottom")

_PRIMITIVES = ("rectangle", "circle", "line", "arc", "ellipse", "polygon")
_U_PLUS = re.compile(r"^[Uu]\+[0-9A-Fa-f]{1,6}$")


@dataclass
class _Colors:
    """What a ``color.<name>`` resolves to."""

    swatches: set[str] = field(default_factory=set)
    #: role -> the internal reference it lowers to
    roles: dict[str, str] = field(default_factory=dict)

    def names(self) -> list[str]:
        return sorted(self.swatches | set(self.roles))


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

    def rekey(self, node: CommentedMap, old: str, new: str, *values: Any,
              author: str | None = None) -> None:
        """Rename ``node[old]`` to ``new`` in place (optionally with a new
        value), keeping its position in the mapping and its source span, and
        recording that the author wrote ``author`` (default ``old``)."""
        keys = list(node)
        index = keys.index(old)
        value = values[0] if values else node[old]
        pos = _lc(node, old)
        del node[old]
        node.insert(index, new, value)
        if pos is not None:
            _set_lc(node, new, pos)
        self.doc.set_origin(node, new, Origin(author or old))

    def add(self, node: CommentedMap, key: str, value: Any, like: str, *,
            author: str | None = None, after: str | None = None) -> None:
        """Add ``node[key] = value``, positioned where ``node[like]`` is in
        the source, and recorded as the author's ``author`` (default
        ``like``)."""
        pos = _lc(node, like)
        if after is not None and after in node:
            node.insert(list(node).index(after) + 1, key, value)
        else:
            node[key] = value
        if pos is not None:
            _set_lc(node, key, list(pos))
        self.doc.set_origin(node, key, Origin(author or like))

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
                        self.colors.roles[role] = f"config.colors.{role}"
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
                self.colors.roles[role] = f"config.{axis}"
        for name in sorted(self.colors.swatches & set(self.colors.roles)):
            node, key = declared[name]
            for span in (self.span(palette, name, of="key"), self.span(node, key, of="key")):
                self.error("color",
                           f"'color.{name}' is both a palette swatch and a colour role",
                           span,
                           "format 2 has one colour namespace: a role is looked up "
                           "first, then a swatch, and a name that is both is refused "
                           "rather than shadowed",
                           "rename the palette swatch or the role")

    def color_ref(self, name: str) -> str | None:
        if name in self.colors.roles:
            return self.colors.roles[name]
        if name in self.colors.swatches:
            return f"palette.{name}"
        return None

    def unknown_color(self, name: str, span: Span | None) -> None:
        near = difflib.get_close_matches(name, self.colors.names(), n=3, cutoff=0.5)
        notes = ([f"did you mean {', '.join(f'color.{n}' for n in near)}?"] if near else
                 [f"declared colours: {', '.join(f'color.{n}' for n in self.colors.names())}"
                  if self.colors.names() else
                  "declare it under 'resources: palette:', or as a 'theme: schemes:' role"])
        self.error("color", f"unknown colour 'color.{name}'", span, *notes)

    def lower_refs(self, node: Any, key: Any, *, author: str | None = None,
                   swatch_only: bool = False, text: str | None = None,
                   ) -> tuple[str, tuple[tuple[int, int], ...]] | None:
        """``node[key]`` (or ``text``) with every ``color.<name>`` rewritten,
        plus the offset map from the rewritten text back to the author's.
        ``None`` (reported) for an unknown or misplaced colour."""
        raw = node[key] if text is None else text
        if not isinstance(raw, str):
            return str(raw), ()
        try:
            tokens = tokenize(raw)
        except ExprError:
            return raw, ()  # the builder reports the syntax error
        out: list[str] = []
        offsets: list[tuple[int, int]] = []
        pos = 0
        length = 0
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
            new = self.color_ref(name)
            span = self.span(node, key)
            if new is None:
                self.unknown_color(name, span)
                ok = False
                continue
            if swatch_only and not new.startswith("palette."):
                self.error("color",
                           f"'color.{name}' is a colour role, but {author or key!r} needs a "
                           "build-time colour",
                           span,
                           "a role follows the active style's scheme or the wearer's "
                           "pick, so it has no single value when the face is built",
                           "name a palette swatch, or write the colour as '#RRGGBB'")
                ok = False
                continue
            out.append(raw[pos:token.offset])
            length += token.offset - pos
            offsets.append((length, token.offset))
            out.append(new)
            length += len(new)
            pos = token.offset + len(token.text)
            offsets.append((length, pos))
        if not ok:
            return None
        return "".join(out) + raw[pos:], tuple(offsets)

    def expr_key(self, node: CommentedMap, key: str, *, author: str | None = None) -> None:
        """Lower the colour references in ``node[key]`` in place."""
        if key not in node or not isinstance(node[key], str):
            return
        lowered = self.lower_refs(node, key, author=author)
        if lowered is None:
            return
        text, offsets = lowered
        original = node[key]
        if text != original:
            node[key] = text
        self.doc.set_origin(node, key, Origin(author or key, str(original), offsets))

    def swatch(self, node: Any, key: Any, author: str) -> None:
        """A colour that must be a build-time literal: a hex literal as it
        is, or ``color.<swatch>`` -> ``palette.<swatch>``."""
        value = node[key]
        if not isinstance(value, str) or not value.startswith("color."):
            return
        lowered = self.lower_refs(node, key, author=author, swatch_only=True)
        if lowered is not None:
            node[key] = lowered[0]

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
        build = data.get("build")
        if isinstance(build, CommentedMap):
            self.lift(data, "build", build, [("targets", "targets")])
        defaults = data.get("defaults")
        if isinstance(defaults, CommentedMap):
            if "aod" in defaults:
                # `defaults: {aod:}` is format 1's `aod: {default:}`.
                aod = data.get("aod")
                if not isinstance(aod, CommentedMap):
                    aod = CommentedMap()
                    data.insert(list(data).index("defaults") + 1, "aod", aod)
                    _set_lc(data, "aod", _lc(data, "defaults"))
                aod.insert(0, "default", defaults["aod"])
                _set_lc(aod, "default", _lc(defaults, "aod"))
                self.doc.set_origin(aod, "default", Origin("defaults.aod"))
                del defaults["aod"]
            self.lift(data, "defaults", defaults, [("antialias", "antialias"),
                                                   ("min_1px", "min_1px")])
        resources = data.get("resources")
        if isinstance(resources, CommentedMap):
            fonts = resources.get("fonts")
            if isinstance(fonts, CommentedMap):
                for font in fonts.values():
                    if isinstance(font, CommentedMap) and "unsupported" in font:
                        self.rekey(font, "unsupported", "if_unavailable", author="unsupported")
            hand_sets = resources.get("hand_sets")
            if isinstance(hand_sets, CommentedMap):
                for hand_set in hand_sets.values():
                    if not isinstance(hand_set, CommentedMap):
                        continue
                    for hand in hand_set.values():
                        if isinstance(hand, CommentedMap):
                            self.expr_key(hand, "color")
                            self.parts(hand.get("parts"))
            self.lift(data, "resources", resources,
                      [("fonts", "fonts"), ("palette", "palette"), ("hand_sets", "hands")])
        theme = data.get("theme")
        if isinstance(theme, CommentedMap):
            schemes = theme.get("schemes")
            if isinstance(schemes, CommentedMap):
                for scheme in schemes.values():
                    colors = scheme.get("colors") if isinstance(scheme, dict) else None
                    if isinstance(colors, CommentedMap):
                        for role in list(colors):
                            self.swatch(colors, role, f"theme.schemes: {role}")
            self.lift(data, "theme", theme, [("schemes", "color_scheme")])
        config = data.get("config")
        if isinstance(config, CommentedMap):
            self.config(config)

    def lift(self, data: CommentedMap, group_key: str, group: CommentedMap,
             members: list[tuple[str, str]]) -> None:
        """Move ``group``'s members up to the top level under their internal
        names, where ``group`` was."""
        index = list(data).index(group_key)
        group_pos = _lc(data, group_key)
        for new_index, (old, new) in enumerate([(o, n) for o, n in members if o in group]):
            value = group[old]
            pos = _lc(group, old)
            data.insert(index + new_index, new, value)
            _set_lc(data, new, list(pos) if pos is not None else group_pos)
            self.doc.set_origin(data, new, Origin(f"{group_key}.{old}"))
        if not [k for k in group if k not in dict(members)]:
            del data[group_key]

    def config(self, config: CommentedMap) -> None:
        for axis in ("accent_color", "data_color"):
            body = config.get(axis)
            if not isinstance(body, CommentedMap):
                continue
            if "role" in body:
                del body["role"]
            if "default" in body:
                self.swatch(body, "default", f"config.{axis}.default")
            choices = body.get("choices")
            if isinstance(choices, CommentedSeq):
                for index, choice in enumerate(choices):
                    if isinstance(choice, str):
                        self.swatch(choices, index, f"config.{axis}.choices")
        style = config.get("style")
        if isinstance(style, CommentedMap) and isinstance(style.get("choices"), CommentedMap):
            for entry in style["choices"].values():
                if isinstance(entry, CommentedMap) and "scheme" in entry:
                    self.rekey(entry, "scheme", "colors", author="scheme")
        if "slots" in config:
            self.rekey(config, "slots", "data", author="slots")
            slots = config["data"]
            if isinstance(slots, CommentedMap):
                for slot in slots.values():
                    if isinstance(slot, CommentedMap):
                        self.slot(slot)

    def slot(self, slot: CommentedMap) -> None:
        if isinstance(slot.get("default"), str):
            slot["default"] = f"complication.{slot['default']}"
        choices = slot.get("choices")
        if not isinstance(choices, CommentedSeq):
            return
        for index, choice in enumerate(choices):
            if isinstance(choice, str):
                choices[index] = f"complication.{choice}"
            elif isinstance(choice, CommentedMap):
                if isinstance(choice.get("type"), str):
                    choice["type"] = f"complication.{choice['type']}"
                icon = choice.get("icon")
                if isinstance(icon, str) and _U_PLUS.match(icon):
                    self.rekey(choice, "icon", "glyph", author="icon")

    # -- elements ------------------------------------------------------------

    def element(self, node: CommentedMap) -> None:
        if id(node) in self.lowered:
            return
        self.lowered.add(id(node))
        kind = node.get("type")
        self.common(node, kind)
        if kind in _PRIMITIVES:
            shape = "rounded_rectangle" if kind == "rectangle" and "corner_radius" in node \
                else kind
            node["type"] = "shape"
            self.add(node, "shape", shape, "type", after="type")
        elif kind == "text":
            self.text(node, several=True)
        elif kind == "gauge":
            node["type"] = "progress"
            if isinstance(node.get("slot"), str):
                node["slot"] = f"config.data.{node['slot']}"
                self.doc.set_origin(node, "slot", Origin("slot"))
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
        elif kind == "hands" and "set" in node:
            self.rekey(node, "set", "hands", author="set")
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
        self.absent(node, kind)
        self.aod(node)

    def common(self, node: CommentedMap, kind: Any) -> None:
        if "sleep_update" in node:
            # An explicit `false` is kept: `sleep_update:` is inherited from
            # an enclosing group, and `false` is how a member opts out.
            modes = CommentedSeq(["active", "low_power"] if node["sleep_update"] is True
                                 else ["active"])
            self.rekey(node, "sleep_update", "modes", modes, author="sleep_update")
        if "unsupported" in node:
            self.rekey(node, "unsupported", "if_unavailable", author="unsupported")
        self.align(node)
        for key in ("color", "track_color", "visible"):
            self.expr_key(node, key)
        if "outline" in node:
            self.outline(node)
        for key in ("at", "to"):
            _anchor(node.get(key))
        points = node.get("points")
        if isinstance(points, list):
            for point in points:
                _anchor(point)

    def align(self, node: CommentedMap) -> None:
        value = node.get("align")
        if not isinstance(value, str):
            return
        value = COMPASS.get(value, value)
        vertical = next((v for v in _V if value == v or value.startswith(v + "_")), None)
        if vertical is None:
            node["align"] = value
            return
        horizontal = value[len(vertical) + 1:] or None
        if horizontal is None:
            self.rekey(node, "align", "vertical_align", vertical, author="align")
        else:
            node["align"] = horizontal
            self.add(node, "vertical_align", vertical, "align", after="align")

    def outline(self, node: CommentedMap) -> None:
        outline = node["outline"]
        if isinstance(outline, CommentedMap):
            self.expr_key(outline, "color", author="outline.color")
        elif outline != "none":
            self.expr_key(node, "outline")

    def text(self, node: CommentedMap, *, several: bool = False) -> None:
        """A ``text:`` template: literal text, or ``value:`` + ``format:``.
        With ``several``, a template with more than one placeholder is
        accepted: the first reading becomes ``value:`` + ``format:`` and each
        later one an entry of ``more_values:``, each with the literal text
        after it (`wfb.template.segments`)."""
        raw = node.get("text")
        if not isinstance(raw, str):
            return
        template = self.template(node, "text", several=several)
        if template is None:
            return
        placeholder = template.placeholder
        if placeholder is None:
            node["text"] = template.literal
            self.doc.set_origin(node, "text", Origin("text", raw))
            return
        lowered = [self.segment(node, raw, segment) for segment in segments(template)]
        if any(found is None for found in lowered):
            return
        keys = list(node)
        index = keys.index("text")
        pos = _lc(node, "text")
        del node["text"]
        (value, origin, first_fmt), *more = (found for found in lowered if found is not None)
        node.insert(index, "value", value)
        if pos is not None:
            _set_lc(node, "value", list(pos))
        self.doc.set_origin(node, "value", origin)
        if first_fmt is not None:
            node.insert(index + 1, "format", first_fmt)
            if pos is not None:
                _set_lc(node, "format", list(pos))
            self.doc.set_origin(node, "format", Origin("text", raw))
        if not more:
            return
        entries = CommentedSeq()
        for value, origin, fmt in more:
            entry = CommentedMap()
            entry["value"] = value
            entry["format"] = fmt if fmt is not None else "{}"
            for key in ("value", "format"):
                if pos is not None:
                    _set_lc(entry, key, list(pos))
            self.doc.set_origin(entry, "value", origin)
            self.doc.set_origin(entry, "format", Origin("text", raw))
            entries.append(entry)
        node.insert(index + (1 if first_fmt is None else 2), "more_values", entries)
        if pos is not None:
            _set_lc(node, "more_values", list(pos))
        self.doc.set_origin(node, "more_values", Origin("text", raw))

    def segment(self, node: CommentedMap, raw: str, template: Template,
                ) -> tuple[str, Origin, str | None] | None:
        """One reading of a ``text:`` template (a single-placeholder
        `Template` cut from it): its lowered expression, the `Origin` that
        points a diagnostic into the author's template, and its internal
        ``format:`` (``None`` for the bare reading)."""
        placeholder = template.placeholder
        assert placeholder is not None
        try:
            expr, fmt = to_value_format(template)
        except TemplateError as exc:
            self.error("format", f"text: {exc.message}", self.span(node, "text"))
            return None
        assert expr is not None
        expr, strip = _strip_template_parens(expr)
        lowered = self.lower_refs(node, "text", text=expr)
        if lowered is None:
            return None
        value, offsets = lowered
        base = placeholder.offset + _leading_space(raw, placeholder.offset) + strip
        shifted = tuple((r, a + base) for r, a in offsets) or ((0, base),)
        if offsets and offsets[0][0] != 0:
            shifted = ((0, base),) + shifted
        return value, Origin("text", raw, shifted, quote=placeholder.expr), fmt

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
            expr = icon.get("for")
            self.rekey(node, "icon", "icon_for", expr, author="icon")
            if isinstance(expr, str):
                lowered = self.lower_refs(node, "icon_for", author="icon.for")
                if lowered is not None:
                    node["icon_for"] = lowered[0]
                    self.doc.set_origin(node, "icon_for",
                                        Origin("icon.for", expr, lowered[1]))
        elif isinstance(icon, str) and _U_PLUS.match(icon):
            self.rekey(node, "icon", "glyph", author="icon")

    def data(self, node: CommentedMap) -> None:
        node["type"] = "complication_slot"
        if isinstance(node.get("slot"), str):
            node["slot"] = f"config.data.{node['slot']}"
            self.doc.set_origin(node, "slot", Origin("slot"))
        icon = node.get("icon")
        if isinstance(icon, CommentedMap):
            index = list(node).index("icon")
            node_pos = _lc(node, "icon")
            del node["icon"]
            for offset, key in enumerate(k for k in ("size", "position", "gap", "color")
                                         if k in icon):
                node.insert(index + offset, f"icon_{key}", icon[key])
                pos = _lc(icon, key)
                _set_lc(node, f"icon_{key}", pos if pos is not None else node_pos)
                self.doc.set_origin(node, f"icon_{key}", Origin(f"icon.{key}"))
            self.expr_key(node, "icon_color", author="icon.color")

    def absent(self, node: CommentedMap, kind: Any) -> None:
        if "absent" not in node:
            return
        value = node["absent"]
        if value == "hide":
            self.rekey(node, "absent", "when_absent", author="absent")
        elif isinstance(value, CommentedMap) and "value" in value:
            self.rekey(node, "absent", "when_absent", "fallback", author="absent")
            self.add(node, "fallback", value["value"], "when_absent", author="absent.value",
                     after="when_absent")
            self.expr_key(node, "fallback", author="absent.value")
        elif isinstance(value, str):
            self.rekey(node, "absent", "when_absent", "placeholder", author="absent")
            self.add(node, "placeholder", value, "when_absent", author="absent",
                     after="when_absent")

    def aod(self, node: CommentedMap) -> None:
        aod = node.get("aod")
        if not isinstance(aod, CommentedMap):
            return
        for key in ("color", "track_color", "visible"):
            self.expr_key(aod, key, author=f"aod.{key}")
        if "outline" in aod:
            self.outline(aod)
        icon = aod.get("icon")
        if isinstance(icon, CommentedMap) and "color" in icon:
            self.rekey(aod, "icon", "icon_color", icon["color"], author="aod.icon.color")
            self.expr_key(aod, "icon_color", author="aod.icon.color")
        if isinstance(aod.get("text"), str):
            self.aod_text(node, aod)

    def aod_text(self, node: CommentedMap, aod: CommentedMap) -> None:
        if "more_values" in node:
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
        own_author = self.doc.origin(node, "value") if node.get("type") == "text" else None
        if placeholder is not None and placeholder.expr:
            expected = None
            if own_author is not None and own_author.text is not None:
                parsed = _placeholder_of(own_author.text)
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
        stripped = Template(tuple(Placeholder("x", p.spec, p.offset)
                                  if isinstance(p, Placeholder) else p
                                  for p in template.pieces))
        try:
            _, fmt = to_value_format(stripped)
        except TemplateError as exc:
            self.error("format", f"aod.text: {exc.message}", self.span(aod, "text"))
            return
        self.rekey(aod, "text", "format", fmt if fmt is not None else "{}", author="aod.text")

    def parts(self, parts: Any, *, pattern: bool = False) -> None:
        if not isinstance(parts, CommentedSeq):
            return
        for part in parts:
            if not isinstance(part, CommentedMap):
                continue
            if "type" in part:
                self.rekey(part, "type", "shape", author="type")
            self.align(part)
            if "unsupported" in part:
                self.rekey(part, "unsupported", "if_unavailable", author="unsupported")
            for key in ("color", "visible"):
                self.expr_key(part, key)
            if "outline" in part:
                self.outline(part)
            if pattern and part.get("shape") == "text":
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


def _set_lc(node: Any, key: Any, pos: Any) -> None:
    """Record ``node[key]``'s source position (a ruamel ``[line, col, line,
    col]``); a mapping this pass created has no position table until the
    first one."""
    if pos is None:
        return
    lc = getattr(node, "lc", None)
    if lc is None:
        return
    lc.add_kv_line_col(key, list(pos))


def _lc(node: Any, key: Any) -> list[int] | None:
    data = getattr(getattr(node, "lc", None), "data", None)
    if not isinstance(data, dict):
        return None
    pos = data.get(key)
    return list(pos) if pos is not None else None


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


def _strip_template_parens(expr: str) -> tuple[str, int]:
    """A ternary needs parentheses inside a placeholder; they are template
    syntax, not part of the expression.  Returns the expression and how many
    characters were dropped from its front."""
    text = expr.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return expr, 0
    depth = 0
    for index, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return expr, 0  # "(a) + (b)": the outer pair is not one group
    inner = text[1:-1]
    if not _top_level_colon(inner):
        return expr, 0
    return inner, 1


def _top_level_colon(expr: str) -> bool:
    try:
        tokens = tokenize(expr)
    except ExprError:
        return False
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.kind == "op" and token.text == ":" and depth == 0:
            return True
    return False


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


def _leading_space(raw: str, offset: int) -> int:
    return len(raw[offset:]) - len(raw[offset:].lstrip())


def _placeholder_of(template: str) -> Placeholder | None:
    try:
        return parse_template(template).placeholder
    except TemplateError:
        return None


def _normalise(expr: str) -> str:
    try:
        return " ".join(t.text for t in tokenize(expr))
    except ExprError:
        return expr.strip()
