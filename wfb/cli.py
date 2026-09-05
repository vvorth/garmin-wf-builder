"""``wfb`` -- the command line.

``wfb build`` is the one command the Phase 2 slice promises: design file in,
compiled ``.prg`` out, with everything in between reported against the YAML.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, catalog, icons
from .build import Toolchain, build as run_build, load, resolve_all, select_devices
from .simulate import SimulatorError, push, screenshot
from .devices import DeviceDatabase, DeviceError
from .diagnostics import Bag

DEFAULT_OUTPUT = Path("build")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfb",
        description="Build a Garmin Connect IQ watch face from a YAML design.",
    )
    parser.add_argument("--version", action="version", version=f"wfb {__version__}")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build", help="validate, generate and compile a design")
    build.add_argument("design", type=Path, help="the .yaml design file")
    build.add_argument("-d", "--device", action="append", dest="devices",
                       help="build only this target (repeatable); defaults to all targets")
    build.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                       help=f"build directory (default: {DEFAULT_OUTPUT})")
    build.add_argument("--no-compile", action="store_true",
                       help="generate the project but do not run monkeyc")
    build.add_argument("--sdk", help="Connect IQ SDK root (default: $CIQ_SDK)")
    build.add_argument("--key", help="developer key .der (default: ~/ciq/developer_key.der)")
    build.add_argument("--devices-dir", help="device definitions directory")
    build.set_defaults(handler=_build)

    check = sub.add_parser("validate", help="validate a design without generating anything")
    check.add_argument("design", type=Path)
    check.add_argument("--devices-dir")
    check.set_defaults(handler=_validate)

    preview = sub.add_parser(
        "preview", help="render the design to a PNG on the host, with no simulator")
    preview.add_argument("design", type=Path)
    preview.add_argument("-d", "--device", action="append", dest="devices")
    preview.add_argument("-o", "--output", type=Path, default=Path("build/preview"))
    preview.add_argument("--scale", type=int, default=2)
    preview.add_argument("--no-quantise", action="store_true",
                         help="skip snapping colours to the device palette")
    preview.add_argument("-w", "--watch", action="store_true",
                         help="re-render whenever the design or a font it uses changes")
    preview.add_argument("--interval", type=float, default=0.4,
                         help="seconds between checks while watching (default: 0.4)")
    preview.add_argument("--devices-dir")
    preview.set_defaults(handler=_preview)

    simulate = sub.add_parser(
        "simulate", help="launch the Connect IQ simulator and push a built face to it")
    simulate.add_argument("design", type=Path)
    simulate.add_argument("-d", "--device", dest="device",
                          help="which target to run (default: the first)")
    simulate.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    simulate.add_argument("--screenshot", type=Path,
                          help="capture the simulator window to this PNG")
    simulate.add_argument("--sdk")
    simulate.add_argument("--key")
    simulate.add_argument("--devices-dir")
    simulate.set_defaults(handler=_simulate)

    new = sub.add_parser("new", help="start a design from a known-good template")
    new.add_argument("name", nargs="?", help="the face's name, e.g. \"My Face\"")
    new.add_argument("-t", "--template", default="dashboard",
                     help="which template to start from (default: dashboard)")
    new.add_argument("-o", "--output", type=Path,
                     help="where to write it (default: <name>.yaml in the current directory)")
    new.add_argument("--list", action="store_true", dest="list_templates",
                     help="list the available templates and exit")
    new.set_defaults(handler=_new)

    devices = sub.add_parser("devices", help="list installed device definitions")
    devices.add_argument("--devices-dir")
    devices.set_defaults(handler=_devices)

    doctor = sub.add_parser(
        "doctor", help="check the environment and say what is missing")
    doctor.add_argument("--devices-dir")
    doctor.set_defaults(handler=_doctor)

    schema = sub.add_parser(
        "schema", help="print the JSON Schema, or where it lives, for editor setup")
    schema.add_argument("--path", action="store_true",
                        help="print the schema's path instead of its contents")
    schema.set_defaults(handler=_schema)

    sources = sub.add_parser("sources", help="list the data-source catalogue")
    sources.set_defaults(handler=_sources)
    return parser


# --------------------------------------------------------------------------


def _build(args) -> int:
    bag = Bag()
    result = run_build(
        args.design,
        output=args.output,
        bag=bag,
        devices_only=args.devices,
        db=DeviceDatabase.discover(args.devices_dir),
        toolchain=Toolchain.discover(args.sdk, args.key),
        compile_prg=not args.no_compile,
    )
    bag.print()
    if result is None or not bag.ok():
        print(f"\nbuild failed -- {bag.summary()}", file=sys.stderr)
        return 1

    print()
    print(f"generated  {result.output_dir}")
    for device_id, path in result.products.items():
        stats = result.memory.get(device_id)
        if stats:
            share = 100.0 * stats["total"] / stats["limit"]
            print(f"built      {path.name}  "
                  f"{stats['total']:,} B / {stats['limit']:,} B ({share:.1f}%)")
        else:
            print(f"built      {path.name}")
    if not result.products and args.no_compile:
        print("           (not compiled: --no-compile)")
    print(f"\n{bag.summary()} in {result.duration:.1f}s")
    return 0


def _validate(args) -> int:
    bag = Bag()
    face = load(args.design, bag)
    if face is not None:
        try:
            db = DeviceDatabase.discover(args.devices_dir)
        except DeviceError as exc:
            bag.note("devices", str(exc))
            db = None
        if db is not None:
            devices = select_devices(face, db, bag)
            if devices:
                resolve_all(face, devices, bag)
    bag.print()
    if face is None or not bag.ok():
        print(f"\ninvalid -- {bag.summary()}", file=sys.stderr)
        return 1
    print(f"{args.design}: ok -- {bag.summary()}")
    return 0


def _render_preview(args, db, *, quiet: bool = False) -> tuple[int, list[Path]]:
    """Render once.  Returns the exit code and the design's dependencies."""
    from .preview import PreviewOptions, write as write_preview

    bag = Bag()
    face = load(args.design, bag)
    if face is None:
        bag.print()
        return 1, [args.design]
    # Font sources are watched too: re-baking on a font change is the whole point
    # of watching, and the design file alone would not notice.
    watched = [args.design] + [spec.source for spec in face.fonts.values()]

    devices = select_devices(face, db, bag, args.devices)
    if not devices:
        bag.print()
        return 1, watched
    resolved, _ = resolve_all(face, devices, bag)
    bag.print()
    if not bag.ok():
        return 1, watched

    options = PreviewOptions(scale=args.scale, quantise=not args.no_quantise)
    for device_id, result in resolved.items():
        path = write_preview(result, args.output / f"{device_id}.png", options)
        print(f"preview    {path}  ({result.device.width}x{result.device.height} "
              f"at {args.scale}x)", flush=True)
    if not quiet:
        print("\nRendered from the same resolved geometry the generated code uses, so the")
        print("two cannot disagree about position.  Glyph rendering and arc caps are")
        print("approximations -- the simulator is authoritative for those.")
    return 0, watched


def _preview(args) -> int:
    db = DeviceDatabase.discover(args.devices_dir)
    if not args.watch:
        print()
        return _render_preview(args, db)[0]

    import time

    def stamps(paths: list[Path]) -> dict[Path, float]:
        out = {}
        for path in paths:
            try:
                out[path] = path.stat().st_mtime
            except OSError:
                out[path] = 0.0
        return out

    print(f"watching {args.design} -- press Ctrl-C to stop\n", flush=True)
    code, watched = _render_preview(args, db, quiet=True)
    seen = stamps(watched)
    try:
        while True:
            time.sleep(args.interval)
            current = stamps(watched)
            if current == seen:
                continue
            seen = current
            print(f"\n--- {time.strftime('%H:%M:%S')} ---", flush=True)
            code, watched = _render_preview(args, db, quiet=True)
            seen.update(stamps(watched))
    except KeyboardInterrupt:
        print("\nstopped watching")
    return code


def _simulate(args) -> int:
    bag = Bag()
    result = run_build(
        args.design,
        output=args.output,
        bag=bag,
        devices_only=[args.device] if args.device else None,
        db=DeviceDatabase.discover(args.devices_dir),
        toolchain=Toolchain.discover(args.sdk, args.key),
        compile_prg=True,
    )
    bag.print()
    if result is None or not result.products:
        print("\nnothing to run -- the build produced no .prg", file=sys.stderr)
        return 1

    device_id = args.device or result.devices[0].id
    prg = result.products.get(device_id)
    if prg is None:
        print(f"\nno build for {device_id}", file=sys.stderr)
        return 1

    toolchain = Toolchain.discover(args.sdk, args.key)
    try:
        push(toolchain, prg, device_id)
    except SimulatorError as exc:
        print(f"\nsimulator: {exc}", file=sys.stderr)
        for hint in exc.hints:
            print(f"  {hint}", file=sys.stderr)
        print("\n  `wfb preview` renders the same resolved geometry with no simulator.",
              file=sys.stderr)
        return 1
    print(f"\npushed {prg.name} to the {device_id} simulator")
    if args.screenshot:
        try:
            path = screenshot(args.screenshot)
            print(f"screenshot {path}")
        except SimulatorError as exc:
            print(f"screenshot failed: {exc}", file=sys.stderr)
            return 1
    return 0


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

TEMPLATE_BLURB = {
    "minimal": "a background and the time -- the smallest face worth building",
    "dashboard": "time, a goal ring, two data clusters and a battery bar",
}


def _new(args) -> int:
    import re
    import uuid

    templates = sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml"))
    if args.list_templates:
        for name in templates:
            print(f"  {name:<12} {TEMPLATE_BLURB.get(name, '')}")
        return 0

    if not args.name:
        print("error: a face name is required", file=sys.stderr)
        print(f"       usage: wfb new \"My Face\" [--template {'|'.join(templates)}]",
              file=sys.stderr)
        return 1

    source = TEMPLATE_DIR / f"{args.template}.yaml"
    if not source.exists():
        print(f"error: no template {args.template!r}", file=sys.stderr)
        print(f"       available: {', '.join(templates)}", file=sys.stderr)
        return 1

    slug = re.sub(r"-+", "-", "".join(
        c.lower() if c.isalnum() else "-" for c in args.name
    )).strip("-") or "face"
    destination = args.output or Path(f"{slug}.yaml")
    if destination.exists():
        print(f"error: {destination} already exists", file=sys.stderr)
        return 1

    # A fresh UUID every time: two faces sharing one id are the same app to the
    # watch, so installing the second replaces the first.
    text = (
        source.read_text(encoding="utf-8")
        .replace("__UUID__", str(uuid.uuid4()))
        .replace("__NAME__", args.name)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")

    print(f"created {destination}  (from the {args.template!r} template)")
    print()
    print("next:")
    print(f"  wfb preview {destination} --watch     # render as you edit")
    print(f"  wfb build   {destination}             # compile it")
    return 0


def _doctor(args) -> int:
    """Report what is present, what is missing, and what to do about it.

    Written for someone -- or something -- arriving with no context: each failure
    names the command that fixes it, and the exit code says whether a build is
    possible at all.  Everything except the last two checks is needed only to
    *compile*; validation and preview work without them.
    """
    from . import __version__
    from .build import Toolchain
    from .validate import SCHEMA_PATH

    ok = "  ok "
    missing = "MISSING"
    problems: list[str] = []
    blocking = 0

    print(f"wfb {__version__}")
    print(f"  python           {sys.version.split()[0]}  ({sys.executable})")

    # -- host dependencies ------------------------------------------------
    for module, package in (("ruamel.yaml", "ruamel.yaml"), ("jsonschema", "jsonschema"),
                            ("PIL", "pillow"), ("fontTools", "fonttools")):
        try:
            __import__(module)
            print(f"{ok} {package}")
        except ImportError:
            print(f"{missing} {package}")
            problems.append(f"pip install {package}")
            blocking += 1

    print(f"{ok if SCHEMA_PATH.exists() else missing} schema           {SCHEMA_PATH}")

    # -- device definitions -----------------------------------------------
    try:
        db = DeviceDatabase.discover(args.devices_dir)
        ids = db.ids()
        print(f"{ok} devices          {len(ids)} installed: {', '.join(ids[:4])}"
              f"{' ...' if len(ids) > 4 else ''}")
        print(f"                   {db.root}")
    except DeviceError:
        print(f"{missing} devices")
        print("                   they cannot be downloaded -- api.gcs.garmin.com "
              "returns HTTP 401.")
        print("                   copy them from a machine where the Connect IQ SDK")
        print("                   Manager has installed them:")
        print("                     macOS  ~/Library/Application Support/Garmin/"
              "ConnectIQ/Devices")
        print("                     Linux  ~/.Garmin/ConnectIQ/Devices")
        print("                   then set WFB_DEVICES to that directory.")
        problems.append("install the device definitions")
        blocking += 1

    # -- the Garmin toolchain ---------------------------------------------
    toolchain = Toolchain.discover()
    if toolchain is None:
        print(f"{missing} Connect IQ SDK")
        print("                   set CIQ_SDK, or run tools/setup-env.sh")
        problems.append("install the Connect IQ SDK")
    else:
        print(f"{ok} Connect IQ SDK   {toolchain.version}  ({toolchain.sdk})")
        key_dir = toolchain.key.parent
        if toolchain.key.exists():
            print(f"{ok} developer key    {toolchain.key}")
        elif os.access(key_dir, os.W_OK):
            # Reporting this as missing would be misleading: the key is created
            # on the first build that needs one, and a build is what a caller is
            # usually about to run.
            print(f"{ok} developer key    will be generated at {toolchain.key}")
        else:
            print(f"{missing} developer key    expected at {toolchain.key},")
            print(f"                   and {key_dir} is not writable.  Create one with:")
            print("                     openssl genpkey -algorithm RSA "
                  "-pkeyopt rsa_keygen_bits:4096 \\")
            print("                       -out key.pem")
            print("                     openssl pkcs8 -topk8 -inform PEM -outform DER \\")
            print(f"                       -in key.pem -out {toolchain.key} -nocrypt")
            problems.append("generate a developer key")

    # -- verdict -----------------------------------------------------------
    print()
    can_compile = (
        toolchain is not None
        and blocking == 0
        and (toolchain.key.exists() or os.access(toolchain.key.parent, os.W_OK))
    )
    if blocking == 0 and can_compile:
        print("ready: validate, preview and build all work.")
        return 0
    if blocking == 0:
        print("partial: validate and preview work; `wfb build` cannot compile yet.")
        print("         fix: " + "; ".join(problems))
        return 0
    print("not ready: " + "; ".join(problems))
    return 1


def _schema(args) -> int:
    from .validate import SCHEMA_PATH

    if args.path:
        print(SCHEMA_PATH)
        return 0
    print(SCHEMA_PATH.read_text(encoding="utf-8"), end="")
    return 0


def _devices(args) -> int:
    db = DeviceDatabase.discover(args.devices_dir)
    print(f"{'id':<24} {'screen':<12} {'shape':<10} {'display':<8} "
          f"{'colors':<7} {'api':<8} {'watch face':<10} family")
    for device_id in db.ids():
        device = db.get(device_id)
        limit = f"{device.watchface_memory_limit // 1024} KB" if device.supports_watchface else "-"
        colors = str(device.display_colors) if device.display_colors else "?"
        print(f"{device.id:<24} {device.width}x{device.height:<8} {device.shape:<10} "
              f"{device.display_type:<8} {colors:<7} {device.api_level:<8} {limit:<10} "
              f"{device.device_family}")
    return 0


def _sources(args) -> int:
    for namespace, paths in catalog.namespaces().items():
        print(f"\n{namespace}")
        for path in paths:
            source = catalog.CATALOG[path]
            flags = []
            if source.guard_needed:
                flags.append("nullable")
            if source.permissions:
                flags.append("needs " + "+".join(source.permissions))
            if source.tier.value != "frame":
                flags.append(f"{source.tier.value} tier")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            print(f"  {path:<34} {source.type.value:<8} {source.doc}{suffix}")
    print(f"\nicons: {', '.join(icons.names())}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
