"""The build pipeline, end to end.

    YAML -> schema -> IR -> per-device resolve -> lint -> generate -> monkeyc

The stages are ordered so that each error is reported against the earliest
representation that can explain it (ADR 0008), and so that everything up to and
including code generation runs with **no Garmin toolchain** -- which is what
makes the compiler testable in CI, where device files are unavailable.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import desugar, lint, validate, yamlsrc
from .devices import Device, DeviceDatabase, DeviceError, version_key
from .diagnostics import Bag
from .emit import GeneratedProject, generate
from .emit import strhash
from .emit.manifest import BASE_API_LEVEL
from .emit.project import write as write_project
from .fonts import BakedFont
from .ir import Face, build as build_ir
from .layout import ResolvedFace


@dataclass
class BuildResult:
    face: Face
    project: GeneratedProject
    devices: list[Device]
    output_dir: Path
    products: dict[str, Path] = field(default_factory=dict)
    memory: dict[str, dict] = field(default_factory=dict)
    duration: float = 0.0


@dataclass
class Toolchain:
    sdk: Path
    key: Path

    @classmethod
    def discover(cls, sdk: str | None = None, key: str | None = None) -> "Toolchain | None":
        sdk_path = Path(sdk or os.environ.get("CIQ_SDK", "")).expanduser()
        key_path = Path(key or os.environ.get("WFB_KEY", Path.home() / "ciq" / "developer_key.der"))
        if not (sdk_path / "bin" / "monkeyc").exists():
            return None
        return cls(sdk_path, key_path.expanduser())

    @property
    def monkeyc(self) -> Path:
        return self.sdk / "bin" / "monkeyc"

    @property
    def version(self) -> str:
        text = (self.sdk / "bin" / "version.txt")
        return text.read_text(encoding="utf-8").strip() if text.exists() else self.sdk.name


# --------------------------------------------------------------------------
# stages 1-3: no Garmin toolchain required


def load(path: Path, bag: Bag) -> Face | None:
    """Parse and validate a design file into an IR, or report why not."""
    doc = yamlsrc.load(path, bag)
    if doc is None:
        return None
    # Stage 0.5: the author's conveniences become the one shape the schema, the
    # IR and codegen know about.  Runs before validation so the schema never has
    # to describe two spellings of the same thing (`wfb/desugar.py`).
    if not desugar.desugar(doc, bag):
        return None
    if not validate.validate(doc, bag):
        return None
    return build_ir(doc, bag)


def select_devices(face: Face, db: DeviceDatabase, bag: Bag,
                   only: list[str] | None = None) -> list[Device]:
    """The devices to resolve and build for: ``only`` (``-d/--device``) when
    given, the design's ``targets:`` otherwise.

    ``only`` may name any installed device, not just a listed target -- the
    generated project takes its product list from the devices passed to it,
    so trying a face on another watch needs no edit to the design.  Such a
    device draws one note, so it is clear the design never promised it."""
    wanted = list(dict.fromkeys(only)) if only else list(face.targets)
    devices: list[Device] = []
    for device_id in wanted:
        try:
            device = db.get(device_id)
        except DeviceError as exc:
            bag.error("target", str(exc))
            continue
        if not device.supports_watchface:
            bag.error("target", f"{device_id} cannot run a watch face at all")
            continue
        if version_key(device.api_level) < version_key(BASE_API_LEVEL):
            bag.error(
                "target",
                f"{device_id} is below the {BASE_API_LEVEL} floor this compiler "
                f"requires (its own ConnectIQ ceiling is {device.api_level})",
                notes=[
                    "every generated manifest declares minApiLevel="
                    f"\"{BASE_API_LEVEL}\" (wfb/emit/manifest.py's BASE_API_LEVEL); "
                    "a device below that floor cannot build at all, whether or not "
                    "the design uses anything that floor actually needs",
                ],
            )
            continue
        if device_id not in face.targets:
            bag.note(
                "target",
                f"{device_id} is not one of this design's targets; using it anyway "
                "because -d asked for it",
                notes=["targets: " + ", ".join(face.targets)],
            )
        devices.append(device)
    return devices


def resolve_all(face: Face, devices: list[Device], bag: Bag,
                ) -> tuple[dict[str, ResolvedFace], dict[str, dict[str, BakedFont]]]:
    """Resolve and lint the design once per target device."""
    from .emit.resources import bake_fonts
    from .layout import resolve

    lint.run_design(face, bag)

    resolved: dict[str, ResolvedFace] = {}
    baked: dict[str, dict[str, BakedFont]] = {}
    for device in devices:
        try:
            fonts = bake_fonts(face, device)
        except (OSError, ValueError) as exc:
            bag.error("font", f"{device.id}: {exc}")
            continue
        baked[device.id] = fonts
        result = resolve(face, device, fonts)
        resolved[device.id] = result
        lint.run(result, bag)
    # Cross-device (plan 11 §2.4): `if_unavailable:` asks "did gates 1-3
    # fail on ANY target?", which no single device's own `ResolvedFace` can
    # answer -- unlike everything `lint.run` checks above, this needs every
    # device in this build resolved first, so it runs once here rather than
    # once per device.
    lint.check_vector_font_availability(face, resolved, bag)
    return resolved, baked


# --------------------------------------------------------------------------
# stage 4: the real build


def build(path: Path, *, output: Path, bag: Bag, devices_only: list[str] | None = None,
          db: DeviceDatabase | None = None, toolchain: Toolchain | None = None,
          compile_prg: bool = True, clean: bool = True) -> BuildResult | None:
    started = time.monotonic()

    face = load(path, bag)
    if face is None:
        return None

    db = db or DeviceDatabase.discover()
    devices = select_devices(face, db, bag, devices_only)
    if not devices or not bag.ok():
        return None

    _, baked = resolve_all(face, devices, bag)
    if not bag.ok():
        return None

    build_dir = (output / slug(face.name)).resolve()
    project = generate(face, devices, build_dir, baked)
    for collision in project.string_collisions:
        shown = " and ".join(
            f"{strhash.describe(text)} ({', '.join(paths)})"
            for text, paths in collision.strings.items())
        bag.error(
            "string-label",
            f"monkeyc cannot compile this design: {shown} share the string "
            f"label str___{collision.hash}",
            notes=[
                "monkeyc names each string constant by its Java hash code and crashes "
                "(\"A critical error has occurred\") when two different strings share one",
                "change one of the two strings, or pick a different icon for one of them",
            ],
        )
    if project.string_collisions:
        return None
    try:
        write_project(project, clean=clean)
    except OSError as exc:
        bag.error(
            "io",
            f"cannot write the build directory {build_dir}: {exc.strerror or exc}",
            notes=[
                "the directory may be left over from a build run as a different user; "
                "remove it and try again",
            ],
        )
        return None

    result = BuildResult(face=face, project=project, devices=devices, output_dir=build_dir)

    if compile_prg:
        toolchain = toolchain or Toolchain.discover()
        if toolchain is None:
            bag.warning(
                "toolchain",
                "no Connect IQ SDK found, so nothing was compiled",
                notes=["set CIQ_SDK, or run ./tools/setup-env.sh",
                       f"the generated project is complete and is in {build_dir}"],
            )
        else:
            for device in devices:
                _compile(result, device, toolchain, bag)

    result.duration = time.monotonic() - started
    return result


def _compile(result: BuildResult, device: Device, toolchain: Toolchain, bag: Bag) -> None:
    output = result.output_dir / f"{slug(result.face.name)}-{device.id}.prg"
    #: Typecheck and optimization levels live in the generated jungle, not here, so
    #: that a hand-run `monkeyc -f monkey.jungle` reproduces this build exactly.
    #: Passing them on the command line as well makes monkeyc warn that one of the
    #: two specifications is being ignored.
    command = [
        str(toolchain.monkeyc),
        "-f", "monkey.jungle",
        "-d", device.id,
        "-o", str(output),
        "-y", str(toolchain.key),
        "-w",
        "--no-gen-styles",
        "--build-stats", "0",
    ]
    process = subprocess.run(
        command, cwd=result.output_dir, capture_output=True, text=True, check=False
    )
    text = _strip_noise(process.stdout + process.stderr)

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ERROR:"):
            bag.error("monkeyc", stripped[len("ERROR:"):].strip())
        elif stripped.startswith("WARNING:"):
            bag.warning("monkeyc", stripped[len("WARNING:"):].strip())

    if process.returncode != 0 or not output.exists():
        bag.error("monkeyc", f"{device.id}: build failed",
                  notes=[line for line in text.splitlines() if line.strip()][-6:])
        return

    result.products[device.id] = output
    stats = lint.check_memory(device, text, bag)
    if stats:
        result.memory[device.id] = stats
    else:
        # `check_memory` returns None when it cannot find the `--build-stats`
        # section in monkeyc's own output -- e.g. a future SDK reformats it.
        # Memory is measured, never estimated (ADR 0008), so a build that
        # silently skips the check is worse than one that says so: without
        # this, a build could go from "measured, under budget" to "never
        # measured again" and nothing would ever report the difference.
        bag.warning(
            "memory",
            f"{device.id}: could not parse monkeyc's --build-stats output, so "
            "this build was not checked against the watch-face memory limit",
            notes=["the .prg itself compiled fine; this is a gap in this "
                   "diagnostic, not evidence the design is too big"],
        )


_NOISE = re.compile(r"^.*JAVA_TOOL_OPTIONS.*$\n?", re.M)

#: The JVM's own deprecated-reflective-access notice, printed by protobuf's
#: ``UnsafeUtil`` inside the resource compiler whenever a
#: ``<watchface-config>`` resource is compiled (reproduced without any
#: generated content, ``docs/research/probes/watchface-config/``).  Its bare
#: ``WARNING:`` prefix would otherwise read as a `monkeyc` diagnostic about
#: the design; matched narrowly so an unrelated real warning stays reported.
_JVM_NOISE = re.compile(r"^.*(?:sun\.misc\.Unsafe|protobuf\.UnsafeUtil).*$\n?", re.M)


def _strip_noise(text: str) -> str:
    return _JVM_NOISE.sub("", _NOISE.sub("", text))


def slug(name: str) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in name)
    return re.sub(r"-+", "-", cleaned).strip("-") or "face"
