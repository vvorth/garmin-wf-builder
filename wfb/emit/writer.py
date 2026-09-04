"""A tiny indentation-aware source writer.

Generated Monkey C is read by humans -- it is what the author debugs when a face
misbehaves on the wrist, and it is the substrate the escape hatch drops into
(ADR 0003).  Getting the indentation right by construction is cheaper than
formatting it afterwards.
"""

from __future__ import annotations


class Writer:
    def __init__(self, indent: str = "    ") -> None:
        self._lines: list[str] = []
        self._indent = indent
        self._level = 0

    def line(self, text: str = "") -> "Writer":
        self._lines.append(f"{self._indent * self._level}{text}" if text else "")
        return self

    def lines(self, *texts: str) -> "Writer":
        for text in texts:
            self.line(text)
        return self

    def blank(self) -> "Writer":
        if self._lines and self._lines[-1] != "":
            self._lines.append("")
        return self

    def comment(self, text: str, marker: str = "//") -> "Writer":
        for part in text.splitlines() or [""]:
            self.line(f"{marker} {part}".rstrip())
        return self

    def doc(self, text: str) -> "Writer":
        return self.comment(text, "//!")

    class _Block:
        def __init__(self, writer: "Writer", closing: str) -> None:
            self.writer, self.closing = writer, closing

        def __enter__(self) -> "Writer":
            self.writer._level += 1
            return self.writer

        def __exit__(self, *exc) -> None:
            self.writer._level -= 1
            self.writer.line(self.closing)

    def block(self, header: str, closing: str = "}") -> "_Block":
        self.line(f"{header} {{" if not header.endswith("{") else header)
        return Writer._Block(self, closing)

    def render(self) -> str:
        text = "\n".join(self._lines).rstrip("\n")
        return text + "\n"
