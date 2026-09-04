#!/usr/bin/env python3
"""Minimal stdlib HTML -> text for reading the offline Connect IQ docs."""
import re
import sys
from html.parser import HTMLParser


class T(HTMLParser):
    SKIP = {"script", "style", "head", "nav"}
    BLOCK = {
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5",
        "pre", "section", "table", "ul", "ol", "dt", "dd",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.row = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("td", "th"):
            self.in_cell = True
            self.row.append("")
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n" + "#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th"):
            self.in_cell = False
        elif tag == "tr":
            if self.row:
                self.out.append("\n| " + " | ".join(c.strip() for c in self.row) + " |")
                self.row = []
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, d):
        if self.skip:
            return
        if self.in_cell and self.row:
            self.row[-1] += d
        else:
            self.out.append(d)


def convert(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        p = T()
        p.feed(fh.read())
    txt = "".join(p.out)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return "\n".join(line.rstrip() for line in txt.splitlines()).strip()


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(f"\n{'=' * 70}\n### FILE: {f}\n{'=' * 70}")
        print(convert(f))
