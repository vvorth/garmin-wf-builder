"""Baking a TrueType source into a Connect IQ bitmap font.

The resource compiler reads BMFont's *text* ``.fnt`` format plus a page image
(SDK: Core_Topics/Resources, "Fonts").  Garmin's own advice is to use the
AngelCode BMFont tool; doing it here instead is what lets the compiler bake
**only the glyphs the design can actually render** -- derived from every format
spec and literal string in the face -- rather than a whole character set.  On a
128 KB budget that is the difference between a large font fitting and not.

Bitmap fonts default to 1-bit because anti-aliasing costs runtime RAM; the
author opts into ``antialias: true`` knowingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Glyph sheets are padded to a power of two, as BMFont's exports are.
_MAX_SHEET = 1024
_PADDING = 1


@dataclass(frozen=True)
class GlyphBox:
    char: str
    x: int
    y: int
    width: int
    height: int
    xoffset: int
    yoffset: int
    xadvance: int


@dataclass
class BakedFont:
    """A rasterised font, plus the metrics layout needs to place text with it."""

    name: str
    face: str
    size: int
    line_height: int
    base: int
    sheet_width: int
    sheet_height: int
    glyphs: dict[str, GlyphBox] = field(default_factory=dict)
    antialias: bool = False
    #: Filenames written by :meth:`write`, relative to the resource directory.
    fnt_name: str = ""
    png_name: str = ""

    def measure(self, text: str) -> tuple[int, int]:
        """The pixel extent of ``text``: (advance width, line height)."""
        width = 0
        for char in text:
            glyph = self.glyphs.get(char)
            if glyph is not None:
                width += glyph.xadvance
        return width, self.line_height

    def missing(self, text: str) -> set[str]:
        """Characters ``text`` needs that this font does not contain (lint 6)."""
        return {c for c in text if c not in self.glyphs}

    # -- output ----------------------------------------------------------

    def to_fnt(self) -> str:
        lines = [
            f'info face="{self.face}" size={-self.size} bold=0 italic=0 charset="" '
            f"unicode=1 stretchH=100 smooth={1 if self.antialias else 0} "
            f"aa=1 padding=0,0,0,0 spacing={_PADDING},{_PADDING} outline=0",
            f"common lineHeight={self.line_height} base={self.base} "
            f"scaleW={self.sheet_width} scaleH={self.sheet_height} pages=1 packed=0 "
            f"alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4",
            f'page id=0 file="{self.png_name}"',
            f"chars count={len(self.glyphs)}",
        ]
        for char in sorted(self.glyphs, key=ord):
            g = self.glyphs[char]
            lines.append(
                f"char id={ord(char)} x={g.x} y={g.y} width={g.width} height={g.height} "
                f"xoffset={g.xoffset} yoffset={g.yoffset} xadvance={g.xadvance} "
                f"page=0 chnl=15"
            )
        lines.append("kernings count=0")
        return "\n".join(lines) + "\n"


def bake(
    source: Path,
    *,
    name: str,
    size: int,
    glyphs: str,
    antialias: bool = False,
) -> tuple[BakedFont, Image.Image]:
    """Rasterise ``glyphs`` from ``source`` at ``size`` pixels."""
    chars = _ordered_unique(glyphs)
    if not chars:
        raise ValueError(f"font {name!r}: no glyphs to bake")

    font = ImageFont.truetype(str(source), size)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent

    rendered: list[tuple[str, Image.Image, int, int, int]] = []
    for char in chars:
        bbox = font.getbbox(char)
        advance = int(round(font.getlength(char)))
        left, top, right, bottom = bbox
        width, height = max(0, right - left), max(0, bottom - top)
        if width == 0 or height == 0:  # space and friends carry advance only
            rendered.append((char, Image.new("L", (1, 1), 0), 0, 0, advance))
            continue
        tile = Image.new("L", (width, height), 0)
        ImageDraw.Draw(tile).text((-left, -top), char, font=font, fill=255)
        if not antialias:
            tile = tile.point(lambda v: 255 if v >= 128 else 0)
        rendered.append((char, tile, left, top, advance))

    sheet_width, sheet_height, placements = _pack([(c, im) for c, im, *_ in rendered])
    sheet = Image.new("L", (sheet_width, sheet_height), 0)
    baked = BakedFont(
        name=name,
        face=_face_name(source),
        size=size,
        line_height=line_height,
        base=ascent,
        sheet_width=sheet_width,
        sheet_height=sheet_height,
        antialias=antialias,
        fnt_name=f"{name}.fnt",
        png_name=f"{name}.png",
    )
    for (char, tile, left, top, advance), (x, y) in zip(rendered, placements):
        if tile.size != (1, 1) or tile.getpixel((0, 0)):
            sheet.paste(tile, (x, y))
        empty = tile.size == (1, 1) and not tile.getpixel((0, 0))
        baked.glyphs[char] = GlyphBox(
            char=char,
            x=x,
            y=y,
            width=0 if empty else tile.width,
            height=0 if empty else tile.height,
            xoffset=left,
            yoffset=top,
            xadvance=advance,
        )
    return baked, sheet


def write(baked: BakedFont, sheet: Image.Image, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    png_path = directory / baked.png_name
    fnt_path = directory / baked.fnt_name
    sheet.save(png_path, format="PNG", optimize=True)
    fnt_path.write_text(baked.to_fnt(), encoding="utf-8")
    return [fnt_path, png_path]


def _ordered_unique(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for char in text:
        if char not in seen:
            seen[char] = None
    return list(seen)


def _pack(tiles: list[tuple[str, Image.Image]]) -> tuple[int, int, list[tuple[int, int]]]:
    """Shelf-pack the glyph tiles into the smallest power-of-two sheet that fits."""
    widest = max(im.width for _, im in tiles) + _PADDING
    total = sum((im.width + _PADDING) for _, im in tiles)
    side = 16
    while side < _MAX_SHEET:
        if side >= widest and _shelf_height(tiles, side) <= side:
            break
        side *= 2
    if side > _MAX_SHEET or total == 0:
        raise ValueError("glyph sheet would exceed 1024x1024 -- reduce the font size or glyph set")

    placements: list[tuple[int, int]] = []
    x = y = row_height = 0
    for _, tile in tiles:
        if x + tile.width + _PADDING > side:
            x, y = 0, y + row_height + _PADDING
            row_height = 0
        placements.append((x, y))
        x += tile.width + _PADDING
        row_height = max(row_height, tile.height)
    return side, side, placements


def _shelf_height(tiles: list[tuple[str, Image.Image]], side: int) -> int:
    x = y = row_height = 0
    for _, tile in tiles:
        if x + tile.width + _PADDING > side:
            x, y = 0, y + row_height + _PADDING
            row_height = 0
        x += tile.width + _PADDING
        row_height = max(row_height, tile.height)
    return y + row_height


def _face_name(source: Path) -> str:
    try:
        from fontTools.ttLib import TTFont

        with TTFont(str(source), fontNumber=0, lazy=True) as ttf:
            for record in ttf["name"].names:
                if record.nameID == 1:
                    return str(record.toUnicode())
    except Exception:
        pass
    return source.stem
