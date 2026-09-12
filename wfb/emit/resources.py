"""Resource generation: fonts, strings, drawables, and the launcher icon.

Two things here are worth more than they look:

* **Font subsetting.**  The glyph set is derived from every format spec and
  literal string the design can render, so a large clock font carries eleven
  glyphs rather than a character set.  The ``filter`` attribute repeats the set
  so the resource compiler agrees with the sheet.
* **Launcher icons are generated per device at the size the device asks for**,
  read from ``compiler.json``.  Shipping one icon and letting the compiler scale
  it is the default failure mode and produces a warning on every build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

from .. import catalog, complications, formatting, icons, units
from ..devices import Device
from ..fonts import BakedFont, bake
from ..fonts.bmfont import write as write_font
from ..ir import (
    CONFIG_SYMBOL, ComplicationSlot, Face, FontSpec, IconElement, Text,
    config_data_ids, config_label_id, config_style_label_id,
)
from ..palette import Color

_XSD = "https://developer.garmin.com/downloads/connect-iq/resources.xsd"
_XMLNS = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


@dataclass
class ResourceBundle:
    """Everything written under one device's resource directory."""

    device_id: str
    directory: str
    files: dict[str, str] = field(default_factory=dict)  # relative path -> text
    fonts: dict[str, BakedFont] = field(default_factory=dict)
    images: dict[str, Image.Image] = field(default_factory=dict)


#: Every letter a localised device string (`Complication.shortLabel`/
#: `.longLabel`, or a `Complications.Unit` that comes back as a raw String
#: rather than the documented enum) could plausibly contain -- the same
#: "the full alphabet has to be present" reasoning `Type.DATE`'s glyph set
#: already uses for a weekday/month string chosen by the firmware, applied
#: here because neither string's content is knowable at build time either.
_COMPLICATION_TEXT_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "
)


def glyph_set(face: Face) -> dict[str, str]:
    """The characters each declared font must contain, derived from the design."""
    needed: dict[str, set[str]] = {name: set() for name in face.fonts}
    for element in face.walk():
        if isinstance(element, ComplicationSlot) and element.font_is_custom:
            # The wearer can point this slot at any of its declared choices,
            # and `Complication.value`'s concrete type genuinely varies by
            # choice (there is no per-choice `format:` to size against --
            # `Builder._build_complication_slot` forbids it) -- so the font
            # has to carry everything *any* choice could render, not one
            # choice's glyphs. See `wfb.layout.Resolver.
            # _complication_slot_widest`'s docstring for the same reasoning
            # applied to the overflow estimate.
            bucket = needed.setdefault(element.font, set())
            slot = face.config_data.get(element.slot)
            choices: tuple[str, ...] = ()
            if slot is not None:
                choices = (slot.default,) if slot.allow_any else slot.choices
            for name in choices:
                ctype = complications.TYPES.get(name)
                if ctype is None:
                    continue
                value_type = (catalog.Type.STRING if ctype.value_type == "string"
                             else catalog.Type.NUMBER)
                bucket |= formatting.glyphs("{}", None, value_type)
                if ctype.value_type == "float":
                    bucket |= set(".")
            if element.placeholder:
                bucket |= set(element.placeholder)
            if element.label != "none" or element.unit:
                # A label is always a localised device string; a unit can be
                # too (`Complications.Unit or Lang.String`) -- both unbounded.
                bucket |= set(_COMPLICATION_TEXT_ALPHABET)
            if element.unit:
                bucket |= set("".join(complications.UNIT_SUFFIX.values()))
            continue
        if not isinstance(element, Text) or not element.font_is_custom:
            continue
        bucket = needed.setdefault(element.font, set())
        if element.literal is not None:
            bucket |= set(element.literal)
            continue
        if element.value is None:
            continue
        source = catalog.get(element.value.sources[0]) if element.value.sources else None
        spec = element.format or "{}"
        bucket |= formatting.glyphs(spec, source, element.value.value.type, element.value.scale)
        if element.placeholder:
            bucket |= set(element.placeholder)
        if element.when_absent == "fallback" and element.fallback is not None:
            # 'fallback:' is drawn through the same format spec as the real
            # value (see Bug 1's _emit_text in wfb.emit.monkeyc) -- a literal
            # string fallback renders exactly as written, the same way
            # 'placeholder:' is handled above; anything else goes through the
            # same digit-set formatting.glyphs already adds for the value.
            fallback = element.fallback
            if fallback.value.type is catalog.Type.STRING and fallback.constant is not None:
                bucket |= set(str(fallback.constant))
            else:
                fallback_source = catalog.get(fallback.sources[0]) if fallback.sources else None
                bucket |= formatting.glyphs(spec, fallback_source, fallback.value.type,
                                            fallback.scale)
    out: dict[str, str] = {}
    for name, chars in needed.items():
        declared = face.fonts[name].glyphs
        out[name] = declared if declared is not None else "".join(sorted(chars))
    return out


def icon_font_specs(face: Face, device: Device) -> dict[str, FontSpec]:
    """One synthetic :class:`FontSpec` per distinct (declared size, glyph) pair.

    A bitmap font is rasterised at one size, so continuous `size:` scaling on
    an `icon` element is offered by baking whichever sizes a design actually
    uses -- exactly as if the author had declared several custom fonts at
    different sizes, except automatic and drawn from the vendored icon font
    rather than one the author supplies.  Independent of :func:`bake_fonts`'s
    caller order: this is a pure function of the design and the device, so it
    can run again in :func:`build_bundle` without needing to be threaded
    through as an argument.

    Keyed by glyph as well as declared size (`wfb.icons.font_key`), not just
    size: two icons declared at the same `size:` do not necessarily need the
    same *nominal* font size to look the same height, because the font's
    aggregated icon sets pad their glyphs inside the em-square differently
    (see `wfb.icons.bake_size`). Each *static* icon's key's char set is
    therefore exactly one codepoint.

    A *dynamic* icon (`icon_for:`) is the one exception: its glyph is chosen
    on-device at runtime (`WfbWeather.mc`), so its font must contain every
    glyph that choice could land on (`wfb.icons.WEATHER_GLYPH_SET`) rather
    than one -- `bake_size` is measured against a single representative glyph
    of that set (`wfb.icons.WEATHER_BAKE_REFERENCE_GLYPH`) for lack of a
    nominal size that fits all of them equally (see that constant's own
    docstring for why one does not exist).

    Also keyed by `element.resolved_antialias`: two icons agreeing on size and
    glyph but not on anti-aliasing need two different sheets, one 1-bit and one
    an 8-bit grey ramp -- see `wfb.icons.font_key`'s docstring.
    """
    # key -> (size, glyphs, bake_reference, antialias)
    by_key: dict[str, tuple[object, str, str, bool]] = {}
    for element in face.walk():
        if isinstance(element, ComplicationSlot):
            if element.icon_size is None:
                continue
            slot = face.config_data.get(element.slot)
            if slot is None or slot.allow_any:
                continue  # rejected slot, or 'choices: any' (icon_size: is an error there)
            mapped = {name: icons.COMPLICATION_ICON[name] for name in slot.choices
                     if name in icons.COMPLICATION_ICON}
            if not mapped:
                # None of this slot's choices has a catalogue icon -- it
                # simply draws none, which is a documented, legitimate
                # outcome (`wfb.icons.COMPLICATION_ICON`'s own docstring),
                # not something to bake a font for.
                continue
            icon_names = sorted(set(mapped.values()))
            glyphs = "".join(sorted({icons.CATALOG[n].codepoint for n in icon_names}))
            # The default choice's own icon normalises the shared nominal
            # size, the same "pick one reference glyph" trade-off
            # `WEATHER_BAKE_REFERENCE_GLYPH` makes for the weather set --
            # documented in `docs/format.md`'s `complication_slot` section.
            reference = icons.CATALOG[mapped.get(slot.default) or icon_names[0]].codepoint
            key = icons.font_key(element.icon_size, f"slot_{element.slot}",
                                 element.resolved_antialias)
            by_key[key] = (element.icon_size, glyphs, reference, element.resolved_antialias)
            continue
        if not isinstance(element, IconElement):
            continue
        if element.is_dynamic:
            glyph_key = icons.DYNAMIC_WEATHER_TAG
            glyphs = icons.WEATHER_GLYPH_SET
            reference = icons.WEATHER_BAKE_REFERENCE_GLYPH
        else:
            glyph_key = glyphs = reference = element.codepoint
        key = icons.font_key(element.size, glyph_key, element.resolved_antialias)
        by_key[key] = (element.size, glyphs, reference, element.resolved_antialias)
    return {
        key: FontSpec(
            name=key,
            source=icons.FONT_PATH,
            size=float(icons.bake_size(
                reference, units.pixel_size(length, device.minor_radius),
            )),
            glyphs=glyphs,
            antialias=antialias,
            scale=False,  # already resolved to this device's final pixel size
            span=None,
        )
        for key, (length, glyphs, reference, antialias) in by_key.items()
    }


def bake_fonts(face: Face, device: Device, reference_minor: float) -> dict[str, BakedFont]:
    """Rasterise every declared font, plus every icon font this design needs,
    at this device's size."""
    sets = glyph_set(face)
    baked: dict[str, BakedFont] = {}
    for name, spec in face.fonts.items():
        # One resolver for both spellings of `size:` -- and, through
        # `wfb.units.pixel_size`, the same one the synthetic icon fonts below
        # go through, so `12px` means the same thing on a font and on an icon.
        size = spec.pixel_size(device.minor_radius, reference_minor)
        font, sheet = bake(
            spec.source,
            name=name,
            size=size,
            glyphs=sets[name] or "0123456789",
            antialias=spec.antialias,
            monospace=spec.monospace,
            align=spec.align,
        )
        baked[name] = font
        font.sheet_image = sheet  # type: ignore[attr-defined]

    for name, spec in icon_font_specs(face, device).items():
        # Not `spec.pixel_size(...)`: an icon font's spec is synthesised, not
        # authored, and its `size` is already this device's final nominal size
        # -- `icon_font_specs` has run the declared `Length` through
        # `units.pixel_size` and then `icons.bake_size` to get there.
        font, sheet = bake(
            spec.source, name=name, size=round(spec.size), glyphs=spec.glyphs,
            antialias=spec.antialias,
        )
        baked[name] = font
        font.sheet_image = sheet  # type: ignore[attr-defined]
    return baked


def build_bundle(face: Face, device: Device, baked: dict[str, BakedFont]) -> ResourceBundle:
    bundle = ResourceBundle(device_id=device.id, directory=f"resources-{device.id}")
    sets = glyph_set(face)
    # Icon fonts are not in face.fonts (nothing in the YAML declares them --
    # they are synthesised from whichever `icon:` elements the design has), so
    # the lookup below needs both merged.
    specs: dict[str, FontSpec] = {**face.fonts, **icon_font_specs(face, device)}

    if baked:
        lines = [f"<fonts {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">"]
        for name, font in baked.items():
            spec = specs[name]
            raw_chars = sets.get(name, spec.glyphs or "")
            lines.append(
                f'    <!-- {name}: {spec.source.name} at {font.size}px, '
                f"{len(font.glyphs)} glyphs -->"
            )
            if any(ord(c) >= 0x10000 for c in raw_chars):
                # The resource compiler's `filter` attribute is parsed as Java
                # UTF-16 code units, so a codepoint above the Basic
                # Multilingual Plane (Material Design Icons and Weather Icons,
                # both used by wfb.icons, live entirely up there) splits into
                # two surrogate halves that match no real glyph and the build
                # fails with "does not have characters in the given filter" --
                # confirmed against a real build, not assumed. The .fnt this
                # font resource points at is already subsetted to exactly
                # these glyphs by wfb's own baking, so filter is redundant
                # protection here, not the only thing keeping the sheet small;
                # omitting it is safe.
                lines.append(
                    f"    <!-- filter omitted: {name} needs a glyph above U+FFFF, "
                    "which the resource compiler's filter parsing cannot represent -->"
                )
                lines.append(
                    f'    <font id="{spec.resource_id}" filename="{font.fnt_name}" '
                    f'antialias="{str(spec.antialias).lower()}" />'
                )
            else:
                chars = escape(raw_chars, {'"': "&quot;"})
                lines.append(
                    # filename is relative to this XML file, which sits beside the sheet.
                    f'    <font id="{spec.resource_id}" filename="{font.fnt_name}" '
                    f'filter="{chars}" antialias="{str(spec.antialias).lower()}" />'
                )
        lines.append("</fonts>")
        bundle.files["fonts/fonts.xml"] = "\n".join(lines) + "\n"
        bundle.fonts = baked

    icon_size = device.compiler.get("launcherIcon") or {"width": 40, "height": 40}
    bundle.images["drawables/launcher_icon.png"] = launcher_icon(
        face, int(icon_size["width"]), int(icon_size["height"])
    )
    bundle.files["drawables/drawables.xml"] = (
        f"<drawables {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">\n"
        f"    <!-- generated at {icon_size['width']}x{icon_size['height']}, "
        f"the size {device.id} asks for -->\n"
        f'    <bitmap id="LauncherIcon" filename="launcher_icon.png" />\n'
        f"</drawables>\n"
    )

    if face.has_config:
        try:
            supported = device.has_symbol(CONFIG_SYMBOL)
        except Exception:
            # `lint.check_config_support` already reported a "not checked"
            # note against a missing symbol table; degrading to "omit the
            # resource" here, rather than crashing the build a second time
            # over the same missing file, matches that.
            supported = False
        if supported:
            bundle.files["configs/watchface.xml"] = config_resource(face)
    return bundle


def config_resource(face: Face) -> str:
    """`resources-<device>/configs/watchface.xml` -- ADR 0006 1, twice amended.

    Called only for a device with the native editor
    (`Device.has_symbol(CONFIG_SYMBOL)`); the caller (`build_bundle`) is
    where that gate lives, so this is pure XML rendering from `face.config`/
    `face.config_colors`.  Grammar: `$CIQ_SDK/bin/resources.xsd`'s
    `watchfaceConfigType` -- an `xs:all`, so `<styles>` and the two colour
    axes may appear in any order; this always writes `<styles>` first.
    """
    lines = [
        f"<resources {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">",
        "    <watchface-config>",
    ]
    if face.config_colors is not None:
        lines.append("        <styles>")
        for index, scheme_name in enumerate(face.config_colors.choices):
            scheme = face.color_scheme[scheme_name]
            attrs = f' id="{index}"'
            if scheme_name == face.config_colors.default:
                attrs += ' default="true"'
            if scheme.label is not None:
                attrs += f' label="@Strings.{config_style_label_id(index)}"'
            lines.append(f"            <style{attrs}/>")
        lines.append("        </styles>")
    if face.config_data:
        lines.append("        <data>")
        for name, slot_id in config_data_ids(face).items():
            slot = face.config_data[name]
            if slot.allow_any:
                lines.append(f'            <complication id="{slot_id}" allowAny="true"/>')
                continue
            lines.append(f'            <complication id="{slot_id}">')
            for choice in slot.choices:
                ctype = complications.TYPES[choice]
                attrs = ' default="true"' if choice == slot.default else ""
                lines.append(f'                <type{attrs}>Complications.{ctype.constant}</type>')
            lines.append("            </complication>")
        lines.append("        </data>")
    for name, entry in face.config.items():
        tag = entry.axis.resource_tag
        if entry.allow_any:
            lines.append(f'        <{tag} allowAny="true"/>')
            continue
        lines.append(f"        <{tag}>")
        for index, choice in enumerate(entry.choices):
            attrs = ""
            if choice.color == entry.default:
                attrs += ' default="true"'
            if choice.label is not None:
                attrs += f' label="@Strings.{config_label_id(name, index)}"'
            lines.append(f"            <color{attrs}>{choice.color.as_monkeyc()}</color>")
        lines.append(f"        </{tag}>")
    lines.append("    </watchface-config>")
    lines.append("</resources>")
    return "\n".join(lines) + "\n"


def config_label_strings(face: Face) -> list[tuple[str, str]]:
    """`(string id, label text)` for every labelled `config:` choice, plus
    every labelled `color_scheme:` entry that `config: colors:` lists.

    Shared across every device -- a label is authored text, not something
    that varies per target -- so these live in `shared_strings()` rather than
    in each device's own resource bundle, the same reasoning `AppName`
    already follows.
    """
    out: list[tuple[str, str]] = []
    if face.config_colors is not None:
        for index, scheme_name in enumerate(face.config_colors.choices):
            scheme = face.color_scheme[scheme_name]
            if scheme.label is not None:
                out.append((config_style_label_id(index), scheme.label))
    for name, entry in face.config.items():
        if entry.allow_any:
            continue
        for index, choice in enumerate(entry.choices):
            if choice.label is not None:
                out.append((config_label_id(name, index), choice.label))
    return out


def shared_strings(face: Face) -> str:
    lines = [
        f"<strings {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">",
        f'    <string id="AppName">{escape(face.name)}</string>',
    ]
    for string_id, text in config_label_strings(face):
        lines.append(f'    <string id="{string_id}">{escape(text)}</string>')
    lines.append("</strings>")
    return "\n".join(lines) + "\n"


def launcher_icon(face: Face, width: int, height: int) -> Image.Image:
    """A plain mark in the design's own colours, at the device's icon size.

    Deliberately simple: a real icon is an art decision, and a generated
    placeholder that looks generated is more honest than one pretending not to be.
    """
    background = face.palette.get("bg", Color(0, 0, 0))
    accent = next(
        (face.palette[name] for name in ("accent", "text", "fg") if name in face.palette),
        Color(0xFF, 0xFF, 0xFF),
    )
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = max(1, width // 10)
    stroke = max(2, width // 12)
    draw.ellipse(
        [inset, inset, width - inset - 1, height - inset - 1],
        outline=(accent.r, accent.g, accent.b, 255),
        fill=(background.r, background.g, background.b, 255),
        width=stroke,
    )
    cx, cy = width / 2, height / 2
    draw.line([cx, cy, cx, inset + stroke + 1], fill=(accent.r, accent.g, accent.b, 255),
              width=max(1, stroke // 2))
    draw.line([cx, cy, width - inset - stroke - 1, cy], fill=(accent.r, accent.g, accent.b, 255),
              width=max(1, stroke // 2))
    return image


def write_bundle(bundle: ResourceBundle, root: Path) -> list[Path]:
    written: list[Path] = []
    base = root / bundle.directory
    for relative, text in bundle.files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    for relative, image in bundle.images.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG", optimize=True)
        written.append(path)
    for font in bundle.fonts.values():
        sheet = getattr(font, "sheet_image", None)
        if sheet is not None:
            written.extend(write_font(font, sheet, base / "fonts"))
    return written
