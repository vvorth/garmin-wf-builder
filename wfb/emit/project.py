"""Assemble a complete, compilable Connect IQ project from a resolved design."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..availability import compute_guards
from ..devices import Device
from ..fonts import BakedFont
from ..ir import Face
from ..layout import ResolvedFace, resolve
from . import jungle, manifest, monkeyc, resources, strhash, usage
from .usage import RUNTIME_LIB

#: Support-barrel files, and what pulls each one in.  Only what a face uses is
#: copied, so an unused helper costs nothing (ADR 0003).
BARREL_FILES = {
    "WfbMath.mc": "expression functions",
    "WfbTime.mc": "12/24-hour clock handling",
    "WfbArc.mc": "arcs -- a `progress` ring, a plain `shape: arc` and a pattern arc part alike",
    "WfbWeather.mc": "weather-condition icon glyphs",
    "WfbComplications.mc": "safe complication subscription and pull",
    "WfbSeries.mc": "graph time-series acquisition, binning and drawing",
    "WfbHands.mc": "analog hands -- the three clock-to-angle functions",
    "WfbGeom.mc": "rotate/translate-and-draw helpers shared by analog hands and patterns",
    "WfbColor.mc": "aod: {dim: ...} -- dimming a colour not known until the device resolves it",
    "WfbAodMask.mc": "aod: {mask: ...} -- the moving 2x2 pixel mask over the AOD frame",
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

    def generated_text(self) -> dict[str, str]:
        """The project-level files and every generated Monkey C source, by
        path -- everything but the resource bundles and the barrel copy."""
        out = {
            "manifest.xml": self.manifest_text,
            "monkey.jungle": self.jungle_text,
            "resources/strings/strings.xml": self.strings_text,
        }
        for source in self.sources:
            out[source.path] = source.text
        return out

    def files(self) -> dict[str, str]:
        """Every text file this project consists of, for golden-file tests."""
        out = self.generated_text()
        for bundle in self.bundles:
            for relative, text in bundle.files.items():
                out[f"{bundle.directory}/{relative}"] = text
        return out


def generate(face: Face, devices: list[Device], root: Path,
             baked: dict[str, dict[str, BakedFont]] | None = None) -> GeneratedProject:
    """Build the project in memory.  :func:`write` puts it on disk."""
    project = GeneratedProject(face=face, devices=devices, root=root)

    project.sources.append(monkeyc.emit_app(face))
    if face.palette:
        project.sources.append(monkeyc.emit_palette(face))

    guards = compute_guards(face, devices)
    project.manifest_text = manifest.render(face, devices)
    project.jungle_text = jungle.render(face, devices)
    project.strings_text = resources.shared_strings(face)

    for device in devices:
        fonts = (baked or {}).get(device.id)
        if fonts is None:
            fonts = resources.bake_fonts(face, device)
        resolved = resolve(face, device, fonts)
        project.resolved[device.id] = resolved
        project.sources.append(monkeyc.emit_layout(resolved, guards))
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
    project.sources.append(monkeyc.emit_view(first, guards))
    if monkeyc.complication_slots(face):
        # The native editor's animated highlight over a complication_slot --
        # the callback that constructs it never fires outside the editor
        # (docs/research/07-carousel-interaction.md), so a design with no
        # slots emits none of it.
        project.sources.append(monkeyc.emit_slot_drawable(face))
    if monkeyc.needs_delegate(face):
        # Shared across devices like the view: the hit regions it references
        # are Layout constants, which are already per-device.  A `config:`-only
        # design (no on_hold) also needs one, purely for
        # onWatchFaceConfigEdited -- see monkeyc.needs_delegate.
        project.sources.append(monkeyc.emit_delegate(first, guards))
    project.barrel = sorted(usage.barrel_modules(source.text for source in project.sources))
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
    for relative, text in project.generated_text().items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
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


