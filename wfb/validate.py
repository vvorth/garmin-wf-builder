"""Stage 1 validation: the JSON Schema, reported against the YAML source.

``jsonschema`` reports failures against an instance path.  The YAML document
carries spans for every node, so the two are joined here and the author sees a
file/line/column pointing at their own text (ADR 0002), never at an internal
representation.

``oneOf`` over the element types would otherwise produce one useless error per
branch.  :func:`_narrow` picks the branch the author clearly meant -- the one
whose ``type`` discriminator matched -- and reports only its errors.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import SUPPORTED_FORMATS
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


#: Keys that only make sense for one `progress` style.  Supplying one set while
#: declaring the other style is a much commoner mistake than omitting a key, and
#: "missing required key 'size'" does not begin to explain it.
PROGRESS_STYLE_KEYS = {
    "arc": ("radius", "thickness", "start_angle", "sweep"),
    "bar": ("size",),
}


#: The element types this format version understands.
ELEMENT_TYPES = (
    "group", "shape", "text", "progress", "icon", "graph", "complication_slot",
    "hands", "pattern",
)

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


def _check_element_types(doc: YamlDocument, bag: Bag) -> list[list]:
    """Report unknown element types, returning the paths already accounted for."""
    bad: list[list] = []

    def visit(elements, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            if _check_progress_style(doc, bag, element):
                bad.append(here)
                continue
            if _check_hands_seconds_always(doc, bag, element):
                bad.append(here)
                continue
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
            visit(element.get("children"), here + ["children"])

    visit(doc.data.get("elements"), ["elements"])
    return bad


def _check_progress_style(doc: YamlDocument, bag: Bag, element: dict) -> bool:
    """Catch a `progress` whose keys belong to the other style."""
    if element.get("type") != "progress":
        return False
    style = element.get("style")
    if style not in PROGRESS_STYLE_KEYS:
        return False
    other = "bar" if style == "arc" else "arc"
    wrong = [key for key in PROGRESS_STYLE_KEYS[other] if key in element]
    if not wrong:
        return False
    missing = [key for key in PROGRESS_STYLE_KEYS[style] if key not in element]
    if not missing:
        return False
    plural = "s" if len(wrong) > 1 else ""
    bag.error(
        "schema",
        f"this progress element is 'style: {style}' but carries "
        f"{other}-only key{plural}: {', '.join(repr(k) for k in wrong)}",
        doc.span(element, "style"),
        notes=[
            f"either set 'style: {other}', or replace those with "
            f"{', '.join(repr(k) for k in PROGRESS_STYLE_KEYS[style])}",
            "'arc' is a stroked ring -- radius, thickness, start_angle, sweep; "
            "'bar' is a rectangle -- size",
        ],
    )
    return True


def _check_hands_seconds_always(doc: YamlDocument, bag: Bag, element: dict) -> bool:
    """Catch `seconds: always` before the schema does, so the message can
    explain *why* it is not implemented instead of just listing the two
    values the enum does accept.

    Follows `_check_progress_style`'s precedent: the friendly explanation
    goes through this hand-written check, and the schema's own `seconds:`
    enum lists only `awake`/`never` -- an author who reaches for `always`
    never sees the blunt "not valid here" a bare enum mismatch would give.
    """
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


def _check_baseline_renamed(doc: YamlDocument, bag: Bag) -> list[list]:
    """Catch `vertical_align: baseline` before the schema does: the schema's
    `verticalAlign` enum no longer has the value at all, so a bare
    "'baseline' is not valid here" would not tell an author it was renamed,
    or why. Checked on a `text` element and on a pattern's `shape: text`
    part -- the two glyph-drawn kinds that ever accepted the old `baseline`
    spelling. Every other kind that accepts `vertical_align:` (`group`,
    `shape`, `progress`, `graph`, `icon`, `complication_slot`, a hand or
    pattern `rectangle`/`circle` part) never accepted `baseline` as a value,
    so needs no check here (`docs/guide/placement.md`'s "Placement" section).

    Follows `_check_hands_seconds_always`'s precedent: the friendly
    explanation goes through this hand-written check, the schema stays
    normative (closed to the old spelling), and this only supplies the
    reason. Returns the exact `vertical_align` leaf path for each
    occurrence, not the whole element -- so only that one (now-inevitable)
    schema `enum` error is dropped, and any other, unrelated mistake on the
    same element still gets its own error ("one error, not N" per
    occurrence, `docs/lore/codegen.md`, not one error per *element*).
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

    def visit(elements, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            if element.get("type") == "text" and element.get("vertical_align") == "baseline":
                report(element, here + ["vertical_align"])
            if element.get("type") == "pattern":
                parts = element.get("parts")
                if isinstance(parts, list):
                    for i, part in enumerate(parts):
                        if isinstance(part, dict) and part.get("shape") == "text" \
                                and part.get("vertical_align") == "baseline":
                            report(part, here + ["parts", i, "vertical_align"])
            visit(element.get("children"), here + ["children"])

    visit(doc.data.get("elements"), ["elements"])
    return bad


def _check_modes_always_on(doc: YamlDocument, bag: Bag) -> list[list]:
    """Catch `modes: [... always_on ...]` before the schema does: `always_on`
    was removed from the `modes` enum outright (plan 14 D3), replaced by
    `aod:`. A bare enum mismatch would just say "not one of active,
    low_power" and leave an author who reaches for the old spelling with no
    pointer to what replaced it.

    Same precedent as `_check_hands_seconds_always`/`_check_baseline_
    renamed`: the schema stays closed to the removed value, and this only
    supplies the reason -- one path per occurrence (the `modes:` leaf, not
    the whole element) so an unrelated mistake on the same element still
    gets its own error. Checked on every element kind uniformly (`modes:`
    is accepted everywhere), not just the kind(s) that used to combine it
    with something else.
    """
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

    def visit(elements, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            modes = element.get("modes")
            if isinstance(modes, list) and "always_on" in modes:
                report(element, here + ["modes"])
            visit(element.get("children"), here + ["children"])

    visit(doc.data.get("elements"), ["elements"])
    return bad


#: A hand-frame length the schema's `handLength` pattern refuses, and why --
#: the schema alone can only say "expected number, got string", which does
#: not tell an author that `3%` is a perfectly good length *everywhere else*.
_HAND_UNIT_REFUSALS = {
    "%": "a hand frame has no parent box for '%' to measure against",
    "pt": "a hand has no font for 'pt' to measure against",
}

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
    """``hands.a.minute.parts[0].radius`` -- the spelling `wfb/ir.py` uses."""
    return "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in path).lstrip(".")


def _check_hand_frame(doc: YamlDocument, bag: Bag) -> list[list]:
    """Explain the two things a hand part's frame refuses that every other
    position accepts -- `%`/`pt` lengths and `anchor:` -- before the schema
    reports them bluntly.  Returns the value paths already accounted for,
    so the schema's own error for each is dropped.

    Same precedent as `_check_hands_seconds_always`: the schema stays
    normative (it refuses both), and this only supplies the reason.
    """
    bad: list[list] = []
    sets = doc.data.get("hands")
    if not isinstance(sets, dict):
        return bad

    def length(container: dict, key: str, path: list) -> None:
        unit = _hand_unit(container.get(key))
        if unit is None:
            return
        bag.error(
            "schema",
            f"{_dotted(path)}: {container[key]!r} -- a hand "
            f"part's lengths are px or %r only; {_HAND_UNIT_REFUSALS[unit]}",
            doc.span(container, key),
            notes=["every coordinate in a hand is measured from its axis; %r (the "
                   "screen's minor radius) scales it with the dial"],
        )
        bad.append(path)

    def position(raw: object, path: list) -> None:
        if not isinstance(raw, dict):
            return
        if "anchor" in raw:
            bag.error(
                "schema",
                f"{_dotted(path)}: 'anchor:' is not accepted in a "
                "hand part -- its coordinates are measured from the hand's axis, "
                "and there is no box to anchor to",
                doc.span(raw, "anchor"),
                notes=["the axis is the element's own 'at:'; inside a hand, "
                       "{dx, dy} or {angle, radius} are offsets from it"],
            )
            bad.append(path)  # the schema reports an unknown key at its object
        for key in _HAND_POSITION_LENGTHS:
            length(raw, key, path + [key])

    for set_name, spec in sets.items():
        if not isinstance(spec, dict):
            continue
        for hand_name in ("hour", "minute", "second"):
            hand = spec.get(hand_name)
            if not isinstance(hand, dict) or not isinstance(hand.get("parts"), list):
                continue
            for index, part in enumerate(hand["parts"]):
                if not isinstance(part, dict):
                    continue
                here = ["hands", set_name, hand_name, "parts", index]
                for key in _HAND_PART_LENGTHS:
                    length(part, key, here + [key])
                for key in _HAND_PART_POSITIONS:
                    position(part.get(key), here + [key])
                size = part.get("size")
                if isinstance(size, dict):
                    for key in ("width", "height"):
                        length(size, key, here + ["size", key])
                points = part.get("points")
                if isinstance(points, list):
                    for i, point in enumerate(points):
                        position(point, here + ["points", i])
    return bad


def _pattern_step_unit(value: object) -> str | None:
    """`pt` when ``value`` is a length string in that unit -- the only one a
    linear pattern's ``{dx, dy}`` step refuses.  Unlike a hand-frame length,
    `px`, `%` and `%r` are all fine here: a step is resolved against the
    parent box, not a boxless frame."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("pt"):
        return "pt"
    return None


def _check_pattern_frame(doc: YamlDocument, bag: Bag) -> list[list]:
    """The same friendly explanation `_check_hand_frame` gives a hand part,
    for a pattern's template (a pattern part is authored exactly like a
    hand part -- px/%r only, no `anchor:`) plus one more of its own: a
    linear pattern's `step:` refuses `pt` (no font in scope), though
    `%`/`%r` are fine there since a step resolves against the parent box,
    unlike a part's own position.

    Returns the value paths already accounted for, so the schema's own
    (blunter) error for each is dropped -- same contract as
    `_check_hand_frame`.
    """
    bad: list[list] = []

    def length(container: dict, key: str, path: list) -> None:
        unit = _hand_unit(container.get(key))
        if unit is None:
            return
        bag.error(
            "schema",
            f"{_dotted(path)}: {container[key]!r} -- a pattern part's "
            f"lengths are px or %r only; {_HAND_UNIT_REFUSALS[unit]}",
            doc.span(container, key),
            notes=["every coordinate in a pattern part is measured from the "
                   "pattern's own 'at:'; %r (the screen's minor radius) "
                   "scales it with the dial"],
        )
        bad.append(path)

    def position(raw: object, path: list) -> None:
        if not isinstance(raw, dict):
            return
        if "anchor" in raw:
            bag.error(
                "schema",
                f"{_dotted(path)}: 'anchor:' is not accepted in a pattern "
                "part -- its coordinates are measured from the pattern's "
                "own 'at:', and there is no box to anchor to",
                doc.span(raw, "anchor"),
                notes=["{dx, dy} or {angle, radius} are offsets from 'at:'"],
            )
            bad.append(path)
        for key in _HAND_POSITION_LENGTHS:
            length(raw, key, path + [key])

    def visit(elements, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            if element.get("type") == "pattern":
                step = element.get("step")
                if isinstance(step, dict):
                    for key in ("dx", "dy"):
                        if _pattern_step_unit(step.get(key)) == "pt":
                            # Recorded as the whole `step` object, not
                            # `step.dx`: `step:` is an angle-or-{dx, dy}
                            # oneOf with no discriminator, so the schema's
                            # own error for it narrows only as far as
                            # `step` itself, never down to the one bad key.
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
                parts = element.get("parts")
                if isinstance(parts, list):
                    for i, part in enumerate(parts):
                        if not isinstance(part, dict):
                            continue
                        part_path = here + ["parts", i]
                        for key in _HAND_PART_LENGTHS:
                            length(part, key, part_path + [key])
                        for key in _HAND_PART_POSITIONS:
                            position(part.get(key), part_path + [key])
                        size = part.get("size")
                        if isinstance(size, dict):
                            for key in ("width", "height"):
                                length(size, key, part_path + ["size", key])
                        points = part.get("points")
                        if isinstance(points, list):
                            for i2, point in enumerate(points):
                                position(point, part_path + ["points", i2])
            visit(element.get("children"), here + ["children"])

    visit(doc.data.get("elements"), ["elements"])
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


def _check_hands_pattern_alignment(doc: YamlDocument, bag: Bag) -> list[list]:
    """Friendly refusal of `align:`/`vertical_align:` on `type: hands`/
    `type: pattern` -- the schema stays closed to both keys on
    `handsElement`/`patternElement`, so this supplies the reason a bare
    "unknown key" would not give.

    Unlike `_check_hand_frame`/`_check_pattern_frame`/`_check_baseline_renamed`,
    whose bad paths each point at one value the schema itself still has a
    property for, `align`/`vertical_align` are not in either element's
    `properties` at all -- an author who writes one trips the element's own
    `additionalProperties` failure, which `jsonschema` reports *once per
    object*, bundling every unexpected key of that object into a single
    message (`_unexpected_keys`). Returning the whole element's path here
    (as `bad_types`' prefix-skip expects) would therefore also swallow any
    other, unrelated unexpected key on the same element -- and everything
    nested under it, `_check_hands_seconds_always`'s coarser precedent, which
    this deliberately avoids: any other, unrelated mistake on the same
    element must still be reported. So nothing is returned for `bad_types`
    here; `validate()` instead rewrites that one bundled schema error itself
    (`_drop_pivot_alignment_keys`), dropping only 'align'/'vertical_align'
    from its "unexpected" list and leaving any other offending key on the
    same element reported exactly as before.
    """
    def visit(elements, path: list) -> None:
        if not isinstance(elements, list):
            return
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            here = path + [index]
            kind = element.get("type")
            reason = _PIVOT_ALIGNMENT_REASON.get(kind)
            if reason is not None:
                for key in ("align", "vertical_align"):
                    if key in element:
                        bag.error(
                            "schema",
                            f"{_dotted(here + [key])}: {key!r} is not accepted "
                            f"on 'type: {kind}' -- {reason}",
                            doc.span(element, key),
                            notes=["align a hand or pattern part instead, or "
                                   "move 'at:'"],
                        )
            visit(element.get("children"), here + ["children"])

    visit(doc.data.get("elements"), ["elements"])
    return []


#: `align`/`vertical_align`: the only two keys `_check_hands_pattern_
#: alignment` ever reports on `type: hands`/`type: pattern` -- shared with
#: `_drop_pivot_alignment_keys` below so the two stay in lockstep.
_PIVOT_ALIGNMENT_KEYS = frozenset({"align", "vertical_align"})


def _drop_pivot_alignment_keys(error: ValidationError) -> ValidationError | None:
    """Narrow an `additionalProperties` failure on a `type: hands`/
    `type: pattern` element so it no longer mentions `align`/`vertical_align`
    -- `_check_hands_pattern_alignment` already gave the real reason for each
    of those, one error per key. Leaves every *other* unexpected key on the
    same element exactly as `jsonschema` reported it -- any other,
    unrelated mistake on the same element is still reported in full.

    Returns the error unchanged when it has nothing to do with this (not an
    `additionalProperties` failure, not on a hands/pattern element, or an
    unexpected-keys set that never included an alignment key), and ``None``
    when alignment keys were the *only* thing wrong -- the caller drops the
    error entirely in that case, since it is now fully explained elsewhere.
    """
    if error.validator != "additionalProperties":
        return error
    if not isinstance(error.instance, dict) or error.instance.get("type") not in _PIVOT_ALIGNMENT_REASON:
        return error
    offending = set(_unexpected_keys(error))
    remaining = sorted(offending - _PIVOT_ALIGNMENT_KEYS)
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
    where = _describe(path)
    message, notes = _humanise(error)
    bag.error("schema", f"{where}{message}" if where else message, span, notes=notes)


def _describe(path: list) -> str:
    if not path:
        return ""
    parts: list[str] = []
    for part in path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        elif parts:
            parts.append(f".{part}")
        else:
            parts.append(str(part))
    return "".join(parts) + ": "


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
