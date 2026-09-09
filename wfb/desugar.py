"""Stage 0.5: rewrite the author's conveniences into the one shape everything
downstream already understands.

Two rewrites live here.  The first is **an element list written as a mapping
whose key is the element id**.

.. code-block:: yaml

    elements:            #  is rewritten to        elements:
      clock:             #                           - id: clock
        type: text       #                             type: text
        value: time.clock#                             value: time.clock

Both spellings are legal and neither is a new format version (ADR 0009: the
format did not change -- the *surface syntax* grew a second way to write
something the schema already accepted).  Putting the rewrite here, between
:func:`wfb.yamlsrc.load` and :func:`wfb.validate.validate`, is what keeps that
promise cheap: the JSON Schema, the IR, layout, lint, preview and codegen see
only the list form and are untouched by this file's existence.  Two spellings
that share every stage after this one cannot drift into meaning different
things -- which is the same anti-drift argument ADR 0004 makes for resolving
geometry once, and the reason the gate on this feature is that a mapping-form
design and its list-form twin generate byte-identical output.

Spans are the whole difficulty.  A diagnostic must point at the author's own
line (ADR 0002), so the rewritten sequence is not a fresh data structure: it is
a :class:`~ruamel.yaml.comments.CommentedSeq` holding the *same*
``CommentedMap`` bodies, with each item's position taken from the position of
the key that named it, and with the injected ``id`` key recorded in the body's
own ``lc`` so ``doc.span(node, "id")`` -- which is what ``wfb/ir.py`` already
calls for a duplicate id -- lands on the author's key rather than on nothing.

Deliberately **not** rewritten: a ``carousel``'s ``items:``.  Those are slots,
not elements; they have no id, and turning their (nonexistent) keys into ids
would silently mangle a real design.  Only two places in the schema take a list
of elements -- the top-level ``elements:`` and a ``group``'s ``children:`` --
and this pass rewrites exactly those two.

The second rewrite is the top-level ``static:`` block:

.. code-block:: yaml

    static:              #  is rewritten to        elements:
      ticks:             #                           - id: static
        type: shape      #                             type: group
    elements:            #                             static: true
      clock:             #                             children:
        type: text       #                               - id: ticks
                         #                                   type: shape
                         #                             - id: clock
                         #                               type: text

Same argument as above, and the same payoff: `static:` is a *spelling*, not a
second feature.  Everything downstream sees one ordinary ``group`` carrying
``static: true``, so the IR's gates, the emitter's buffer and the
``graphics-pool`` lint have exactly one shape to handle -- and the group lands
at the **front** of draw order for free, which is where an opaque static buffer
has to be (`docs/research/probes/static-buffer/`).

The synthetic group's id, :data:`STATIC_GROUP_ID`, is reserved: a design that
already uses it gets an error naming the collision rather than a confusing
``duplicate-id`` against a line that does not exist in the source.
"""

from __future__ import annotations

import re
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .diagnostics import Bag
from .yamlsrc import YamlDocument

#: ``#/$defs/identifier`` from ``schema/wfb-face-1.schema.json``, kept in step
#: with it by ``tests/test_desugar.py``, which reads the pattern out of the
#: schema rather than repeating it.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The id the top-level ``static:`` block's synthetic group is given.  Reserved:
#: an element that claims it is an error, because the two would collide into one
#: generated symbol and only one of them has a line in the source file.
STATIC_GROUP_ID = "static"

# The diagnostic codes this pass emits are `element-mapping` and `static`,
# written out as literals at each call site rather than through a constant so
# that `tests/test_lint.py`'s grep-based ALL_CODES registry can see them.  A
# duplicate key is not among them: ruamel's round-trip loader raises
# DuplicateKeyError before this file ever sees the document, and
# `wfb/yamlsrc.py`'s `load` already reports that as error[yaml] against the
# second key's own line -- verified, not assumed
# (`tests/test_desugar.py::test_a_duplicate_key_is_a_clear_diagnostic`).


def desugar(doc: YamlDocument, bag: Bag) -> bool:
    """Normalise ``doc`` in place.  False (with diagnostics) if it cannot be."""
    data = doc.data
    if not isinstance(data, dict):
        return True  # `validate.check_format_version` reports this properly
    ok = _rewrite(doc, data, "elements", bag)
    return _static_block(doc, data, bag) and ok


# --------------------------------------------------------------------------
# the top-level `static:` block


def _static_block(doc: YamlDocument, data: Any, bag: Bag) -> bool:
    """Fold ``static:`` into one ``group`` at the front of ``elements:``.

    Runs *after* the mapping-form rewrite above so that ``elements:`` is already
    a sequence to insert into; the block's own children are then put through the
    same rewrite, so ``static:`` accepts both spellings exactly as ``elements:``
    does.
    """
    if "static" not in data:
        return True
    node = data["static"]
    span = doc.span(data, "static", of="key")
    if not isinstance(node, (dict, list)) or not node:
        bag.error(
            "static",
            "the top-level `static:` block must be a list of elements or a "
            "mapping of id -> element",
            span,
            notes=["it takes the same two spellings `elements:` does",
                   "`static: true` on a single element is the other spelling of "
                   "this feature, and belongs *inside* `elements:`"],
        )
        return False

    group = CommentedMap()
    group["id"] = STATIC_GROUP_ID
    group["type"] = "group"
    group["static"] = True
    group["children"] = node
    if span is not None:
        line, col = span.line - 1, span.col - 1
        group.lc.line, group.lc.col = line, col
        for key in ("id", "type", "static", "children"):
            group.lc.add_kv_line_col(key, [line, col, line, col])

    ok = _rewrite(doc, group, "children", bag)

    elements = data.get("elements")
    if elements is None:
        elements = CommentedSeq()
        data["elements"] = elements
    if not isinstance(elements, list):
        # The mapping-form rewrite above failed and already said why; leaving
        # `elements:` as the author wrote it keeps that diagnostic honest.
        return False
    for existing in elements:
        if isinstance(existing, dict) and existing.get("id") == STATIC_GROUP_ID:
            bag.error(
                "static",
                f"the id {STATIC_GROUP_ID!r} is reserved while a top-level "
                "`static:` block is present",
                doc.span(existing, "id") or span,
                notes=["the block is rewritten into a group under that id, and "
                       "two elements cannot share one",
                       "rename this element, or drop the `static:` block and put "
                       "`static: true` on the group you want buffered"],
            )
            return False
    elements.insert(0, group)
    if hasattr(elements, "lc"):
        # Every existing item shifted one place along; without this each one's
        # span would be read off the item that used to sit at that index.
        existing_lc = getattr(elements.lc, "data", None) or {}
        shifted = {index + 1: value for index, value in existing_lc.items()}
        if span is not None:
            line, col = span.line - 1, span.col - 1
            shifted[0] = [line, col, line, col]
        elements.lc.data = shifted
    del data["static"]
    return ok


# --------------------------------------------------------------------------


def _rewrite(doc: YamlDocument, parent: Any, key: str, bag: Bag) -> bool:
    """Convert ``parent[key]`` to the list form if needed, then recurse."""
    node = parent.get(key) if isinstance(parent, dict) else None
    ok = True
    if isinstance(node, dict):
        converted = _to_sequence(doc, node, bag)
        ok = converted is not None
        if converted is not None:
            parent[key] = converted
            node = converted
    if isinstance(node, list):
        for body in node:
            # A group is the only element that owns further elements.  A
            # carousel's `items:` are slots and are left exactly as written.
            if isinstance(body, dict) and body.get("type") == "group":
                ok = _rewrite(doc, body, "children", bag) and ok
    return ok


def _to_sequence(doc: YamlDocument, mapping: Any, bag: Bag) -> CommentedSeq | None:
    """Build the list-form twin of ``mapping``, carrying every span across."""
    seq = CommentedSeq()
    lc = getattr(mapping, "lc", None)
    if lc is not None:
        seq.lc.line, seq.lc.col = lc.line, lc.col
    ok = True
    seen: dict[int, Any] = {}
    for index, (name, body) in enumerate(mapping.items()):
        pos = _key_position(mapping, name)
        if pos is not None:
            # `lc.item(i)` reads data[i][0:2]; that is what YamlDocument.span
            # uses for an integer index into a sequence.
            seq.lc.add_idx_line_col(index, list(pos))
        key_span = doc.span(mapping, name, of="key")

        if not isinstance(name, str) or not IDENTIFIER.match(name):
            bag.error(
                "element-mapping",
                f"{name!r} is not a valid element id",
                key_span,
                notes=[
                    "in the mapping form of `elements:`/`children:` the key *is* "
                    "the element id",
                    "an id starts with a letter or underscore and continues with "
                    "letters, digits or underscores",
                ],
            )
            ok = False
        elif isinstance(body, CommentedMap) or isinstance(body, dict):
            ok = _inject_id(doc, body, name, pos, key_span, seen, bag) and ok
        seq.append(body)
    return seq if ok else None


def _inject_id(doc: YamlDocument, body: Any, name: str, pos: Any,
               key_span: Any, seen: dict[int, Any], bag: Bag) -> bool:
    if id(body) in seen:
        bag.error(
            "element-mapping",
            f"the body under {name!r} is the same node as the one under "
            f"{seen[id(body)]!r}",
            key_span,
            notes=["a YAML alias cannot give two elements two different ids; "
                   "write the second one out"],
        )
        return False
    seen[id(body)] = name

    if "id" in body:
        bag.error(
            "element-mapping",
            "an element written in the mapping form must not also declare 'id:'",
            doc.span(body, "id", of="key") or key_span,
            notes=[f"the key {name!r} already is this element's id",
                   "delete the 'id:' line, or write this element as a list "
                   "item instead"],
        )
        return False

    if isinstance(body, CommentedMap):
        body.insert(0, "id", name)
        if pos is not None:
            line, col = pos
            # key line/col *and* value line/col both point at the author's key,
            # which is the only text that exists for this pair.
            body.lc.add_kv_line_col("id", [line, col, line, col])
    else:  # pragma: no cover -- ruamel always hands back CommentedMap
        body["id"] = name
    return True


def _key_position(mapping: Any, name: Any) -> tuple[int, int] | None:
    lc = getattr(mapping, "lc", None)
    if lc is None:
        return None
    try:
        return lc.key(name)
    except (KeyError, IndexError, AttributeError, TypeError):
        return None
