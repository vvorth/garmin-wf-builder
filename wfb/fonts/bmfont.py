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
    #: Every glyph was given the same advance (:attr:`cell_width`).
    monospace: bool = False
    #: The shared advance, in pixels, when :attr:`monospace`; 0 otherwise.
    cell_width: int = 0
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


#: How much bigger than the target the glyph is rasterised before being
#: averaged down.
#:
#: Not a taste decision.  Rendering straight to the target size asks FreeType
#: to fit an outline to a pixel grid at single-digit sizes, and its hinting
#: then breaks the shape's own symmetry: measured over 99 glyphs from the
#: vendored icon font that are provably symmetric (rendered at 256px they
#: mirror exactly), across 12 sizes from 8 to 28 px, **16.8% of ink pixels
#: landed asymmetrically**.  A plain square came out 7x7 inside an 8x8 tile;
#: `md-circle_outline` at 16px was lopsided in every row.
#:
#: The cause is sub-pixel positioning, not curve sampling: the outline's true
#: origin is fractional, integer placement drops that fraction, and the 1-bit
#: threshold then turns a half-covered edge pixel into ink on one side and
#: nothing on the other.  Rasterising large and box-averaging down recovers
#: real per-pixel coverage before the threshold sees it.
#:
#: The factor was chosen by measuring, not assumed -- asymmetry falls
#: monotonically (4.5% at 4x, 1.8% at 8x, 1.1% at 16x, 0.7% at 24x) while the
#: cost stays flat, because the work is dominated by per-glyph overhead rather
#: than pixels.  16 sits at the knee: **1.06%, a sixteenfold improvement**, for
#: about 0.2 ms a glyph.
SUPERSAMPLE = 16


def _rasterise(source: Path, size: int, char: str,
               antialias: bool) -> tuple[Image.Image | None, int, int]:
    """One glyph, and where its ink starts relative to the pen.

    Returns ``(None, 0, 0)`` for a glyph with no ink at all.
    """
    big = ImageFont.truetype(str(source), size * SUPERSAMPLE)
    left, top, right, bottom = big.getbbox(char)
    if right - left <= 0 or bottom - top <= 0:
        return None, 0, 0

    # Draw into a padded canvas so a hinted outline that spills past its own
    # reported bbox is not clipped, then find the ink that actually landed --
    # measured, rather than trusting the bbox, which is what went wrong before.
    pad = SUPERSAMPLE * 2
    canvas = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), 0)
    ImageDraw.Draw(canvas).text((-left + pad, -top + pad), char, font=big, fill=255)
    ink = canvas.getbbox()
    if ink is None:
        return None, 0, 0

    crop = canvas.crop(ink)
    width = max(1, round(crop.width / SUPERSAMPLE))
    height = max(1, round(crop.height / SUPERSAMPLE))
    # BOX is an area average, so each target pixel gets the fraction of itself
    # the glyph actually covers -- which is the number the threshold below
    # wants, and the number drawing at the target size never produces.
    tile = crop.resize((width, height), Image.BOX)
    if not antialias:
        tile = tile.point(lambda v: 255 if v >= 128 else 0)

    # Back to target pixels: the canvas's own origin sits at (left - pad) in
    # the supersampled pen space, so the ink starts that much further along.
    return tile, round((left - pad + ink[0]) / SUPERSAMPLE), \
        round((top - pad + ink[1]) / SUPERSAMPLE)


#: Where a glyph's ink sits inside its cell when ``monospace`` is on.
ALIGNMENTS = ("left", "center", "right")


def bake(
    source: Path,
    *,
    name: str,
    size: int,
    glyphs: str,
    antialias: bool = False,
    monospace: bool = False,
    align: str = "center",
) -> tuple[BakedFont, Image.Image]:
    """Rasterise ``glyphs`` from ``source`` at ``size`` pixels.

    ``monospace`` gives every baked glyph the *same* advance, which is what a
    digital clock in a proportional face needs: its characters are each as wide
    as they want to be, so the line's width -- and, centred, every character's
    position -- moves as the reading changes.  Measured on the vendored Open
    Sans at 33 px: `Fri 11:11` is 111 px and `Wed 00:00` is 125 px.  (Its
    *figures* happen to be tabular, all 19 px, so a digits-only clock is
    already steady in that particular face; its colon is not, at 9 px.)

    Baking one cell width costs nothing at runtime -- the device just reads the
    advances out of the `.fnt` -- and it works on a proportional source as well
    as a monospaced one, because the cell is measured from the glyphs actually
    baked rather than trusted from the font's `post` table.

    ``align`` places the ink inside that cell.  ``center`` is the default
    because it is what a tabular figure wants; ``left``/``right`` exist for
    the rarer case of a column of readings whose edges should line up.
    """
    if align not in ALIGNMENTS:
        raise ValueError(f"font {name!r}: unknown align {align!r}")
    chars = _ordered_unique(glyphs)
    if not chars:
        raise ValueError(f"font {name!r}: no glyphs to bake")

    font = ImageFont.truetype(str(source), size)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent

    rendered: list[tuple[str, Image.Image, int, int, int]] = []
    for char in chars:
        # The advance and the line metrics stay at the target size: they decide
        # where glyphs sit relative to each other, and nothing about the
        # rasterising below should move text around.
        advance = int(round(font.getlength(char)))
        tile, left, top = _rasterise(source, size, char, antialias)
        if tile is None:  # space and friends carry advance only
            rendered.append((char, Image.new("L", (1, 1), 0), 0, 0, advance))
            continue
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
        monospace=monospace,
        cell_width=_cell_width(rendered) if monospace else 0,
        fnt_name=f"{name}.fnt",
        png_name=f"{name}.png",
    )
    for (char, tile, left, top, advance), (x, y) in zip(rendered, placements):
        if tile.size != (1, 1) or tile.getpixel((0, 0)):
            sheet.paste(tile, (x, y))
        empty = tile.size == (1, 1) and not tile.getpixel((0, 0))
        ink_width = 0 if empty else tile.width
        if monospace:
            # The cell replaces the natural advance *and* the natural left
            # bearing: keeping the bearing would re-introduce the very jitter
            # the cell removes, since a narrow glyph's ink would still sit
            # where the proportional face put it.
            advance = baked.cell_width
            left = 0 if empty else _ink_offset(align, baked.cell_width, ink_width)
        baked.glyphs[char] = GlyphBox(
            char=char,
            x=x,
            y=y,
            width=ink_width,
            height=0 if empty else tile.height,
            xoffset=left,
            yoffset=top,
            xadvance=advance,
        )
    return baked, sheet


def _cell_width(rendered: list[tuple[str, Image.Image, int, int, int]]) -> int:
    """The shared advance for a monospaced bake.

    The widest natural advance, but never narrower than the widest *ink*.  An
    outline may overhang its own advance -- the two are separate numbers in the
    font, and the ink measured here is this rasteriser's own supersampled
    bitmap, not the face's declared bbox -- and a cell narrower than the ink it
    holds would overlap its neighbour rather than merely being tight.  Cheap
    insurance: on a face where it does not happen the term simply loses.
    """
    widest_advance = max(advance for *_, advance in rendered)
    widest_ink = max(
        (tile.width for _, tile, *_ in rendered
         if tile.size != (1, 1) or tile.getpixel((0, 0))),
        default=0,
    )
    return max(1, widest_advance, widest_ink)


def _ink_offset(align: str, cell: int, ink_width: int) -> int:
    if align == "left":
        return 0
    if align == "right":
        return cell - ink_width
    return round((cell - ink_width) / 2)


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
