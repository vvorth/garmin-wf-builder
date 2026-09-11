"""wfb -- build a Garmin Connect IQ watch face from a YAML design.

    wfb validate design.yaml     # fast feedback: schema + semantic checks, no toolchain
    wfb preview  design.yaml     # render to a PNG, with no simulator
    wfb build    design.yaml     # generate Monkey C, resources and manifest, then compile

Run `wfb help` for the full command list, or `wfb help <command>` /
`wfb <command> help` for one command's own help -- both are read straight
from that command's handler docstring in this file, which is the one place
its behaviour is documented; nothing here is duplicated into a markdown doc.
`wfb doctor` reports what is installed and what to do about anything
missing; `wfb sources` and `wfb devices` list what a design may bind and
which watches it may target.
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from pathlib import Path

from . import __version__, catalog, icons, series as series_catalog
from .build import Toolchain, build as run_build, load, resolve_all, select_devices
from .simulate import SimulatorError, push, screenshot
from .devices import DeviceDatabase, DeviceError
from .diagnostics import Bag

DEFAULT_OUTPUT = Path("build")


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    parser = _parser()
    raw = _rewrite_trailing_help(raw, _subparsers(parser))
    args = parser.parse_args(raw)
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


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Every registered subcommand parser, by name.

    argparse has no public accessor for this; walking ``_subparsers``'s
    ``_group_actions`` for the ``_SubParsersAction`` and reading its
    ``choices`` is the standard, stable way every argparse-introspecting tool
    does it. Both `_rewrite_trailing_help` (which command names does
    ``... help`` need to recognise) and `_help` (which subparser to print)
    need this same dict, so it lives in one place rather than two.
    """
    for action in parser._subparsers._group_actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _rewrite_trailing_help(argv: list[str], commands: dict[str, argparse.ArgumentParser]) -> list[str]:
    """``wfb <command> help`` -> ``wfb <command> --help``.

    A trailing ``help`` is how most CLIs a person (or an LLM) has already
    used behave, so it is worth supporting alongside the leading ``wfb help
    <command>`` form and plain ``-h``/``--help`` -- three spellings of the
    same request rather than one a caller has to remember exactly.
    """
    if len(argv) == 2 and argv[1] == "help" and argv[0] in commands:
        return [argv[0], "--help"]
    return argv


def _command(sub: argparse._SubParsersAction, name: str, handler) -> argparse.ArgumentParser:
    """Register one subcommand, with its help text sourced entirely from
    ``handler``'s docstring: the first line is the short summary ``wfb
    --help`` lists next to the command name, and the whole docstring is what
    ``wfb <command> --help`` / ``wfb help <command>`` / ``wfb <command>
    help`` all print. One docstring, not a hand-written ``help=`` string and
    a separately maintained description that can drift from it.
    """
    doc = inspect.getdoc(handler) or ""
    summary = doc.splitlines()[0] if doc else ""
    parser = sub.add_parser(
        name, help=summary, description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(handler=handler)
    return parser


def _help(args) -> int:
    """show help for wfb, or for one command

    ``wfb help`` alone is the same as ``wfb --help``. ``wfb help <command>``
    -- or, equivalently, ``wfb <command> help`` -- is the same as
    ``wfb <command> --help``.
    """
    parser = _parser()
    if not args.topic:
        parser.print_help()
        return 0
    commands = _subparsers(parser)
    target = commands.get(args.topic)
    if target is None:
        print(f"error: no such command {args.topic!r}", file=sys.stderr)
        print(f"       commands: {', '.join(sorted(commands))}", file=sys.stderr)
        return 1
    target.print_help()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfb",
        description=inspect.getdoc(sys.modules[__name__]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"wfb {__version__}")
    sub = parser.add_subparsers(dest="command")

    build = _command(sub, "build", _build)
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

    check = _command(sub, "validate", _validate)
    check.add_argument("design", type=Path)
    check.add_argument("--devices-dir")

    preview = _command(sub, "preview", _preview)
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

    simulate = _command(sub, "simulate", _simulate)
    simulate.add_argument("design", type=Path)
    simulate.add_argument("-d", "--device", dest="device",
                          help="which target to run (default: the first)")
    simulate.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    simulate.add_argument("--screenshot", type=Path,
                          help="capture the simulator window to this PNG")
    simulate.add_argument("--sdk")
    simulate.add_argument("--key")
    simulate.add_argument("--devices-dir")

    new = _command(sub, "new", _new)
    new.add_argument("name", nargs="?", help="the face's name, e.g. \"My Face\"")
    new.add_argument("-t", "--template", default="dashboard",
                     help="which template to start from (default: dashboard)")
    new.add_argument("-o", "--output", type=Path,
                     help="where to write it (default: <name>.yaml in the current directory)")
    new.add_argument("--list", action="store_true", dest="list_templates",
                     help="list the available templates and exit")

    devices = _command(sub, "devices", _devices)
    devices.add_argument("--devices-dir")

    doctor = _command(sub, "doctor", _doctor)
    doctor.add_argument("--devices-dir")

    schema = _command(sub, "schema", _schema)
    schema.add_argument("--path", action="store_true",
                        help="print the schema's path instead of its contents")

    _command(sub, "sources", _sources)
    _command(sub, "complications", _complications)
    _command(sub, "series", _series)

    help_cmd = _command(sub, "help", _help)
    help_cmd.add_argument("topic", nargs="?", help="a command name, e.g. `wfb help build`")
    return parser


# --------------------------------------------------------------------------


def _build(args) -> int:
    """validate, generate and compile a design into a sideloadable .prg

    Runs the full pipeline: YAML load -> schema validation -> semantic
    checks (types, null policy) -> per-device layout resolve -> lint ->
    Monkey C + resources + jungle + manifest generation -> `monkeyc`. Every
    stage's diagnostics are reported against the design file's own lines.

    `--no-compile` stops after generating the project, before invoking
    `monkeyc` -- useful with no Garmin toolchain installed, or to inspect
    the generated Monkey C directly. `-d/--device` restricts the build to
    one or more targets instead of every target the design lists.
    """
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
    """validate a design without generating or compiling anything

    The cheapest, fastest feedback loop: schema and semantic checks plus a
    per-device layout resolve and lint, with no font baking, no Monkey C
    generation, and no Garmin toolchain required. Call this after every
    edit; reach for `wfb build` only once this is clean.
    """
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
    """render the design to a PNG on the host, with no simulator

    Resolves the same per-device geometry `wfb build` would generate code
    from, then rasterises it directly with Pillow -- so a preview and a
    compiled face cannot disagree about *position*. Glyph shapes and arc
    caps are approximations; the Connect IQ simulator is authoritative for
    those, when it can run at all (see docs/limitations.md).

    `-w/--watch` re-renders whenever the design file or any font it
    references changes, polling every `--interval` seconds (default 0.4).
    """
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
    """launch the Connect IQ simulator and push a built face to it

    Builds the design (like `wfb build`) and pushes the result to a
    *running* simulator via `monkeydo` -- the simulator itself is not
    started automatically, and in a sandboxed Linux container usually
    cannot run at all (see docs/limitations.md); `wfb preview` covers that
    gap. `--screenshot` captures the simulator window to a PNG once the
    push succeeds.
    """
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
    """start a design from a known-good template

    Copies one of the bundled templates (`--list` shows them, with a
    one-line blurb each) to a new YAML file, substituting a fresh UUID and
    the given name. Two faces sharing a UUID are the same app to the watch
    -- installing the second replaces the first -- so every call mints its
    own.
    """
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
    """check the environment and say what is missing

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
    """print the JSON Schema, or where it lives, for editor setup

    With no flags, prints the schema itself -- for piping into a validator,
    or reading by eye. `--path` prints only the file's path, for pointing an
    editor's `yaml-language-server` schema mapping at it.
    """
    from .validate import SCHEMA_PATH

    if args.path:
        print(SCHEMA_PATH)
        return 0
    print(SCHEMA_PATH.read_text(encoding="utf-8"), end="")
    return 0


def _devices(args) -> int:
    """list installed device definitions

    Reads the device files (`~/.Garmin/ConnectIQ/Devices` by default; see
    `--devices-dir`/`WFB_DEVICES`) and prints each device's screen, shape,
    display type, colour count, API level and watch-face memory limit. These
    files cannot be downloaded unauthenticated -- run `wfb doctor` for how
    to get them onto this machine.
    """
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
    """list the data-source catalogue: every value a design may bind

    For each source: its type, whether it is nullable, any permission
    binding it implies, its conventional `on_hold: auto` launch target (if
    it has one), and the SDK page it was taken from. Every read is a plain
    per-frame read now -- there is no refresh-tier concept left to show.
    This is the authoritative, always-current list -- never bind a path
    that is not listed here, and never trust a copy of this list pasted
    into prose, which goes stale the moment the catalogue grows.

    Also lists `config.*` -- the two native on-device colour axes (ADR 0006
    1) -- even though, unlike everything above, these are not read from any
    device API: a design that declares `config:` binds them the same way,
    as an ordinary colour expression.
    """
    for namespace, paths in catalog.namespaces().items():
        print(f"\n{namespace}")
        for path in paths:
            source = catalog.CATALOG[path]
            flags = []
            if source.guard_needed:
                flags.append("nullable")
            if source.permissions:
                flags.append("needs " + "+".join(source.permissions))
            if source.launch_complication:
                flags.append(f"on_hold: auto -> {source.launch_complication}")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            ref = f"  ({source.source_ref})" if source.source_ref else ""
            print(f"  {path:<34} {source.type.value:<8} {source.doc}{suffix}{ref}")
    print("\nconfig  (declared per design in 'config:' -- fēnix 8 Solar's native "
          "editor only, see docs/format.md)")
    print(f"  {'config.accent_color':<34} {'color':<8} the one accent-colour axis "
          "(<accentColors>, Settings.accentColor)")
    print(f"  {'config.data_color':<34} {'color':<8} the one data-colour axis "
          "(<dataColors>, Settings.complicationColor)")
    print(f"\nicons: {', '.join(icons.names())}")
    print("\nrun `wfb complications` for the full list of on_hold: targets")
    return 0


def _complications(args) -> int:
    """list the complication type table: what `on_hold:` may launch, and
    what `complication.*` may read

    A watch face cannot open an arbitrary app. The platform offers exactly
    one exit -- `Complications.exitTo`, "launches the app associated with
    the complication" -- so an interactive element names a complication
    type and the watch opens whichever glance or app owns it. The same 42
    types are also readable directly as `complication.<name>` data sources
    (see `wfb sources`) -- this is the one table both draw from.

    Printed for each: the name a design writes, the Monkey C constant it
    compiles to, and the API level that type was introduced at. An API
    level is not a promise the watch has it; a hold on a type the watch
    does not know simply does nothing, which is why `wfb validate` also
    checks each target's own symbol table.

    Binding one of these -- as `on_hold:`, as `complication.<name>`, or via
    `on_hold: auto` -- adds the ComplicationSubscriber permission and
    raises minApiLevel to 4.2.0 automatically, the same way a data binding
    derives its own requirements.
    """
    from . import complications

    width = max(len(name) for name in complications.names())
    for name in complications.names():
        entry = complications.TYPES[name]
        since = "" if entry.since == complications.EXIT_TO_API_LEVEL else f"  (since {entry.since})"
        print(f"  {name:<{width}}  Complications.{entry.constant}{since}")
    print(f"\n{len(complications.TYPES)} complication types. "
          f"Use one as `on_hold:` on any element:")
    print("    - id: hr\n      type: icon\n      icon: heart\n      on_hold: heart_rate")
    print("\n...or let the compiler pick one from the element's own value binding:")
    print("    - id: hr\n      type: icon\n      icon: heart\n      on_hold: auto")
    return 0


def _series(args) -> int:
    """list the time-series catalogue: every `series:` a `graph` element may plot

    A `graph` plots a series, not a scalar -- a different kind of binding
    from `wfb sources`' data-source catalogue, acquired and cached on-device
    rather than read fresh every frame (`docs/format.md`'s `graph` section).
    Four families, and neither solar nor anything backed by
    `Toybox.SensorHistory` (pressure, stress, elevation, Body Battery) is one
    of them -- see `docs/limitations.md`.

    Printed for each: its value type, the natural interval `range:` as a
    duration divides by (none for `heart_rate`, which bins by real time
    instead), the documented maximum sample count if the SDK states one, and
    the SDK page it was taken from.
    """
    width = max(len(name) for name in series_catalog.names())
    for name in series_catalog.names():
        entry = series_catalog.SERIES[name]
        flags = []
        if entry.interval_seconds is not None:
            flags.append(f"1 sample / {entry.interval_seconds}s")
        if entry.max_count is not None:
            flags.append(f"max {entry.max_count}")
        if entry.unit:
            flags.append(entry.unit)
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {name:<{width}}  {entry.value_type.value:<6} {entry.doc}{suffix}"
              f"  ({entry.source_ref})")
    print(f"\n{len(series_catalog.SERIES)} series. Use one on a `graph` element:")
    print("    - id: hr_graph\n      type: graph\n      series: heart_rate\n"
          "      range: 4h\n      style: line\n      color: palette.accent")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
