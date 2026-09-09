"""Stage 0.5: rewrite the author's conveniences into the one shape everything
downstream already understands.

Today that is exactly one rewrite: **an element list written as a mapping whose
key is the element id**.

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

# The one diagnostic code this pass emits is `element-mapping`, written out as a
# literal at each call site rather than through a constant so that
# `tests/test_lint.py`'s grep-based ALL_CODES registry can see it.  A duplicate
# key is not among them: ruamel's round-trip loader raises DuplicateKeyError
# before this file ever sees the document, and `wfb/yamlsrc.py`'s `load` already
# reports that as error[yaml] against the second key's own line -- verified, not
# assumed (`tests/test_desugar.py::test_a_duplicate_key_is_a_clear_diagnostic`).


def desugar(doc: YamlDocument, bag: Bag) -> bool:
    """Normalise ``doc`` in place.  False (with diagnostics) if it cannot be."""
    data = doc.data
    if not isinstance(data, dict):
        return True  # `validate.check_format_version` reports this properly
    return _rewrite(doc, data, "elements", bag)


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
