"""`ReadPlan` -- which API calls happen, and where, for one view."""

from __future__ import annotations

from ... import catalog, formatting
from ...availability import Guards
from ...catalog import READERS, Type
from ...ir import HandsElement, Progress, Text, local_name
from ...layout import ResolvedFace
from .common import _NO_GUARDS
from ..writer import Writer


# --------------------------------------------------------------------------
# the read plan: which API calls happen, and where


class ReadPlan:
    """Decides which reader locals each element needs, and hoists the reads.

    Sources are grouped by reader so that ``ActivityMonitor.getInfo()`` is called
    once per frame no matter how many fields read off it, and every nullable
    field becomes a named local that the element's guard narrows.

    ``guards`` (`wfb.availability.Guards`) says which of this *build*'s
    target devices lack something this design uses -- a module
    (`Complications`) or a bare field (e.g. `stressScore`) -- aggregated over
    every target, since the view/delegate this plan drives is generated once
    and shared across all of them (`wfb/emit/project.py`'s `generate`).
    Defaults to :data:`_NO_GUARDS` so every existing call site that builds a
    `ReadPlan` without one -- every test that predates this feature, and any
    single-device caller -- keeps generating exactly the code it always did:
    a guard is only ever added on top of that baseline, never removed from
    it, and only for a target set that actually needs one.
    """

    def __init__(self, resolved: ResolvedFace, guards: "Guards | None" = None) -> None:
        self.resolved = resolved
        self.device_guards = guards if guards is not None else _NO_GUARDS
        self.modules: set[str] = set()
        self.barrel: set[str] = set(resolved.face.barrel_functions())
        #: Every source an element touches, for reader hoisting.
        self._per_element: dict[str, list[str]] = {}
        #: The subset referenced by compiled expressions, which read through a
        #: named local.  Format specs read their reader directly instead.
        self._bound: dict[str, list[str]] = {}
        #: The subset of `_bound` reached through the element's *value*
        #: expression(s) specifically -- `Text.value`, or `Progress.value`
        #: and `Progress.maximum` together, since both feed one fraction.
        #: This is what a `when_absent: placeholder`/`fallback` policy
        #: actually governs (Bug 5).
        self._value_bound: dict[str, list[str]] = {}
        #: The subset reached through every *other* expression (colour, track
        #: colour, max on its own) -- collected independently of
        #: `_value_bound`, not by subtracting it, because a source can be
        #: dereferenced at *both* sites (`value: heart_rate.current` and
        #: `color: "heart_rate.current > 100 ? ..."`) and each site needs its
        #: own protection: the value's dereference is what `when_absent`
        #: covers, but the colour's is a second, independent dereference of
        #: the same possibly-null local, which a placeholder for the *text*
        #: does nothing to protect.
        self._other_bound: dict[str, list[str]] = {}
        #: The subset reached through `visible:` (SPEC.md T5).  Kept apart from
        #: both of the above because a visibility binding gets its *own* guard,
        #: emitted first and combined with the condition itself
        #: (`if (x == null || !(cond)) { return; }`) -- "absent means hidden".
        #: Paths that land here are subtracted from the value and other guards
        #: rather than being null-checked twice: that guard has already
        #: returned, so a second `== null` on the same local would be dead code
        #: a human reviewer would (rightly) ask about.
        self._visible_bound: dict[str, list[str]] = {}
        self._readers_for_mode: dict[str, list[str]] = {}
        self._analyse()

    def _analyse(self) -> None:
        for placed in self.resolved.items:
            element = placed.element
            value_exprs = self._value_expressions(element)
            paths: list[str] = []
            value_paths: list[str] = []
            other_paths: list[str] = []
            visible_paths: list[str] = []
            for expression in element.expressions():
                self.modules |= set(expression.modules)
                is_value = any(expression is v for v in value_exprs)
                is_visible = expression is element.visible
                for path in expression.sources:
                    if path not in paths:
                        paths.append(path)
                    if is_visible:
                        if path not in visible_paths:
                            visible_paths.append(path)
                    elif is_value:
                        if path not in value_paths:
                            value_paths.append(path)
                    elif path not in other_paths:
                        other_paths.append(path)
            # A time format reads the clock (and, for %h, the device settings)
            # even though the format string names no source.
            format_paths: list[str] = []
            if (isinstance(element, Text) and element.format
                    and formatting.is_time_spec(element.format)):
                # A date format reads the calendar; a time format reads the clock,
                # and %h additionally reads the 12/24-hour setting.
                if element.value is not None and element.value.value.type is Type.DATE:
                    format_paths.append("date.today")
                else:
                    format_paths.append("time.clock")
                    if "%h" in element.format:
                        format_paths.append("device.is_24_hour")
            # A hands element reads the clock too, with no author expression
            # at all (plan 04 §5.5) -- the same `time.clock` reader a `Text`
            # element's own time format uses, which is what gives every
            # `draw<Id>(dc, ...)` a `clock as System.ClockTime` parameter for
            # free, through `parameters`/`arguments` below, with no
            # hands-specific code at either call site.
            if isinstance(element, HandsElement):
                format_paths.append("time.clock")
            self._bound[placed.id] = list(paths)
            self._visible_bound[placed.id] = list(visible_paths)
            # A path read by `visible:` needs no second guard anywhere else on
            # the element: the visibility guard runs first and returns on null.
            self._value_bound[placed.id] = [p for p in value_paths if p not in visible_paths]
            self._other_bound[placed.id] = [p for p in other_paths if p not in visible_paths]
            paths = paths + [p for p in format_paths if p not in paths]
            self._per_element[placed.id] = paths
            for path in paths:
                self.modules.add(READERS[catalog.CATALOG[path].reader].module)

        for mode in ("active", "low_power", "always_on"):
            readers: list[str] = []
            for placed in self.resolved.items:
                if mode not in placed.element.modes:
                    continue
                readers = self._dedupe_readers(self._per_element[placed.id], readers)
            self._readers_for_mode[mode] = readers

    # -- emission ---------------------------------------------------------

    def complication_readers(self) -> list[str]:
        """Reader names this design reads through `Toybox.Complications`.

        These are the readers `onLayout` subscribes to.  The *read* itself is
        an ordinary pull like every other reader (`emit_reads` below) -- the
        subscription only keeps the platform's own value fresh, it is not how
        the value arrives.  Found under every mode, not just `active`: with
        the refresh-tier concept gone there is nothing stopping a `low_power`
        element binding one.
        """
        names = {name for readers in self._readers_for_mode.values()
                 for name in readers if READERS[name].complication_type}
        return sorted(names)

    def emit_reads(self, w: Writer, mode: str) -> None:
        readers = self._readers_for_mode.get(mode) or []
        if not readers:
            return
        w.comment("data for this frame" if mode == "active"
                  else f"data for this frame ({mode}); every reader is a plain pull")
        # A complication reader's own `call` builds `new Complications.Id(...)`
        # inline -- that construction runs *before* WfbComplications.valueOf
        # is ever reached, so a guard inside the barrel alone would not stop
        # it.  One `hasComplications` local per frame (not per reader) is
        # enough: every complication pull this mode uses reads through it.
        guard_complications = self.device_guards.complications and any(
            READERS[name].requires_module for name in readers
        )
        if guard_complications:
            w.line("var hasComplications = Toybox has :Complications;")
        for name in readers:
            # Every reader is a plain pull, complications included: the value
            # each one returns is already the platform's own cached reading
            # (`Weather.getCurrentConditions()` is documented as "the most
            # recently cached weather conditions"), so a second cache inside
            # the face's 128 KB would re-store what the system already holds.
            reader = READERS[name]
            if guard_complications and reader.requires_module:
                # Absent on a device lacking Toybox.Complications (fenix6,
                # fr245): reads as null, the same "absence is normal"
                # contract every other nullable reader already has -- the
                # element's own guard downstream cannot tell this apart from
                # an ordinary unsupported complication *type*.
                w.line(f"var {reader.name} = hasComplications ? {reader.call} : null;")
            else:
                w.line(f"var {reader.name} = {reader.call};")

    def parameters(self, placed) -> str:
        params = []
        for name in self._readers_used_by(placed):
            reader = READERS[name]
            params.append(f", {reader.name} as {reader.monkeyc_type}")
        return "".join(params)

    def arguments(self, placed) -> str:
        return "".join(f", {READERS[name].name}" for name in self._readers_used_by(placed))

    def _guard_needed(self, source) -> bool:
        """Whether `declarations()` gave this source's local a nullable type.

        `Source.guard_needed` alone (nullable itself, or its reader is) is
        the whole answer when every target device has everything this
        design uses -- the `_NO_GUARDS` baseline, where this is exactly
        `source.guard_needed` and nothing here changes behaviour. A field
        some target lacks (`self.device_guards.fields`) widens it: `declarations()`
        wraps that field's read in a `has`-guarded ternary regardless of
        the source's own declared nullability (`system.battery_in_days` is
        declared non-null -- Stats fields "are" non-null when present -- yet
        `fr245` lacks the field entirely, which is a *different* kind of
        absence than the SDK's own nullability and still needs the local
        guarded), so every caller that decides whether an element must
        null-check this local has to agree with that, or the generated draw
        method would dereference a local `declarations()` just made
        nullable.
        """
        if source.guard_needed:
            return True
        root = source.field_name.split(".", 1)[0] if source.field_name else None
        return root is not None and root in self.device_guards.fields

    def guards(self, placed) -> list[str]:
        """Every local the element must null-check, declared in dependency order.

        Used as-is for an element with no placeholder/fallback policy (the
        whole thing hides together, as one guard always has); split into
        :meth:`value_guards`/:meth:`other_guards` for one that has one
        (Bug 5): the policy governs the value, not a colour.
        """

        names: list[str] = []
        visible = self._visible_bound[placed.id]
        for path in self._bound[placed.id]:
            if path in visible:
                # Already null-checked by the visibility guard above.
                continue
            source = catalog.CATALOG[path]
            if self._guard_needed(source):
                names.append(local_name(path))
        return names

    def _guarded_locals(self, paths: list[str]) -> list[str]:
        """``paths`` narrowed to the ones that actually need a null check
        (`_guard_needed`), each turned into its local's name -- the one
        filter-then-name step `value_guards`/`visible_guards`/`other_guards`
        all perform, over three different path lists.
        """
        return [local_name(path) for path in paths if self._guard_needed(catalog.CATALOG[path])]

    def value_guards(self, placed) -> list[str]:
        """Locals reached through the element's own *value* expression(s)."""

        return self._guarded_locals(self._value_bound[placed.id])

    def visible_guards(self, placed) -> list[str]:
        """Locals `visible:` dereferences, in declaration order.

        These become the `x == null` halves of the visibility guard
        (`_emit_visible_guard`).  "Absent means hidden" is the whole rule:
        unlike a value, an unavailable reading has no substitute, so there is
        no `when_absent:` to consult here.
        """

        return self._guarded_locals(self._visible_bound[placed.id])

    def other_guards(self, placed) -> list[str]:
        """Locals dereferenced by a *different* expression (colour, track
        colour, max) -- there is no placeholder for a colour, so every one of
        these needs a real guard (Bug 5), even a source that is *also* the
        value: `color: "heart_rate.current > 100 ? ..."` dereferences
        `heartRateCurrent` at its own call site, which a placeholder guarding
        only the text's dereference does nothing to protect.
        """

        return self._guarded_locals(self._other_bound[placed.id])

    @staticmethod
    def _value_expressions(element) -> tuple:
        """Which of an element's expressions its `when_absent:` policy governs.

        A `Text`'s only substitutable value is `value:`; a `Progress`'s fill
        fraction depends on both `value:` and `max:` together (one nullable
        reading is as absent as the other, from the fraction's point of
        view), which is also why `Builder._build_progress` checks their
        combined nullability as one thing. Every other element kind has no
        `when_absent:` field at all, so nothing here is "the value" -- every
        binding is an "other" one, guarded unconditionally.
        """
        if isinstance(element, Text):
            return (element.value,) if element.value is not None else ()
        if isinstance(element, Progress):
            return tuple(e for e in (element.value, element.maximum) if e is not None)
        return ()

    def declarations(self, placed) -> list[tuple[str, str]]:

        out: list[tuple[str, str]] = []
        for path in self._bound[placed.id]:
            source = catalog.CATALOG[path]
            if source.field_name is None and source.type in (Type.TIME, Type.DATE):
                # time.clock/date.today: formatting.py reads the reader
                # parameter (`clock`/`date`) directly by name instead of
                # through a value local, so declaring one here would go
                # unused. Any other field_name-less source (an EVENT-tier
                # complication, where the reader *is* the value) still wants
                # its own named local below, the same as a source with a
                # field_name -- it is what `guards()` and the compiled
                # expression both reference by name.
                continue
            reader = READERS[source.reader]
            base = (reader.name if source.array_index is None
                    else f"{reader.name}[{source.array_index}]")
            guard_parts = []
            if reader.nullable:
                # The reader itself can be absent -- Activity.getActivityInfo()
                # returns null when there is no activity -- so the field cannot
                # be dereferenced unconditionally.  Narrowing here keeps the
                # element's own `when_absent` guard below unchanged: an absent
                # reader and an absent field are the same thing to the design.
                guard_parts.append(f"{reader.name} != null")
            if source.array_guard is not None:
                # An Array being non-null does not mean it has an element at
                # this index -- a forecast provider can return fewer days than
                # asked for. Short-circuit `&&` means the null check above (if
                # any) always runs first, so `.size()` never hits a null array.
                guard_parts.append(source.array_guard)

            intermediate = source.intermediate
            # `_guard_needed`/`wfb.availability.design_fields` both key a
            # device-absent field by its *first* dotted segment -- for a
            # dotted `field_name` that is the intermediate object itself
            # (`activeMinutesWeek`, not `.total`, which belongs to a
            # different class entirely -- `Device.has_field` cannot resolve
            # a nested field to its owning class, see that method's own
            # caveat), and for a plain one it is `field_name` unchanged.
            # `x has :field` is the SDK's own documented idiom
            # ($CIQ_SDK/doc/docs/Monkey_C/Functions.html) for exactly this:
            # unlike `guard_parts` above (a *nullable* reading, still the
            # same field on every device), this is a field some target
            # device does not declare *at all* -- a device missing it
            # entirely throws "Symbol Not Found" on any unconditional
            # reference, not just a null one.
            field_root = intermediate if intermediate is not None else source.field_name
            if field_root is not None and field_root.split(".", 1)[0] in self.device_guards.fields:
                guard_parts.append(f"{base} has :{field_root.split('.', 1)[0]}")

            if intermediate is not None:
                # A dotted field_name (`activeMinutesWeek.total`) has its own
                # nullable intermediate object.  monkeyc's flow typing narrows
                # a *local variable*, not a field-access expression, inside a
                # ternary -- `(reader.field != null) ? reader.field.x : null`
                # still typechecks `.x` against the declared (nullable) type
                # of `reader.field` and fails -- confirmed against a real
                # build, not assumed.  So the intermediate gets its own local
                # first, and the final field is guarded off *that* local,
                # exactly the pattern every other nullable field here uses.
                obj_read = f"{base}.{intermediate}"
                if guard_parts:
                    obj_read = f"({' && '.join(guard_parts)}) ? {obj_read} : null"
                obj_name = f"{local_name(path)}Obj"
                out.append((obj_name, obj_read))
                suffix = source.field_name[len(intermediate) + 1:]
                out.append((local_name(path), f"({obj_name} != null) ? {obj_name}.{suffix} : null"))
                continue

            read = source.read_expr
            if source.cast is not None:
                # `Complication.value` is a union (`String or Number or Float or
                # Long or Double or Null`), so -l 3 will not let it reach a
                # typed local unaided.  The cast binds tighter than the ternary
                # below, and needs no parentheses of its own -- confirmed by a
                # real build, see docs/research/probes/complication-pull/.
                read = f"{read} as {source.cast}"
            if guard_parts:
                read = f"({' && '.join(guard_parts)}) ? {read} : null"
            out.append((local_name(path), read))
        return out

    def _readers_used_by(self, placed) -> list[str]:
        return self._dedupe_readers(self._per_element[placed.id])

    @staticmethod
    def _dedupe_readers(paths: list[str], into: list[str] | None = None) -> list[str]:
        """The reader each of ``paths`` reads through, in first-seen order
        with no repeats -- shared by `_analyse` (which folds every element in
        one mode's readers together, passing its running list as ``into``)
        and `_readers_used_by` (one element at a time, starting fresh).
        """
        readers = list(into) if into is not None else []
        for path in paths:
            reader = catalog.CATALOG[path].reader
            if reader not in readers:
                readers.append(reader)
        return readers

    def sources_for(self, placed) -> list[str]:
        return self._per_element[placed.id]
