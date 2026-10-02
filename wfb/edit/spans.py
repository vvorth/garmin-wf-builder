"""The span index: every `key: value` entry of a design's text, with the
exact character range of its key and value.

ruamel's composer (`YAML().compose`) gives every node a `start_mark` and an
`end_mark`, which are character offsets into the text. A patch rewrites
those characters and nothing else, so every byte outside an edit is left
alone. `wfb.yamlsrc` keeps only start positions (`lc`), which is enough for
a diagnostic but not for a rewrite.

Two facts about the marks every range here relies on:

- **A block value ends where the next token starts.** Its end mark sits at
  the next key's column on the following line (or at the end of the text),
  not at a line start.
- A flow value's or a plain scalar's end mark sits inside its own last
  line, just past its last character.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Iterator

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from ..diagnostics import Span

#: One step of an author path: a mapping key or a sequence index.
Step = str | int
Path = tuple[Step, ...]

#: The keys whose value is a mapping of element id to element: the top
#: level's and a layout's `elements:`/`static:`, and a group's `children:`.
ELEMENT_BLOCKS = frozenset({"elements", "static", "children"})


class Refused(ValueError):
    """A patch that cannot be made, or that the gate would not accept. The
    message says why, in the author's terms."""


@dataclass(frozen=True)
class Entry:
    """One `key: value` pair of a block or flow mapping."""

    path: Path
    key: ScalarNode
    value: Node
    #: The mapping holding this entry.
    parent: MappingNode

    @property
    def name(self) -> str:
        return str(self.key.value)

    @property
    def is_flow(self) -> bool:
        """Whether the mapping holding this entry is a flow mapping."""
        return bool(self.parent.flow_style)


def compose(text: str) -> Node | None:
    try:
        node: Node | None = YAML().compose(io.StringIO(text))
        return node
    except MarkedYAMLError as exc:
        raise Refused(f"the text is not valid YAML: {(exc.problem or 'invalid YAML').strip()}"
                      ) from None


def parse(text: str) -> Any:
    """The plain data ``text`` parses to: dicts in key order, lists and
    scalars, with no comments or positions. What the gate compares."""
    try:
        return YAML(typ="safe", pure=True).load(io.StringIO(text))
    except MarkedYAMLError as exc:
        raise Refused(f"the text is not valid YAML: {(exc.problem or 'invalid YAML').strip()}"
                      ) from None


def line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def line_end(text: str, index: int) -> int:
    """The index just past the newline ending the line ``index`` is on."""
    end = text.find("\n", index)
    return len(text) if end < 0 else end + 1


def indent_of(text: str, index: int) -> int:
    start = line_start(text, index)
    line = text[start:line_end(text, index)]
    return len(line) - len(line.lstrip(" "))


class SpanIndex:
    """A design's text, its composed node tree and its plain data, with
    every mapping entry addressable by its author path."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.root = compose(text)
        self.data = parse(text)
        self._entries = list(_entries(self.root, ())) if self.root is not None else []
        self._by_path = {e.path: e for e in self._entries}
        self._by_position = {(e.key.start_mark.line + 1, e.key.start_mark.column + 1): e
                             for e in self._entries}
        #: The entry whose value is a given mapping node, by node identity.
        self._holder = {id(e.value): e for e in self._entries}

    # -- lookup -------------------------------------------------------------

    def entries(self) -> list[Entry]:
        return list(self._entries)

    def get(self, path: Path) -> Entry | None:
        return self._by_path.get(tuple(path))

    def __getitem__(self, path: Path) -> Entry:
        entry = self.get(path)
        if entry is None:
            raise Refused(f"{dotted(path)} is not in the file")
        return entry

    def at_span(self, span: Span | None) -> Entry | None:
        """The entry whose key starts at ``span`` -- an `Element.span`, the
        1-based line and column of the element's key."""
        if span is None:
            return None
        return self._by_position.get((span.line, span.col))

    def holder(self, mapping: Node) -> Entry | None:
        """The entry whose value is ``mapping``, or ``None`` at the top."""
        return self._holder.get(id(mapping))

    def elements(self) -> list[Entry]:
        """Every element entry, in document order: a key of an element
        block (`ELEMENT_BLOCKS`) whose value is a mapping with a `type:`."""
        return [e for e in self._entries if is_element(self, e)]

    def element_ids(self) -> set[str]:
        return {e.name for e in self.elements()}

    # -- ranges -------------------------------------------------------------

    def entry_range(self, entry: Entry) -> tuple[int, int]:
        """Whole lines, from the entry's leading comment lines (at the key's
        own indent) to its value's last line, newline included. Trailing
        blank lines and shallower comments are left to what follows."""
        text = self.text
        start = line_start(text, entry.key.start_mark.index)
        indent = entry.key.start_mark.column
        while start > 0:
            prev = line_start(text, start - 1)
            line = text[prev:start - 1]
            if line.strip().startswith("#") and len(line) - len(line.lstrip()) == indent:
                start = prev
            else:
                break
        return start, self.value_end(entry)

    def value_end(self, entry: Entry) -> int:
        """Just past the newline of the value's last line, skipping the
        blank lines and comments a block value's end mark swallows."""
        text = self.text
        end_index = entry.value.end_mark.index
        head = line_start(text, end_index)
        if text[head:end_index].strip() == "" and end_index > entry.key.start_mark.index:
            end = head  # a block value: everything before the next token's line
        else:
            end = line_end(text, max(end_index - 1, 0))
        key_line = line_start(text, entry.key.start_mark.index)
        indent = entry.key.start_mark.column
        while end > key_line:
            last = line_start(text, end - 1)
            if last <= key_line:
                break
            line = text[last:end].rstrip("\n")
            stripped = line.strip()
            if stripped == "" or (stripped.startswith("#")
                                  and len(line) - len(line.lstrip()) <= indent):
                end = last
            else:
                break
        return end


def is_element(index: SpanIndex, entry: Entry) -> bool:
    if not isinstance(entry.value, MappingNode):
        return False
    if not any(isinstance(k, ScalarNode) and k.value == "type" for k, _ in entry.value.value):
        return False
    block = index.holder(entry.parent)
    return block is not None and block.name in ELEMENT_BLOCKS


def dotted(path: Path) -> str:
    return ".".join(str(p) for p in path)


def _entries(node: Node, path: Path) -> Iterator[Entry]:
    if isinstance(node, MappingNode):
        for k, v in node.value:
            if isinstance(k, ScalarNode):
                here = path + (str(k.value),)
                yield Entry(here, k, v, node)
                yield from _entries(v, here)
    elif isinstance(node, SequenceNode):
        for i, v in enumerate(node.value):
            yield from _entries(v, path + (i,))
