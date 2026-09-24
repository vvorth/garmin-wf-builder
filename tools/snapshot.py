#!/usr/bin/env python3
"""Record everything the compiler produces, so a later refactor can be
proven "no output change" or "exactly these outputs changed".

This is `docs/plans/19-architecture-refactor.md` step A0: it drives the
real `wfb` CLI as subprocesses (``sys.executable wfb.py ...``, cwd = repo
root) rather than internal APIs, so CLI wiring is covered too. It is a
separate tool, not part of the pytest suite (a full run takes minutes).

    ./tools/snapshot.py save DIR              # run every case, save to DIR
    ./tools/snapshot.py diff OLD NEW          # compare two saved snapshots
    ./tools/snapshot.py compare OLD           # save to a temp dir, then diff

Run from the repo root (or anywhere -- paths are resolved against this
file's own location, the same way `tools/docs-shots.py` does).

## Cases

Every `*.yaml` under `examples/` and `tests/fixtures/` is a *design*,
identified by its path relative to the repo root with the `.yaml` suffix
stripped (e.g. ``examples/features/graph/face``). For each design:

- ``build/<design>/{targets,amoled-mix,fenix9-mix}``: ``wfb build
  --no-compile`` for the design's own targets, then two mixed device sets
  (``fenix847mm fenix8solar47mm fr245 fenix6`` and ``fenix947mm fr955``).
  Captures stdout/stderr/exit plus every file the generated project
  contains. A design failing on some device is a valid, deterministic
  result, not a tool error.
- ``validate/<design>/all-devices``: `wfb validate` against every installed
  device (discovered via `wfb devices`), one sub-result per device.
- ``preview/<design>/{default,asleep,all-styles,time,aod,aod-minute-7,
  aod-minute-1234,heatmap}``: `wfb preview` with the matching flags,
  capturing every PNG plus stdout/stderr/exit. ``all-styles`` on a design
  with no `config: style:` axis is expected to fail cleanly
  (`UnknownStyleError`) -- that failure is recorded, not treated as a tool
  error. The AOD-flavoured cases run only on `fenix847mm` (the one
  installed AMOLED target the project's own screenshot tooling already
  singles out for this -- see `tools/docs-shots.py`).

Global, design-independent CLI cases, each run with both ``--color never``
and ``--color always`` (the exception is ``cli/validate-color``, which only
makes sense in colour):

- ``cli/help`` and ``cli/help-<cmd>`` for every subcommand `wfb --help`
  lists (read from its ``{build,validate,...}`` usage line, so a new command
  is covered without editing this file; ``simulate`` is included even though
  the *command* itself is skipped below, because `wfb help simulate` only
  prints its docstring and touches no simulator);
- ``cli/devices``, ``cli/fonts``, ``cli/fonts-<id>`` (fenix8solar47mm,
  fr955, fenix847mm -- the two verification devices plus the one AMOLED
  target), ``cli/sources``, ``cli/complications``, ``cli/series``,
  ``cli/schema``, ``cli/doctor``, ``cli/new-list``;
- ``cli/new-<template>`` for every bundled template: writes a fresh design
  file (the UUID is normalised away -- see below) and captures it too;
- ``cli/validate-color/<design>`` for three representative designs
  (showcase, features/aod, features/graph), ``--color always`` only, to
  snapshot the ANSI-coloured diagnostic rendering.

`wfb simulate` is never run (it needs a live simulator, which does not
survive `monkeydo` in this environment -- root `CLAUDE.md` §3), and no case
uses `-w/--watch`.

## Normalisation

Every captured text artifact (stdout, stderr, and any generated text file
that decodes as UTF-8) is normalised before hashing and storage, so a
snapshot is comparable across machines and re-runs:

1. Each case's own scratch/output directory (an ephemeral `tempfile`
   directory passed to the CLI as `-o`) is replaced with ``<OUT>``.
2. The repository root (this file's grandparent) is replaced with
   ``<ROOT>``.
3. The home directory (`Path.home()`) is replaced with ``<HOME>``.
4. `wfb build`'s own closing line is the only place a wall-clock duration
   is printed (``_verdict``'s ``after=f" in {result.duration:.1f}s"`` in
   `wfb/cli.py`) -- ``in <digits>.<digits>s`` is normalised to ``in <T>s``.
   No other command prints an elapsed time; this was confirmed by reading
   `wfb/cli.py`, not guessed, and re-confirmed empirically by the
   determinism check this tool's own header describes (two `save` runs,
   diffed).
5. Only inside a ``cli/new-*`` case, an 8-4-4-4-12 hex UUID is replaced
   with ``<UUID>`` (the face id `wfb new` mints fresh every call). A design
   UUID appearing anywhere else (an example's own `face: id:`) is real,
   stable content and is deliberately left alone.

A `.png` file is hashed by its *decoded pixels* (Pillow: `mode`, `size`,
then `tobytes()`), not its encoded bytes, so a Pillow/zlib encoder version
change cannot show up as a spurious diff. The actual PNG bytes are still
kept on disk under the snapshot directory, so a human can open old vs new.
Every other binary (non-UTF-8-decodable) file is hashed as raw bytes.

## Storage

    DIR/manifest.json               -- {"version", "created", "python",
                                         "env", "cases": {key: {"exit",
                                         "artifacts": {name: {"kind",
                                         "sha256"}}}}}
    DIR/cases/<key>/<artifact name>  -- the stored (normalised, for text)
                                         content of each artifact

`created` is metadata only and never participates in a diff. `diff` needs
nothing but two saved directories.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
WFB = ROOT / "wfb.py"

#: Build device sets beyond a design's own `targets:` (plan 19 §A0).
AMOLED_MIX = ["fenix847mm", "fenix8solar47mm", "fr245", "fenix6"]
FENIX9_MIX = ["fenix947mm", "fr955"]

#: The one installed AMOLED target used for every AOD-flavoured preview case.
AOD_DEVICE = "fenix847mm"

PREVIEW_VARIANTS: dict[str, list[str]] = {
    "default": [],
    "asleep": ["--asleep"],
    "all-styles": ["--all-styles"],
    "time": ["--time", "03:41:17"],
    "aod": ["-d", AOD_DEVICE, "--aod"],
    "aod-minute-7": ["-d", AOD_DEVICE, "--aod", "--minute", "7"],
    "aod-minute-1234": ["-d", AOD_DEVICE, "--aod", "--minute", "1234"],
    "heatmap": ["-d", AOD_DEVICE, "--heatmap"],
}

FONTS_DEVICES = ("fenix8solar47mm", "fr955", "fenix847mm")
NEW_TEMPLATES = ("minimal", "dashboard")
VALIDATE_COLOR_DESIGNS = ("examples/showcase/face", "examples/features/aod/face",
                          "examples/features/graph/face")

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: The only elapsed-time text any command prints -- see the module docstring's
#: normalisation rule 4.
TIMING_RE = re.compile(r"\bin \d+\.\d+s\b")

_HOME = os.environ.get("HOME") or str(Path.home())


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Case:
    key: str
    #: Given a scratch directory and the subprocess environment, runs the
    #: case and returns (exit_code, {artifact name: Path on disk}, out_dir
    #: to normalise away, or None).
    run: Callable[[Path, dict], tuple[int, dict[str, Path], str | None]]


def run_wfb(args: list[str], *, env: dict, timeout: float = 240.0) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(WFB), *args]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=timeout)


def _write_std(scratch: Path, proc: subprocess.CompletedProcess) -> dict[str, Path]:
    out_path = scratch / "__stdout.txt"
    err_path = scratch / "__stderr.txt"
    out_path.write_text(proc.stdout, encoding="utf-8")
    err_path.write_text(proc.stderr, encoding="utf-8")
    return {"stdout": out_path, "stderr": err_path}


def _collect_dir(out_dir: Path, *, pattern: str = "*") -> dict[str, Path]:
    files = {}
    if out_dir.exists():
        for path in sorted(out_dir.rglob(pattern)):
            if path.is_file():
                files[path.relative_to(out_dir).as_posix()] = path
    return files


def discover_designs() -> list[Path]:
    designs = set(ROOT.glob("examples/**/*.yaml")) | set(ROOT.glob("tests/fixtures/**/*.yaml"))
    return sorted(designs)


def design_id(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return rel[: -len(".yaml")] if rel.endswith(".yaml") else rel


def discover_device_ids(env: dict) -> list[str]:
    proc = run_wfb(["--color", "never", "devices"], env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"wfb devices failed (exit {proc.returncode}): {proc.stderr}")
    ids = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if line:
            ids.append(line.split()[0])
    return sorted(ids)


def discover_commands(env: dict) -> list[str]:
    """Every subcommand, from the ``{build,validate,...}`` choice list in
    `wfb --help`'s usage line."""
    proc = run_wfb(["--color", "never", "--help"], env=env)
    commands = parse_commands(proc.stdout)
    if proc.returncode != 0 or commands is None:
        raise RuntimeError(f"cannot read the command list from wfb --help: {proc.stderr}")
    return commands


def parse_commands(help_text: str) -> list[str] | None:
    """The subcommand list out of `wfb --help` text. The usage line has two
    ``{...}`` lists and `--color {auto,always,never}` comes first, so the
    one naming ``build`` is it."""
    lists = [m.split(",") for m in re.findall(r"\{([a-z,-]+)\}", help_text)]
    return next((names for names in lists if "build" in names), None)


def make_build_case(design_rel: str, extra_devices: list[str]) -> Callable:
    def run(scratch: Path, env: dict):
        out_dir = scratch / "out"
        args = ["--color", "never", "build", "--no-compile", "-o", str(out_dir), design_rel]
        for device in extra_devices:
            args += ["-d", device]
        proc = run_wfb(args, env=env)
        files = _write_std(scratch, proc)
        files.update(_collect_dir(out_dir))
        return proc.returncode, files, str(out_dir)

    return run


def make_validate_all_devices_case(design_rel: str, device_ids: list[str]) -> Callable:
    def run(scratch: Path, env: dict):
        files = {}
        exit_codes = {}
        for device_id in device_ids:
            proc = run_wfb(["--color", "never", "validate", "-d", device_id, design_rel], env=env)
            out_path = scratch / f"{device_id}__stdout.txt"
            err_path = scratch / f"{device_id}__stderr.txt"
            out_path.write_text(proc.stdout, encoding="utf-8")
            err_path.write_text(proc.stderr, encoding="utf-8")
            files[f"{device_id}/stdout"] = out_path
            files[f"{device_id}/stderr"] = err_path
            exit_codes[device_id] = proc.returncode
        summary_path = scratch / "__exit_codes.json"
        summary_path.write_text(json.dumps(exit_codes, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        files["exit_codes.json"] = summary_path
        overall = 0 if all(code == 0 for code in exit_codes.values()) else 1
        return overall, files, None

    return run


def make_preview_case(design_rel: str, variant_args: list[str]) -> Callable:
    def run(scratch: Path, env: dict):
        out_dir = scratch / "out"
        args = ["--color", "never", "preview", "-o", str(out_dir), *variant_args, design_rel]
        proc = run_wfb(args, env=env)
        files = _write_std(scratch, proc)
        files.update(_collect_dir(out_dir, pattern="*.png"))
        return proc.returncode, files, str(out_dir)

    return run


def make_help_case(topic: str | None, color: str) -> Callable:
    def run(scratch: Path, env: dict):
        args = ["--color", color, "help"]
        if topic:
            args.append(topic)
        proc = run_wfb(args, env=env)
        return proc.returncode, _write_std(scratch, proc), None

    return run


def make_argv_case(argv: list[str], color: str) -> Callable:
    def run(scratch: Path, env: dict):
        proc = run_wfb(["--color", color, *argv], env=env)
        return proc.returncode, _write_std(scratch, proc), None

    return run


def make_new_case(template: str, color: str) -> Callable:
    def run(scratch: Path, env: dict):
        design_path = scratch / "x.yaml"
        proc = run_wfb(["--color", color, "new", "Snap Face", "-t", template,
                        "-o", str(design_path)], env=env)
        files = _write_std(scratch, proc)
        if design_path.exists():
            files["x.yaml"] = design_path
        return proc.returncode, files, str(scratch)

    return run


def make_validate_color_case(design_rel: str) -> Callable:
    def run(scratch: Path, env: dict):
        proc = run_wfb(["--color", "always", "validate", design_rel], env=env)
        return proc.returncode, _write_std(scratch, proc), None

    return run


def build_cases(device_ids: list[str], commands: list[str]) -> list[Case]:
    cases: list[Case] = []
    for design_path in discover_designs():
        rel = design_path.relative_to(ROOT).as_posix()
        did = design_id(design_path)
        cases.append(Case(f"build/{did}/targets", make_build_case(rel, [])))
        cases.append(Case(f"build/{did}/amoled-mix", make_build_case(rel, AMOLED_MIX)))
        cases.append(Case(f"build/{did}/fenix9-mix", make_build_case(rel, FENIX9_MIX)))
        cases.append(Case(f"validate/{did}/all-devices",
                          make_validate_all_devices_case(rel, device_ids)))
        for variant, extra in PREVIEW_VARIANTS.items():
            cases.append(Case(f"preview/{did}/{variant}", make_preview_case(rel, extra)))

    for color in ("never", "always"):
        cases.append(Case(f"cli/help/color-{color}", make_help_case(None, color)))
        for cmd in commands:
            cases.append(Case(f"cli/help-{cmd}/color-{color}", make_help_case(cmd, color)))
        cases.append(Case(f"cli/devices/color-{color}", make_argv_case(["devices"], color)))
        cases.append(Case(f"cli/fonts/color-{color}", make_argv_case(["fonts"], color)))
        for device_id in FONTS_DEVICES:
            cases.append(Case(f"cli/fonts-{device_id}/color-{color}",
                              make_argv_case(["fonts", device_id], color)))
        cases.append(Case(f"cli/sources/color-{color}", make_argv_case(["sources"], color)))
        cases.append(Case(f"cli/complications/color-{color}",
                          make_argv_case(["complications"], color)))
        cases.append(Case(f"cli/series/color-{color}", make_argv_case(["series"], color)))
        cases.append(Case(f"cli/schema/color-{color}", make_argv_case(["schema"], color)))
        cases.append(Case(f"cli/doctor/color-{color}", make_argv_case(["doctor"], color)))
        cases.append(Case(f"cli/new-list/color-{color}",
                          make_argv_case(["new", "--list"], color)))
        for template in NEW_TEMPLATES:
            cases.append(Case(f"cli/new-{template}/color-{color}",
                              make_new_case(template, color)))

    for did in VALIDATE_COLOR_DESIGNS:
        cases.append(Case(f"cli/validate-color/{did}", make_validate_color_case(f"{did}.yaml")))

    return sorted(cases, key=lambda c: c.key)


# ---------------------------------------------------------------------------
# Normalisation and hashing
# ---------------------------------------------------------------------------


def normalize_text(text: str, *, key: str, out_dir: str | None) -> str:
    if out_dir:
        text = text.replace(out_dir, "<OUT>")
    text = text.replace(str(ROOT), "<ROOT>")
    if _HOME:
        text = text.replace(_HOME, "<HOME>")
    text = TIMING_RE.sub("in <T>s", text)
    if key.startswith("cli/new-"):
        text = UUID_RE.sub("<UUID>", text)
    return text


def classify_image(raw: bytes) -> tuple[str, bytes, str]:
    from PIL import Image

    image = Image.open(io.BytesIO(raw))
    image.load()
    payload = f"{image.mode}|{image.size[0]}x{image.size[1]}|".encode("utf-8") + image.tobytes()
    return "image", raw, hashlib.sha256(payload).hexdigest()


def load_artifact(path: Path, *, key: str, out_dir: str | None) -> tuple[str, bytes, str]:
    raw = path.read_bytes()
    if path.suffix.lower() == ".png":
        return classify_image(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", raw, hashlib.sha256(raw).hexdigest()
    normalized = normalize_text(text, key=key, out_dir=out_dir)
    data = normalized.encode("utf-8")
    return "text", data, hashlib.sha256(data).hexdigest()


def finalize_case(key: str, exit_code: int, files: dict[str, Path], *, out_dir: str | None,
                  cases_root: Path) -> dict:
    case_dir = cases_root / key
    artifacts = {}
    for name in sorted(files):
        kind, stored, digest = load_artifact(files[name], key=key, out_dir=out_dir)
        dest = case_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(stored)
        artifacts[name] = {"kind": kind, "sha256": digest}
    return {"exit": exit_code, "artifacts": artifacts}


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def execute_case(case: Case, env: dict, cases_root: Path) -> tuple[str, dict, float, str | None]:
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="wfbsnap-") as tmp:
            exit_code, files, out_dir = case.run(Path(tmp), env)
            entry = finalize_case(case.key, exit_code, files, out_dir=out_dir,
                                  cases_root=cases_root)
        return case.key, entry, time.monotonic() - started, None
    except Exception:
        tb = traceback.format_exc()
        case_dir = cases_root / case.key
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "error").write_text(tb, encoding="utf-8")
        entry = {"exit": -1, "artifacts": {"error": {"kind": "text",
                                                      "sha256": hashlib.sha256(tb.encode()).hexdigest()}}}
        return case.key, entry, time.monotonic() - started, tb


def do_save(dir_path: Path, *, jobs: int, only: list[str] | None, force: bool,
           no_garmin_fonts: bool) -> int:
    if dir_path.exists() and any(dir_path.iterdir()) and not force:
        print(f"error: {dir_path} exists and is not empty (use --force)", file=sys.stderr)
        return 2

    env = dict(os.environ)
    if no_garmin_fonts:
        env["WFB_NO_GARMIN_FONTS"] = "1"

    dir_path.mkdir(parents=True, exist_ok=True)
    cases_root = dir_path / "cases"
    if cases_root.exists():
        shutil.rmtree(cases_root)
    cases_root.mkdir(parents=True)

    device_ids = discover_device_ids(env)
    cases = build_cases(device_ids, discover_commands(env))
    if only:
        cases = [c for c in cases if any(sub in c.key for sub in only)]
    if not cases:
        print("error: --only matched no cases", file=sys.stderr)
        return 2

    total = len(cases)
    print(f"snapshot save: {total} cases, {len(device_ids)} devices, -j{jobs}", file=sys.stderr)
    started = time.monotonic()
    manifest_cases: dict[str, dict] = {}
    done = 0
    failures = 0
    lock = threading.Lock()

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(execute_case, case, env, cases_root) for case in cases]
        for future in concurrent.futures.as_completed(futures):
            key, entry, duration, error = future.result()
            with lock:
                done += 1
                manifest_cases[key] = entry
                if error is not None:
                    failures += 1
                    print(f"[{done}/{total}] ERROR {key} ({duration:.1f}s)\n{error}",
                          file=sys.stderr)
                elif entry["exit"] not in (0, 1):
                    print(f"[{done}/{total}] exit={entry['exit']} {key} ({duration:.1f}s)",
                          file=sys.stderr)
                elif done % 10 == 0 or done == total:
                    print(f"[{done}/{total}] {key} ({duration:.1f}s)", file=sys.stderr)

    manifest = {
        "version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "env": {
            "WFB_NO_GARMIN_FONTS": env.get("WFB_NO_GARMIN_FONTS"),
            "WFB_FONTS": env.get("WFB_FONTS"),
        },
        "cases": manifest_cases,
    }
    (dir_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")

    elapsed = time.monotonic() - started
    artifact_count = sum(len(entry["artifacts"]) for entry in manifest_cases.values())
    total_bytes = sum(f.stat().st_size for f in cases_root.rglob("*") if f.is_file())
    print(f"saved {total} cases ({failures} errored), {artifact_count} artifacts, "
          f"{total_bytes:,} bytes, in {elapsed:.1f}s -> {dir_path}", file=sys.stderr)
    # A case the tool itself failed to run is not a result: an incomplete
    # snapshot must not pass for a good one.
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def image_diff_summary(old_path: Path, new_path: Path) -> str:
    from PIL import Image, ImageChops

    old_image = Image.open(old_path).convert("RGBA")
    new_image = Image.open(new_path).convert("RGBA")
    if old_image.size != new_image.size:
        return f"size changed {old_image.size} -> {new_image.size}"
    diff = ImageChops.difference(old_image, new_image)
    # Both images were forced to RGBA above and are typically fully opaque
    # (`alphaBlendingSupport: false`, root CLAUDE.md §4.10): `getbbox`'s
    # default `alpha_only=True` looks at the alpha channel alone for an
    # image that has one, so an RGB-only difference under an identical,
    # fully-opaque alpha channel would otherwise report no bounding box at
    # all even though the pixels visibly differ.
    bbox = diff.getbbox(alpha_only=False)
    if bbox is None:
        return "pixels identical (only PNG mode/encoding metadata differs)"
    get_flat = getattr(diff, "get_flattened_data", diff.getdata)
    count = sum(1 for pixel in get_flat() if any(pixel))
    return f"pixels differ: {count} px changed, bbox {bbox}"


def print_text_diff(name: str, old_path: Path, new_path: Path, *, context: int,
                    max_lines: int) -> None:
    old_lines = old_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = new_path.read_text(encoding="utf-8").splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"old/{name}",
                                           tofile=f"new/{name}", n=context))
    print(f"  ~ {name}:")
    for line in diff_lines[:max_lines]:
        print("    " + line.rstrip("\n"))
    if len(diff_lines) > max_lines:
        print(f"    ... ({len(diff_lines) - max_lines} more diff lines truncated)")


def print_case_diff(key: str, old_dir: Path, new_dir: Path, old_entry: dict, new_entry: dict,
                    *, context: int, max_lines: int) -> None:
    print(f"\n=== {key} ===")
    if old_entry["exit"] != new_entry["exit"]:
        print(f"  exit: {old_entry['exit']} -> {new_entry['exit']}")
    old_art, new_art = old_entry["artifacts"], new_entry["artifacts"]
    for name in sorted(set(old_art) | set(new_art)):
        o, n = old_art.get(name), new_art.get(name)
        if o == n:
            continue
        if o is None:
            print(f"  + {name} (added, {n['kind']})")
            continue
        if n is None:
            print(f"  - {name} (removed, {o['kind']})")
            continue
        old_path, new_path = old_dir / "cases" / key / name, new_dir / "cases" / key / name
        if n["kind"] == "text":
            print_text_diff(name, old_path, new_path, context=context, max_lines=max_lines)
        elif n["kind"] == "image":
            print(f"  ~ {name}: {image_diff_summary(old_path, new_path)}")
        else:
            print(f"  ~ {name}: binary changed (sha256 {o['sha256'][:12]}.. -> "
                  f"{n['sha256'][:12]}..)")


def do_diff(old_dir: Path, new_dir: Path, *, context: int = 3, max_lines: int = 60,
           only: list[str] | None = None) -> int:
    old_manifest = json.loads((old_dir / "manifest.json").read_text(encoding="utf-8"))
    new_manifest = json.loads((new_dir / "manifest.json").read_text(encoding="utf-8"))
    if old_manifest.get("env") != new_manifest.get("env"):
        print(f"warning: snapshots taken with different env: old={old_manifest.get('env')} "
              f"new={new_manifest.get('env')}", file=sys.stderr)

    old_cases, new_cases = old_manifest["cases"], new_manifest["cases"]
    if only:
        old_cases = {k: v for k, v in old_cases.items() if any(sub in k for sub in only)}
        new_cases = {k: v for k, v in new_cases.items() if any(sub in k for sub in only)}
    old_keys, new_keys = set(old_cases), set(new_cases)
    common = old_keys & new_keys
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = sorted(key for key in common if old_cases[key] != new_cases[key])
    unchanged = len(common) - len(changed)

    print(f"{unchanged} unchanged, {len(changed)} changed, {len(added)} added, "
          f"{len(removed)} removed")
    for key in added:
        print(f"+ {key}")
    for key in removed:
        print(f"- {key}")
    for key in changed:
        print_case_diff(key, old_dir, new_dir, old_cases[key], new_cases[key],
                        context=context, max_lines=max_lines)

    return 0 if not (changed or added or removed) else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    save = sub.add_parser("save", help="run every case and write results under DIR")
    save.add_argument("dir", type=Path)
    save.add_argument("-j", type=int, default=os.cpu_count() or 4)
    save.add_argument("--only", action="append", default=None,
                      help="restrict to cases whose key contains this substring (repeatable)")
    save.add_argument("--force", action="store_true",
                      help="overwrite DIR even if it exists and is non-empty")
    save.add_argument("--no-garmin-fonts", action="store_true",
                      help="set WFB_NO_GARMIN_FONTS=1 for every subprocess")

    diff = sub.add_parser("diff", help="compare two saved snapshots")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    diff.add_argument("--context", type=int, default=3)
    diff.add_argument("--max-lines", type=int, default=60)

    compare = sub.add_parser("compare", help="save into a temp dir (or --keep), then diff")
    compare.add_argument("old", type=Path)
    compare.add_argument("-j", type=int, default=os.cpu_count() or 4)
    compare.add_argument("--only", action="append", default=None)
    compare.add_argument("--keep", type=Path, default=None,
                         help="save the new snapshot here instead of a throwaway temp dir")
    compare.add_argument("--no-garmin-fonts", action="store_true")
    compare.add_argument("--context", type=int, default=3)
    compare.add_argument("--max-lines", type=int, default=60)

    args = parser.parse_args(argv)

    if args.command == "save":
        return do_save(args.dir, jobs=args.j, only=args.only, force=args.force,
                       no_garmin_fonts=args.no_garmin_fonts)

    if args.command == "diff":
        return do_diff(args.old, args.new, context=args.context, max_lines=args.max_lines)

    if args.command == "compare":
        if args.keep is not None:
            new_dir = args.keep
            rc = do_save(new_dir, jobs=args.j, only=args.only, force=True,
                        no_garmin_fonts=args.no_garmin_fonts)
            if rc != 0:
                return rc
            return do_diff(args.old, new_dir, context=args.context, max_lines=args.max_lines, only=args.only)
        with tempfile.TemporaryDirectory(prefix="wfbsnap-compare-") as tmp:
            new_dir = Path(tmp)
            rc = do_save(new_dir, jobs=args.j, only=args.only, force=True,
                        no_garmin_fonts=args.no_garmin_fonts)
            if rc != 0:
                return rc
            return do_diff(args.old, new_dir, context=args.context, max_lines=args.max_lines, only=args.only)

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
