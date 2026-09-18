"""Tests for `wfb/fonts/cft.py` (plan 10 Step A).

Core coverage does not depend on Garmin's licensed files: a small test-side
**encoder** below (`write_cft` and friends) writes synthetic `.cft` files --
36-byte RLE 2 bpp, 36-byte raw 1 bpp, and 40-byte zlib 1 bpp (all three
"maybe-compressed" magic variants) -- and round-trips known pixel grids
through `cft.load`. The encoder is built from the same spec `cft.py`'s
decoder is (module docstring there), not from the decoder's own code, so a
passing round trip is real evidence, not a tautology: see
`test_a_broken_decoder_is_caught` for the check that these tests actually
fail against a broken implementation.

Two tests read real files from `vendor/fonts/` (the user's own licensed
Garmin fonts, gitignored) and skip cleanly when absent.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from wfb.fonts import cft

# ---------------------------------------------------------------------------
# test-side encoder -- the inverse of cft.py's decode, built from the format
# spec (plan 10 §2.2), not from cft.py's own code
# ---------------------------------------------------------------------------


class _TestBitWriter:
    """LSB-first bit writer -- the encoder's counterpart to `cft._BitReader`,
    written independently rather than reused, so a bug shared by both sides
    could not cancel out."""

    def __init__(self) -> None:
        self._out = bytearray()
        self._acc = 0
        self._nbits = 0

    def put(self, value: int, n: int) -> None:
        self._acc |= (value & ((1 << n) - 1)) << self._nbits
        self._nbits += n
        while self._nbits >= 8:
            self._out.append(self._acc & 0xFF)
            self._acc >>= 8
            self._nbits -= 8

    def finish(self) -> bytes:
        if self._nbits:
            self._out.append(self._acc & 0xFF)
        return bytes(self._out)


def pack_pixels(grid: list[list[int]], advance: int, height: int, bpp: int, align: int) -> bytes:
    """`grid` (row-major, one level 0..2**bpp-1 per pixel) packed exactly the
    way `.cft` glyph cells are: LSB-first within a byte, each row padded to
    `align` bytes."""
    ppb = 8 // bpp
    bytes_to_count = -(-advance // ppb)
    byte_width = -(-bytes_to_count // align) * align
    out = bytearray(byte_width * height)
    for row in range(height):
        row_off = row * byte_width
        for x in range(advance):
            value = grid[row][x] & ((1 << bpp) - 1)
            out[row_off + x // ppb] |= value << ((x % ppb) * bpp)
    return bytes(out)


def _bits_of_bytes(data: bytes, chunk_size: int, n_symbols: int) -> list[int]:
    """`data` read as a stream of `chunk_size`-bit symbols, LSB-first,
    zero-padded past `data`'s own length -- the encoder's mirror of what
    `_rle_decode`'s bit reader produces, used only to pick run lengths."""
    total_bits = len(data) * 8
    symbols = []
    bitpos = 0
    for _ in range(n_symbols):
        value = 0
        for i in range(chunk_size):
            idx = bitpos + i
            bit = (data[idx // 8] >> (idx % 8)) & 1 if idx < total_bits else 0
            value |= bit << i
        symbols.append(value)
        bitpos += chunk_size
    return symbols


def _tokens_from_symbols(symbols: list[int], escape: int) -> list[tuple]:
    """Symbols -> `("literal", v)` / `("run", r)` / `("escape_literal",)`
    tokens. A run of the escape value is always spelled out as repeated
    `escape_literal`s (an `r=0` after a run marker would be ambiguous with
    a fresh literal-escape read); a run of >= 3 of any other value uses a
    genuine run marker (`r = run_len - 2`, since the marker's own literal
    plus its `(r+1)`-repeat must total `run_len`, and `r=0`/`r=1` would
    themselves be a 1- or 2-long run, not worth a marker); anything shorter
    is spelled out as separate literals. This exercises the same three
    decode paths the plan asks for (an escape literal, a run > 1, and,
    depending on chunk size, a chunk straddling a byte boundary) driven by
    real pixel content, not hand-assembled bitstreams.
    """
    tokens: list[tuple] = []
    i, n = 0, len(symbols)
    while i < n:
        value = symbols[i]
        run_len = 1
        while i + run_len < n and symbols[i + run_len] == value:
            run_len += 1
        if value == escape:
            tokens.extend([("escape_literal",)] * run_len)
        elif run_len >= 3:
            tokens.append(("literal", value))
            tokens.append(("run", run_len - 2))
        else:
            tokens.extend([("literal", value)] * run_len)
        i += run_len
    return tokens


def _encode_tokens(run_bits: int, chunk_size: int, escape: int, tokens: list[tuple]) -> bytes:
    writer = _TestBitWriter()
    for _ in range(run_bits - 1):
        writer.put(0, 1)
    writer.put(1, 1)
    writer.put(chunk_size - 1, 5)
    writer.put(escape, chunk_size)
    for token in tokens:
        kind = token[0]
        if kind == "literal":
            writer.put(token[1], chunk_size)
        elif kind == "escape_literal":
            writer.put(escape, chunk_size)
            writer.put(0, run_bits)
        elif kind == "run":
            writer.put(escape, chunk_size)
            writer.put(token[1], run_bits)
        else:
            raise ValueError(kind)
    return writer.finish()


def rle_encode_bytes(packed: bytes, size: int, chunk_size: int, run_bits: int, escape: int) -> bytes:
    n_symbols = -(-(size * 8) // chunk_size)
    symbols = _bits_of_bytes(packed, chunk_size, n_symbols)
    tokens = _tokens_from_symbols(symbols, escape)
    return _encode_tokens(run_bits, chunk_size, escape, tokens)


def _encode_glyph_rle(grid, advance, height, bpp, align, chunk_size, run_bits, escape) -> bytes:
    packed = pack_pixels(grid, advance, height, bpp, align)
    ppb = 8 // bpp
    bytes_to_count = -(-advance // ppb)
    byte_width = -(-bytes_to_count // align) * align
    size = byte_width * height
    return rle_encode_bytes(packed, size, chunk_size, run_bits, escape)


def _pack_glyph_word(offset: int, advance: int) -> bytes:
    """The inverse of `cft.py`'s glyph-info decode:
    `glyph_offset = ((word>>16)&0xffff) + ((word&0xff00)<<8)`,
    `advance = word&0xff`. Solved for the big-endian bytes `[b0, b1, b2,
    b3]` such that `word = b0<<24|b1<<16|b2<<8|b3`."""
    b2 = (offset >> 16) & 0xFF
    remainder = offset & 0xFFFF
    b0 = (remainder >> 8) & 0xFF
    b1 = remainder & 0xFF
    b3 = advance & 0xFF
    return bytes([b0, b1, b2, b3])


def write_cft(
    path: Path,
    *,
    header_size: int,
    rle: bool,
    bpp: int,
    glyphs: list[tuple[int, list[list[int]]]],
    cmap_groups: list[tuple[int, int, int]],
    align: int = 1,
    zlib_variant: str | None = None,
    height: int,
    ascent: int,
    leading: int = 0,
    rle_chunk_size: int | None = None,
    rle_run_bits: int = 4,
    rle_escape: int | None = None,
) -> None:
    """Write a synthetic `.cft` file at `path`.

    `glyphs` is `[(advance, grid), ...]` in glyph-index order (index 0 is
    the "missing glyph" box a cmap miss falls back to). `cmap_groups` is
    `[(start, end, start_glyph), ...]`, written in the given order (a later
    group overwrites an earlier one for an overlapping codepoint, matching
    the format's own semantics).
    """
    if rle_chunk_size is None:
        rle_chunk_size = bpp
    if rle_escape is None:
        rle_escape = (1 << rle_chunk_size) - 1

    flags = (0x02 if rle else 0) | (0x04 if bpp == 2 else 0)
    ppb = 8 // bpp

    glyph_words = []
    glyph_blobs = []
    cursor = 0
    for advance, grid in glyphs:
        if rle:
            blob = _encode_glyph_rle(
                grid, advance, height, bpp, align, rle_chunk_size, rle_run_bits, rle_escape
            )
        else:
            blob = pack_pixels(grid, advance, height, bpp, align)
        glyph_words.append(_pack_glyph_word(cursor, advance))
        glyph_blobs.append(blob)
        cursor += len(blob)
    glyph_info_section = b"".join(glyph_words)
    glyph_data = b"".join(glyph_blobs)

    if header_size == 40:
        if zlib_variant == "raw":
            glyph_data_section = struct.pack(">I", 0xD000000D) + glyph_data
        elif zlib_variant == "length_prefixed":
            body = zlib.compress(glyph_data)
            glyph_data_section = struct.pack(">II", 0xCD00000D, len(body)) + body
        else:  # "default": a bare length word, then zlib
            body = zlib.compress(glyph_data)
            glyph_data_section = struct.pack(">I", len(body)) + body
    else:
        glyph_data_section = glyph_data

    cmap_section = bytearray(16)
    struct.pack_into(">I", cmap_section, 12, len(cmap_groups))
    for start, end, start_glyph in cmap_groups:
        cmap_section += struct.pack(">III", start, end, start_glyph)

    cmap_offset = header_size
    glyph_info_offset = cmap_offset + len(cmap_section)
    glyph_data_offset = glyph_info_offset + len(glyph_info_section)
    total_length = glyph_data_offset + len(glyph_data_section)

    header = bytearray(header_size)
    struct.pack_into(">H", header, 0, header_size)
    header[3] = flags
    struct.pack_into(">I", header, 4, total_length)
    struct.pack_into(">III", header, 8, cmap_offset, glyph_info_offset, glyph_data_offset)
    struct.pack_into(">HHH", header, 22, height, ascent, leading)
    if header_size == 40:
        header[36] = align

    path.write_bytes(bytes(header) + bytes(cmap_section) + glyph_info_section + glyph_data_section)


def _flatten(grid: list[list[int]]) -> bytes:
    return bytes(v for row in grid for v in row)


# ---------------------------------------------------------------------------
# 36-byte header, RLE, 2 bpp
# ---------------------------------------------------------------------------


def test_escape_literal_round_trips(tmp_path):
    """A pixel whose level equals the RLE escape value, appearing on its
    own (not as part of a run), must decode via the `r=0` "this escape read
    is actually a literal" path -- plan 10 §3
    A.3's "escape literal (r=0)" case."""
    escape = 3  # max level at 2 bpp
    grid = [
        [0, 1, 2, escape],
        [escape, 0, 1, 2],
        [1, 2, escape, 0],
        [2, escape, 0, 1],
        [0, 0, 0, 0],
    ]
    path = tmp_path / "escape.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=5, ascent=4,
        glyphs=[(4, grid)], cmap_groups=[(65, 65, 0)],
    )
    font = cft.load(path)
    assert font is not None
    glyph = font.glyph("A")
    assert glyph.advance == 4
    assert glyph.height == 5
    assert glyph.levels == _flatten(grid)


def test_run_longer_than_one_round_trips(tmp_path):
    """A stretch of >= 3 repeated pixel values must decode via the run
    marker (`r >= 1`, repeating the previous literal `r + 1` times) --
    §3 A.3's "a run longer than one value" case."""
    grid = [
        [1, 1, 1, 1, 2, 0, 3, 1],
        [0, 0, 0, 2, 2, 2, 2, 2],
        [3, 3, 3, 3, 1, 0, 2, 1],
        [1, 2, 3, 0, 1, 2, 3, 0],
    ]
    path = tmp_path / "run.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=4, ascent=3,
        glyphs=[(8, grid)], cmap_groups=[(66, 66, 0)],
    )
    font = cft.load(path)
    assert font is not None
    glyph = font.glyph("B")
    assert glyph.levels == _flatten(grid)


def test_rle_chunk_straddles_a_byte_boundary(tmp_path):
    """A `run_bits`/`chunk_size` combination whose header does not end on a
    byte boundary (3 unary bits + 5 + 3 = 11 bits here) forces later chunk
    reads to straddle a byte in the underlying stream -- §3 A.3's "a chunk
    that straddles a byte boundary" case. The RLE chunk size (3 bits) is
    deliberately unrelated to the pixel bpp (2): the codec compresses the
    packed-pixel byte stream generically, not per-pixel."""
    grid = [[(r + c) % 3 for c in range(10)] for r in range(4)]
    path = tmp_path / "straddle.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=4, ascent=3,
        glyphs=[(10, grid)], cmap_groups=[(67, 67, 0)],
        rle_chunk_size=3, rle_run_bits=3, rle_escape=7,
    )
    font = cft.load(path)
    assert font is not None
    glyph = font.glyph("C")
    assert glyph.levels == _flatten(grid)


def test_cmap_miss_falls_back_to_glyph_zero(tmp_path):
    grid0 = [[1, 1], [1, 1]]
    grid1 = [[2, 2, 2], [2, 2, 2]]
    path = tmp_path / "cmapmiss.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=2, ascent=2,
        glyphs=[(2, grid0), (3, grid1)],
        cmap_groups=[(66, 66, 1)],  # only 'B' is mapped, to glyph 1
    )
    font = cft.load(path)
    assert font is not None
    missing = font.glyph("Z")  # never in any cmap group
    assert missing.advance == 2
    assert missing.levels == _flatten(grid0)
    assert font.advance("Z") == 2
    mapped = font.glyph("B")
    assert mapped.advance == 3
    assert mapped.levels == _flatten(grid1)


def test_multi_group_cmap(tmp_path):
    """Several disjoint cmap groups each resolve their own range; a
    codepoint in none of them still falls back to glyph 0."""
    grid0 = [[0, 0]]
    grid_a = [[1, 1]]
    grid_x = [[2, 2]]
    path = tmp_path / "multigroup.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=1, ascent=1,
        glyphs=[(2, grid0), (2, grid_a), (2, grid_x)],
        cmap_groups=[(65, 65, 1), (88, 90, 2)],  # 'A'->1; 'X'..'Z'->2,3,4 (only 2 exists)
    )
    font = cft.load(path)
    assert font is not None
    assert font.glyph("A").levels == _flatten(grid_a)
    assert font.glyph("X").levels == _flatten(grid_x)
    assert font.glyph("Q").levels == _flatten(grid0)  # unmapped -> glyph 0


def test_truncated_file_returns_none(tmp_path):
    grid = [[1, 1], [1, 1]]
    full = tmp_path / "full.cft"
    write_cft(
        full, header_size=36, rle=True, bpp=2, height=2, ascent=2,
        glyphs=[(2, grid)], cmap_groups=[(65, 65, 0)],
    )
    truncated = tmp_path / "truncated.cft"
    truncated.write_bytes(full.read_bytes()[:20])  # cuts off inside the header
    assert cft.load(truncated) is None


def test_missing_file_returns_none(tmp_path):
    assert cft.load(tmp_path / "does-not-exist.cft") is None


def test_garbage_header_size_returns_none(tmp_path):
    path = tmp_path / "garbage.cft"
    path.write_bytes(struct.pack(">H", 12) + bytes(50))  # neither 36 nor 40
    assert cft.load(path) is None


# ---------------------------------------------------------------------------
# 36-byte header, raw (non-RLE), 1 bpp
# ---------------------------------------------------------------------------


def test_raw_1bpp_36_byte_header_round_trips(tmp_path):
    grid_a = [[1, 0, 1, 0, 1], [0, 1, 0, 1, 0], [1, 1, 1, 0, 0]]
    grid_b = [[0, 0, 1, 1, 1, 0, 1], [1, 0, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1]]
    path = tmp_path / "raw1bpp.cft"
    write_cft(
        path, header_size=36, rle=False, bpp=1, height=3, ascent=2,
        glyphs=[(5, grid_a), (7, grid_b)],
        cmap_groups=[(65, 66, 0)],  # 'A'->0, 'B'->1
    )
    font = cft.load(path)
    assert font is not None
    assert font.height == 3
    assert font.ascent == 2
    assert font.bpp == 1
    assert font.max_level == 1
    a = font.glyph("A")
    assert a.advance == 5
    assert a.levels == _flatten(grid_a)
    b = font.glyph("B")
    assert b.advance == 7
    assert b.levels == _flatten(grid_b)
    assert font.advances("AB") == [5, 7]


# ---------------------------------------------------------------------------
# 40-byte header, zlib, 1 bpp, row alignment 8 -- all three maybe-compressed
# magic variants (plan 10 §2.2)
# ---------------------------------------------------------------------------


def _zlib_grid_case():
    # advance=9 forces a non-multiple-of-8 row, which align=8 pads to 2
    # bytes/row -- exercises the alignment math, not just the zlib framing.
    grid = [[(r ^ c) & 1 for c in range(9)] for r in range(6)]
    return grid


@pytest.mark.parametrize("variant", ["length_prefixed", "raw", "default"])
def test_zlib_40_byte_header_align8_round_trips(tmp_path, variant):
    grid = _zlib_grid_case()
    path = tmp_path / f"zlib-{variant}.cft"
    write_cft(
        path, header_size=40, rle=False, bpp=1, align=8, height=6, ascent=5,
        glyphs=[(9, grid)], cmap_groups=[(68, 68, 0)],
        zlib_variant=variant,
    )
    font = cft.load(path)
    assert font is not None
    assert font.height == 6
    assert font.ascent == 5
    assert font.bpp == 1
    glyph = font.glyph("D")
    assert glyph.advance == 9
    assert glyph.levels == _flatten(grid)


# ---------------------------------------------------------------------------
# the watched-fail check (docs/lore/working-agreement.md: "a guard nobody
# has watched fail is not a guard") -- see the report for the manual run
# that broke cft._BitReader.get to MSB-first and confirmed these tests went
# red before this file was finalised. Kept here as a lightweight in-suite
# echo of that check, run against a deliberately-wrong decode of the same
# fixture the RLE tests use.
# ---------------------------------------------------------------------------


def test_a_broken_bit_order_is_caught(tmp_path):
    """Decoding the same RLE stream MSB-first instead of LSB-first must not
    silently agree with the real (LSB-first) grid -- proof that
    `test_run_longer_than_one_round_trips`'s assertion is not a tautology
    that would pass no matter how the bits are read."""
    grid = [
        [1, 1, 1, 1, 2, 0, 3, 1],
        [0, 0, 0, 2, 2, 2, 2, 2],
        [3, 3, 3, 3, 1, 0, 2, 1],
        [1, 2, 3, 0, 1, 2, 3, 0],
    ]
    path = tmp_path / "run.cft"
    write_cft(
        path, header_size=36, rle=True, bpp=2, height=4, ascent=3,
        glyphs=[(8, grid)], cmap_groups=[(66, 66, 0)],
    )
    font = cft.load(path)
    assert font is not None

    raw = path.read_bytes()
    glyph_data_offset = struct.unpack_from(">I", raw, 16)[0]
    msb_first = _rle_decode_msb_first(raw, glyph_data_offset, len(pack_pixels(grid, 8, 4, 2, 1)))
    assert msb_first != _flatten(grid)


def _rle_decode_msb_first(data: bytes, offset: int, size: int) -> bytes:
    """A deliberately-wrong sibling of `cft._rle_decode` that reads bits
    MSB-first -- used only to prove the real decoder's LSB-first choice is
    load-bearing, not to be trusted for anything else."""

    class _MsbReader:
        def __init__(self, data, offset):
            self._data = data
            self._pos = offset
            self._acc = 0
            self._nbits = 0

        def get(self, n):
            while self._nbits < n:
                self._acc = (self._acc << 8) | self._data[self._pos]
                self._pos += 1
                self._nbits += 8
            self._nbits -= n
            result = (self._acc >> self._nbits) & ((1 << n) - 1)
            self._acc &= (1 << self._nbits) - 1
            return result

    reader = _MsbReader(data, offset)
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


# ---------------------------------------------------------------------------
# real files (vendor/fonts/, the user's own licensed Garmin fonts) -- skip
# cleanly when absent, and explicit relative-to-repo-root paths per the plan
# ---------------------------------------------------------------------------


def test_real_fenix6_roboto_20b(repo_root):
    path = repo_root / "vendor" / "fonts" / "FNT_FENIX6_CDPG_ROBOTO_20B.cft"
    if not path.is_file():
        pytest.skip("vendor/fonts/FNT_FENIX6_CDPG_ROBOTO_20B.cft not present")

    raw = path.read_bytes()
    assert raw[3] == 0x06  # flags: RLE (bit 1) + 2 bpp (bit 2)

    font = cft.load(path)
    assert font is not None
    assert font.height == 32
    assert font.ascent == 25
    assert font.bpp == 2

    digit_advances = font.advances("0123456789")
    assert all(a > 0 for a in digit_advances)
    assert len(set(digit_advances)) == 1  # a fixed-width numeral ladder

    glyph = font.glyph("A")
    assert glyph.height == font.height
    ink_rows = {i // glyph.advance for i, v in enumerate(glyph.levels) if v}
    assert ink_rows, "glyph 'A' decoded to a completely blank cell"
    assert min(ink_rows) >= 0
    assert max(ink_rows) < font.height


def test_real_fr255_roboto_15b_zlib(repo_root):
    path = repo_root / "vendor" / "fonts" / "FNT_006B402400_CDPG_ROBOTO_15B.cft"
    if not path.is_file():
        pytest.skip("vendor/fonts/FNT_006B402400_CDPG_ROBOTO_15B.cft not present")

    font = cft.load(path)
    assert font is not None
    assert font.height == 24
    assert font.ascent == 19
    assert font.bpp == 1
