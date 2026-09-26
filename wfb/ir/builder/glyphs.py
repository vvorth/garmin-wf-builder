"""Fonts, icons and the text decorations shared by `text` elements and
pattern text parts: `outline:`, `curve:`, `if_unavailable:`, icon names and
glyphs, and the per-`shape:`/`style:` foreign-key check."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Final, Literal

from ... import icons
from ...diagnostics import Span

from ..model import Curve, Element, MAX_OUTLINE_WIDTH, Outline
from .absence import AbsenceChecks

#: Sentinels for `Builder._resolve_choice_icon_override`'s result: "no
#: `icon:`/`glyph:` override declared" and "declared, invalid, already
#: reported".  Not `None`, which is itself a legitimate answer
#: (`icon: none`, an explicit "no icon").


class _IconOverride(Enum):
    NONE = "no override"
    ERROR = "error"


_NO_ICON_OVERRIDE: Final = _IconOverride.NONE
_ICON_OVERRIDE_ERROR: Final = _IconOverride.ERROR

#: Which key each `curve:` `style:` reads: only `radial` has a circle for
#: `radius:`/`direction:` to describe.  The schema still parses both under
#: `angled` so `_check_curve_keys` can name the actual mistake.
CURVE_STYLE_KEYS = {
    "angled": frozenset(),
    "radial": frozenset({"radius", "direction"}),
}
_ALL_CURVE_STYLE_KEYS = frozenset().union(*CURVE_STYLE_KEYS.values())

#: The note on an icon size given in a unit other than `px`/`%r`.
ICON_SIZE_NOTE = ("an icon's font is baked once, before layout runs, so its size "
                  "cannot depend on a parent box (%) or an element's own font (pt)")


class GlyphHelpers(AbsenceChecks):
    """Text, font and icon helpers shared across element kinds."""

    def check_foreign_keys(
        self, node: dict[str, Any], chosen: str, table: dict[str, frozenset[str]],
        all_keys: frozenset[str], *, code: str, disc: str,
        prefix: str = "", qualifier: str = "", suffix: str = "",
        empty_label: str = "(no geometry keys)",
        extra_notes: Callable[[str], list[str]] | None = None,
    ) -> bool:
        """Reject a key from another row of `table` that `chosen`'s own row
        does not read -- the shared "key not used by this X" sweep
        `wfb.kinds.shape._check_shape_keys`, `_check_hand_part_keys` and
        `wfb.kinds.graph._check_graph_style_keys` each specialise, for `disc`
        (the discriminator word: `shape`/`style`) in `'{disc}: {chosen}'`.

        `prefix`/`qualifier`/`suffix` build the message around that quoted
        phrase (``f"{prefix}{key!r} is not used by {qualifier}'{disc}:
        {chosen}'{suffix}"``) so each caller keeps its own exact wording;
        `extra_notes(key)` appends any further, caller-specific notes (an
        alignment or an arc-centring reason) after the two standard ones.
        Returns whether every key present belonged to `chosen`'s own row.
        """
        ok = True
        for key in sorted(all_keys - table[chosen]):
            if key not in node:
                continue
            owners = sorted(s for s, keys in table.items() if key in keys)
            notes = [
                f"'{disc}: {chosen}' reads: "
                + (", ".join(sorted(table[chosen])) or empty_label),
                f"{key!r} belongs to " + " and ".join(f"'{disc}: {s}'" for s in owners),
            ]
            if extra_notes is not None:
                notes.extend(extra_notes(key))
            self.bag.error(
                code,
                f"{prefix}{key!r} is not used by {qualifier}'{disc}: {chosen}'{suffix}",
                self.doc.span(node, key) or self.doc.span(node),
                notes=notes,
            )
            ok = False
        return ok


    def build_outline(
        self, node: dict[str, Any], key: str, label: str, *, element: Element | None = None,
    ) -> Outline | None:
        """`outline:` (plan 15) on a `text` element, or -- with
        `element=None` -- on a pattern's `shape: text` part: the stamped ring
        research 14 measured, drawn N times at small pixel offsets in
        `outline.color`, then once more, unshifted, in the fill colour.

        Two spellings collapse to one `Outline` (D7): a bare colour
        expression (`width: 2` implied) or an explicit `{color, width}`
        mapping.  `outline.color` goes through the same `color_expression`
        `color:` uses (D8).  `width` is capped at `MAX_OUTLINE_WIDTH` with a
        build error rather than a schema `maximum`, so the message can cite
        the evidence the cap rests on (D6).  `label` leads the width-cap
        error (the element id, or the part's `part_where`).

        **Absence.** A `text` element (`element` given) gets its own
        `check_other_absence` here.  A pattern part does not: a pattern
        polices absence once for the whole element over
        `PatternElement.colors` (`wfb.kinds.pattern._check_pattern_absence`),
        which the caller folds `outline.color` into -- checking here too
        would double-report the same source.
        """
        raw = node.get(key)
        if raw is None or raw == "none":
            return None
        span = self.doc.span(node, key)
        if isinstance(raw, dict):
            color = self.color_expression(raw, "color")
            color_span = self.doc.span(raw, "color") or span
            width = raw.get("width", 2)
            width_span = self.doc.span(raw, "width") or span
        else:
            color = self.color_expression(node, key)
            color_span = span
            width = 2
            width_span = span
        if color is None:
            return None
        if width > MAX_OUTLINE_WIDTH:
            self.bag.error(
                "text-outline",
                f"{label}: 'outline: width: {width}' is more than "
                f"{MAX_OUTLINE_WIDTH}px",
                width_span,
                notes=[
                    "every offset set research 14 measured stops at "
                    f"{MAX_OUTLINE_WIDTH}px -- a wider ring was never evidenced "
                    "(docs/research/14-stamped-ring-text.md §1)",
                    "the ring/solid pixel ratio keeps climbing past this width "
                    "with no measurement to say it still reads as an outline "
                    "rather than a second, blockier glyph (§4.1)",
                ],
            )
            return None
        if element is not None:
            self.check_other_absence(node, element, "outline.color", color, span=color_span)
        return Outline(color=color, width=width)

    def _check_curve_keys(self, node: dict[str, Any], style: str) -> None:
        """Reject a `curve:` key the chosen `style:` does not read -- the same
        `wfb.kinds.shape._check_shape_keys` precedent (`radius:`/`direction:`
        only mean something with a circle to describe, and `style: angled`
        has none).
        """
        if style not in CURVE_STYLE_KEYS:
            return  # the schema has already rejected an unknown style
        self.check_foreign_keys(
            node, style, CURVE_STYLE_KEYS, _ALL_CURVE_STYLE_KEYS,
            code="text-curve", disc="style", empty_label="(nothing)",
            extra_notes=lambda key: (
                ["an angled line has no circle for it to describe -- "
                 "'radius:'/'direction:' only mean something with 'style: radial'"]
                if style == "angled" else []
            ),
        )

    def is_vector_font(self, font: str, is_custom: bool) -> bool:
        """Whether a resolved `(font, is_custom)` reference names a `face:`
        (vector) font.  Safe to call on any resolved reference:
        `_font_reference` only returns a custom name already in `self.fonts`,
        and an unresolved one keeps the system-font default."""
        return is_custom and self.fonts[font].is_vector

    @staticmethod
    def font_kind_note(font: str, is_custom: bool) -> str:
        """What kind of (non-vector) font a `text` element's `font:` resolved
        to -- the extra note `build_curve`/`check_if_unavailable` add for
        a `text` element."""
        if is_custom:
            return f"'font: font.{font}' is a baked bitmap font, declared with 'source:'"
        return f"'font: {font}' is one of the platform's fixed system fonts"

    def build_curve(
        self, node: dict[str, Any], label: str, *, vertical_align: str, font_ok: bool,
        font_is_vector: bool, font_note: str | None = None,
    ) -> Curve | None:
        """`curve:` (plan 11) on a `text` element or a pattern's `shape: text`
        part: bends the text along a line (`style: angled`) or around a
        circle (`style: radial`).  `label` leads every message (the element
        id, or the part's `part_where`).

        `Dc.drawAngledText`/`drawRadialText` refuse a resource font, so
        `font:` must name a `face:` font -- checked only when `font_ok`: a
        font reference that itself failed already has its own error (the
        `NamedRegistry` cascade discipline).  `font_note` is the extra
        "what this font is" note a `text` element's message carries.

        On a pattern part the angle is authored in the template's own local
        frame; a radial pattern's per-copy rotation composes with it
        downstream (`wfb.kinds.pattern._pattern_part_ink`, `wfb.kinds.
        pattern._emit_pattern_text_angle_expr`), so twelve hour numerals
        share one authored angle.
        """
        raw = node["curve"]
        span = self.doc.span(node, "curve")
        style = raw["style"]
        self._check_curve_keys(raw, style)
        angle = self.angle(raw, "angle")
        if angle is None:
            return None
        radius = self.length(raw, "radius") if style == "radial" else None
        direction = str(raw.get("direction", "clockwise")) if style == "radial" else None
        if font_ok and not font_is_vector:
            self.bag.error(
                "text-curve",
                f"{label}: 'curve:' needs a 'face:' (vector) font",
                span,
                notes=[
                    "\"These APIs only support scalable fonts and do not support "
                    "custom fonts loaded as resources\" ($CIQ_SDK/doc/docs/"
                    "Core_Topics/Graphics.html §Scalable Fonts)",
                    *([font_note] if font_note is not None else []),
                    "declare this font with 'face:' instead of 'source:', or point "
                    "'font:' at one that already does",
                ],
            )
        if vertical_align == "bottom" and style == "angled":
            self.bag.error(
                "text-curve",
                f"{label}: 'vertical_align: bottom' is not accepted under "
                "'curve: {style: angled}'",
                self.doc.span(node, "vertical_align") or span,
                notes=[
                    "an upright text's 'bottom' is implemented by subtracting the "
                    "font's own height from the anchor in screen space -- once the "
                    "baseline is rotated that subtraction no longer points along "
                    "the text's own vertical axis, so the ink would land somewhere "
                    "this compiler cannot predict",
                    "use 'top' or 'center' instead ('curve: {style: radial}' "
                    "accepts all three)",
                ],
            )
        return Curve(style=style, angle=angle, radius=radius, direction=direction)

    def check_if_unavailable(
        self, node: dict[str, Any], label: str, font_is_vector: bool, font_note: str | None = None,
    ) -> None:
        """`if_unavailable:` on a `text` element or a pattern's `shape: text`
        part -- only meaningful when the font is a `face:` (vector) font:
        nothing about a baked or system font can ever be unavailable, so
        accepting it would promise a check that never runs (the same
        reasoning `_build_baked_font` applies to the key on a `fonts:` entry).
        Callers only reach this once the font reference itself resolved.
        """
        if font_is_vector:
            return
        self.bag.error(
            "text-curve",
            f"{label}: 'if_unavailable:' is not accepted here",
            self.doc.span(node, "if_unavailable"),
            notes=[
                "'if_unavailable:' governs a device-resident 'face:' font "
                "failing to publish a face on some target device -- nothing "
                "about a baked or system font can ever be unavailable",
                *([font_note] if font_note is not None else []),
                "drop 'if_unavailable:', or point 'font:' at a 'face:' font",
            ],
        )

    def resolve_icon_name(self, name: str, span: Span | None) -> str | None:
        """A catalogue name -> its codepoint, or `None` plus a reported error.

        The shared "unknown icon" diagnostic: used by `wfb.kinds.icon.IconKind.build`'s
        own inline check and by a `complication_slot` choice's `icon:` override
        (`_resolve_choice_icon_override`), so both report the exact same
        message rather than a second, slightly-different one for what is
        the same mistake either place it is made.
        """
        codepoint = icons.resolve_codepoint(name)
        if codepoint is None:
            self.bag.error(
                "icon",
                f"unknown icon {name!r}",
                span,
                notes=[
                    "the catalogue has: " + ", ".join(icons.names()),
                    "for a glyph the catalogue does not name, write "
                    "'glyph: \"U+XXXX\"' instead -- see wfb/assets/icons/README.md",
                ],
            )
        return codepoint

    def resolve_icon_glyph(self, raw: str, span: Span | None) -> str | None:
        """`"U+F0BC"` -> the character, or `None` plus a reported error.

        The shared `glyph:` diagnostics: used by `wfb.kinds.icon._build_glyph_icon`'s
        own inline checks and by a `complication_slot` choice's `glyph:`
        override (`_resolve_choice_icon_override`), which needs the
        identical "not that notation" / "not in the font" messages, not a
        second copy of them.
        The "this glyph is already a catalogue name" note is a `bag.note`,
        not an error, so it does not affect the caller's success/failure
        return either way.
        """
        character = icons.parse_codepoint(raw)
        if character is None:
            self.bag.error(
                "icon",
                f"glyph must be a codepoint written 'U+XXXX', not {raw!r}",
                span,
                notes=["e.g. glyph: \"U+F0BC\" -- 1 to 6 hex digits, case-insensitive",
                       "to use a name from the built-in catalogue, write 'icon:' instead"],
            )
            return None
        if not icons.font_has(character):
            self.bag.error(
                "icon",
                f"the icon font has no glyph at {raw.upper()}",
                span,
                notes=[
                    "checked against the icon font's own character map, the same "
                    "way a custom text font's coverage is checked",
                    "https://www.nerdfonts.com/cheat-sheet lists the codepoints this "
                    "font actually carries",
                ],
            )
            return None
        named = icons.name_for_codepoint(character)
        if named is not None:
            self.bag.note(
                "icon",
                f"glyph {raw.upper()} is in the catalogue as {named!r} -- "
                f"'icon: {named}' says the same thing and survives a font update",
                span,
            )
        return character

    def _resolve_choice_icon_override(
        self, item: dict[str, Any], what: str, fallback_span: Span | None,
    ) -> "icons.SlotIcon | None | Literal[_IconOverride.NONE, _IconOverride.ERROR]":
        """A `config: data:` choice's own `icon:`/`glyph:`, if it declares
        one.

        Returns `_NO_ICON_OVERRIDE` when the choice names neither key (fall
        back to `wfb.icons.COMPLICATION_ICON`), `_ICON_OVERRIDE_ERROR` when
        one was named and did not resolve (already reported; the caller
        rejects the whole slot the same way any other bad choice does),
        `None` for an explicit `icon: none` (remove any catalogue default),
        or a real `icons.SlotIcon`.  Reuses `resolve_icon_name`/
        `resolve_icon_glyph` -- the exact validation (and messages) a plain
        `icon` element's own `icon:`/`glyph:` get -- rather than a second,
        parallel set of diagnostics for what is the same two keys.
        """
        has_icon = "icon" in item
        has_glyph = "glyph" in item
        if not has_icon and not has_glyph:
            return _NO_ICON_OVERRIDE
        if has_icon and has_glyph:
            self.bag.error(
                "config",
                f"{what}: 'icon:' and 'glyph:' are mutually exclusive",
                fallback_span,
                notes=["'icon:' names a catalogue entry; 'glyph:' is any codepoint "
                       "in the icon font -- pick one"],
            )
            return _ICON_OVERRIDE_ERROR
        if has_icon:
            raw_icon = item["icon"]
            span = self.doc.span(item, "icon") or fallback_span
            if raw_icon == "none":
                return None
            if not isinstance(raw_icon, str):
                self.bag.error(
                    "config", f"{what}.icon: expected a string, got {raw_icon!r}", span)
                return _ICON_OVERRIDE_ERROR
            codepoint = self.resolve_icon_name(raw_icon, span)
            if codepoint is None:
                return _ICON_OVERRIDE_ERROR
            return icons.SlotIcon(raw_icon, codepoint)
        raw_glyph = str(item["glyph"])
        span = self.doc.span(item, "glyph") or fallback_span
        character = self.resolve_icon_glyph(raw_glyph, span)
        if character is None:
            return _ICON_OVERRIDE_ERROR
        return icons.SlotIcon(icons.codepoint_key(character), character)
