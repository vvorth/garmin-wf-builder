"""`source/SlotScale.mc` -- a gauge's automatic scale for the complication
type it shows (`wfb.complications.SCALE`)."""

from __future__ import annotations

from collections.abc import Iterable

from ... import complications
from ...ir import Face, Progress
from ..writer import Writer
from .common import SourceFile, header

#: The generated module a gauge's automatic scale comes from.
SLOT_SCALE_MODULE = "SlotScale"


def _number(value: float) -> str:
    """A scale figure as a Monkey C literal: whole figures as Numbers."""
    return str(int(value)) if value == int(value) else repr(value)


def _vo2max_ends() -> list[float]:
    """`WfbProfileScale.vo2max`'s table: the female rows then the male rows, ages
    20-29 to 70-79, each a minimum then a maximum."""
    ends: list[float] = []
    for sex in ("female", "male"):
        for fair, _, _, superior in complications.VO2MAX_RATINGS[sex]:
            ends.extend(complications.vo2max_ends(fair, superior))
    return ends


def slot_scale_text(names: Iterable[str], apps: bool, header_text: str) -> str:
    """The module's source: a case for each of ``names`` that has a scale,
    and, with ``apps``, one for a Connect IQ app's complication, which only
    its own `ranges` can scale."""
    scaled = [name for name in sorted(set(names)) if name in complications.SCALE]
    by_kind: dict[str, list[str]] = {}
    for name in scaled:
        by_kind.setdefault(complications.SCALE[name].kind, []).append(name)

    def case(name: str) -> str:
        return f"case Complications.{complications.TYPES[name].constant}:"

    w = Writer()
    w.doc(header_text).blank()
    imports = ["import Toybox.Complications;", "import Toybox.Lang;"]
    if "goal" in by_kind:
        imports.insert(0, "import Toybox.ActivityMonitor;")
    w.lines(*imports).blank()
    w.doc(
        "A gauge's automatic scale for the complication type it shows,\n"
        "generated from wfb.complications.SCALE."
    )
    with w.block(f"module {SLOT_SCALE_MODULE}"):
        if "vo2max" in by_kind:
            w.doc("WfbProfileScale.vo2max's table, from wfb.complications.VO2MAX_RATINGS.")
            figures = ", ".join(repr(value) for value in _vo2max_ends())
            w.line(f"const VO2MAX_ENDS = [{figures}] as Array<Float>;")
            w.blank()
        w.doc(
            "`[minimum, maximum]` for the pulled complication `c`, of type `t`, or\n"
            "null when it has no scale."
        )
        with w.block("function scale(t as Complications.Type, c as Complications.Complication)\n"
                     "        as Array<Numeric>?"):
            if "goal" in by_kind:
                w.line("var info = ActivityMonitor.getInfo();")
            with w.block("switch (t)"):
                fixed: dict[tuple[float, float], list[str]] = {}
                for name in by_kind.get("fixed", []):
                    scale = complications.SCALE[name]
                    fixed.setdefault((scale.minimum, scale.maximum), []).append(name)
                for (low, high), group in fixed.items():
                    for name in group:
                        w.line(case(name))
                    w.line(f"    return [{_number(low)}, {_number(high)}] as Array<Numeric>;")
                for name in by_kind.get("goal", []):
                    field = complications.SCALE[name].goal
                    # some devices lack a goal field altogether (pushGoal, or
                    # floorsClimbedGoal without a barometer)
                    w.line(case(name))
                    w.line(f"    return WfbScale.upTo((info has :{field}) ? info.{field} : null);")
                for name in by_kind.get("heart_rate_zones", []):
                    w.line(case(name))
                    w.line("    return WfbProfileScale.heartRate();")
                for name in by_kind.get("vo2max", []):
                    w.line(case(name))
                if "vo2max" in by_kind:
                    w.line("    return WfbProfileScale.vo2max(VO2MAX_ENDS, c);")
                if apps:
                    w.line("case Complications.COMPLICATION_TYPE_INVALID:")
                    w.line("    return WfbScale.ranges(c);")
            w.line("return null;")
    return w.render()


def emit_slot_scale(face: Face, names: Iterable[str], apps: bool) -> SourceFile:
    """`source/SlotScale.mc` for ``face``: see :func:`slot_scale_text`."""
    return SourceFile(f"source/{SLOT_SCALE_MODULE}.mc",
                      slot_scale_text(names, apps, header(face)))


def slot_gauges(face: Face) -> list[Progress]:
    """Every gauge drawing a declared `config: slots:` slot, in draw order."""
    return [e for e in face.walk()
            if isinstance(e, Progress) and e.slot is not None and e.slot in face.config_data]


def slot_scale_types(face: Face) -> tuple[list[str], bool]:
    """The complication types a slot gauge can show, and whether any can show
    a Connect IQ app's complication (`choices: any`)."""
    names: set[str] = set()
    apps = False
    for gauge in slot_gauges(face):
        assert gauge.slot is not None
        slot = face.config_data[gauge.slot]
        names |= set(complications.TYPES) if slot.allow_any else set(slot.choices)
        apps = apps or slot.allow_any
    return sorted(names), apps


#: The `wfb.complications.SCALE` kinds that read `Toybox.UserProfile`.
PROFILE_SCALES = frozenset({"heart_rate_zones", "vo2max"})


def reads_user_profile(face: Face) -> bool:
    """Does a slot gauge's scale read the wearer's profile (heart-rate zones,
    sex and birth year), so the build needs the `UserProfile` permission?"""
    names, _ = slot_scale_types(face)
    return any(name in complications.SCALE and complications.SCALE[name].kind in PROFILE_SCALES
               for name in names)
