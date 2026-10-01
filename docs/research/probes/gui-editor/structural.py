"""The editor's structural text patches, over the example corpus.

Backs docs/research/28-editor-open-questions.md §2-§3. Host-side only.

    ./.venv/bin/python docs/research/probes/gui-editor/structural.py

Every patch edits the file's *text* only, located by the composed node
tree's marks (`YAML().compose`), and is accepted only when the patched text

1. still loads through the full pipeline with no new error, and
2. parses (safe loader) to exactly the expected data: the original data
   with the one intended change, and nothing else different.

The edits, per element-carrying face (every example except the user's
playground):

- **map**: every element in `Face.walk()` found by its `span` (the 1-based
  line:col of its key) in the composed tree;
- **set-absent**: add `dx: 1%r` to an `at:` that has no `dx` (flow or block);
- **remove**: delete `dy` from an `at:` that has one;
- **delete**: remove an element's entry (its leading comment lines too);
- **duplicate**: copy an element's entry under `<id>_copy`, right after it;
- **reorder**: move an element above its previous sibling;
- **add**: append a new `rectangle` element at the end of `elements:`.

A delete, duplicate or reorder that the *compiler* rejects for a reason
the patch did not cause (the copy's id clashes with a slot, a reference to
the deleted element) is counted separately as "refused by the compiler".
"""

from __future__ import annotations

import copy
import glob
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.nodes import MappingNode, ScalarNode  # noqa: E402

from wfb.build import load  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402

OUT: list[str] = []
FACES = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
               if "examples/dashboard/" not in f)


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def data_of(text: str):
    return YAML(typ="safe").load(text)


def compiles(path: Path, text: str) -> tuple[bool, list[str]]:
    probe = path.with_name(".gui-probe.yaml")
    probe.write_text(text, encoding="utf-8")
    bag = Bag()
    try:
        face = load(probe, bag)
    finally:
        probe.unlink()
    errors = [d.message for d in bag.errors]
    return face is not None and not errors, errors


# -- the span index -------------------------------------------------------------

class Entry:
    """One `key: value` pair of a block or flow mapping, with its text range."""

    def __init__(self, parent: MappingNode, key: ScalarNode, value, path: tuple):
        self.parent, self.key, self.value, self.path = parent, key, value, path


def entries(node, path=()):
    if isinstance(node, MappingNode):
        for k, v in node.value:
            if isinstance(k, ScalarNode):
                yield Entry(node, k, v, path + (k.value,))
                yield from entries(v, path + (k.value,))
    elif hasattr(node, "value") and isinstance(node.value, list):
        for i, v in enumerate(node.value):
            yield from entries(v, path + (i,))


def by_position(root) -> dict[tuple[int, int], Entry]:
    return {(e.key.start_mark.line + 1, e.key.start_mark.column + 1): e for e in entries(root)}


def line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def line_end(text: str, index: int) -> int:
    """The index just past the newline ending the line ``index`` is on."""
    end = text.find("\n", index)
    return len(text) if end < 0 else end + 1


def entry_range(text: str, e: Entry) -> tuple[int, int]:
    """Whole lines from the entry's leading comments to its value's last
    line.  A block value's end mark sits at the start of the line after it;
    a flow value's (or scalar's) inside its last line."""
    start = line_start(text, e.key.start_mark.index)
    indent = e.key.start_mark.column
    while start > 0:
        prev = line_start(text, start - 1)
        line = text[prev:start - 1]
        if line.strip().startswith("#") and len(line) - len(line.lstrip()) == indent:
            start = prev
        else:
            break
    end_index = e.value.end_mark.index
    head = line_start(text, end_index)
    if text[head:end_index].strip() == "" and end_index > e.key.start_mark.index:
        # a block value ends where the next token starts: at that line's
        # indentation, so the value is everything before that line
        end = head
    else:
        end = line_end(text, end_index - 1 if end_index else 0)
    # a block value's end mark may already include trailing blank/comment
    # lines that belong to the next entry: trim back to the value's last
    # non-blank, non-comment line at deeper indent
    body = text[start:end].split("\n")
    while len(body) > 1 and (body[-1] == "" or body[-1].strip() == ""
                             or (body[-1].lstrip().startswith("#")
                                 and len(body[-1]) - len(body[-1].lstrip()) <= indent)):
        body.pop()
    return start, start + len("\n".join(body)) + 1


def mapping_style_flow(node: MappingNode) -> bool:
    return bool(node.flow_style)


# -- the patches -------------------------------------------------------------------

def set_absent(text: str, at: MappingNode, key: str, value: str) -> str:
    if mapping_style_flow(at):
        close = at.end_mark.index - 1                 # the `}`
        assert text[close] == "}", text[close - 5:close + 5]
        before = text[:close].rstrip()
        sep = "" if before.endswith("{") else ","
        pad = " " if text[close - 1] == " " else ""
        return before + f"{sep} {key}: {value}" + pad + text[close:]
    last_key = at.value[-1][0]
    indent = last_key.start_mark.column
    end = line_end(text, at.value[-1][1].end_mark.index - 1)
    return text[:end] + " " * indent + f"{key}: {value}\n" + text[end:]


def remove_key(text: str, at: MappingNode, key: str) -> str:
    pairs = at.value
    i = next(i for i, (k, _) in enumerate(pairs) if k.value == key)
    k, v = pairs[i]
    if mapping_style_flow(at):
        start, end = k.start_mark.index, v.end_mark.index
        if i + 1 < len(pairs):                        # eat the following ", "
            end = pairs[i + 1][0].start_mark.index
        elif i > 0:                                   # eat the preceding ", "
            start = pairs[i - 1][1].end_mark.index
        return text[:start] + text[end:]
    start = line_start(text, k.start_mark.index)
    return text[:start] + text[line_end(text, v.end_mark.index - 1):]


def delete_entry(text: str, e: Entry, parent: Entry | None = None) -> str:
    """Remove the entry.  When it is its mapping's only entry, ``parent``
    (the key holding that mapping) goes too: an emptied block mapping
    would otherwise parse as null."""
    if parent is not None and len(e.parent.value) == 1:
        e = parent
    start, end = entry_range(text, e)
    return text[:start] + text[end:]


def duplicate_entry(text: str, e: Entry, suffix: str, element_keys: list[ScalarNode]) -> str:
    """Copy the entry right after itself, every element id inside it --
    its own key and each descendant element's -- renamed with ``suffix``,
    so a copied group's children do not clash with the originals."""
    start, end = entry_range(text, e)
    block = text[start:end]
    inside = sorted((k for k in element_keys if start <= k.start_mark.index < end),
                    key=lambda k: k.start_mark.index, reverse=True)
    for k in inside:
        at = k.start_mark.index - start
        block = block[:at] + k.value + suffix + block[at + len(k.value):]
    # leading comments are not copied
    first = e.key.start_mark.index - start
    return text[:end] + block[line_start(block, first):] + text[end:]


def swap_with_previous(text: str, prev: Entry, e: Entry) -> str:
    a0, a1 = entry_range(text, prev)
    b0, b1 = entry_range(text, e)
    return text[:a0] + text[b0:b1] + text[a1:b0] + text[a0:a1] + text[b1:]


def append_element(text: str, elements: Entry, block: dict[str, str]) -> str:
    node = elements.value
    if not isinstance(node, MappingNode) or node.flow_style or not node.value:
        raise ValueError("elements: is not a non-empty block mapping")
    first = node.value[0][0]
    indent = first.start_mark.column
    _, end = entry_range(text, Entry(node, node.value[-1][0], node.value[-1][1], ()))
    inner = " " * (indent + 2)
    lines = [" " * indent + "wfb_new_box:"] + [f"{inner}{k}: {v}" for k, v in block.items()]
    return text[:end] + "\n".join(lines) + "\n" + text[end:]


# -- expected data -----------------------------------------------------------------

def get(data, path):
    for p in path:
        data = data[p]
    return data


def parent_of(data, path):
    return get(data, path[:-1]), path[-1]


def reinsert(d: dict, items: list) -> None:
    d.clear()
    for k, v in items:
        d[k] = v


# -- the run -----------------------------------------------------------------------

def main() -> None:
    results: dict[str, list[int]] = {}   # edit -> [tried, accepted, refused by compiler]
    failures: list[str] = []

    def record(kind: str, path: Path, text: str, patched: str, expected, what: str) -> None:
        r = results.setdefault(kind, [0, 0, 0])
        r[0] += 1
        try:
            got = data_of(patched)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{kind} {path} {what}: does not parse: {exc}".splitlines()[0])
            return
        if got != expected or list(_walk_keys(got)) != list(_walk_keys(expected)):
            failures.append(f"{kind} {path} {what}: parsed data differs from the intended change")
            return
        ok, errors = compiles(path, patched)
        if ok:
            r[1] += 1
        else:
            r[2] += 1
            failures.append(f"{kind} {path} {what}: refused by the compiler: {errors[0][:90]}")

    mapped = total = 0
    for design in FACES:
        path = Path(design)
        text = path.read_text(encoding="utf-8")
        root = YAML().compose(io.StringIO(text))
        data = data_of(text)
        index = by_position(root)
        face = load(path, Bag())
        assert face is not None, design
        all_entries = list(entries(root))
        holder = {id(x.value): x for x in all_entries}
        found: dict[str, Entry] = {}
        for element in face.walk():
            total += 1
            span = element.span
            e = index.get((span.line, span.col)) if span else None
            if e is not None:
                mapped += 1
                found[element.id] = e
            else:
                failures.append(f"map {design} {element.id}: no entry at {span}")
        authored = {i: e for i, e in found.items()
                    if isinstance(e.value, MappingNode)
                    and any(k.value == "type" for k, _ in e.value.value)}

        # set-absent and remove, on the first few `at:` mappings
        done_set = done_rm = 0
        for element_id, e in authored.items():
            at = next((v for k, v in e.value.value if k.value == "at"), None)
            if not isinstance(at, MappingNode) or any(k.value == "angle" for k, _ in at.value):
                continue
            keys = [k.value for k, _ in at.value]
            if "dx" not in keys and done_set < 3:
                expected = copy.deepcopy(data)
                get(expected, e.path)["at"]["dx"] = "1%r"
                record("set-absent", path, text, set_absent(text, at, "dx", "1%r"), expected,
                       f"{element_id} ({'flow' if at.flow_style else 'block'})")
                done_set += 1
            if "dy" in keys and len(keys) > 1 and done_rm < 3:
                expected = copy.deepcopy(data)
                del get(expected, e.path)["at"]["dy"]
                record("remove", path, text, remove_key(text, at, "dy"), expected,
                       f"{element_id} ({'flow' if at.flow_style else 'block'})")
                done_rm += 1

        # delete, duplicate, reorder: up to three elements per face
        for element_id, e in list(authored.items())[:3]:
            parent, key = parent_of(data, e.path)
            expected = copy.deepcopy(data)
            container = holder.get(id(e.parent))
            if len(e.parent.value) == 1 and container is not None:
                del get(expected, container.path[:-1])[container.path[-1]]
            else:
                del get(expected, e.path[:-1])[key]
            record("delete", path, text, delete_entry(text, e, container), expected, element_id)

            expected = copy.deepcopy(data)
            p = get(expected, e.path[:-1])
            items = list(p.items())
            i = [k for k, _ in items].index(key)
            ids = {x.id for x in face.walk()}
            items.insert(i + 1, (f"{key}_copy", _renamed(copy.deepcopy(p[key]), ids, "_copy")))
            reinsert(p, items)
            element_keys = [found[x].key for x in found]
            record("duplicate", path, text,
                   duplicate_entry(text, e, "_copy", element_keys), expected, element_id)

            siblings = [k for k, _ in e.parent.value]
            i = [k.value for k in siblings].index(key)
            if i > 0:
                prev_key = siblings[i - 1]
                prev_value = e.parent.value[i - 1][1]
                prev = Entry(e.parent, prev_key, prev_value, e.path[:-1] + (prev_key.value,))
                expected = copy.deepcopy(data)
                p = get(expected, e.path[:-1])
                items = list(p.items())
                items[i - 1], items[i] = items[i], items[i - 1]
                reinsert(p, items)
                record("reorder", path, text, swap_with_previous(text, prev, e), expected,
                       element_id)

        # add one element at the end of the top-level `elements:`
        top = next((e for e in entries(root) if e.path == ("elements",)), None)
        # a new element takes a colour the face already uses: the first
        # element's own `color:` in document order
        color = next((x.value.value for x in all_entries
                      if x.path[-1:] == ("color",) and isinstance(x.value, ScalarNode)
                      and x.value.value.startswith("color.")), None)
        if top is not None and color is not None:
            block = {"type": "rectangle", "at": "{ anchor: center }",
                     "size": "{ width: 10%, height: 10% }", "color": color}
            try:
                patched = append_element(text, top, block)
            except ValueError:
                pass
            else:
                expected = copy.deepcopy(data)
                expected["elements"]["wfb_new_box"] = {
                    "type": "rectangle", "at": {"anchor": "center"},
                    "size": {"width": "10%", "height": "10%"}, "color": color}
                record("add", path, text, patched, expected, "wfb_new_box")

    say("## structural text patches over the example corpus")
    say(f"map: {mapped}/{total} elements (groups, `static:` and layout blocks included) "
        f"found by their span in the composed tree")
    for kind, (tried, ok, refused) in results.items():
        say(f"{kind:<11} {ok}/{tried} accepted"
            + (f", {refused} refused by the compiler" if refused else ""))
    say("not accepted:")
    for f in failures:
        say("  " + f)
    Path(__file__).with_name("structural_results.txt").write_text("\n".join(OUT) + "\n",
                                                                   encoding="utf-8")


def _renamed(node, ids: set[str], suffix: str):
    """``node`` with every mapping key that is an element id renamed."""
    if isinstance(node, dict):
        return {(k + suffix if k in ids else k): _renamed(v, ids, suffix) for k, v in node.items()}
    if isinstance(node, list):
        return [_renamed(v, ids, suffix) for v in node]
    return node


def _walk_keys(node, path=()):
    """Every key path in document order, so a reorder is checked too."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + (k,)
            yield from _walk_keys(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_keys(v, path + (i,))


if __name__ == "__main__":
    main()
