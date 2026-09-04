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

from .. import catalog, formatting
from ..devices import Device
from ..fonts import BakedFont, bake
from ..fonts.bmfont import write as write_font
from ..ir import Face, Text
from ..layout import font_pixel_size
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


def glyph_set(face: Face) -> dict[str, str]:
    """The characters each declared font must contain, derived from the design."""
    needed: dict[str, set[str]] = {name: set() for name in face.fonts}
    for element in face.walk():
        if not isinstance(element, Text) or not element.font_is_custom:
            continue
        bucket = needed.setdefault(element.font, set())
        if element.literal is not None:
            bucket |= set(element.literal)
            continue
        if element.value is None:
            continue
        source = catalog.get(element.value.sources[0]) if element.value.sources else None
        bucket |= formatting.glyphs(element.format or "{}", source, element.value.value.type)
        if element.placeholder:
            bucket |= set(element.placeholder)
    out: dict[str, str] = {}
    for name, chars in needed.items():
        declared = face.fonts[name].glyphs
        out[name] = declared if declared is not None else "".join(sorted(chars))
    return out


def bake_fonts(face: Face, device: Device, reference_minor: float) -> dict[str, BakedFont]:
    """Rasterise every declared font at this device's size."""
    sets = glyph_set(face)
    baked: dict[str, BakedFont] = {}
    for name, spec in face.fonts.items():
        size = (
            font_pixel_size(spec.size, device, reference_minor)
            if spec.scale
            else round(spec.size)
        )
        font, sheet = bake(
            spec.source,
            name=name,
            size=size,
            glyphs=sets[name] or "0123456789",
            antialias=spec.antialias,
        )
        baked[name] = font
        font.sheet_image = sheet  # type: ignore[attr-defined]
    return baked


def build_bundle(face: Face, device: Device, baked: dict[str, BakedFont]) -> ResourceBundle:
    bundle = ResourceBundle(device_id=device.id, directory=f"resources-{device.id}")
    sets = glyph_set(face)

    if baked:
        lines = [f"<fonts {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">"]
        for name, font in baked.items():
            spec = face.fonts[name]
            chars = escape(sets[name], {'"': "&quot;"})
            lines.append(
                f'    <!-- {name}: {spec.source.name} at {font.size}px, '
                f"{len(font.glyphs)} glyphs -->"
            )
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
    return bundle


def shared_strings(face: Face) -> str:
    return (
        f"<strings {_XMLNS} xsi:noNamespaceSchemaLocation=\"{_XSD}\">\n"
        f'    <string id="AppName">{escape(face.name)}</string>\n'
        f"</strings>\n"
    )


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
