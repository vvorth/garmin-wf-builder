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

Only two places in the schema take a list of elements -- the top-level
``elements:`` and a ``group``'s ``children:`` -- and this pass rewrites
exactly those two, recursing only into a body whose ``type`` is ``group``. A
non-element list field elsewhere in the format (e.g. a `shape: polygon`'s
`points:`) is never touched, because nothing here scans for such fields --
the recursion is keyed on `type: group`, not on any particular field name.

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

The third rewrite is a ``layouts:`` entry's own ``static:``/``elements:``
(plan 02 §12.2 -- form A is the only one this format
builds; there is no element-level membership key):

.. code-block:: yaml

    layouts:                     #  static:/elements: fold into two groups,
      digital:                   #  appended to the top-level elements:
        static:
          steps_track:
            type: shape
        elements:
          clock:
            type: text

    # becomes, conceptually:
    elements:
      - id: layout_digital_static
        type: group
        static: true
        children: [ steps_track ]
      - id: layout_digital
        type: group
        children: [ clock ]
    layouts:
      digital: {}                #  static:/elements: popped -- only lint:, if any, remains

Same argument as the other two rewrites, extended one step further: a layout
body is not even a second *spelling*, it is authoring sugar for two more
``group``\\ s the IR, layout, lint and emitter never have to know are special
-- ``Element.layout`` is assigned to these groups and their descendants
afterwards, by id (`wfb/ir.py`'s ``Builder._assign_layouts``), which is the
only place "this element belongs to layout X" is decided at all.  The two
reserved ids one layout named ``<name>`` claims --
``layout_<name>_static``/``layout_<name>`` -- are minted by
:func:`layout_ids`, the one place that naming convention is defined; nothing
else in this file or ``wfb/ir.py`` re-derives it.  A layout's own content is
always **appended** after the top-level ``static:`` block's group (if any),
never interleaved with it -- draw order is not decided here, though: it is
``wfb/ir.py``'s ``draw_sort_key`` that gives layout content its own rank, so
appending here only has to avoid disturbing anything already in
``elements:``, not get the final order right.
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

# The diagnostic codes this pass emits are `element-mapping`, `static` and
# `layouts`, written out as literals at each call site rather than through a
# constant so that `tests/test_lint.py`'s grep-based ALL_CODES registry can
# see them.  A duplicate key is not among them: ruamel's round-trip loader
# raises DuplicateKeyError before this file ever sees the document, and
# `wfb/yamlsrc.py`'s `load` already reports that as error[yaml] against the
# second key's own line -- verified, not assumed
# (`tests/test_desugar.py::test_a_duplicate_key_is_a_clear_diagnostic`).


def layout_ids(name: str) -> tuple[str, str]:
    """The reserved element ids one ``layouts: <name>:`` body's
    ``static:``/``elements:`` halves are rewritten into --
    ``(static_id, elements_id)``.

    The single place this naming convention is defined (plan 02
    §12.2).  ``wfb/ir.py`` imports this rather than
    re-deriving the strings, so the desugar rewrite and the IR's later
    ``Element.layout`` assignment can never drift out of step.
    """
    return f"layout_{name}_static", f"layout_{name}"


def desugar(doc: YamlDocument, bag: Bag) -> bool:
    """Normalise ``doc`` in place.  False (with diagnostics) if it cannot be."""
    data = doc.data
    if not isinstance(data, dict):
        return True  # `validate.check_format_version` reports this properly
    ok = _rewrite(doc, data, "elements", bag)
    ok = _static_block(doc, data, bag) and ok
    return _layouts_block(doc, data, bag) and ok


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
# `layouts:` -- form A only (plan 02 §12.1, §12.2)


def _layouts_block(doc: YamlDocument, data: Any, bag: Bag) -> bool:
    """Fold each ``layouts: <name>:`` body's ``static:``/``elements:`` into
    two synthetic groups, appended to the top-level ``elements:``.

    Runs *after* :func:`_static_block`, so the top-level ``static:`` group
    (if any) is already at the front of ``elements:`` and this pass only ever
    appends after it -- draw order itself is a `wfb/ir.py` concern
    (``draw_sort_key``'s layer rank), not this one's; appending merely avoids
    disturbing anything already there.  Each group is built exactly the way
    :func:`_static_block` builds its own: ``static: true`` on the static
    half, and the content put through :func:`_rewrite` first so a layout's
    own ``static:``/``elements:`` accept both spellings too.  The two
    reserved ids -- :func:`layout_ids` -- are the one place that naming
    convention is defined; ``wfb/ir.py`` looks elements back up by those same
    ids to assign ``Element.layout``.

    After this returns, ``data["layouts"]`` is left as a mapping of name ->
    ``{}`` (or ``{lint: ...}``, if the author wrote one) -- ``static:``/
    ``elements:`` are popped from each body, an empty list or mapping treated
    as absent the same way an absent key is (popped either way, so the
    schema never sees an empty ``static: []``, which its own ``minItems: 1``
    would otherwise reject).  That trimmed mapping is what carries the
    declared names, in declaration order, plus each layout's own ``lint:``,
    into the IR (``Builder._build_layouts``).  A non-mapping ``layouts:``, or
    a body that is not itself a mapping, is left untouched for the schema to
    report -- this pass does not crash on it.
    """
    if "layouts" not in data:
        return True
    layouts = data["layouts"]
    if not isinstance(layouts, dict):
        return True  # the schema reports this

    elements = data.get("elements")
    if elements is None:
        elements = CommentedSeq()
        data["elements"] = elements
    if not isinstance(elements, list):
        # The mapping-form rewrite (or `_static_block`) already failed and
        # said why; leaving `elements:` alone keeps that diagnostic honest.
        return False

    # Every id already spoken for, so a layout's generated id can be checked
    # against an ordinary element *and* against another layout's own
    # generated id in one pass -- `existing_ids[id]` names whichever claimed
    # it first, for the collision error.  Walked *recursively*: an author id
    # buried inside a shared group's `children:` is just as real a collision
    # as a top-level one, and a generic `duplicate-id` later would name the
    # wrong thing (the layout's own `elements:` key has no id of its own).
    existing_ids: dict[str, str] = {}
    _collect_ids(elements, existing_ids, "an element")

    ok = True
    for name, body in layouts.items():
        if not isinstance(name, str) or not IDENTIFIER.match(name):
            continue  # the schema reports this (propertyNames: identifier)
        if not isinstance(body, dict):
            continue  # the schema reports this

        static_id, elements_id = layout_ids(name)
        for generated_id, key, wrap_static in (
            (static_id, "static", True),
            (elements_id, "elements", False),
        ):
            node = body.get(key)
            if not node:
                if key in body:
                    del body[key]  # an empty list/mapping -- treated as absent
                continue
            key_span = doc.span(body, key, of="key")

            claimant = existing_ids.get(generated_id)
            if claimant is not None:
                bag.error(
                    "layouts",
                    f"layouts.{name}.{key}: the generated id {generated_id!r} "
                    f"collides with {claimant}",
                    key_span,
                    notes=[
                        f"'layouts: {name}:' needs id {generated_id!r} for its "
                        f"own {key!r} content",
                        "rename the layout, or whatever already claims that id",
                    ],
                )
                ok = False
                continue

            group = CommentedMap()
            group["id"] = generated_id
            group["type"] = "group"
            if wrap_static:
                group["static"] = True
            group["children"] = node
            if key_span is not None:
                line, col = key_span.line - 1, key_span.col - 1
                group.lc.line, group.lc.col = line, col
                keys = ("id", "type", "static", "children") if wrap_static \
                    else ("id", "type", "children")
                for k in keys:
                    group.lc.add_kv_line_col(k, [line, col, line, col])

            ok = _rewrite(doc, group, "children", bag) and ok
            # Register this group's own id *and every descendant's*, so a
            # later layout's generated id is checked against everything
            # appended so far -- nested content included, not just this
            # group's own top-level id.
            _collect_ids(group, existing_ids, f"layout {name!r}")

            idx = len(elements)
            elements.append(group)
            if hasattr(elements, "lc") and key_span is not None:
                line, col = key_span.line - 1, key_span.col - 1
                elements.lc.add_idx_line_col(idx, [line, col])

            del body[key]

    return ok


def _collect_ids(node: Any, out: dict[str, str], label: str) -> None:
    """Recursively collect every element id under ``node`` (a list of
    elements, or one element/group mapping) into ``out``, first claim wins.

    Shared by :func:`_layouts_block`'s initial scan of the whole ``elements:``
    tree and by registering each newly appended layout group's own
    descendants -- a reserved-id collision can be buried inside a shared
    group's ``children:`` just as easily as it can sit at the top level, and
    a generic ``duplicate-id`` later would name the wrong thing (the layout's
    own ``static:``/``elements:`` key has no id of its own to blame).
    """
    if isinstance(node, list):
        for item in node:
            _collect_ids(item, out, label)
        return
    if not isinstance(node, dict):
        return
    element_id = node.get("id")
    if isinstance(element_id, str) and element_id not in out:
        out[element_id] = label
    _collect_ids(node.get("children"), out, label)


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
            # A group is the only element that owns further elements.
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
