"""Decode Garmin's ``.cft`` bitmap-font container -- the format 8 of the 13
installed devices (`fenix6`, `fenix6xpro`, `fenix7pro`, `fenix7x`,
`fenix7xpro`, `fenix7xpronowifi`, `fr245`, `fr255`) resolve *every* `FONT_*`
symbol to (`docs/plans/10-cft-bitmap-fonts.md` §2.1), used today by
`wfb/fonts/fetch_system.py`'s :func:`garmin_cft_file` only for diagnostics.
This module is Step A of that plan: pure decoding, no policy about when a
`.cft` should be preferred over a TTF (Step B).

**Format, ported from prior art.** The container format was reverse
engineered by, and this module is a direct port of the decode logic in,
**`markw65/monkeyc-optimizer`**, file `src/cftinfo.ts`, pinned at commit
`cea919a92da74de1f5d277064caa6f7920554af7`
(<https://raw.githubusercontent.com/markw65/monkeyc-optimizer/cea919a92da74de1f5d277064caa6f7920554af7/src/cftinfo.ts>),
MIT licence. Credited in `README.md`'s licence section.

Everything in the container is big-endian::

    Off  Size  Field
    0    2     header size: 36, or 40 (maybe-zlib variant)
    3    1     flags: bit 1 (2) = RLE glyph data, bit 2 (4) = 2 bpp (else 1 bpp)
    4    4     file size
    8    4     cmap offset
    12   4     glyph-info offset
    16   4     glyph-data offset
    22   2     height (px, the line box)
    24   2     ascent (baseline, px from the top)
    26   2     internal leading (unused here)
    32   4     0x12345678 when RLE (36-byte header) -- documented by the
                reference tool but not actually consulted by its decode path
                (the flags byte at offset 3 already carries this), so this
                module does not check it either
    36   1     row alignment in bytes (40-byte header only; else 1)

* **cmap**, at ``cmap offset + 12``: a u32 group count, then that many
  ``(start, end, start_glyph)`` u32 triples starting at ``cmap offset + 16``.
  A codepoint in ``[start, end]`` maps to glyph ``start_glyph + (codepoint -
  start)``. Groups are scanned in file order and a *later* group's mapping
  wins for an overlapping codepoint (matching the reference's dict-assignment
  semantics, where each group's codepoints are written into the same map in
  turn). A codepoint matched by no group maps to glyph 0, the "missing" box
  -- what the device itself draws for an unmapped character is UNVERIFIED
  (plan §2.2); glyph 0 is the working assumption.
* **Glyph info**: one u32 per glyph, at ``glyph-info offset + 4 * index``.
  ``glyph_offset = ((word >> 16) & 0xffff) + ((word & 0xff00) << 8)``, masked
  ``& 0x7fffff`` when RLE. ``advance = word & 0xff``. Every glyph is a full
  ``advance x height`` cell -- no bearings, no bbox offsets, no kerning.
* **Pixel layout**: row-major. Each row is
  ``ceil(ceil(advance / ppb) / align) * align`` bytes (``ppb`` = 4 at 2 bpp,
  8 at 1 bpp; ``align`` is 1 for a 36-byte header), and pixels are packed
  **LSB-first** within a byte. A level runs ``0..3`` (2 bpp) or ``0..1``
  (1 bpp), 0 background, max full ink.
* **RLE** (:func:`_rle_decode`): bits are read LSB-first from the byte
  stream. The header is a unary ``run_bits`` (count of 0 bits up to the
  first 1, plus 1), then 5 bits of ``chunk_size - 1``, then ``chunk_size``
  bits of ``escape``. Each following chunk is a literal ``chunk_size``-bit
  value; when it equals ``escape``, ``run_bits`` bits of run length ``r``
  follow -- ``r == 0`` means the escape value is itself a literal, otherwise
  the *previous* literal repeats ``r + 1`` times. Output is packed as
  ``chunk_size``-bit values, LSB-first, until ``row_bytes * height`` bytes
  exist. Ported faithfully from the reference, but with a byte-array output
  writer and a small bounded bit accumulator rather than the reference's
  approach of shifting one Python-scale big integer -- the naive port grows
  quadratically on a large glyph (`docs/plans/10-cft-bitmap-fonts.md` §3
  A.1's warning); this implementation is linear in the glyph's pixel count.
* **40-byte header**: glyph data may be zlib-compressed. At the glyph-data
  offset, a first u32 of ``0xCD00000D`` (3439329293) means "skip 4, then a
  u32 length, then zlib". ``0xD000000D`` (3489660941) means "skip 4, raw,
  not compressed". Any other value means "u32 length, then zlib" (the value
  itself *is* that length).

Standard library only: :mod:`struct`, :mod:`zlib`, :mod:`functools`,
:mod:`dataclasses`, :mod:`pathlib` -- no Pillow import, the same spirit as
`wfb/fonts/fetch_system.py`.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: Flag bits at header offset 3.
_FLAG_RLE = 0x02
_FLAG_2BPP = 0x04

#: The two "maybe-zlib" magic words a 40-byte header's glyph data may open
#: with (plan §2.2 / cftinfo.ts's `getGlyphData`).
_ZLIB_MAGIC_LENGTH_PREFIXED = 0xCD00000D
_ZLIB_MAGIC_RAW = 0xD000000D


@dataclass(frozen=True)
class Glyph:
    """One decoded glyph cell.

    ``levels`` is row-major, one byte per pixel, each value ``0..max_level``
    (0 background, ``max_level`` full ink) -- never packed bits, so a caller
    never needs to know the container's bpp/alignment to read a pixel:
    ``levels[row * advance + col]``.
    """

    #: The pen advance, in pixels -- also the cell width.
    advance: int
    #: The cell height, in pixels -- always the font's own `height`.
    height: int
    levels: bytes


@dataclass(frozen=True)
class CftFont:
    """A decoded `.cft` font. Build with :func:`load`, never directly.

    All fields but the leading-underscore ones are the public API
    (`docs/plans/10-cft-bitmap-fonts.md` §3 A.1). Decoded glyphs are cached
    by the module-level :func:`_decode_glyph_cached`, keyed on
    ``(path, glyph_index)`` -- this dataclass stays frozen and holds no
    mutable cache of its own.
    """

    path: str
    #: The line box height, in pixels.
    height: int
    #: The baseline, in pixels down from the line box's own top.
    ascent: int
    internal_leading: int
    #: 1 or 2.
    bpp: int
    #: ``2 ** bpp - 1`` -- the highest ink level a pixel can carry.
    max_level: int
    _rle: bool
    #: Row byte-alignment (40-byte header only; 1 otherwise).
    _align: int
    #: ``(start, end, start_glyph)`` triples, in file order.
    _cmap: tuple[tuple[int, int, int], ...]
    #: Offset of the glyph-info table within `_raw`.
    _glyph_info_offset: int
    #: The whole file, verbatim -- the glyph-info table is never compressed,
    #: even under a 40-byte zlib header, so this is kept alongside
    #: `_glyph_data` rather than in place of it.
    _raw: bytes = field(repr=False)
    #: The bytes glyph offsets are relative to `_base` within: `_raw` itself
    #: for a 36-byte header or an uncompressed 40-byte one, or the
    #: zlib-inflated glyph data for a compressed one.
    _glyph_data: bytes = field(repr=False)
    _base: int

    def _glyph_index(self, ch: str) -> int:
        """`ch`'s glyph index, or 0 (the "missing" box) when no cmap group
        covers its codepoint. A later group wins over an earlier one for an
        overlapping codepoint (module docstring)."""
        codepoint = ord(ch)
        result = 0
        for start, end, start_glyph in self._cmap:
            if start <= codepoint <= end:
                result = start_glyph + (codepoint - start)
        return result

    def advance(self, ch: str) -> int:
        """`ch`'s pen advance, in pixels -- reads only the glyph-info word,
        never decodes pixels."""
        return _glyph_word(self.path, self._glyph_index(ch)) & 0xFF

    def advances(self, text: str) -> list[int]:
        return [self.advance(ch) for ch in text]

    def glyph(self, ch: str) -> Glyph:
        """`ch`'s decoded :class:`Glyph`. Cached module-wide, keyed on this
        font's path and the resolved glyph index."""
        return _decode_glyph_cached(self.path, self._glyph_index(ch))


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load(path: "str | Path") -> CftFont | None:
    """Decode the `.cft` file at `path`, or `None` if it cannot be read or is
    malformed/truncated. Never raises. `lru_cache`d on the path's string
    form, so a repeated call (e.g. once per glyph a build measures) does not
    re-read or re-parse the file."""
    return _load(str(path))


@lru_cache(maxsize=None)
def _load(path: str) -> CftFont | None:
    try:
        return _parse(path, Path(path).read_bytes())
    except Exception:  # noqa: BLE001 -- malformed input must never raise
        return None


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _glyph_data_segment(data: bytes, offset: int, header_size: int) -> tuple[bytes, int]:
    """`(bytes glyph offsets are relative to, base offset within them)` --
    the 40-byte header's maybe-zlib dance (module docstring), or, for a
    36-byte header, `data` itself with no adjustment."""
    if header_size != 40:
        return data, offset

    first_word = struct.unpack_from(">I", data, offset)[0]
    if first_word == _ZLIB_MAGIC_RAW:
        return data, offset + 4

    if first_word == _ZLIB_MAGIC_LENGTH_PREFIXED:
        offset += 4  # skip the magic word
    # Either the length-prefixed-zlib magic (skip it, then read+skip the
    # length word below) or the "any other value" case, where that value
    # *is* the length word already positioned at `offset`.
    offset += 4  # skip the (now-current) length word
    return zlib.decompress(data[offset:]), 0


def _parse(path: str, data: bytes) -> CftFont:
    if len(data) < 36:
        raise ValueError("truncated cft header")

    header_size = struct.unpack_from(">H", data, 0)[0]
    if header_size not in (36, 40):
        raise ValueError(f"unsupported cft header size {header_size}")
    if len(data) < header_size:
        raise ValueError("truncated cft header")

    flags = data[3]
    _file_size, cmap_offset, glyph_info_offset, glyph_data_offset = struct.unpack_from(
        ">IIII", data, 4
    )
    height, ascent, internal_leading = struct.unpack_from(">HHH", data, 22)
    align = data[36] if header_size == 40 else 1

    rle = bool(flags & _FLAG_RLE)
    bpp = 2 if flags & _FLAG_2BPP else 1

    glyph_data, base = _glyph_data_segment(data, glyph_data_offset, header_size)

    if cmap_offset + 16 > len(data):
        raise ValueError("truncated cmap header")
    n_groups = struct.unpack_from(">I", data, cmap_offset + 12)[0]
    groups_start = cmap_offset + 16
    groups_end = groups_start + 12 * n_groups
    if groups_end > len(data):
        raise ValueError("truncated cmap groups")
    groups = tuple(
        struct.unpack_from(">III", data, groups_start + 12 * i) for i in range(n_groups)
    )

    return CftFont(
        path=path,
        height=height,
        ascent=ascent,
        internal_leading=internal_leading,
        bpp=bpp,
        max_level=(1 << bpp) - 1,
        _rle=rle,
        _align=align,
        _cmap=groups,
        _glyph_info_offset=glyph_info_offset,
        _raw=data,
        _glyph_data=glyph_data,
        _base=base,
    )


# ---------------------------------------------------------------------------
# glyph decoding -- module-level, cached, so CftFont stays a plain frozen
# dataclass with no mutable cache of its own
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8192)
def _glyph_word(path: str, glyph_index: int) -> int:
    """The raw glyph-info u32 for `glyph_index`, or 0 if `path` doesn't load
    or the index is out of range -- never raises. Cached separately from the
    full pixel decode (:func:`_decode_glyph_cached`) so `CftFont.advance`
    never has to unpack a glyph's pixels just to answer a width query."""
    font = load(path)
    if font is None:
        return 0
    try:
        offset = font._glyph_info_offset + 4 * glyph_index
        return struct.unpack_from(">I", font._raw, offset)[0]
    except struct.error:
        return 0


@lru_cache(maxsize=4096)
def _decode_glyph_cached(path: str, glyph_index: int) -> Glyph:
    font = load(path)
    if font is None:
        return Glyph(advance=0, height=0, levels=b"")
    return _decode_glyph(font, glyph_index)


def _decode_glyph(font: CftFont, glyph_index: int) -> Glyph:
    try:
        word = _glyph_word(font.path, glyph_index)
        advance = word & 0xFF
        glyph_offset = ((word >> 16) & 0xFFFF) + ((word & 0xFF00) << 8)
        if font._rle:
            glyph_offset &= 0x7FFFFF

        ppb = 4 if font.bpp == 2 else 8
        bytes_to_count = _ceil_div(advance, ppb)
        byte_width = _ceil_div(bytes_to_count, font._align) * font._align
        size = byte_width * font.height
        start = font._base + glyph_offset

        if font._rle:
            packed = _rle_decode(font._glyph_data, start, size)
        else:
            packed = font._glyph_data[start:start + size]
            if len(packed) < size:
                # A short read (e.g. a truncated/corrupt data section) is
                # padded with background rather than raising -- the whole
                # point of a bitmap "missing glyph" box is to draw *some*
                # sane cell.
                packed = packed + bytes(size - len(packed))

        mask = font.max_level
        bpp = font.bpp
        levels = bytearray(advance * font.height)
        pos = 0
        for row in range(font.height):
            row_offset = row * byte_width
            for x in range(advance):
                byte = packed[row_offset + x // ppb]
                levels[pos] = (byte >> ((x % ppb) * bpp)) & mask
                pos += 1

        return Glyph(advance=advance, height=font.height, levels=bytes(levels))
    except (struct.error, IndexError, ValueError):
        return Glyph(advance=0, height=font.height, levels=b"")


class _BitReader:
    """Reads big-endian-packed-file bits **LSB-first within each byte**,
    starting at byte `offset` of `data`. Used only for the RLE header
    (`run_bits`/`chunk_size`/`escape`) and each chunk value afterwards.

    The accumulator never holds more than one pending byte's worth beyond
    what `get` was asked for (at most ~39 bits, since `chunk_size` is at
    most 32), so this stays O(1) per call -- no quadratic blowup, unlike
    building the whole bitstream into one Python integer.
    """

    __slots__ = ("_data", "_pos", "_acc", "_nbits")

    def __init__(self, data: bytes, offset: int) -> None:
        self._data = data
        self._pos = offset
        self._acc = 0
        self._nbits = 0

    def get(self, n: int) -> int:
        while self._nbits < n:
            self._acc |= self._data[self._pos] << self._nbits
            self._pos += 1
            self._nbits += 8
        result = self._acc & ((1 << n) - 1)
        self._acc >>= n
        self._nbits -= n
        return result


def _rle_decode(data: bytes, offset: int, size: int) -> bytes:
    """The RLE glyph-data codec (module docstring). `size` is the exact
    number of packed output bytes the caller needs (`row_bytes * height`);
    output beyond it is never produced. Bounded accumulators throughout --
    the output is written straight into a `bytearray`, not assembled as one
    big integer, so this is linear in `size` regardless of run lengths."""
    if size <= 0:
        return b""

    reader = _BitReader(data, offset)
    run_bits = 1
    while reader.get(1) == 0:
        run_bits += 1
    chunk_size = reader.get(5) + 1
    escape = reader.get(chunk_size)

    out = bytearray(size)
    out_pos = 0
    acc = 0
    acc_bits = 0
    prev = -1

    while out_pos + (acc_bits >> 3) < size:
        val = reader.get(chunk_size)
        if val != escape:
            prev = val
            value, count = val, 1
        else:
            run = reader.get(run_bits)
            if run == 0:
                prev = val
                value, count = val, 1
            else:
                value, count = prev, run + 1

        for _ in range(count):
            acc |= value << acc_bits
            acc_bits += chunk_size
            while acc_bits >= 8:
                if out_pos < size:
                    out[out_pos] = acc & 0xFF
                out_pos += 1
                acc >>= 8
                acc_bits -= 8

    if acc_bits and out_pos < size:
        out[out_pos] = acc & 0xFF

    return bytes(out)
