"""Assemble a complete, compilable Connect IQ project from a resolved design."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .. import formatting
from ..devices import Device
from ..fonts import BakedFont
from ..ir import Face
from ..layout import ResolvedFace
from . import jungle, manifest, monkeyc, resources, strhash

RUNTIME_LIB = Path(__file__).resolve().parent.parent.parent / "runtime-lib"

#: Support-barrel files, and what pulls each one in.  Only what a face uses is
#: copied, so an unused helper costs nothing (ADR 0003).
BARREL_FILES = {
    "WfbMath.mc": "expression functions",
    "WfbTime.mc": "12/24-hour clock handling",
    "WfbArc.mc": "arcs -- a `progress` ring and a plain `shape: arc` alike",
    "WfbWeather.mc": "weather-condition icon glyphs",
    "WfbComplications.mc": "safe complication subscription and pull",
    "WfbSeries.mc": "graph time-series acquisition, binning and drawing",
    "WfbHands.mc": "analog hands -- rotate a hand's resolved geometry by the time and draw it",
}


@dataclass
class GeneratedProject:
    face: Face
    devices: list[Device]
    root: Path
    sources: list[monkeyc.SourceFile] = field(default_factory=list)
    bundles: list[resources.ResourceBundle] = field(default_factory=list)
    manifest_text: str = ""
    jungle_text: str = ""
    strings_text: str = ""
    barrel: list[str] = field(default_factory=list)
    resolved: dict[str, ResolvedFace] = field(default_factory=dict)
    #: String literals that would still share a monkeyc `str___<hash>` label
    #: after `_avoid_string_label_collisions` -- `wfb.build` reports each as an
    #: error, because monkeyc would otherwise crash on them.
    string_collisions: list[strhash.Collision] = field(default_factory=list)

    def files(self) -> dict[str, str]:
        """Every text file this project consists of, for golden-file tests."""
        out = {
            "manifest.xml": self.manifest_text,
            "monkey.jungle": self.jungle_text,
            "resources/strings/strings.xml": self.strings_text,
        }
        for source in self.sources:
            out[source.path] = source.text
        for bundle in self.bundles:
            for relative, text in bundle.files.items():
                out[f"{bundle.directory}/{relative}"] = text
        return out


def generate(face: Face, devices: list[Device], root: Path,
             baked: dict[str, dict[str, BakedFont]] | None = None) -> GeneratedProject:
    """Build the project in memory.  :func:`write` puts it on disk."""
    from ..layout import resolve

    project = GeneratedProject(face=face, devices=devices, root=root)

    project.sources.append(monkeyc.emit_app(face))
    if face.palette:
        project.sources.append(monkeyc.emit_palette(face))

    features = _features(face)
    project.manifest_text = manifest.render(face, devices, features)
    project.jungle_text = jungle.render(face, devices)
    project.strings_text = resources.shared_strings(face)

    for device in devices:
        fonts = (baked or {}).get(device.id)
        if fonts is None:
            fonts = resources.bake_fonts(face, device)
        resolved = resolve(face, device, fonts)
        project.resolved[device.id] = resolved
        project.sources.append(monkeyc.emit_layout(resolved))
        project.bundles.append(resources.build_bundle(face, device, fonts))

    # The view is shared across devices; generate it from the first resolved
    # device, since only the Layout constants differ between them.
    first = project.resolved[devices[0].id]
    needs_icon_glyphs = (
        any(placed.kind == "icon" and placed.element.is_dynamic for placed in first.items)
        or any(placed.kind == "complication_slot" and placed.element.icon_size is not None
               for placed in first.items)
    )
    if needs_icon_glyphs:
        project.sources.append(monkeyc.emit_icon_glyphs(face))
    project.sources.append(monkeyc.emit_view(first))
    if monkeyc.complication_slots(face):
        # The native editor's animated highlight over a complication_slot --
        # dead weight on a design with none (research 07 §1: the callback
        # that would ever construct one never fires outside the editor).
        project.sources.append(monkeyc.emit_slot_drawable(face))
    if monkeyc.needs_delegate(face):
        # Shared across devices like the view: the hit regions it references
        # are Layout constants, which are already per-device.  A `config:`-only
        # design (no on_hold) also needs one, purely for
        # onWatchFaceConfigEdited -- see monkeyc.needs_delegate.
        project.sources.append(monkeyc.emit_delegate(first))
    project.barrel = _barrel_for(face, first)
    _avoid_string_label_collisions(project)
    return project


def _program_texts(project: GeneratedProject) -> dict[str, str]:
    """Every Monkey C source monkeyc will assemble into one program."""
    texts = {source.path: source.text for source in project.sources}
    for name in project.barrel:
        texts[f"runtime-lib/{name}"] = (RUNTIME_LIB / name).read_text(encoding="utf-8")
    return texts


def _avoid_string_label_collisions(project: GeneratedProject) -> None:
    """Keep two different string literals from sharing one monkeyc label.

    monkeyc labels a string constant by its Java hash and crashes when two
    different strings share one (`wfb.emit.strhash`). The only literals this
    compiler can move out of the way without changing behaviour are the
    glyphs in `IconGlyphs.mc`: any glyph involved in a collision is rebuilt
    at runtime with `Number.toChar` instead. Anything left over is recorded
    on the project for `wfb.build` to report.
    """
    found = strhash.collisions(_program_texts(project))
    if not found:
        return
    index = next((i for i, source in enumerate(project.sources)
                  if source.path == "source/IconGlyphs.mc"), None)
    if index is not None:
        colliding = {text for collision in found for text in collision.strings}
        entries = monkeyc.icon_glyph_entries(project.face)
        via_char = frozenset(key for key, glyph in entries.items() if glyph in colliding)
        if via_char:
            project.sources[index] = monkeyc.emit_icon_glyphs(project.face, via_char)
            found = strhash.collisions(_program_texts(project))
    project.string_collisions = found


def write(project: GeneratedProject, *, clean: bool = True) -> list[Path]:
    root = project.root
    if clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for relative, text in (
        ("manifest.xml", project.manifest_text),
        ("monkey.jungle", project.jungle_text),
        ("resources/strings/strings.xml", project.strings_text),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)

    for source in project.sources:
        path = root / source.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.text, encoding="utf-8")
        written.append(path)

    barrel_dir = root / "runtime-lib"
    barrel_dir.mkdir(parents=True, exist_ok=True)
    for name in project.barrel:
        destination = barrel_dir / name
        shutil.copyfile(RUNTIME_LIB / name, destination)
        written.append(destination)

    for bundle in project.bundles:
        written.extend(resources.write_bundle(bundle, root))
    return written


def _is_time_value(element) -> bool:
    from ..catalog import Type

    return element.value is not None and element.value.value.type is Type.TIME


def _features(face: Face) -> set[str]:
    """Which API-gated features this design uses.  Drives ``minApiLevel``."""
    from ..catalog import READERS

    features: set[str] = set()
    if any(READERS[name].complication_type for name in face.requirements().readers):
        features.add("complications")
    if face.config_data:
        # A `config: data:` slot reads `Toybox.Complications` (`Complications.
        # Id`, `Complications.COMPLICATION_TYPE_*`) even though it is not a
        # catalogue reader at all -- the type the wearer picks is not known
        # until runtime, so `face.requirements().readers` above never sees it.
        features.add("complications")
    if monkeyc.launches_a_glance(face):
        # `Complications.exitTo` is what an `on_hold:` compiles to -- API
        # 4.2.0, the same floor a complication *reader* needs, for the same
        # module. Deliberately not onTap's own 5.1.0: nothing the generator
        # emits references onTap at all, because onTap never fires outside
        # the on-device config editor (research 07 1a).
        features.add("complications")
    # `config:` deliberately adds nothing here: the probe confirms
    # <watchface-config> forces no minApiLevel bump
    # (docs/research/probes/watchface-config/), and the whole feature is
    # gated by `Device.has_symbol`, a runtime check, not a version compare
    # (constraint 6) -- so raising the floor for every device would be wrong
    # even for a design that never targets fr955.
    return features


def _barrel_for(face: Face, resolved: ResolvedFace) -> list[str]:
    needed: set[str] = set()
    plan = monkeyc.ReadPlan(resolved)
    if face.barrel_functions():
        needed.add("WfbMath.mc")
    if plan.complication_readers() or face.config_data:
        # A `config: data:` slot pulls through `WfbComplications.valueOf` too,
        # even though it binds no ordinary `complication.*` catalogue reader
        # at all -- see `_features` above for the same reasoning.
        needed.add("WfbComplications.mc")
    for placed in resolved.items:
        kind = placed.kind
        if kind == "progress":
            needed.add("WfbArc.mc")
            needed.add("WfbMath.mc")  # the fill fraction goes through percent()
        elif kind == "shape" and placed.element.shape == "arc":
            # A plain arc draws through the same WfbArc.drawSpan a progress
            # element's unfilled track uses -- one arc convention, one helper.
            needed.add("WfbArc.mc")
        elif kind == "text":
            element = placed.element
            spec = getattr(element, "format", None)
            # Only a *time* format needs the clock helpers; a date format reads
            # Gregorian fields directly and a literal % is just punctuation.
            if spec and formatting.is_time_spec(spec) and _is_time_value(element):
                needed.add("WfbTime.mc")
        elif kind == "icon" and placed.element.is_dynamic:
            needed.add("WfbWeather.mc")
        elif kind == "graph":
            needed.add("WfbSeries.mc")
        elif kind == "hands":
            needed.add("WfbHands.mc")
    return sorted(needed)
