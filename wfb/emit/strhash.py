"""Find string literals that `monkeyc` would give the same assembler label.

`monkeyc` 9.2.0 names each distinct string constant's data label
`str___<N>`, where `N` is the string's Java `String.hashCode()`. Two
*different* strings with the same hash therefore get the same label, and the
build dies inside `Compiler2.assembleProject` with "Redefinition of label
(data) str___<N>", which the user sees only as monkeyc's generic "A critical
error has occurred".

Reproduced directly (2026-09-13, docs/lore/toolchain.md): the `distance`
glyph U+F08F0 and the `temperature` glyph U+F050F both hash to 1798574, and
a slot whose `choices:` list holds just those two types fails, while
38 other types together build clean. A glyph above the Basic Multilingual
Plane is two UTF-16 code units `(hi, lo)`, whose hash is `31*hi + lo`, so two
glyphs collide whenever they are 993 codepoints apart within the right
range -- common in Material Design Icons.

This module only *finds* collisions. `wfb.emit.project.generate` resolves the
ones it can (an `IconGlyphs` glyph is rebuilt at runtime with
`Number.toChar`, so it is no longer a literal), and `wfb.build` reports the
rest as a build error instead of letting monkeyc crash.
"""

from __future__ import annotations

from dataclasses import dataclass

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}


def java_string_hash(text: str) -> int:
    """Java's `String.hashCode()`: over UTF-16 code units, as a signed 32-bit int."""
    units = text.encode("utf-16-be")
    value = 0
    for i in range(0, len(units), 2):
        value = (31 * value + int.from_bytes(units[i:i + 2], "big")) & 0xFFFFFFFF
    return value - (1 << 32) if value >= (1 << 31) else value


def string_literals(source: str) -> list[str]:
    """Every `"..."` literal in Monkey C `source`, unescaped.

    Skips `//` and `/* */` comments and `'x'` Char literals, so a quote
    inside a comment is not mistaken for a string.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end + 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "\"'":
            chars: list[str] = []
            i += 1
            while i < n and source[i] != c:
                if source[i] == "\\" and i + 1 < n:
                    chars.append(_ESCAPES.get(source[i + 1], source[i + 1]))
                    i += 2
                else:
                    chars.append(source[i])
                    i += 1
            i += 1
            if c == '"':
                out.append("".join(chars))
        else:
            i += 1
    return out


@dataclass(frozen=True)
class Collision:
    """Two or more distinct strings that would share one `str___<hash>` label."""

    hash: int
    #: Each colliding string -> the files it appears in.
    strings: dict[str, tuple[str, ...]]


def collisions(files: dict[str, str]) -> list[Collision]:
    """Hash collisions among every string literal in `files` (path -> source)."""
    by_hash: dict[int, dict[str, set[str]]] = {}
    for path, text in files.items():
        for literal in string_literals(text):
            by_hash.setdefault(java_string_hash(literal), {}).setdefault(literal, set()).add(path)
    return [
        Collision(h, {s: tuple(sorted(paths)) for s, paths in sorted(group.items())})
        for h, group in sorted(by_hash.items())
        if len(group) > 1
    ]


def describe(text: str) -> str:
    """A literal as a reader can see it: non-ASCII characters as `U+XXXX`."""
    if all(32 <= ord(ch) < 127 for ch in text):
        return repr(text)
    return '"' + "".join(ch if 32 <= ord(ch) < 127 else f"<U+{ord(ch):04X}>" for ch in text) + '"'
