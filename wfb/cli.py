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

Every subcommand takes `--color {auto,always,never}` (default auto), either
before or after the command name -- `wfb --color never build x` and `wfb
build --color never x` both work.
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from pathlib import Path

from . import __version__, catalog, complications, fonts, icons, series as series_catalog, term
from .build import Toolchain, build as run_build, load, resolve_all, select_devices, slug
from .simulate import SimulatorError, push, screenshot
from .devices import DeviceDatabase, DeviceError
from .diagnostics import Bag

DEFAULT_OUTPUT = Path("build")


def _error(message: str, *, file=None) -> None:
    """Print ``error: <message>``, with the label bold red when ``file`` is
    coloured -- centralised so every failure path styles the same way
    instead of re-deriving ``term.should_color(file)`` at each call site.
    ``file`` defaults to the *current* ``sys.stderr``, looked up per call."""
    file = sys.stderr if file is None else file
    label = term.style("error:", "bold", "red", enabled=term.should_color(file))
    print(f"{label} {message}", file=file)


def _status(label: str, *, color: bool) -> str:
    """A status word -- ``generated``, ``built``, ``preview``, ``pushed``,
    ``screenshot`` -- styled bold green when ``color``."""
    return term.style(label, "bold", "green", enabled=color)


def _memory_share(share: float, *, color: bool) -> str:
    """The ``N.N%`` memory-share figure, styled green/yellow/red by how
    close it is to the device's watch-face memory limit."""
    text = f"{share:.1f}%"
    if share >= 90:
        name = "red"
    elif share >= 75:
        name = "yellow"
    else:
        name = "green"
    return term.style(text, name, enabled=color)


def _format_built(products: dict, memory: dict, *, color: bool) -> list[str]:
    """Format ``_build``'s ``built`` lines, one per compiled device.

    Pulled out of ``_build`` so the column alignment can be unit-tested with
    plain dicts and ``Path`` objects, without invoking `monkeyc`: device
    ``.prg`` names differ in length, which is what makes the byte figures
    ragged without it.
    """
    name_width = max((len(path.name) for path in products.values()), default=0)
    lines = []
    for device_id, path in products.items():
        stats = memory.get(device_id)
        label = _status("built", color=color)
        if stats:
            share = 100.0 * stats["total"] / stats["limit"]
            lines.append(f"{label}      {path.name:<{name_width}}  "
                         f"{stats['total']:,} B / {stats['limit']:,} B "
                         f"({_memory_share(share, color=color)})")
        else:
            lines.append(f"{label}      {path.name}")
    return lines


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    parser = _parser()
    raw = _rewrite_trailing_help(raw, _subparsers(parser))
    raw = _rewrite_stdout_output(raw)
    args = parser.parse_args(raw)
    # `color` only exists once a subcommand parser has run; `color_before` is
    # always present from the top-level parser (see `_color_parser`).
    term.set_mode(getattr(args, "color", None) or args.color_before or "auto")
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except (DeviceError, icons.IconFontMissing) as exc:
        _error(str(exc))
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Every registered subcommand parser, by name.

    argparse has no public accessor for this; walking the top-level parser's
    ``_subparsers._group_actions`` for the ``_SubParsersAction`` and reading
    its ``choices`` is the standard, stable way to get it. Shared by
    `_rewrite_trailing_help` and `_help`, which both need the same dict.
    """
    for action in parser._subparsers._group_actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _rewrite_trailing_help(argv: list[str], commands: dict[str, argparse.ArgumentParser]) -> list[str]:
    """``wfb <command> help`` -> ``wfb <command> --help``.

    Supported alongside the leading ``wfb help <command>`` form and plain
    ``-h``/``--help``, since a trailing ``help`` is how most CLIs a caller
    has already used behave.
    """
    if len(argv) == 2 and argv[1] == "help" and argv[0] in commands:
        return [argv[0], "--help"]
    return argv


#: What ``-o`` is given to write the image itself to stdout.  Both spellings
#: are accepted; `_rewrite_stdout_output` normalises the one argparse cannot
#: see, and `_is_stdout` still recognises the ``--output=--`` form it never
#: touches.
STDOUT_OUTPUT = ("-", "--")


def _rewrite_stdout_output(argv: list[str]) -> list[str]:
    """``-o --`` -> ``-o -``.

    argparse removes the first bare ``--`` from the argument list as the
    end-of-options separator *before* any option can consume it as a value,
    so ``wfb preview face.yaml -o --`` would otherwise die with "expected one
    argument".  Both spellings mean the same thing, and this is the only
    place that can still see the ``--``.
    """
    out = list(argv)
    for index, token in enumerate(out[:-1]):
        if token in ("-o", "--output") and out[index + 1] == "--":
            out[index + 1] = "-"
    return out


def _is_stdout(output: Path | None) -> bool:
    """Is this ``-o``/``--output`` value the write-to-stdout marker?"""
    return output is not None and str(output) in STDOUT_OUTPUT


def _color_parser(dest: str = "color") -> argparse.ArgumentParser:
    """A parent-parser fragment for ``--color``, mixed into the top-level
    parser (as ``color_before``) and every subcommand (as ``color``) so the
    flag works on either side of the command name.  They must be different
    ``dest``s: a subparser's ``parse_known_args`` call always merges its
    *whole* namespace -- including unset options at their default -- back
    into the shared one, so one shared ``color`` dest would let ``wfb
    --color never build x`` be silently overwritten by ``build``'s own
    default the moment its subparser runs.  ``main`` combines the two,
    subcommand-level taking precedence.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--color", dest=dest, choices=term.MODES, default=None,
                        help="colour the output: auto (default), always or never")
    return parser


def _command(sub: argparse._SubParsersAction, name: str, handler) -> argparse.ArgumentParser:
    """Register one subcommand, with its help text sourced entirely from
    ``handler``'s docstring: the first line is the short summary ``wfb
    --help`` lists next to the command name, and the whole docstring is what
    ``wfb <command> --help`` / ``wfb help <command>`` / ``wfb <command>
    help`` all print -- one docstring, not a hand-written ``help=`` string
    that can drift from it.
    """
    doc = inspect.getdoc(handler) or ""
    summary = doc.splitlines()[0] if doc else ""
    parser = sub.add_parser(
        name, help=summary, description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[_color_parser()],
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
        _error(f"no such command {args.topic!r}")
        print(f"       commands: {', '.join(sorted(commands))}", file=sys.stderr)
        return 1
    target.print_help()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfb",
        description=inspect.getdoc(sys.modules[__name__]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[_color_parser("color_before")],
    )
    parser.add_argument("--version", action="version", version=f"wfb {__version__}")
    sub = parser.add_subparsers(dest="command")

    build = _command(sub, "build", _build)
    build.add_argument("design", type=Path, help="the .yaml design file")
    build.add_argument("-d", "--device", action="append", dest="devices",
                       help="build only this device (repeatable); any installed device, "
                            "not just a listed target; defaults to all targets")
    build.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                       help=f"build directory (default: {DEFAULT_OUTPUT})")
    build.add_argument("--no-compile", action="store_true",
                       help="generate the project but do not run monkeyc")
    build.add_argument("--sdk", help="Connect IQ SDK root (default: $CIQ_SDK)")
    build.add_argument("--key", help="developer key .der (default: ~/ciq/developer_key.der)")
    build.add_argument("--devices-dir", help="device definitions directory")

    check = _command(sub, "validate", _validate)
    check.add_argument("design", type=Path)
    check.add_argument("-d", "--device", action="append", dest="devices",
                       help="check only this device (repeatable); any installed device, "
                            "not just a listed target; defaults to all targets")
    check.add_argument("--devices-dir")

    preview = _command(sub, "preview", _preview)
    preview.add_argument("design", type=Path)
    preview.add_argument("-d", "--device", action="append", dest="devices",
                         help="render only this device (repeatable); any installed "
                              "device, not just a listed target; defaults to all targets")
    preview.add_argument("-o", "--output", type=Path, default=Path("build/preview"),
                         help="directory to write the PNGs to (default: build/preview); "
                              "`-o -` (or `-o --`) writes ONE PNG to stdout instead, for "
                              "piping -- e.g. `wfb preview face.yaml -o -- | chafa`")
    preview.add_argument("-q", "--quiet", action="store_true",
                         help="print nothing to stdout; errors and warnings still go to "
                              "stderr (implied by `-o -`)")
    preview.add_argument("--scale", type=int, default=2)
    preview.add_argument("--no-quantise", action="store_true",
                         help="skip snapping colours to the device palette")
    preview.add_argument("--style", help="render one 'config: style:' entry by name "
                         "(default: the default entry)")
    preview.add_argument("--all-styles", action="store_true",
                         help="render every 'config: style:' entry side by side, one "
                              "PNG per device")
    preview.add_argument("--time", metavar="HH:MM[:SS]",
                         help="render analog hands (and any time.*-bound element) at "
                              "this time instead of the sample 10:09:42")
    preview.add_argument("--asleep", action="store_true",
                         help="render the sleeping onUpdate frame: the 'always_on' "
                              "element set when the design has one, 'active' "
                              "otherwise, with every awake-only second hand hidden")
    preview.add_argument("-w", "--watch", action="store_true",
                         help="re-render whenever the design or a font it uses changes")
    preview.add_argument("--interval", type=float, default=0.4,
                         help="seconds between checks while watching (default: 0.4)")
    preview.add_argument("--devices-dir")
    preview.add_argument("--fonts", dest="fonts_dir",
                         help="Garmin ConnectIQ Fonts directory (default: $WFB_FONTS, "
                              "vendor/fonts/, or the SDK Manager's per-OS install location); "
                              "without it, any face the registry has no exact match for is "
                              "drawn with a stand-in typeface -- see `wfb doctor`")

    simulate = _command(sub, "simulate", _simulate)
    simulate.add_argument("design", type=Path)
    simulate.add_argument("-d", "--device", dest="device",
                          help="which device to run, target or not (default: the "
                               "first target)")
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
    doctor.add_argument("--fonts", dest="fonts_dir",
                         help="Garmin ConnectIQ Fonts directory (default: $WFB_FONTS, "
                              "vendor/fonts/, or the SDK Manager's per-OS install location)")

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
    the generated Monkey C directly. `-d/--device` builds one or more
    devices instead of every target the design lists; it may name any
    installed device (`wfb devices`), not only a listed target, which
    draws a note and needs no edit to the design.
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
        color_err = term.should_color(sys.stderr)
        word = term.style("failed", "bold", "red", enabled=color_err)
        print(f"\nbuild {word} -- {bag.summary(color=color_err)}", file=sys.stderr)
        return 1

    color_out = term.should_color(sys.stdout)
    print()
    print(f"{_status('generated', color=color_out)}  {result.output_dir}")
    for line in _format_built(result.products, result.memory, color=color_out):
        print(line)
    if not result.products and args.no_compile:
        print("           (not compiled: --no-compile)")
    word = term.style("succeeded", "bold", "green", enabled=color_out)
    print(f"\nbuild {word} -- {bag.summary(color=color_out)} in {result.duration:.1f}s")
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
            devices = select_devices(face, db, bag, args.devices)
            if devices:
                resolve_all(face, devices, bag)
    bag.print()
    if face is None or not bag.ok():
        color_err = term.should_color(sys.stderr)
        word = term.style("invalid", "red", enabled=color_err)
        print(f"\n{word} -- {bag.summary(color=color_err)}", file=sys.stderr)
        return 1
    color_out = term.should_color(sys.stdout)
    word = term.style("ok", "bold", "green", enabled=color_out)
    print(f"{args.design}: {word} -- {bag.summary(color=color_out)}")
    return 0


def _parse_preview_time(text: str) -> tuple[int, int, int] | None:
    """``HH:MM`` or ``HH:MM:SS`` -- ``wfb preview --time``.  Returns ``None``
    for anything else, so the caller can print one clean error rather than
    an uncaught ``ValueError``."""
    parts = text.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return (hour, minute, second)


def _render_preview(args, db, *, blurb: bool = True) -> tuple[int, list[Path]]:
    """Render once.  Returns the exit code and the design's dependencies.

    ``blurb`` is watch mode's suppression of the closing note alone -- it
    still wants to see each re-render's line.  ``--quiet``, and the stdout
    marker that implies it, silence stdout completely; diagnostics are
    unaffected either way, because `Bag.print` writes to stderr.
    """
    from .preview import PreviewOptions, UnknownStyleError, render, render_all_styles
    from .preview import stand_in_warning as preview_stand_in_warning
    from .preview import write as write_preview, write_all_styles

    to_stdout = _is_stdout(getattr(args, "output", None))
    quiet = to_stdout or getattr(args, "quiet", False)
    style = getattr(args, "style", None)
    all_styles = getattr(args, "all_styles", False)
    if style is not None and all_styles:
        _error("--style and --all-styles are mutually exclusive")
        return 1, [args.design]

    time_arg = getattr(args, "time", None)
    time: tuple[int, int, int] | None = None
    if time_arg is not None:
        time = _parse_preview_time(time_arg)
        if time is None:
            _error(f"--time {time_arg!r} is not HH:MM or HH:MM:SS")
            return 1, [args.design]

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
    if to_stdout:
        # One stream, one image: the first device asked for with -d, or the
        # design's first target.  `select_devices` keeps that order.
        devices = devices[:1]
    resolved, _ = resolve_all(face, devices, bag)
    bag.print()
    if not bag.ok():
        return 1, watched

    options = PreviewOptions(scale=args.scale, quantise=not args.no_quantise, style=style,
                             time=time, asleep=getattr(args, "asleep", False),
                             fonts_root=getattr(args, "fonts_dir", None))
    color_out = term.should_color(sys.stdout)
    label = _status("preview", color=color_out)
    # Collects every distinct face this whole call resolves, across every
    # device and (with --all-styles) every panel, so the stand-in warning
    # below fires once per run rather than once per device (plan 12 R1.1/R1.2).
    used_faces: dict = {}
    try:
        for device_id, result in resolved.items():
            if to_stdout:
                image = (render_all_styles(result, options, used_faces=used_faces) if all_styles
                         else render(result, options, used_faces=used_faces))
                image.save(sys.stdout.buffer, format="PNG")
                sys.stdout.buffer.flush()
                continue
            if all_styles:
                path = write_all_styles(
                    result, args.output / f"{device_id}--all-styles.png", options,
                    used_faces=used_faces)
            else:
                suffix = f"--{style}" if style is not None else ""
                path = write_preview(result, args.output / f"{device_id}{suffix}.png", options,
                                     used_faces=used_faces)
            if not quiet:
                print(f"{label}    {path}  ({result.device.width}x{result.device.height} "
                      f"at {args.scale}x)", flush=True)
    except UnknownStyleError as exc:
        _error(str(exc))
        return 1, watched
    # Not suppressed by -q/-o - (R1.4): those silence stdout progress, and a
    # wrong typeface is a correctness warning, not progress.  Always to
    # stderr, always after every device/panel has had a chance to record a
    # face, so it names everything the whole run drew with, not just the
    # first device.
    warning = preview_stand_in_warning(used_faces)
    if warning:
        print(warning, file=sys.stderr)
    if blurb and not quiet:
        print()
        for line in (
            "Rendered from the same resolved geometry the generated code uses, so the",
            "two cannot disagree about position.  Glyph rendering and arc caps are",
            "approximations -- the simulator is authoritative for those.",
        ):
            print(term.style(line, "dim", enabled=color_out))
    return 0, watched


def _preview(args) -> int:
    """render the design to a PNG on the host, with no simulator

    Resolves the same per-device geometry `wfb build` would generate code
    from, then rasterises it directly with Pillow -- so a preview and a
    compiled face cannot disagree about *position*. Glyph shapes and arc
    caps are approximations; the Connect IQ simulator is authoritative for
    those, when it can run at all (see docs/limitations.md).

    A system or vector font is drawn with the user's own licensed Garmin
    font file when `--fonts DIR` (or `WFB_FONTS`, or `vendor/fonts/`) finds
    one; otherwise it falls back to a free stand-in, or even Pillow's own
    bundled default, silently as far as the image goes -- except that this
    command then prints one warning to stderr naming every font that
    happened to, and what to do about it (`wfb doctor` reports the same
    root). See `docs/lore/toolchain.md`.

    `--style <entry>` renders one `config: style:` entry -- its scheme's
    colours and only the shared content plus that entry's own layout --
    naming an unknown entry is a clean error listing the declared ones.
    `--all-styles` renders every entry side by side in one PNG per device,
    each panel captioned with the entry's label. Neither needs a `config:
    style:` axis to exist for an ordinary preview with neither flag.

    `--time HH:MM[:SS]` renders analog hands (and any `time.*`-bound
    element) at that time instead of the sample 10:09:42. `--asleep` renders
    the sleeping `onUpdate` frame -- the `always_on` element set when the
    design has one, `active` otherwise -- with every `awake`-only second
    hand hidden, the same choice the generated `_sleeping` branch makes
    (plan 04 §7).

    `-w/--watch` re-renders whenever the design file or any font it
    references changes, polling every `--interval` seconds (default 0.4).

    `-o -` -- or `-o --`, which reads better next to a pipe -- writes the
    PNG bytes to stdout instead of to files, and renders exactly one image:
    the device `-d` names, or the design's first target. It implies
    `-q/--quiet`, so stdout carries the image and nothing else; warnings and
    errors still go to stderr. That makes a terminal preview a one-liner:

        wfb preview face.yaml -o -- | chafa
        wfb preview face.yaml -d fr955 -o - > face.png

    `-q/--quiet` on its own silences stdout while still writing the PNG
    files, for a script that only cares about the exit code.
    """
    if _is_stdout(args.output) and args.watch:
        _error("-o - writes one image and exits; it cannot be combined with --watch")
        return 1
    db = DeviceDatabase.discover(args.devices_dir)
    if not args.watch:
        if not (args.quiet or _is_stdout(args.output)):
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

    color_out = term.should_color(sys.stdout)
    if not args.quiet:
        print(f"watching {args.design} -- press Ctrl-C to stop\n", flush=True)
    code, watched = _render_preview(args, db, blurb=False)
    seen = stamps(watched)
    try:
        while True:
            time.sleep(args.interval)
            current = stamps(watched)
            if current == seen:
                continue
            seen = current
            if not args.quiet:
                separator = term.style(f"--- {time.strftime('%H:%M:%S')} ---",
                                       "dim", enabled=color_out)
                print(f"\n{separator}", flush=True)
            code, watched = _render_preview(args, db, blurb=False)
            seen.update(stamps(watched))
    except KeyboardInterrupt:
        if not args.quiet:
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
    color_out = term.should_color(sys.stdout)
    print(f"\n{_status('pushed', color=color_out)} {prg.name} to the {device_id} simulator")
    if args.screenshot:
        try:
            path = screenshot(args.screenshot)
            print(f"{_status('screenshot', color=color_out)} {path}")
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
    import uuid

    templates = sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml"))
    if args.list_templates:
        for name in templates:
            print(f"  {name:<12} {TEMPLATE_BLURB.get(name, '')}")
        return 0

    if not args.name:
        _error("a face name is required")
        print(f"       usage: wfb new \"My Face\" [--template {'|'.join(templates)}]",
              file=sys.stderr)
        return 1

    source = TEMPLATE_DIR / f"{args.template}.yaml"
    if not source.exists():
        _error(f"no template {args.template!r}")
        print(f"       available: {', '.join(templates)}", file=sys.stderr)
        return 1

    destination = args.output or Path(f"{slug(args.name)}.yaml")
    if destination.exists():
        _error(f"{destination} already exists")
        return 1

    # A fresh UUID every call -- see the docstring for why.
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
    from .validate import SCHEMA_PATH

    color_out = term.should_color(sys.stdout)
    # Pad the fixed-width column text *before* wrapping it in ANSI codes --
    # styling after padding would count the escape bytes towards the width
    # and misalign every line that follows.
    ok = term.style("  ok ", "green", enabled=color_out)
    missing = term.style("MISSING", "bold", "red", enabled=color_out)
    absent = term.style(" none", "yellow", enabled=color_out)
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

    # -- the icon font ----------------------------------------------------
    if icons.FONT_PATH.is_file():
        print(f"{ok} icon font        {icons.FONT_PATH}")
    else:
        print(f"{missing} icon font        {icons.FONT_PATH}")
        print("                   run tools/setup-env.sh, or python3 tools/fetch-icon-font.py")
        problems.append("install the icon font")
        blocking += 1

    # -- Garmin's own font files (optional; outrank the registry when found) --
    # Never triggers a download: doctor only reports what is already there.
    # Both branches state the *consequence* of the finding, not only whether
    # it is optional (plan 12 R3.2) -- "optional" alone reads as "safe to
    # ignore", when what it actually costs is `wfb preview` drawing every
    # non-exact-matched face with a stand-in typeface instead of the
    # device's own (`wfb.preview.stand_in_warning`, R1, says which ones).
    fetch_system = fonts.fetch_system
    fonts_root = fetch_system.garmin_font_root(getattr(args, "fonts_dir", None))
    if fonts_root is not None:
        print(f"{ok} Garmin fonts     {fonts_root}  (previews draw exact glyph shapes)")
    else:
        print(f"{absent} Garmin fonts     not found (optional; previews draw stand-in "
              "typefaces for any face the registry has no exact match for)")
        if os.environ.get("WFB_CONTAINER") == "1":
            # vendor/ never reaches the image (.dockerignore): a mount is the
            # only way in, at the WFB_FONTS the Dockerfile sets.
            mount = os.environ.get("WFB_FONTS") or "/fonts"
            print("                   mount the SDK Manager's Fonts directory:")
            print(f"                     -v <SDK Manager's Fonts dir>:{mount}:ro")
            print("                   -- see docs/container.md")
        else:
            print("                   copy the SDK Manager's Fonts directory into vendor/fonts/,")
            print("                   or set WFB_FONTS / pass --fonts DIR -- see docs/container.md")

    # -- the system fonts each target device needs (registry stand-ins) ---
    for device_id in fetch_system.DEFAULT_TARGET_DEVICES:
        needed = fetch_system.device_needed_names(device_id)
        if not needed:
            continue
        # "unmapped" is a deliberate registry decision (a CJK/RTL-only face),
        # not something an install could fix, so it never flips the marker.
        tiers = {"garmin": 0, "installed": 0, "cached": 0, "missing": 0, "unmapped": 0}
        for name, face in needed:
            # `garmin_any_file` counts a `.cft` bitmap hit as usable too
            # (plan 10 §3 B.2) -- the same lookup `fetch_system.locate`
            # uses, so this summary and the actual measure/preview path
            # can never disagree about what counts as "found".
            if fonts_root is not None and fetch_system.garmin_any_file(name, fonts_root) is not None:
                tiers["garmin"] += 1
                continue
            key = fetch_system.resolve(name, face)
            if key is None:
                tiers["unmapped"] += 1
                continue
            tiers[fetch_system.tier_for(key) or "missing"] += 1
        summary = ", ".join(f"{count} {label}" for label, count in tiers.items() if count)
        marker = ok if tiers["missing"] == 0 else absent
        print(f"{marker} fonts: {device_id:<16} {summary}")
    print("                   never downloads -- run tools/setup-env.sh, or "
          "python3 tools/fetch-system-fonts.py; not blocking, falls back to a "
          "substitute face at build time")

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
        word = term.style("ready", "green", enabled=color_out)
        print(f"{word}: validate, preview and build all work.")
        return 0
    if blocking == 0:
        word = term.style("partial", "yellow", enabled=color_out)
        print(f"{word}: validate and preview work; `wfb build` cannot compile yet.")
        print("         fix: " + "; ".join(problems))
        return 0
    word = term.style("not ready", "red", enabled=color_out)
    print(f"{word}: " + "; ".join(problems))
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
    color_out = term.should_color(sys.stdout)
    header = (f"{'id':<24} {'screen':<12} {'shape':<10} {'display':<8} "
              f"{'colors':<7} {'api':<8} {'watch face':<10} family")
    print(term.style(header, "bold", enabled=color_out))
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

    Also lists `config.*` -- the native on-device colour axes, including
    Styles (`config.colors.<role>`, ADR 0006 1, twice amended) -- even
    though, unlike everything above, these are not read from any device API:
    a design that declares `config:` binds them the same way, as an ordinary
    colour expression.
    """
    color_out = term.should_color(sys.stdout)
    for namespace, paths in catalog.namespaces().items():
        print(f"\n{term.style(namespace, 'bold', enabled=color_out)}")
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
    print(f"\n{term.style('config', 'bold', enabled=color_out)}  (declared per design in "
          "'config:' -- fēnix 8 Solar's native editor only, see docs/format.md)")
    print(f"  {'config.accent_color':<34} {'color':<8} the one accent-colour axis "
          "(<accentColors>, Settings.accentColor)")
    print(f"  {'config.data_color':<34} {'color':<8} the one data-colour axis "
          "(<dataColors>, Settings.complicationColor)")
    print(f"  {'config.colors.<role>':<34} {'color':<8} the Styles axis -- one role of a "
          "declared 'color_scheme:' entry, picked via the active 'config: style:' "
          "entry's 'colors:' (<styles>, Settings.styleId)")
    print(f"  {'config.data.<name>':<34} {'':<8} the Data axis -- a named native "
          "complication slot declared in 'config: data:' (<data><complication>, "
          "Settings.complicationSettings); drawn by a 'type: complication_slot' "
          "element ('slot:'), not bound as an ordinary expression")
    print(f"\nicons: {', '.join(icons.names())}")
    print("\nrun `wfb complications` for the full list of on_hold: targets")
    return 0


def _complications(args) -> int:
    """list the complication type table: what `on_hold:` may launch, what
    `complication.*` may read, and what `config: data:` may offer a slot

    A watch face cannot open an arbitrary app. The platform offers exactly
    one exit -- `Complications.exitTo`, "launches the app associated with
    the complication" -- so an interactive element names a complication
    type and the watch opens whichever glance or app owns it. The same 42
    types are also readable directly as `complication.<name>` data sources
    (see `wfb sources`), and are what a `config: data:` slot's own
    `default:`/`choices:` name -- this is the one table all three draw from.

    Printed for each: the name a design writes, the Monkey C constant it
    compiles to, the API level that type was introduced at, and the
    catalogue icon a `complication_slot`'s `icon_size:` draws for it by
    default (`wfb.icons.COMPLICATION_ICON`, all 42 types since 2026-09-13 --
    a `choices:` mapping-form entry can override this per design). An API
    level is not a promise the watch has it; a hold on a type the watch
    does not know simply does nothing, which is why `wfb validate` also
    checks each target's own symbol table (and, for a slot, each target's
    own ConnectIQ ceiling -- see `api-gated` in docs/format.md).

    Binding one of these -- as `on_hold:`, as `complication.<name>`, or via
    `on_hold: auto` -- adds the ComplicationSubscriber permission
    automatically, the same way a data binding derives its own
    requirements. A `config: data:` slot does too, even though it reads no
    catalogue source directly. `minApiLevel` itself no longer moves for any
    of this (`manifest.xml` is one file shared by every target device, so a
    per-feature bump broke any build that also targeted a lower-level
    device): a target that lacks `Toybox.Complications` -- fenix6 and fr245,
    this project's lowest-level installed devices, both do -- instead has
    the generated code guard every use of it at runtime (`wfb.availability`,
    `wfb/emit/monkeyc.py`), so the binding simply reads as absent there.
    """
    width = max(len(name) for name in complications.names())
    icon_width = max(len(icons.COMPLICATION_ICON.get(name, "")) for name in complications.names())
    for name in complications.names():
        entry = complications.TYPES[name]
        since = "" if entry.since == complications.EXIT_TO_API_LEVEL else f"  (since {entry.since})"
        icon_name = icons.COMPLICATION_ICON.get(name, "")
        print(f"  {name:<{width}}  Complications.{entry.constant}  "
              f"icon: {icon_name:<{icon_width}}{since}")
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
