"""What the editor's inspector and global panel show: an element's keys as
widgets, and the face's colours, styles, fonts and targets.

The inspector is generated from the published schema (`wfb.validate`'s
own copy), so it offers exactly the keys the format has for the element's
`type:`. A key's widget follows from the `$defs` entry its schema names
(`length`, `angle`, `align`, a colour, `position`, `size`) or else its JSON
type; a key no widget covers (a list, a nested structure such as `aod:` or
`curve:`) is shown as its text, edited in the YAML.  A shape's keys are
narrowed to its own (`wfb.kinds.shape.SHAPE_GEOMETRY_KEYS`), since the
schema lists every shape key on every shape.

Values are the author's, read from the text: what the author wrote, in
their units, or nothing when the key is absent.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path as FilePath
from typing import Any

from .. import catalog, complications, icon_catalog
from ..devices import Device, DeviceDatabase
from ..edit import colors, hands
from ..edit.geometry import selector_paths
from ..edit.spans import Path, SpanIndex, index_for
from ..palette import MIP64_NAMED, Color, ColorError

SCHEMA = FilePath(__file__).resolve().parents[2] / "schema" / "wfb-face-2.schema.json"

#: The keys an override may patch (`docs/guide/placement.md`): edited with
#: the "all targets / this device / this shape" chooser.
GEOMETRY = frozenset({"at", "size", "radius", "align"})

#: `$defs` entries that pick a widget, by the name the schema refers to.
_WIDGET_BY_REF = {
    "length": "length", "handLength": "length", "patternLength": "length",
    "angle": "angle",
    "align": "align",
    "colorExpression": "color", "colorRef": "color", "color": "color",
    "hexColor": "color", "swatchColor": "color",
    "visible": "expression", "expression": "expression",
}
#: Objects shown as their own keys, one level down.
_NESTED = frozenset({"position", "size"})
#: Keys the inspector leaves out: structure (the layer tree edits it), and
#: the overrides the chooser writes.
_SKIPPED = frozenset({"children", "overrides"})


@functools.cache
def schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return data


def _ref_name(node: dict[str, Any]) -> str | None:
    ref = node.get("$ref")
    return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None


def _deref(node: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The first `$defs` name ``node`` refers to, and the schema it ends at."""
    first = _ref_name(node)
    defs = schema()["$defs"]
    seen = 0
    while _ref_name(node) is not None and seen < 10:
        node = defs[_ref_name(node)]
        seen += 1
    return first, node


def element_schema(type_: str) -> dict[str, Any] | None:
    """The schema branch for elements of ``type_``."""
    for option in schema()["$defs"]["element"]["oneOf"]:
        _, branch = _deref(option)
        if branch.get("properties", {}).get("type", {}).get("const") == type_:
            return branch
    return None


def _hidden(type_: str) -> frozenset[str]:
    from ..kinds.shape import SHAPE_GEOMETRY_KEYS

    shapes = {"rectangle": ("rectangle", "rounded_rectangle"), "circle": ("circle",),
              "ellipse": ("ellipse",), "line": ("line",), "arc": ("arc",),
              "polygon": ("polygon",)}
    if type_ not in shapes:
        return frozenset()
    every = frozenset().union(*SHAPE_GEOMETRY_KEYS.values())
    own = frozenset().union(*(SHAPE_GEOMETRY_KEYS[s] for s in shapes[type_]))
    hidden = every - own
    if type_ != "arc":
        hidden |= {"start_angle", "sweep"}
    return hidden


def _widget(key: str, type_: str, node: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ref, resolved = _deref(node)
    if key == "type":
        return "readonly", resolved
    if ref in _NESTED or (key == "icon" and type_ == "data"):
        return "object", resolved
    if ref in _WIDGET_BY_REF:
        return _WIDGET_BY_REF[ref], resolved
    if key == "text" and type_ == "text":
        return "template", resolved
    if key == "slot":
        return "slot", resolved
    if key == "set" and type_ == "hands":
        return "handset", resolved
    if key == "font":
        return "font", resolved
    if key == "icon":
        return "icon", resolved
    if key == "on_hold":
        return "complication", resolved
    if "enum" in resolved:
        return "enum", resolved
    kind = resolved.get("type")
    if kind == "boolean":
        return "bool", resolved
    if kind in ("integer", "number"):
        return "number", resolved
    if kind == "string":
        return "text", resolved
    return "yaml", resolved


def _field(key: str, path: Path, type_: str, node: dict[str, Any], value: Any,
           required: bool) -> dict[str, Any]:
    widget, resolved = _widget(key, type_, node)
    description = node.get("description") or resolved.get("description") or ""
    field: dict[str, Any] = {
        "key": key, "path": list(path), "widget": widget, "description": description,
        "value": value, "present": value is not None, "required": required,
        "default": resolved.get("default", node.get("default")),
        "geometry": path[0] in GEOMETRY if path else False,
    }
    if "enum" in resolved:
        field["enum"] = resolved["enum"]
    if widget == "object":
        own = value if isinstance(value, dict) else {}
        field["children"] = [
            _field(k, tuple(path) + (k,), type_, sub, own.get(k), False)
            for k, sub in resolved.get("properties", {}).items()]
    if widget in ("icon", "complication", "color", "yaml") and value is not None \
            and not isinstance(value, (str, int, float, bool)):
        field["widget"] = "yaml"
    if field["widget"] == "yaml" and value is not None:
        field["text"] = json.dumps(value) if not isinstance(value, str) else value
    return field


def _data_at(data: Any, path: Path) -> Any:
    for step in path:
        if isinstance(data, dict) and step in data:
            data = data[step]
        elif isinstance(data, list) and isinstance(step, int) and -len(data) <= step < len(data):
            data = data[step]
        else:
            return None
    return data


def inspect(text: str, element: Path, device: Device | None) -> dict[str, Any]:
    """The inspector for the element at author path ``element``: its fields
    in schema order (the keys it has first), and, for each geometry key,
    the overrides the viewed ``device`` reads."""
    index = index_for(text)
    data = _data_at(index.data, element)
    if not isinstance(data, dict) or "type" not in data:
        return {"element": list(element), "fields": [], "error": "not an element"}
    type_ = str(data["type"])
    branch = element_schema(type_) or {"properties": {}}
    hidden = _hidden(type_)
    required = set(branch.get("required", []))
    props = branch.get("properties", {})
    order = [k for k in data if k in props] + [k for k in props if k not in data]
    fields = [
        _field(k, (k,), type_, props[k], data.get(k), k in required)
        for k in order if k not in _SKIPPED and (k not in hidden or k in data)
        # a key the schema lists only to refuse it with its reason (`format:`
        # on a data element) is offered only when the author wrote it
        and (k in data or not str(props[k].get("description", "")).startswith("Not accepted"))]
    unknown = [k for k in data if k not in props]
    overrides: dict[str, Any] = {}
    if device is not None:
        for scope, selector in zip(("device", "shape"), selector_paths(device)):
            patch = _data_at(data, selector)
            if isinstance(patch, dict):
                overrides[scope] = {"selector": selector[1], "keys": patch}
    return {"element": list(element), "id": element[-1], "type": type_, "fields": fields,
            "unknown": unknown, "overrides": overrides,
            "device": device.id if device is not None else None,
            "shape": device.shape if device is not None else None}


# -- the global panel ------------------------------------------------------------------

def _legal_on(value: Any, devices: list[Device]) -> list[str]:
    """The devices whose panel would dither ``value``."""
    try:
        color = Color.parse(value)
    except ColorError:
        return []
    return [d.id for d in devices if not color.is_palette_legal(d.display_colors)]


def _slots(index: SpanIndex) -> list[dict[str, Any]]:
    """Each `config: slots:` entry: its label, default and choices (`any`,
    or a list of `{type, icon}`), and the elements drawing it."""
    from ..edit.patch import slot_drawers

    data = index.data
    out = []
    for name, entry in (((data.get("config") or {}).get("slots")) or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        raw = entry.get("choices")
        choices: str | list[dict[str, Any]] | None
        if isinstance(raw, list):
            choices = [{"type": c.get("type"), "icon": c.get("icon")} if isinstance(c, dict)
                       else {"type": c, "icon": None} for c in raw]
        else:
            choices = raw
        out.append({"name": name, "label": entry.get("label"), "default": entry.get("default"),
                    "choices": choices, "drawn_by": slot_drawers(index, str(name))})
    return out


def _automatic(name: str, value: Any) -> bool:
    try:
        return colors.is_automatic(name, value)
    except Exception:
        return False


def _axes(data: dict[str, Any]) -> dict[str, Any]:
    """`config: accent_color:` and `data_color:`: each one's default,
    choices (`any`, or the listed colours) and the role it binds."""
    config = data.get("config") or {}
    out: dict[str, Any] = {}
    for axis, role in (("accent_color", "accent"), ("data_color", "data")):
        entry = config.get(axis)
        if not isinstance(entry, dict):
            out[axis] = None
            continue
        raw = entry.get("choices")
        choices = raw if isinstance(raw, str) else [
            c.get("color") if isinstance(c, dict) else c for c in (raw or [])]
        out[axis] = {"default": entry.get("default"), "choices": choices,
                     "raw": raw, "role": entry.get("role") or role, "own_role": "role" in entry}
    return out


def globals_of(text: str, db: DeviceDatabase) -> dict[str, Any]:
    """The face's colours, schemes, styles, layouts, fonts, slots and
    targets."""
    try:
        index = index_for(text)
    except ValueError:
        return {}
    data = index.data
    if not isinstance(data, dict):
        return {}
    targets = list((data.get("build") or {}).get("targets") or [])
    devices = []
    for target in targets:
        try:
            devices.append(db.get(str(target)))
        except Exception:
            continue
    resources = data.get("resources") or {}
    palette = []
    for name, entry in (resources.get("palette") or {}).items():
        value = entry.get("value") if isinstance(entry, dict) else entry
        palette.append({"name": name, "value": value,
                        "label": entry.get("label") if isinstance(entry, dict) else None,
                        "long": isinstance(entry, dict), "dithers_on": _legal_on(value, devices),
                        "used_by": colors.user_names(index, str(name)),
                        "automatic": _automatic(str(name), value),
                        "launcher": name in colors.LAUNCHER})
    schemes = (data.get("theme") or {}).get("schemes") or {}
    roles: list[str] = []
    for scheme in schemes.values():
        for role in ((scheme or {}).get("colors") or {}):
            if role not in roles:
                roles.append(role)
    style = (data.get("config") or {}).get("style") or {}
    fonts = []
    for name, spec in (resources.get("fonts") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        fonts.append({"name": name, "source": spec.get("source"), "face": spec.get("face"),
                      "size": spec.get("size")})
    return {
        "palette": palette,
        "schemes": {"names": list(schemes), "roles": roles,
                    "colors": {n: dict((s or {}).get("colors") or {})
                               for n, s in schemes.items()}},
        "styles": {"default": style.get("default"),
                   "entries": [{"name": n, **(e if isinstance(e, dict) else {})}
                               for n, e in (style.get("choices") or {}).items()]},
        "layouts": list((data.get("layouts") or {})),
        "fonts": fonts,
        "slots": _slots(index),
        "roles": colors.roles(index),
        "axes": _axes(data),
        "displays": sorted({d.display_colors for d in devices if d.display_colors}),
        "hand_sets": list((resources.get("hand_sets") or {})),
        "hands": hands.summary(index),
        "targets": targets,
    }


def _complication_type(name: str) -> dict[str, Any]:
    """One complication type as a slot's checklist shows it: its label and
    group, its catalogue icon, and the reading the preview draws for it."""
    from ..icons import COMPLICATION_ICON
    from ..kinds.complication_slot import COMPLICATION_SLOT_SAMPLE

    sample = COMPLICATION_SLOT_SAMPLE.get(name)
    reading = complications.format_reading(name, sample) if sample is not None else None
    return {"name": name, "label": complications.label(name),
            "category": complications.category(name),
            "icon": COMPLICATION_ICON.get(name), "sample": reading}


@functools.cache
def vocabulary() -> dict[str, Any]:
    """What the pickers offer: data sources by namespace, icon names and
    complication types. Device-independent."""
    from .. import series
    from ..edit import element_types

    return {
        "sources": catalog.namespaces(),
        "icons": sorted(icon_catalog.CATALOG),
        "complications": ["auto"] + complications.names(),
        "series": series.names(),
        "types": element_types(),
        "mip": [{"name": n, "value": v, "label": label} for n, v, label in MIP64_NAMED],
        "hand_presets": list(hands.presets()),
        "categories": list(complications.CATEGORIES),
        "complication_types": [_complication_type(n) for n in complications.names()],
        "icon_glyphs": {name: ord(icon.codepoint) for name, icon in icon_catalog.CATALOG.items()},
    }


def devices(db: DeviceDatabase) -> list[dict[str, Any]]:
    """Every installed device that can run a face, for the targets list."""
    from ..emit.manifest import BASE_API_LEVEL
    from ..devices import version_key

    out = []
    for device_id in db.ids():
        try:
            device = db.get(device_id)
        except Exception:
            continue
        if not device.supports_watchface or \
                version_key(device.api_level) < version_key(BASE_API_LEVEL):
            continue
        from ..preview import has_skin

        ppi = device.simulator.get("ppi")
        out.append({"id": device.id, "name": device.compiler.get("displayName") or device.id,
                    "shape": device.shape, "size": f"{device.width}x{device.height}",
                    "width": device.width, "height": device.height,
                    # the screen's pixels per inch, when its files say: what
                    # "real size" on the editor's screen is computed from
                    "ppi": float(ppi) if isinstance(ppi, (int, float)) and ppi > 0 else None,
                    "skin": has_skin(device), "display": device.display_type,
                    "fonts": list(device.system_fonts)})
    return sorted(out, key=lambda d: d["name"].lower())
