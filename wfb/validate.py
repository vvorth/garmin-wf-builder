"""Stage 1 validation: the JSON Schema, reported against the YAML source.

``jsonschema`` reports failures against an instance path.  The YAML document
carries spans for every node, so the two are joined here and the author sees a
file/line/column pointing at their own text (ADR 0002), never at an internal
representation.

``oneOf`` over the element types would otherwise produce one useless error per
branch.  :func:`_narrow` picks the branch the author clearly meant -- the one
whose ``type`` discriminator matched -- and reports only its errors.

The ``_check_*`` functions are **friendly pre-checks**: each catches one
mistake the schema already refuses (a removed or renamed value, a unit a
boxless frame cannot measure, a key that belongs to the other style) and
says *why*, then returns the paths it accounted for so :func:`validate` drops
the schema's own, blunter error there.  The schema stays normative; a
pre-check only supplies the reason.  A returned path is as narrow as the
schema error allows, so an unrelated mistake on the same element is still
reported ("one error, not N", ``docs/lore/codegen.md``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Iterable, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import SUPPORTED_FORMATS
from .diagnostics import Bag
from .yamlsrc import YamlDocument

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SCHEMA_PATH = SCHEMA_DIR / "wfb-face-2.schema.json"


@lru_cache(maxsize=None)
def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def check_format_version(doc: YamlDocument, bag: Bag) -> bool:
    """ADR 0009: refuse an unknown format outright rather than parsing part of it."""
    if not isinstance(doc.data, dict):
        bag.error("schema", "the document must be a mapping", doc.span(doc.data))
        return False
    if "format" not in doc.data:
        bag.error(
            "schema",
            "the document has no 'format:' key",
            doc.span(doc.data),
            notes=[f"add 'format: {SUPPORTED_FORMATS[-1]}' at the top of the file"],
        )
        return False
    declared = doc.data["format"]
    if declared == 1:
        bag.error(
            "format-version",
            "this file is format 1, which this compiler no longer reads",
            doc.span(doc.data, "format"),
            notes=[f"run 'wfb migrate --in-place {doc.path}' to rewrite it as format 2, "
                   "once -- comments, key order and quoting survive",
                   "every rename is listed in docs/guide/format-2-migration.md"],
        )
        return False
    if declared not in SUPPORTED_FORMATS:
        supported = ", ".join(str(v) for v in SUPPORTED_FORMATS)
        bag.error(
            "format-version",
            f"this file declares format {declared!r}, which this compiler does not understand",
            doc.span(doc.data, "format"),
            notes=[f"supported format versions: {supported}"],
        )
        return False
    return True


def validate(doc: YamlDocument, bag: Bag) -> bool:
    """Run the schema.  Returns ``True`` when the document is structurally sound."""
    if not check_format_version(doc, bag):
        return False

    before = len(bag.errors)

    # An unknown element `type:` makes every oneOf branch fail for the same
    # uninformative reason, so it is caught first and named directly.
    bad_types = (
        _check_element_types(doc, bag) + _check_hand_frame(doc, bag)
        + _check_pattern_frame(doc, bag) + _check_hands_pattern_alignment(doc, bag)
        + _check_reserved(doc, bag)
    )

    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(doc.data), key=lambda e: list(e.absolute_path))
    for error in errors:
        # Checked per *narrowed* (leaf) error, not the raw one straight out of
        # `iter_errors`: an element lives inside the `element` oneOf, so a
        # violation nested inside it (a pattern part's `anchor:`, say) only
        # gets its own full path once `_narrow` has picked the one branch the
        # author meant -- the outer oneOf failure's own `absolute_path` is
        # just the element's, too shallow to match a `_check_pattern_frame`/
        # `_check_hand_frame` entry for a key several levels deeper.  `hands:`
        # and a whole bad `type:` are unaffected: neither sits inside a
        # oneOf, so `_narrow` hands either straight back unchanged.
        for narrowed in _narrow(error):
            if any(_under(list(narrowed.absolute_path), prefix) for prefix in bad_types):
                continue
            # `_check_hands_pattern_alignment` returns no `bad_types` prefix
            # (an `additionalProperties` failure bundles a whole object's
            # unexpected keys into one error, too coarse a prefix to skip
            # without also hiding an unrelated mistake on the same element),
            # so its one schema error is narrowed here instead.
            kept = _drop_pivot_alignment_keys(narrowed)
            if kept is not None:
                kept = _drop_reserved_keys(kept, bad_types)
            if kept is None:
                continue
            _report(doc, bag, kept)
    return len(bag.errors) == before


def _element_types_from_schema() -> tuple[str, ...]:
    """The element types the format understands, read from the schema's own
    discriminated `element` `oneOf`, in the order it lists them -- rather
    than a second, hand-kept copy of the same list."""
    defs = load_schema()["$defs"]
    out = []
    for ref in defs["element"]["oneOf"]:
        name = ref["$ref"].rsplit("/", 1)[-1]
        out.append(defs[name]["properties"]["type"]["const"])
    return tuple(out)


ELEMENT_TYPES = _element_types_from_schema()

#: Names authors reach for that belong to another element type, or to another
#: format entirely.  Mapping them beats listing the valid types and leaving
#: the author to work out which one a progress ring is.
ELEMENT_ALIASES: dict[str, str] = {
    "shape": "type: rectangle      # or circle, line, arc, ellipse, polygon",
    "rounded_rectangle": "type: rectangle\n    corner_radius: 3%r",
    "triangle": "type: polygon",
    "progress": "type: gauge",
    "ring": "type: gauge\n    style: arc",
    "bar": "type: gauge\n    style: bar",
    "progress_bar": "type: gauge\n    style: bar",
    "complication_slot": "type: data",
    "complication": "type: data",
    "slot": "type: data",
    "label": "type: text",
    "string": "type: text",
    "digital_clock": "type: text\n    text: \"{time.clock:%H:%M}\"",
    "clock": "type: text\n    text: \"{time.clock:%H:%M}\"",
    "time": "type: text\n    text: \"{time.clock:%H:%M}\"",
    "hand": "type: hands\n    set: <name>      # a name declared under 'resources: hand_sets:'",
    "analog": "type: hands\n    set: <name>      # a name declared under 'resources: hand_sets:'",
    "analog_clock": "type: hands\n    set: <name>      # a name declared under "
                    "'resources: hand_sets:'",
}

#: Element types this format does not have *yet*, so the message can say so
#: rather than implying the author misspelled something.
ELEMENT_NOT_YET = {
    "image": "images are not implemented yet",
    "bitmap": "images are not implemented yet",
    "raw": "the `raw` escape hatch is not implemented yet (ADR 0007)",
}


def _visit_elements(doc: YamlDocument, visit: Callable[[dict[str, Any], list[str | int]], bool | None]) -> None:
    """Call ``visit(element, path)`` for every element mapping in the
    document, recursing into each one's ``children:`` unless ``visit``
    returns ``True``.  ``path`` is the jsonschema-style path to the element.
    The element blocks -- ``static:``, ``elements:``, each layout's, and a
    group's ``children:`` -- are mappings keyed by id."""
    def walk(elements: object, path: list[str | int]) -> None:
        if not isinstance(elements, dict):
            return
        for index, element in elements.items():
            if not isinstance(element, dict):
                continue
            here = path + [index]
            if not visit(element, here):
                walk(element.get("children"), here + ["children"])

    data = doc.data
    for block in ("static", "elements"):
        walk(data.get(block), [block])
    layouts = data.get("layouts")
    if isinstance(layouts, dict):
        for name, body in layouts.items():
            if isinstance(body, dict):
                for block in ("static", "elements"):
                    walk(body.get(block), ["layouts", name, block])


def _check_element_types(doc: YamlDocument, bag: Bag) -> list[list[str | int]]:
    """Report unknown element types, and the two whole-element mistakes of a
    known one (:func:`_check_progress_style_keys`,
    :func:`_check_hands_seconds_always`), returning the paths already
    accounted for."""
    bad: list[list[str | int]] = []

    types = ELEMENT_TYPES
    aliases = ELEMENT_ALIASES

    def visit(element: dict[str, Any], here: list[str | int]) -> bool:
        if (_check_progress_style_keys(doc, bag, element)
                or _check_hands_seconds_always(doc, bag, element)):
            bad.append(here)
            return True
        kind = element.get("type")
        if isinstance(kind, str) and kind not in types:
            notes = []
            alias = aliases.get(kind)
            pending = ELEMENT_NOT_YET.get(kind)
            if alias:
                notes.append(f"write it as:\n    {alias}")
            elif pending:
                notes.append(pending)
            notes.append("this format has: " + ", ".join(types))
            bag.error(
                "schema",
                f"unknown element type {kind!r}",
                doc.span(element, "type"),
                notes=notes,
            )
            bad.append(here)
        return False

    _visit_elements(doc, visit)
    return bad


#: The keys each `progress` style draws with.  Supplying another style's
#: keys while declaring this one is a much commoner mistake than omitting a
#: key, and "missing required key 'size'" does not begin to explain it.
_PROGRESS_STYLE_KEYS = {
    "arc": ("radius", "thickness", "start_angle", "sweep"),
    "bar": ("size",),
    "needle": ("start_angle", "sweep", "needle"),
}

#: What each style is, for the note naming the right keys.
_PROGRESS_STYLE_SHAPES = {
    "arc": "a stroked ring -- radius, thickness, start_angle, sweep",
    "bar": "a rectangle -- size",
    "needle": "a gauge needle turned about at: -- start_angle, sweep, needle",
}


def _check_progress_style_keys(doc: YamlDocument, bag: Bag, element: dict[str, Any]) -> bool:
    """Catch a gauge whose keys belong to another style.  True when it
    reported an error for this element."""
    if element.get("type") != "gauge":
        return False
    style = element.get("style")
    # `segments`/`scale` take either an arc's keys or a bar's, so no key of
    # the three fixed-geometry styles is "the wrong style's" there; the
    # builder checks which geometry they chose (`wfb.kinds.progress`).
    if style not in _PROGRESS_STYLE_KEYS:
        return False
    own = set(_PROGRESS_STYLE_KEYS[style])
    others = {key: other for other, keys in _PROGRESS_STYLE_KEYS.items() if other != style
              for key in keys if key not in own}
    wrong = [key for key in others if key in element]
    if not wrong:
        return False
    missing = [key for key in _PROGRESS_STYLE_KEYS[style] if key not in element]
    if not missing:
        return False
    plural = "s" if len(wrong) > 1 else ""
    candidates = list(dict.fromkeys(others[key] for key in wrong))
    bag.error(
        "schema",
        f"this {element['type']} element is 'style: {style}' but carries "
        f"{'/'.join(candidates)}-only key{plural}: {', '.join(repr(k) for k in wrong)}",
        doc.span(element, "style"),
        notes=[
            f"either set 'style: {' or '.join(candidates)}', or replace those with "
            f"{', '.join(repr(k) for k in _PROGRESS_STYLE_KEYS[style])}",
            "; ".join(f"'{name}' is {shape}" for name, shape in _PROGRESS_STYLE_SHAPES.items()),
        ],
    )
    return True


#: Format 2 keys whose vocabulary is fixed but which are not built yet
#: (plan 22 §5): where each may appear, and what the error says.
_RESERVED_ELEMENT_KEYS = {
    "effects": "'effects:' (a drop shadow and the like) is reserved and not implemented yet",
    "use": "components ('use:'/'with:', declared under 'resources: components:') are "
           "reserved and not implemented yet",
    "with": "components ('use:'/'with:', declared under 'resources: components:') are "
            "reserved and not implemented yet",
}
_RESERVED_DATA_KEYS = {
    key: "a data element's own parts ('parts:', 'arrange:', 'requires:', 'fallback:') "
         "are reserved and not implemented yet"
    for key in ("parts", "arrange", "requires", "fallback")
}
_RESERVED_NOTE = "docs/limitations.md, \"Not implemented yet\""


def _check_reserved(doc: YamlDocument, bag: Bag) -> list[list[str | int]]:
    """Format 2's reserved vocabulary (plan 22 §5): each key is a friendly
    "not implemented yet" error, never a generic unknown key.  Returns the
    paths accounted for; a reserved key inside an object is also stripped
    from that object's own unknown-key error (`_drop_reserved_keys`)."""
    bad: list[list[str | int]] = []

    def report(container: dict[str, Any], key: str, message: str,
               path: list[str | int], *notes: str) -> None:
        bag.error("reserved", f"{_dotted(path)}: {message}", doc.span(container, key, of="key"),
                  notes=[*notes, _RESERVED_NOTE])
        bad.append(path)

    resources = doc.data.get("resources")
    if isinstance(resources, dict) and "components" in resources:
        report(resources, "components", "components are reserved and not implemented yet",
               ["resources", "components"])

    def rule_list(value: object) -> bool:
        return (isinstance(value, list) and bool(value)
                and all(isinstance(item, dict) and ("when" in item or "else" in item)
                        for item in value))

    def parts(element: dict[str, Any], key: str, here: list[str | int], *,
              pattern: bool) -> None:
        items = element.get(key)
        if not isinstance(items, list):
            return
        for index, part in enumerate(items):
            if not isinstance(part, dict) or "outline" not in part:
                continue
            if pattern and part.get("type") == "text":
                continue
            report(part, "outline", "'outline:' on a hand, needle or pattern part other "
                   "than text is reserved and not implemented yet",
                   here + [key, index, "outline"],
                   "a text part of a pattern takes 'outline:' today")

    def ring_width(container: dict[str, Any], path: list[str | int]) -> None:
        """`outline: {color, width}` -- removed: a ring is always 1px
        (measured on a watch, research 19 §4.5), so the colour is all
        there is to say."""
        outline = container.get("outline")
        if not isinstance(outline, dict):
            return
        color = outline.get("color")
        bag.error("outline",
                  f"{_dotted(path + ['outline'])}: 'outline:' takes a colour or 'none' -- "
                  "a ring is always 1px", doc.span(container, "outline"),
                  notes=[f"write it as:\n    outline: {color}" if isinstance(color, str)
                         else "write it as:\n    outline: <colour>",
                         "a wider ring measured 1.8x the draw time of a 1px one on a "
                         "watch (docs/research/19-outline-everything.md §4.5)"])
        bad.append(path + ["outline"])

    def visit(element: dict[str, Any], here: list[str | int]) -> None:
        ring_width(element, here)
        if isinstance(element.get("aod"), dict):
            ring_width(element["aod"], here + ["aod"])
        for index, part in enumerate(element.get("parts") or []):
            if isinstance(part, dict):
                ring_width(part, here + ["parts", index])
        for key, message in _RESERVED_ELEMENT_KEYS.items():
            if key in element:
                report(element, key, message, here + [key])
        if element.get("type") == "data":
            for key, message in _RESERVED_DATA_KEYS.items():
                if key in element:
                    report(element, key, message, here + [key])
        for key, value in element.items():
            if rule_list(value):
                report(element, key, "'when:' rule lists are reserved and not "
                       "implemented yet", here + [key],
                       "for now, write the choice as one expression: "
                       "\"cond ? a : b\"")
        if element.get("type") == "gauge":
            parts(element, "needle", here, pattern=False)
        if element.get("type") == "pattern":
            parts(element, "parts", here, pattern=True)

    _visit_elements(doc, visit)
    sets = resources.get("hand_sets") if isinstance(resources, dict) else None
    if isinstance(sets, dict):
        for set_name, spec in sets.items():
            if isinstance(spec, dict):
                for hand_name, hand in spec.items():
                    if isinstance(hand, dict):
                        parts(hand, "parts", ["resources", "hand_sets", set_name, hand_name],
                              pattern=False)
    return bad


def _check_hands_seconds_always(doc: YamlDocument, bag: Bag, element: dict[str, Any]) -> bool:
    """`seconds: always` is not implemented; say why rather than list the
    two values the schema's `seconds:` enum does accept.  True when it
    reported an error for this element."""
    if element.get("type") != "hands":
        return False
    if element.get("seconds") != "always":
        return False
    bag.error(
        "schema",
        "'seconds: always' is not implemented yet -- a second hand while "
        "asleep needs a full-frame buffer and a moving onPartialUpdate clip, "
        "a different buffer architecture from 'static:'s paint-once one",
        doc.span(element, "seconds"),
        notes=["see docs/limitations.md, \"Not implemented yet\"",
               "'seconds: awake' (the default -- drawn while awake, hidden "
               "asleep) or 'seconds: never' are implemented"],
    )
    return True


#: A hand-frame length the schema's `handLength` pattern refuses, and why --
#: the schema alone can only say "expected number, got string", which does
#: not tell an author that `3%` is a perfectly good length *everywhere else*.
#: The keys of a hand part that hold a length, and those that hold a position.
_HAND_PART_LENGTHS = ("radius", "thickness")
_HAND_PART_POSITIONS = ("at", "to")
_HAND_POSITION_LENGTHS = ("dx", "dy", "radius")


def _hand_unit(value: object) -> str | None:
    """`%` or `pt` when ``value`` is a length string in one of those units."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("%r") or text.endswith("px"):
        return None
    if text.endswith("%"):
        return "%"
    if text.endswith("pt"):
        return "pt"
    return None


def _dotted(path: list[str | int]) -> str:
    """``hands.a.minute.parts[0].radius`` -- a jsonschema-style path as an
    author reads it."""
    out: list[str] = []
    for part in path:
        if isinstance(part, int):
            out.append(f"[{part}]")
        elif out:
            out.append(f".{part}")
        else:
            out.append(str(part))
    return "".join(out)


def _parts(element: dict[str, Any]) -> Iterable[tuple[int, dict[str, Any]]]:
    """``(index, part)`` for every mapping in a hand's or pattern's ``parts:``."""
    parts = element.get("parts")
    if isinstance(parts, list):
        for index, part in enumerate(parts):
            if isinstance(part, dict):
                yield index, part


@dataclass(frozen=True)
class _Frame:
    """How to word a hand part's or a pattern part's boxless frame."""

    noun: str
    origin: str
    length_note: str
    anchor_note: str
    #: Why each refused length unit (`_hand_unit`) means nothing in this frame.
    unit_refusals: dict[str, str]


_HAND_FRAME = _Frame(
    "hand part", "the hand's axis",
    "every coordinate in a hand is measured from its axis; %r (the "
    "screen's minor radius) scales it with the dial",
    "the axis is the element's own 'at:'; inside a hand, "
    "{dx, dy} or {angle, radius} are offsets from it",
    {"%": "a hand frame has no parent box for '%' to measure against",
     "pt": "a hand has no font for 'pt' to measure against"},
)
_PATTERN_FRAME = _Frame(
    "pattern part", "the pattern's own 'at:'",
    "every coordinate in a pattern part is measured from the "
    "pattern's own 'at:'; %r (the screen's minor radius) "
    "scales it with the dial",
    "{dx, dy} or {angle, radius} are offsets from 'at:'",
    {"%": "a pattern part's frame has no parent box for '%' to measure against",
     "pt": "a pattern part's geometry has no font for 'pt' to measure against"},
)


def _check_frame_part(doc: YamlDocument, bag: Bag, part: dict[str, Any], path: list[str | int],
                      frame: _Frame) -> list[list[str | int]]:
    """Explain the two things a hand or pattern part's frame refuses that
    every other position accepts -- `%`/`pt` lengths and `anchor:` -- before
    the schema reports them bluntly.  Returns the value paths accounted for,
    so the schema's own error for each is dropped.  The schema stays
    normative (it refuses both); this only supplies the reason.
    """
    bad: list[list[str | int]] = []

    def length(container: dict[str, Any], key: str, at: list[str | int]) -> None:
        unit = _hand_unit(container.get(key))
        if unit is None:
            return
        bag.error(
            "schema",
            f"{_dotted(at)}: {container[key]!r} -- a {frame.noun}'s lengths "
            f"are px or %r only; {frame.unit_refusals[unit]}",
            doc.span(container, key),
            notes=[frame.length_note],
        )
        bad.append(at)

    def position(raw: object, at: list[str | int]) -> None:
        if not isinstance(raw, dict):
            return
        if "anchor" in raw:
            bag.error(
                "schema",
                f"{_dotted(at)}: 'anchor:' is not accepted in a {frame.noun} -- "
                f"its coordinates are measured from {frame.origin}, and there "
                "is no box to anchor to",
                doc.span(raw, "anchor"),
                notes=[frame.anchor_note],
            )
            bad.append(at)  # the schema reports an unknown key at its object
        for key in _HAND_POSITION_LENGTHS:
            length(raw, key, at + [key])

    for key in _HAND_PART_LENGTHS:
        length(part, key, path + [key])
    for key in _HAND_PART_POSITIONS:
        position(part.get(key), path + [key])
    size = part.get("size")
    if isinstance(size, dict):
        for key in ("width", "height"):
            length(size, key, path + ["size", key])
    points = part.get("points")
    if isinstance(points, list):
        for i, point in enumerate(points):
            position(point, path + ["points", i])
    return bad


def _check_hand_frame(doc: YamlDocument, bag: Bag) -> list[list[str | int]]:
    """`_check_frame_part` over every part of every declared hand set."""
    bad: list[list[str | int]] = []
    resources = doc.data.get("resources")
    sets = resources.get("hand_sets") if isinstance(resources, dict) else None
    where: list[str | int] = ["resources", "hand_sets"]
    if not isinstance(sets, dict):
        return bad
    for set_name, spec in sets.items():
        if not isinstance(spec, dict):
            continue
        for hand_name in ("hour", "minute", "second"):
            hand = spec.get(hand_name)
            if not isinstance(hand, dict):
                continue
            for index, part in _parts(hand):
                bad += _check_frame_part(doc, bag, part,
                                         where + [set_name, hand_name, "parts", index],
                                         _HAND_FRAME)
    return bad


def _check_pattern_frame(doc: YamlDocument, bag: Bag) -> list[list[str | int]]:
    """`_check_frame_part` over every `type: pattern` element's parts, plus
    one refusal of its own: a linear pattern's `step:` refuses `pt` (no font
    in scope), though `%`/`%r` are fine there since a step resolves against
    the parent box, unlike a part's own position.
    """
    bad: list[list[str | int]] = []

    def visit(element: dict[str, Any], here: list[str | int]) -> None:
        if element.get("type") != "pattern":
            return
        step = element.get("step")
        if isinstance(step, dict):
            for key in ("dx", "dy"):
                value = step.get(key)
                if isinstance(value, str) and value.strip().endswith("pt"):
                    # Recorded as the whole `step` object, not `step.dx`:
                    # `step:` is an angle-or-{dx, dy} oneOf with no
                    # discriminator, so the schema's own error for it
                    # narrows only as far as `step` itself.
                    step_path = here + ["step"]
                    bag.error(
                        "schema",
                        f"{_dotted(step_path + [key])}: {step[key]!r} -- a "
                        "linear pattern's step is px, % or %r, not "
                        "pt: there is no font in scope to measure a "
                        "pt against",
                        doc.span(step, key),
                        notes=["px, %r and a bare number are also "
                               "fine here"],
                    )
                    bad.append(step_path)
        for i, part in _parts(element):
            bad.extend(_check_frame_part(doc, bag, part, here + ["parts", i], _PATTERN_FRAME))

    _visit_elements(doc, visit)
    return bad


#: Why `type: hands`/`type: pattern` refuse element-level `align:`/
#: `vertical_align:`: both elements' `at:` is a pivot the geometry turns
#: about or steps from, not a box -- moving it would break the very thing
#: the element draws, unlike every other kind that accepts alignment.
_PIVOT_ALIGNMENT_REASON = {
    "hands": "'at:' is the axis the hands turn about, not a box to align",
    "pattern": "'at:' is the origin every copy turns about (radial) or steps "
               "from (linear), not a box to align",
}


#: The keys `_check_hands_pattern_alignment` reports and
#: `_drop_pivot_alignment_keys` strips -- one tuple so the two stay in lockstep.
_PIVOT_ALIGNMENT_KEYS = ("align",)


def _check_hands_pattern_alignment(doc: YamlDocument, bag: Bag) -> list[list[str | int]]:
    """Refuse `align:`/`vertical_align:` on `type: hands`/`type: pattern`
    with the reason a bare "unknown key" would not give.

    Returns no paths: both keys trip the element's own
    `additionalProperties` failure, which `jsonschema` reports once per
    object with every unexpected key bundled in, so skipping the element's
    path would also hide an unrelated unknown key.  `validate()` instead
    strips just these two keys from that bundled error
    (`_drop_pivot_alignment_keys`).
    """
    def visit(element: dict[str, Any], here: list[str | int]) -> None:
        kind = element.get("type")
        if not isinstance(kind, str):
            return
        reason = _PIVOT_ALIGNMENT_REASON.get(kind)
        if reason is None:
            return
        for key in _PIVOT_ALIGNMENT_KEYS:
            if key in element:
                bag.error(
                    "schema",
                    f"{_dotted(here + [key])}: {key!r} is not accepted "
                    f"on 'type: {kind}' -- {reason}",
                    doc.span(element, key),
                    notes=["align a hand or pattern part instead, or "
                           "move 'at:'"],
                )

    _visit_elements(doc, visit)
    return []


def _drop_pivot_alignment_keys(error: ValidationError) -> ValidationError | None:
    """Strip `align`/`vertical_align` from an `additionalProperties` failure
    on a `type: hands`/`type: pattern` element -- `_check_hands_pattern_
    alignment` already explained each -- leaving any other unexpected key
    reported as `jsonschema` gave it.  Returns the error unchanged when no
    alignment key is involved, and ``None`` when they were the only keys.
    """
    if error.validator != "additionalProperties":
        return error
    if not isinstance(error.instance, dict) or error.instance.get("type") not in _PIVOT_ALIGNMENT_REASON:
        return error
    offending = set(_unexpected_keys(error))
    remaining = sorted(offending.difference(_PIVOT_ALIGNMENT_KEYS))
    if len(remaining) == len(offending):
        return error  # no alignment key was among the unexpected ones
    if not remaining:
        return None
    joined = ", ".join(f"{k!r}" for k in remaining)
    verb = "was" if len(remaining) == 1 else "were"
    # The same wording `jsonschema` itself uses (verified against the
    # installed version), so `_humanise`'s `.replace("Additional properties
    # are not allowed", "unknown key")` still fires on it unchanged.
    error.message = f"Additional properties are not allowed ({joined} {verb} unexpected)"
    return error


def _drop_reserved_keys(error: ValidationError, reported: list[list[str | int]],
                        ) -> ValidationError | None:
    """Strip the keys `_check_reserved` already explained from an unknown-key
    error on the object holding them; ``None`` when they were all it had."""
    if error.validator != "additionalProperties":
        return error
    here = list(error.absolute_path)
    explained = {path[-1] for path in reported
                 if len(path) == len(here) + 1 and path[:-1] == here}
    offending = set(_unexpected_keys(error))
    remaining = sorted(offending - explained)
    if len(remaining) == len(offending):
        return error
    if not remaining:
        return None
    joined = ", ".join(f"{k!r}" for k in remaining)
    verb = "was" if len(remaining) == 1 else "were"
    error.message = f"Additional properties are not allowed ({joined} {verb} unexpected)"
    return error


def _under(path: list[str | int], prefix: list[str | int]) -> bool:
    return path[: len(prefix)] == prefix


def _narrow(error: ValidationError) -> Iterable[ValidationError]:
    """Collapse a ``oneOf`` failure to the branch the author meant.

    An element with ``type: text`` that is missing ``value`` should produce one
    error about ``value``, not five about not being a group, a shape, a progress
    or an icon either.  ``jsonschema`` flattens every branch's errors into one
    ``context`` list, tagged with the branch index in ``schema_path[0]``, so the
    branches are regrouped here and the ones whose ``type`` discriminator did not
    match are dropped.
    """
    if error.validator == "oneOf" and not error.context:
        # Every branch *passed*.  jsonschema calls this "is valid under each
        # of {...}, {...}" and renders the whole element dict, which tells an
        # author nothing.  The shape that reaches here is a pair of
        # mutually-exclusive keys (`text:` vs `value:` on a text element), so
        # name them instead.
        yield _exclusive(error)
        return
    if error.validator not in ("oneOf", "anyOf") or not error.context:
        yield error
        return

    branches: dict[object, list[ValidationError]] = {}
    for sub in error.context:
        path = list(sub.schema_path)
        branches.setdefault(path[0] if path else 0, []).append(sub)

    candidates = {
        index: errors
        for index, errors in branches.items()
        if not any(_is_discriminator(sub) for sub in errors)
    }
    if not candidates or len(candidates) == len(branches):
        # Nothing discriminated: drop the branches that do not even take
        # this kind of value (`aod: {...}` against `aod`'s 'hide'|'show'
        # branch), then report whichever remaining branch got furthest.
        depth = len(list(error.absolute_path))
        shaped = [errors for errors in branches.values()
                  if not any(_wrong_kind(sub, depth) for sub in errors)]
        pool = [sub for errors in shaped for sub in errors] or error.context
        best = min(pool, key=lambda e: (-len(list(e.absolute_path)), len(e.message)))
        yield from _narrow(best)
        return

    for errors in candidates.values():
        required = [e for e in errors if e.validator == "required"]
        nested = [e for e in errors if e.validator in ("oneOf", "anyOf") and e.context]
        if nested and not required:
            for sub in nested:
                merged = _merge_alternatives(sub)
                if merged.validator == "required-one-of":
                    yield merged
                else:
                    yield from _narrow(sub)
            continue
        for sub in errors:
            if _is_discriminator(sub):
                continue
            yield from _narrow(sub)


def _exclusive(error: ValidationError) -> ValidationError:
    """Name the mutually-exclusive keys behind a "valid under each of" oneOf.

    Fires only when every branch of the `oneOf` is a bare ``{"required": [...]}``
    and more than one of those keys is actually present -- which is exactly the
    "author wrote both spellings" case, and nothing else.  Anything wider is
    left alone rather than given a confident, wrong message.
    """
    branches = error.validator_value if isinstance(error.validator_value, list) else []
    names: list[str] = []
    for branch in branches:
        if not isinstance(branch, dict) or set(branch) != {"required"}:
            return error
        required = branch["required"]
        if len(required) != 1:
            return error
        names.append(required[0])
    present = [n for n in names if isinstance(error.instance, dict) and n in error.instance]
    if len(present) < 2:
        return error
    joined = " and ".join(f"{n!r}" for n in present)
    either = " or ".join(f"{n!r}" for n in present)
    error.message = f"{joined} cannot both be set -- use {either}, not both"
    error.validator = "exclusive-keys"
    return error


def _wrong_kind(sub: ValidationError, depth: int) -> bool:
    """Did this branch reject the value itself for being the wrong kind of
    value -- a `type` mismatch, or an `enum`/`const` none of whose values
    is even the same JSON type -- rather than for something inside it?"""
    if len(list(sub.absolute_path)) != depth:
        return False
    if sub.validator == "type":
        return True
    if sub.validator in ("enum", "const"):
        value = sub.validator_value
        allowed = (value if isinstance(value, list) else []) if sub.validator == "enum" \
            else [value]
        return all(_type_name(value) != _type_name(sub.instance) for value in allowed)
    return False


def _is_discriminator(sub: ValidationError) -> bool:
    """Did this sub-error come from a branch's ``type`` const not matching?"""
    path = list(sub.schema_path)
    return sub.validator == "const" and path[-2:] == ["type", "const"]


def _merge_alternatives(error: ValidationError) -> ValidationError:
    """Turn "must match one of [needs a, needs b]" into "needs a or b"."""
    missing = [
        sub.message.split("'")[1]
        for sub in (error.context or [])
        if sub.validator == "required"
    ]
    if len(missing) < 2:
        return error
    joined = " or ".join(f"{name!r}" for name in missing)
    error.message = f"needs one of {joined}"
    error.validator = "required-one-of"
    return error


def _report(doc: YamlDocument, bag: Bag, error: ValidationError) -> None:
    path = list(error.absolute_path)
    unexpected = _unexpected_keys(error) if error.validator == "additionalProperties" else []
    # An unknown key is pointed at itself, not at the mapping's first key.
    span = (doc.span(error.instance, unexpected[0], of="key") if unexpected else None) \
        or doc.span_for_path(path)
    message, notes = _humanise(error)
    bag.error("schema", f"{_dotted(path)}: {message}" if path else message, span, notes=notes)


#: A format 1 key an author may still type into a format 2 file, and how
#: format 2 writes it.
FORMAT_1_KEYS = {
    "targets": "'build: {targets: [...]}'",
    "fonts": "'resources: {fonts: ...}'",
    "palette": "'resources: {palette: ...}'",
    "hands": "'set:' on a 'type: hands' element, and 'resources: {hand_sets: ...}' "
             "at the top level",
    "color_scheme": "'theme: {schemes: ...}'",
    "antialias": "'defaults: {antialias: ...}' at the top level",
    "min_1px": "'defaults: {min_1px: ...}' at the top level",
    "default": "'defaults: {aod: hide|show}'",
    "data": "'config: {slots: ...}'",
    "colors": "'scheme:'",
    "when_absent": "'absent:' -- 'hide', a placeholder string, or {value: <expression>}",
    "placeholder": "'absent: \"--\"'",
    "fallback": "'absent: {value: <expression>}'",
    "vertical_align": "one 'align:', e.g. 'align: top_left'",
    "if_unavailable": "'unsupported:'",
    "modes": "'sleep_update: true' (for [active, low_power]; [active] is the default)",
    "static": "a 'static:' block -- move the element into it",
    "value": "one 'text:' template, e.g. 'text: \"{time.hour:02d}\"' (on a gauge, "
             "'value:' is still the reading)",
    "format": "one 'text:' template, e.g. 'text: \"{activity.steps:d}\"'",
    "glyph": "'icon: \"U+XXXX\"'",
    "icon_for": "'icon: {for: <expression>}'",
    "icon_size": "'icon: {size: ...}'",
    "icon_position": "'icon: {position: ...}'",
    "icon_gap": "'icon: {gap: ...}'",
    "icon_color": "'icon: {color: ...}'",
    "shape": "'type: <shape>' (type: rectangle, circle, line, ...)",
    "id": "the element's key: elements are a mapping of id -> element",
}


def _humanise(error: ValidationError) -> tuple[str, list[str]]:
    """Turn jsonschema's wording into something an author can act on."""
    notes: list[str] = []
    description = _schema_of(error).get("description")

    if error.validator == "exclusive-keys":
        message = error.message
    elif error.validator == "required-one-of":
        message = error.message
    elif error.validator == "required":
        missing = error.message.split("'")[1]
        message = f"missing required key {missing!r}"
    elif error.validator == "additionalProperties":
        message = error.message.replace(
            "Additional properties are not allowed", "unknown key"
        )
        offending = set(_unexpected_keys(error))
        if offending & {"x", "y", "dx", "dy", "width", "height", "cx", "cy"}:
            notes.append(
                "positions go in `at:` and sizes in `size:` -- this format has no "
                "top-level x/y/width/height, because a position is relative to an "
                "anchor rather than absolute:\n"
                "    at: {anchor: center, dy: -18%}\n"
                "    size: {width: 60%, height: 12%}"
            )
        for key in _unexpected_keys(error):
            if key in FORMAT_1_KEYS:
                notes.append(f"'{key}:' is format 1; format 2 writes {FORMAT_1_KEYS[key]} "
                             "-- 'wfb migrate' rewrites a whole file")
        notes.append(
            "unknown keys are an error, not a warning -- a misspelled key is how a "
            "design silently loses an element (ADR 0009)"
        )
        allowed = _schema_of(error).get("properties")
        if allowed:
            notes.append("keys allowed here: " + ", ".join(sorted(allowed)))
    elif error.validator == "enum":
        message = f"{error.instance!r} is not valid here"
        values = error.validator_value if isinstance(error.validator_value, list) else []
        notes.append("allowed: " + ", ".join(repr(v) for v in values))
    elif error.validator == "const":
        message = f"expected {error.validator_value!r}, got {error.instance!r}"
    elif error.validator == "pattern" and "propertyNames" in error.schema_path:
        message = f"{error.instance!r} is not a valid name"
    elif error.validator == "pattern":
        message = f"{error.instance!r} has the wrong shape"
    elif error.validator == "type":
        message = f"expected {error.validator_value}, got {_type_name(error.instance)}"
    elif error.validator in ("minItems", "maxItems") and isinstance(error.instance, list):
        # jsonschema's own wording repeats the whole array back, which for a
        # 65-vertex polygon is a screenful of noise around a one-number fact.
        adjective = "at least" if error.validator == "minItems" else "at most"
        message = (f"needs {adjective} {error.validator_value} items, "
                   f"got {len(error.instance)}")
    else:
        message = error.message

    if description and error.validator in ("pattern", "enum", "required", "anyOf", "type",
                                           "minItems", "maxItems"):
        notes.append(description)
    return message, notes


def _schema_of(error: ValidationError) -> dict[str, Any]:
    """The schema object the error was raised against, or `{}` for a
    boolean schema (or none)."""
    return error.schema if isinstance(error.schema, dict) else {}


def _unexpected_keys(error: ValidationError) -> list[str]:
    """The key names an additionalProperties failure is complaining about."""
    allowed = set(_schema_of(error).get("properties") or ())
    instance = error.instance
    if not isinstance(instance, dict):
        return []
    return [k for k in instance if k not in allowed]


def _type_name(value: Any) -> str:
    return {
        bool: "boolean", int: "integer", float: "number",
        str: "string", list: "array", dict: "object", type(None): "null",
    }.get(type(value), type(value).__name__)
