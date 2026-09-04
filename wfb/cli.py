"""``wfb`` -- the command line.

``wfb build`` is the one command the Phase 2 slice promises: design file in,
compiled ``.prg`` out, with everything in between reported against the YAML.
"""

from __future__ import annotations

import argparse
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

    devices = sub.add_parser("devices", help="list installed device definitions")
    devices.add_argument("--devices-dir")
    devices.set_defaults(handler=_devices)

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


def _preview(args) -> int:
    from .preview import PreviewOptions, write as write_preview

    bag = Bag()
    face = load(args.design, bag)
    if face is None:
        bag.print()
        return 1
    db = DeviceDatabase.discover(args.devices_dir)
    devices = select_devices(face, db, bag, args.devices)
    if not devices:
        bag.print()
        return 1
    resolved, _ = resolve_all(face, devices, bag)
    bag.print()
    if not bag.ok():
        return 1
    options = PreviewOptions(scale=args.scale, quantise=not args.no_quantise)
    print()
    for device_id, result in resolved.items():
        path = write_preview(result, args.output / f"{device_id}.png", options)
        print(f"preview    {path}  ({result.device.width}x{result.device.height} "
              f"at {args.scale}x)")
    print("\nRendered from the same resolved geometry the generated code uses, so the")
    print("two cannot disagree about position.  Glyph rendering and arc caps are")
    print("approximations -- the simulator is authoritative for those.")
    return 0


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
