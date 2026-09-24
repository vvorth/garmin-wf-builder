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
from typing import Any, Callable, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import SUPPORTED_FORMATS, kinds
from .diagnostics import Bag
from .yamlsrc import YamlDocument

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SCHEMA_PATH = SCHEMA_DIR / "wfb-face-1.schema.json"


@lru_cache(maxsize=None)
def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
        + _check_pattern_frame(doc, bag) + _check_baseline_renamed(doc, bag)
        + _check_hands_pattern_alignment(doc, bag) + _check_modes_always_on(doc, bag)
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
            narrowed = _drop_pivot_alignment_keys(narrowed)
            if narrowed is None:
                continue
            _report(doc, bag, narrowed)
    return len(bag.errors) == before


def _element_types_from_schema() -> tuple[str, ...]:
    """The element types this format version understands, read from the
    schema's own discriminated `element` `oneOf`, in the order it lists
    them -- rather than a second, hand-kept copy of the same list."""
    defs = load_schema()["$defs"]
    out = []
    for ref in defs["element"]["oneOf"]:
        name = ref["$ref"].rsplit("/", 1)[-1]
        out.append(defs[name]["properties"]["type"]["const"])
    return tuple(out)


ELEMENT_TYPES = _element_types_from_schema()

#: Names authors reach for that belong to a discriminated pair, or to another
#: format entirely.  Mapping them beats listing the five valid types and leaving
#: the author to work out which one a rectangle is.
ELEMENT_ALIASES: dict[str, str] = {
    "rectangle": "type: shape\n    shape: rectangle",
    "rounded_rectangle": "type: shape\n    shape: rounded_rectangle",
    "circle": "type: shape\n    shape: circle",
    "line": "type: shape\n    shape: line",
    "ellipse": "type: shape\n    shape: ellipse",
    "polygon": "type: shape\n    shape: polygon",
    "triangle": "type: shape\n    shape: polygon",
    # Two right answers, so name both rather than guess: an arc bound to a
    # reading is a `progress`, an arc that just decorates is a `shape`.
    "arc": "type: progress\n    style: arc      # bound to a reading\n"
           "  # ...or, for a plain decorative arc:\n"
           "    type: shape\n    shape: arc",
    "ring": "type: progress\n    style: arc",
    "bar": "type: progress\n    style: bar",
    "progress_bar": "type: progress\n    style: bar",
    "gauge": "type: progress\n    style: arc",
    "label": "type: text",
    "string": "type: text",
    "digital_clock": "type: text\n    value: time.clock\n    format: \"{:%H:%M}\"",
    "clock": "type: text\n    value: time.clock\n    format: \"{:%H:%M}\"",
    "time": "type: text\n    value: time.clock\n    format: \"{:%H:%M}\"",
    "hand": "type: hands\n    hands: <name>      # a name declared under top-level 'hands:'",
    "analog": "type: hands\n    hands: <name>      # a name declared under top-level 'hands:'",
    "analog_clock": "type: hands\n    hands: <name>      # a name declared under top-level 'hands:'",
}

#: Element types this format does not have *yet*, so the message can say so
#: rather than implying the author misspelled something.
ELEMENT_NOT_YET = {
    "image": "images are not implemented yet",
    "bitmap": "images are not implemented yet",
    "raw": "the `raw` escape hatch is not implemented yet (ADR 0007)",
}


def _visit_elements(doc: YamlDocument, visit: Callable[[dict, list], bool | None]) -> None:
    """Call ``visit(element, path)`` for every element mapping under
    ``elements:``, recursing into each one's ``children:`` unless ``visit``
    returns ``True``.  ``path`` is the jsonschema-style path to the element."""
    def walk(elements: object, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            if not visit(element, here):
                walk(element.get("children"), here + ["children"])

    walk(doc.data.get("elements"), ["elements"])


def _check_element_types(doc: YamlDocument, bag: Bag) -> list[list]:
    """Report unknown element types, returning the paths already accounted for."""
    bad: list[list] = []

    def visit(element: dict, here: list) -> bool:
        # Each precheck answers only for its own `type:`, so at most one fires.
        if any(kind.precheck(doc, bag, element) for kind in kinds.all()):
            bad.append(here)
            return True
        kind = element.get("type")
        if isinstance(kind, str) and kind not in ELEMENT_TYPES:
            notes = []
            alias = ELEMENT_ALIASES.get(kind)
            pending = ELEMENT_NOT_YET.get(kind)
            if alias:
                notes.append(f"write it as:\n    {alias}")
            elif pending:
                notes.append(pending)
            notes.append("this format version has: " + ", ".join(ELEMENT_TYPES))
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


def _check_baseline_renamed(doc: YamlDocument, bag: Bag) -> list[list]:
    """`vertical_align: baseline` was renamed `bottom`; say so.  Checked on
    a `text` element and a pattern's `shape: text` part, the only two kinds
    that ever accepted `baseline`.  Returns each `vertical_align` leaf path.
    """
    bad: list[list] = []

    def report(container: dict, path: list) -> None:
        bag.error(
            "schema",
            "'vertical_align: baseline' was renamed 'bottom'",
            doc.span(container, "vertical_align"),
            notes=["it always meant the bottom of the full line box, never "
                   "the typographic baseline glyphs sit on -- Dc.drawText has "
                   "no bottom-justify flag, so a true typographic baseline "
                   "was never actually drawn",
                   "write 'vertical_align: bottom' instead"],
        )
        bad.append(path)

    def visit(element: dict, here: list) -> None:
        if element.get("type") == "text" and element.get("vertical_align") == "baseline":
            report(element, here + ["vertical_align"])
        if element.get("type") == "pattern":
            for i, part in _parts(element):
                if part.get("shape") == "text" and part.get("vertical_align") == "baseline":
                    report(part, here + ["parts", i, "vertical_align"])

    _visit_elements(doc, visit)
    return bad


def _check_modes_always_on(doc: YamlDocument, bag: Bag) -> list[list]:
    """`modes: [... always_on ...]` was replaced by `aod:` (plan 14 D3);
    point at the replacement.  Returns each `modes:` leaf path."""
    bad: list[list] = []

    def report(container: dict, path: list) -> None:
        bag.error(
            "schema",
            "'modes:' no longer accepts 'always_on'",
            doc.span(container, "modes"),
            notes=["the always-on-display sleep frame is now 'aod:' -- a "
                   "per-element/group override, plus a face-wide "
                   "'aod: {default: hide|show}' -- not a mode to opt an "
                   "element into (docs/guide/always-on-display.md)",
                   "'modes:' now means only the two MIP partial-update "
                   "modes, 'active'/'low_power'"],
        )
        bad.append(path)

    def visit(element: dict, here: list) -> None:
        modes = element.get("modes")
        if isinstance(modes, list) and "always_on" in modes:
            report(element, here + ["modes"])

    _visit_elements(doc, visit)
    return bad


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


def _dotted(path: list) -> str:
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


def _parts(element: dict) -> Iterable[tuple[int, dict]]:
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


def _check_frame_part(doc: YamlDocument, bag: Bag, part: dict, path: list,
                      frame: _Frame) -> list[list]:
    """Explain the two things a hand or pattern part's frame refuses that
    every other position accepts -- `%`/`pt` lengths and `anchor:` -- before
    the schema reports them bluntly.  Returns the value paths accounted for,
    so the schema's own error for each is dropped.  The schema stays
    normative (it refuses both); this only supplies the reason.
    """
    bad: list[list] = []

    def length(container: dict, key: str, at: list) -> None:
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

    def position(raw: object, at: list) -> None:
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


def _check_hand_frame(doc: YamlDocument, bag: Bag) -> list[list]:
    """`_check_frame_part` over every part of every top-level `hands:` set."""
    bad: list[list] = []
    sets = doc.data.get("hands")
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
                                         ["hands", set_name, hand_name, "parts", index],
                                         _HAND_FRAME)
    return bad


def _check_pattern_frame(doc: YamlDocument, bag: Bag) -> list[list]:
    """`_check_frame_part` over every `type: pattern` element's parts, plus
    one refusal of its own: a linear pattern's `step:` refuses `pt` (no font
    in scope), though `%`/`%r` are fine there since a step resolves against
    the parent box, unlike a part's own position.
    """
    bad: list[list] = []

    def visit(element: dict, here: list) -> None:
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
_PIVOT_ALIGNMENT_KEYS = ("align", "vertical_align")


def _check_hands_pattern_alignment(doc: YamlDocument, bag: Bag) -> list[list]:
    """Refuse `align:`/`vertical_align:` on `type: hands`/`type: pattern`
    with the reason a bare "unknown key" would not give.

    Returns no paths: both keys trip the element's own
    `additionalProperties` failure, which `jsonschema` reports once per
    object with every unexpected key bundled in, so skipping the element's
    path would also hide an unrelated unknown key.  `validate()` instead
    strips just these two keys from that bundled error
    (`_drop_pivot_alignment_keys`).
    """
    def visit(element: dict, here: list) -> None:
        kind = element.get("type")
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


def _under(path: list, prefix: list) -> bool:
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
        # Nothing discriminated: report whichever branch got furthest.
        best = min(error.context, key=lambda e: (-len(list(e.absolute_path)), len(e.message)))
        yield from _narrow(best)
        return

    for errors in candidates.values():
        required = [e for e in errors if e.validator == "required"]
        nested = [e for e in errors if e.validator in ("oneOf", "anyOf") and e.context]
        if nested and not required:
            for sub in nested:
                yield _merge_alternatives(sub)
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
    span = doc.span_for_path(path)
    message, notes = _humanise(error)
    bag.error("schema", f"{_dotted(path)}: {message}" if path else message, span, notes=notes)


def _humanise(error: ValidationError) -> tuple[str, list[str]]:
    """Turn jsonschema's wording into something an author can act on."""
    notes: list[str] = []
    description = (error.schema or {}).get("description") if isinstance(error.schema, dict) else None

    if error.validator == "exclusive-keys":
        message = error.message
        if isinstance(error.instance, dict) and {"text", "value"} <= set(error.instance):
            notes.append(
                "'text:' is a literal string, drawn exactly as written; 'value:' is "
                "an expression over data sources, formatted by 'format:'"
            )
            notes.append("for a fixed label, keep 'text:' and delete 'value:'")
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
        notes.append(
            "unknown keys are an error, not a warning -- a misspelled key is how a "
            "design silently loses an element (ADR 0009)"
        )
        allowed = (error.schema or {}).get("properties")
        if allowed:
            notes.append("keys allowed here: " + ", ".join(sorted(allowed)))
    elif error.validator == "enum":
        message = f"{error.instance!r} is not valid here"
        notes.append("allowed: " + ", ".join(repr(v) for v in error.validator_value))
    elif error.validator == "const":
        message = f"expected {error.validator_value!r}, got {error.instance!r}"
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


def _unexpected_keys(error: ValidationError) -> list[str]:
    """The key names an additionalProperties failure is complaining about."""
    allowed = set((error.schema or {}).get("properties") or ())
    instance = error.instance
    if not isinstance(instance, dict):
        return []
    return [k for k in instance if k not in allowed]


def _type_name(value: Any) -> str:
    return {
        bool: "boolean", int: "integer", float: "number",
        str: "string", list: "array", dict: "object", type(None): "null",
    }.get(type(value), type(value).__name__)
