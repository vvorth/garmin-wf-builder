"""The `fonts:` block: a baked font (a TTF/OTF rasterised to a BMFont
sheet at build time) or a vector `face:` (a device-resident scalable
font)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import units
from ...diagnostics import Span
from ...units import Length, UnitError

from ..model import FontSpec
from .visibility import VisibilityHelpers


class FontBlock(VisibilityHelpers):
    """Builds `fonts:` into its `NamedRegistry`."""

    def _build_fonts(self, raw: dict[str, Any]) -> None:
        base = self.doc.path.parent
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.fonts.declare(name, span)
            # The schema's `oneOf` guarantees exactly one of `source`/`face`.
            if "face" in spec:
                font = self._build_vector_font(name, spec, span)
            else:
                font = self._build_baked_font(name, spec, base, span)
            if font is None:
                self.fonts.reject(name)
                continue
            self.fonts[name] = font

    def _build_baked_font(
        self, name: str, spec: dict[str, Any], base: Path, span: Span | None,
    ) -> FontSpec | None:
        source = base / str(spec["source"])
        if not source.exists():
            self.bag.error(
                "font",
                f"font {name!r}: source file not found: {spec['source']}",
                self.doc.span(spec, "source"),
                notes=[f"resolved against the design file, to {source}"],
            )
            return None
        size = self._font_size(name, spec)
        if size is None:
            return None
        monospace = bool(spec.get("monospace", False))
        if "align" in spec and not monospace:
            self.bag.error(
                "font",
                f"font {name!r}: 'align' needs 'monospace: true'",
                self.doc.span(spec, "align"),
                notes=[
                    "align says where a glyph's ink sits inside its cell, and a "
                    "proportional font has no cell -- every glyph is exactly as "
                    "wide as it needs to be",
                    "add 'monospace: true', or drop 'align'",
                ],
            )
            return None
        if "if_unavailable" in spec:
            self.bag.error(
                "font",
                f"font {name!r}: 'if_unavailable:' is not accepted on a baked font",
                self.doc.span(spec, "if_unavailable"),
                notes=[
                    "'if_unavailable:' governs a device-resident 'face:' font "
                    "failing to publish a face -- a baked font is rasterised from "
                    "your own 'source:' at build time, so it is never unavailable "
                    "on any device",
                    "drop 'if_unavailable:', or switch this entry to 'face:' if "
                    "you meant a device-resident font",
                ],
            )
            return None
        return FontSpec(
            name=name,
            source=source,
            size=size,
            glyphs=spec.get("glyphs"),
            # No tree to inherit through: the face default applies directly.
            antialias=bool(spec.get("antialias", self.face_antialias)),
            span=span,
            monospace=monospace,
            align=str(spec.get("align", "center")),
        )

    #: `fonts.<name>` keys that only mean something while baking a sheet --
    #: rejected on a `face:` (vector) entry by `_build_vector_font`, each
    #: with its own "why" rather than a bare "unknown key" (the schema
    #: still parses all four there for exactly this reason, the same
    #: "text-antialias" precedent `wfb.kinds.text._reject_text_antialias` follows).
    _VECTOR_FONT_BAKING_KEYS = ("glyphs", "monospace", "align", "antialias")

    def _build_vector_font(self, name: str, spec: dict[str, Any], span: Span | None) -> FontSpec | None:
        """`fonts.<name>.face:` -- a device-resident scalable face (plan 11
        §2.1), resolved per device later (`wfb.availability.
        vector_font_face`); here only the author-facing shape is checked.
        """
        ok = True
        for key in self._VECTOR_FONT_BAKING_KEYS:
            if key not in spec:
                continue
            self.bag.error(
                "font",
                f"font {name!r}: {key!r} is not accepted on a 'face:' font",
                self.doc.span(spec, key),
                notes=[
                    f"{key!r} is a property of baking a bitmap sheet, and a "
                    "vector font has no sheet -- it is drawn straight from the "
                    "device's own resident face, at any size, with nothing "
                    "rasterised at build time",
                    "drop it, or switch this entry to 'source:' if you meant a "
                    "baked font",
                ],
            )
            ok = False
        size = self._font_size(name, spec)
        if not ok or size is None:
            return None
        raw_face = spec["face"]
        face = (raw_face,) if isinstance(raw_face, str) else tuple(raw_face)
        return FontSpec(
            name=name,
            size=size,
            span=span,
            face=face,
            if_unavailable=str(spec.get("if_unavailable", "error")),
        )

    def _font_size(self, name: str, spec: dict[str, Any]) -> Length | None:
        """`fonts.<name>.size`, as a `Length`.

        A bare number is rejected here, with the exact `%r`/`px` conversion
        named in the error, rather than accepted and silently reinterpreted:
        this stage of the compiler has no device knowledge at all (the
        module docstring: "nothing here knows a screen size"), so it cannot
        look up a target's minor radius and hand back a computed number --
        only the rule to apply by hand.
        """
        raw = spec["size"]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            self.bag.error(
                "font",
                f"font {name!r}: size must be a length such as '18%r' or "
                f"'12px', not a bare number ({raw!r})",
                self.doc.span(spec, "size"),
                notes=[
                    f"size: {raw!r} used to mean {raw!r}px on the smallest "
                    "target, scaled per device by the ratio of minor radii "
                    "-- the exact equivalent is (size / <smallest target's "
                    "minor radius, in px> * 100)%r, e.g. 68 on a 130px minor "
                    "radius (fenix8solar47mm, fr955) is 52.3076923077%r",
                    "for the same pixel count on every device instead -- "
                    "what 'scale: false' used to give you -- use 'px', "
                    f"e.g. '{raw!r}px'",
                ],
            )
            return None
        try:
            size = Length.parse(raw, what=f"font {name!r}: size")
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(spec, "size"))
            return None
        if size.unit not in units.SIZE_UNITS:
            self.bag.error(
                "font",
                f"font {name!r}: size must be px or %r, not {size.unit}",
                self.doc.span(spec, "size"),
                notes=[
                    "a font's sheet is rasterised before any element is placed, so its "
                    "size cannot depend on a parent box (%) or on a font (pt) -- there "
                    "is no box yet, and the font being sized is the one 'pt' would "
                    "measure against",
                    "use '%r' for a size that follows the screen, e.g. '18%r'",
                ],
            )
            return None
        if size.value <= 0:
            self.bag.error(
                "font", f"font {name!r}: size must be greater than zero",
                self.doc.span(spec, "size"),
            )
            return None
        return size
