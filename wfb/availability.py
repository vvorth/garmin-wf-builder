"""One source of truth for what a design's catalogue bindings and features
need from a *target device*, checked against that device's own symbol table
(`wfb.devices.Device.has_symbol`/`has_module`/`has_field`) -- never an API
level, because CLAUDE.md constraint 6 is not a suggestion: `monkeyc` checks
the SDK-wide API, not the device's, and a device's own ConnectIQ ceiling is
not a reliable stand-in for what it actually implements (fr955 is 5.2.0 and
still lacks `WatchFaceDelegate.onTap`).

**Why this module exists.** `manifest.xml` is one file shared by every
target device in a build (`wfb/emit/manifest.py`'s `BASE_API_LEVEL`), so it
cannot answer "is X available" per device -- only per *build*. The question
this module answers is smaller and sharper: for one (design, device) pair,
which of the design's own catalogue reads are unavailable, and why; and for
one (design, every target device) pair, which runtime guards the *one*
generated view/delegate shared across every target must carry so that none
of them can ever execute a symbol the device running it does not have.

**Two consumers, two altitudes:**

* `wfb.emit.monkeyc` (codegen) only needs the aggregate: `compute_guards`
  answers "does the shared code need a `Toybox has :Complications` guard
  anywhere at all, and which bare field names need an `x has :field`
  guard" -- yes/no questions resolved once per project, over every target
  device, so a design whose targets all support everything it uses
  generates the exact same code it always did (no guard is ever emitted
  for a thing every target has).
* A lint pass (not built here -- see the working agreement this task
  inherited) needs the *per-element, per-device* detail: which of *this*
  element's expression source paths are unavailable on *this* device, and
  whether that is because a module, a function or a field is missing, with
  the missing symbol's name, so it can point at the YAML line responsible.
  `source_unavailable`/`reader_unavailable` (and `Unavailable` itself)
  exist for that; `compute_guards` is built out of them, not the other way
  around, so the two views cannot drift apart.

**Policy, not just mechanism** (decided by the user, see the plan this task
was assigned from -- not re-litigated here): a binding a target device lacks
*reads as absent* on that device -- the same `when_absent` path every
nullable source already has (every catalogue field is nullable, CLAUDE.md
constraint 8) -- not a build failure and not a silently wrong value. An
`on_hold:` simply never fires there, and a `config: data:` slot keeps its
compiled-in default. This module answers *what* is absent and *why*;
`wfb.emit.monkeyc` is what turns that into "yields null" or "never fires",
and the lint pass (elsewhere) is what turns it into a warning a human reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .catalog import CATALOG, READERS, Source
from .devices import Device
from .ir import Face


@dataclass(frozen=True)
class Unavailable:
    """Why one thing a design uses is unavailable on one device.

    `kind` is one of ``"module"`` (a bare `Toybox` module name, `Device.
    has_module`'s namespace), ``"function"`` (a ``Parent.name`` symbol,
    `Device.has_symbol`'s namespace) or ``"field"`` (a bare field name,
    `Device.has_field`'s namespace, exact for absence -- see that method's
    own caveat about presence). `symbol` is the missing name in that
    namespace; `reason` is a ready-to-show sentence a lint message can use
    verbatim or fold into a longer one.
    """

    kind: str
    symbol: str
    reason: str


def _module_gap(module: str, device: Device) -> Unavailable | None:
    if device.has_module(module):
        return None
    return Unavailable("module", module, f"Toybox.{module} is absent on {device.id}")


def _symbol_gap(symbol: str, device: Device) -> Unavailable | None:
    if device.has_symbol(symbol):
        return None
    return Unavailable("function", symbol, f"{symbol} is absent on {device.id}")


def _field_gap(field: str, device: Device) -> Unavailable | None:
    if device.has_field(field):
        return None
    return Unavailable("field", field, f"field {field!r} is absent on {device.id}")


def reader_unavailable(reader_name: str, device: Device) -> Unavailable | None:
    """Is `catalog.READERS[reader_name]`'s call unavailable on `device`?

    Checked in the order a call actually fails at runtime: a missing module
    makes every symbol under it moot (`Reader.requires_module`, set only for
    the 42 complication readers -- fenix6/fr245 lack `Toybox.Complications`
    itself, not merely one function in it), so that is checked first; only
    then the specific function symbols `Reader.requires` names. Returns the
    first gap found, or ``None`` when the reader's call is fully available.
    """
    reader = READERS[reader_name]
    if reader.requires_module is not None:
        gap = _module_gap(reader.requires_module, device)
        if gap is not None:
            return gap
    for symbol in reader.requires:
        gap = _symbol_gap(symbol, device)
        if gap is not None:
            return gap
    return None


def _field_root(source: Source) -> str | None:
    """The bare field name `Device.has_field` checks for `source`, or
    ``None`` when `source` reads no field at all (its reader *is* the
    value -- `time.clock`, `date.today`).

    The *first* dotted segment of `field_name`: for a dotted path like
    `activity.active_minutes_week`'s `"activeMinutesWeek.total"`, that is
    the nullable intermediate object itself (`Source.intermediate`, set to
    the very same name for exactly this reason) -- the field the reader
    object actually carries. `"total"` belongs to a *different* class
    (`ActivityMonitor.ActiveMinutes`), which this module has no way to
    resolve `has_field` against precisely (see `Device.has_field`'s own
    presence-is-approximate caveat) and which is not what would be missing
    on a device that simply lacks the outer field anyway.
    """
    if source.field_name is None:
        return None
    return source.field_name.split(".", 1)[0]


def source_unavailable(path: str, device: Device) -> Unavailable | None:
    """Is the catalogue path `path` unavailable on `device`, and why?

    Checks, in order: the reader it comes off (`reader_unavailable` --
    covers every `complication.*` path's `Toybox.Complications` gate for
    free, since they all share one of the 42 generated complication
    readers); `Source.requires` (currently unused by any entry in
    `catalog.CATALOG`, but honoured here so an author populating it later
    is not silently ignored); and finally the field itself, via
    `Device.has_field` on `_field_root`. Returns ``None`` for an unknown
    path (nothing to say) or one that is fully available.
    """
    source = CATALOG.get(path)
    if source is None:
        return None
    gap = reader_unavailable(source.reader, device)
    if gap is not None:
        return gap
    for symbol in source.requires:
        gap = _symbol_gap(symbol, device)
        if gap is not None:
            return gap
    root = _field_root(source)
    if root is not None:
        gap = _field_gap(root, device)
        if gap is not None:
            return gap
    return None


def unavailable_sources(paths: Iterable[str], device: Device) -> dict[str, Unavailable]:
    """`{path: Unavailable}` for every path in `paths` that `device` cannot
    provide -- a path that is available, or not a real catalogue path at
    all, is simply absent from the result. The per-element entry point a
    lint pass iterates: give it one element's `expression.sources` and one
    target device, get back exactly the paths worth warning about."""
    out: dict[str, Unavailable] = {}
    for path in paths:
        gap = source_unavailable(path, device)
        if gap is not None:
            out[path] = gap
    return out


# --------------------------------------------------------------------------
# design-wide queries (what this Face uses, independent of any one device)


def design_paths(face: Face) -> frozenset[str]:
    """Every catalogue path (`catalog.CATALOG` key) this design's bound
    expressions read, over every element -- the same walk `Face.
    requirements()` does, but keeping the paths themselves rather than
    reducing them to permissions/readers/modules, because a lint pass needs
    to point at the element and the exact path, not just the aggregate."""
    paths: set[str] = set()
    for element in face.walk():
        for expression in element.expressions():
            paths.update(expression.sources)
    return frozenset(paths)


def design_fields(face: Face) -> frozenset[str]:
    """Bare field names (`Device.has_field`'s namespace) this design's
    bound sources actually read off a reader -- `_field_root` of every
    bound path that has one. A path with no field at all (`time.clock`) or
    one whose reader is itself gated by a module (every `complication.*`
    path) contributes nothing here: the latter is handled by
    `uses_complications` instead, since a device lacking `Toybox.
    Complications` has no field to check in the first place."""
    fields: set[str] = set()
    for path in design_paths(face):
        source = CATALOG.get(path)
        if source is None or READERS[source.reader].requires_module is not None:
            continue
        root = _field_root(source)
        if root is not None:
            fields.add(root)
    return frozenset(fields)


def uses_complications(face: Face) -> bool:
    """Does this design need `Toybox.Complications` for any reason?

    Three independent reasons, any one sufficient -- the same three
    `wfb/emit/project.py`'s now-removed `_features()` used to raise
    `minApiLevel` for, kept here verbatim because the *design* question
    ("does this need Complications at all") is unchanged; only the
    *consequence* moved, from bumping a shared manifest floor to gating a
    runtime guard (see `wfb/emit/manifest.py`'s module docstring):

    1. a bound `complication.*` source (any reader with `complication_type`
       set -- equivalently, any reader with `requires_module ==
       "Complications"`);
    2. a declared `config: data:` slot, which pulls the wearer's *chosen*
       type through `WfbComplications.valueOf` even though it binds no
       `complication.*` catalogue path at all -- the type is not known
       until runtime;
    3. any `on_hold:` anywhere in the design (a fixed complication type, or
       a `complication_slot`'s `on_hold: auto`), which compiles to
       `Complications.exitTo`.
    """
    if any(READERS[name].requires_module == "Complications"
           for name in face.requirements().readers):
        return True
    if face.config_data:
        return True
    if any(element.on_hold is not None for element in face.walk()):
        return True
    return False


# --------------------------------------------------------------------------
# the aggregate the shared generated code needs


@dataclass(frozen=True)
class Guards:
    """What the *one* generated view/delegate, shared across every target
    device in a build, must guard against -- aggregated over every target,
    so a guard is included only when at least one target actually lacks the
    thing. A design whose targets all support everything it uses gets an
    empty `Guards` and so generates byte-identical code to before this
    module existed; that is what `compute_guards` is for, not something a
    caller has to check separately.
    """

    #: True iff `uses_complications(face)` and some target device lacks the
    #: `Complications` module. The one module this project currently
    #: guards, individually, at several call sites (`wfb/emit/monkeyc.py`:
    #: `onLayout`'s subscribe/register loop, every complication-reader pull,
    #: `on_hold:`'s `Complications.exitTo`, a `config: data:` slot's
    #: `Complications.Id` field) -- one flag here rather than a per-site
    #: computation, so every site agrees on the same yes/no answer.
    complications: bool
    #: Bare field names (`Device.has_field`'s namespace) this design reads
    #: that some target device lacks -- e.g. ``{"stressScore"}``. Empty when
    #: every field this design touches is present on every target.
    fields: frozenset[str]

    @property
    def any(self) -> bool:
        """Whether the shared code needs *any* guard at all -- a design
        with neither a missing module nor a missing field generates plain,
        unguarded code, exactly as it did before this feature existed."""
        return self.complications or bool(self.fields)


def compute_guards(face: Face, devices: Iterable[Device]) -> Guards:
    """The `Guards` the shared generated code needs for `face`, across every
    device in `devices` (a build's full target list, not just the one
    `wfb.layout.resolve` happened to generate the view from -- the view is
    shared, so the guard decision has to be too).
    """
    devices = list(devices)
    complications = uses_complications(face) and any(
        not device.has_module("Complications") for device in devices
    )
    used_fields = design_fields(face)
    missing_fields = frozenset(
        field for field in used_fields
        if any(not device.has_field(field) for device in devices)
    )
    return Guards(complications=complications, fields=missing_fields)
