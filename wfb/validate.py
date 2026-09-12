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
    bad_types = _check_element_types(doc, bag)

    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(doc.data), key=lambda e: list(e.absolute_path))
    for error in errors:
        if any(_under(list(error.absolute_path), prefix) for prefix in bad_types):
            continue
        for narrowed in _narrow(error):
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
}

#: Element types this format does not have *yet*, so the message can say so
#: rather than implying the author misspelled something.
ELEMENT_NOT_YET = {
    "image": "images are not implemented yet",
    "bitmap": "images are not implemented yet",
    # `complication_slot` shipped (docs/research/09-data-library-and-config-axes.md
    # §4) -- it is a real element type now, listed in `ELEMENT_TYPES` below, not
    # an alias here any more.
    "raw": "the `raw` escape hatch is not implemented yet (ADR 0007)",
    "analog_clock": "analog hands are not implemented yet -- build them from `shape: line`",
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
