"""wfb -- build a Garmin Connect IQ watch face from a YAML design.

    wfb validate design.yaml     # fast feedback: schema + semantic checks, no toolchain
    wfb preview  design.yaml     # render to a PNG, with no simulator
    wfb build    design.yaml     # generate Monkey C, resources and manifest, then compile

Run `wfb help` for the full command list, or `wfb help <command>` /
`wfb <command> help` for one command's own help. `wfb doctor` reports what is installed and what to do about anything
missing; `wfb sources`, `wfb devices` and `wfb fonts` list what a design
may bind and which watches and fonts it may use.

Every subcommand takes `--color {auto,always,never}` (default auto), either
before or after the command name -- `wfb --color never build x` and `wfb
build --color never x` both work.
"""

from __future__ import annotations

import argparse
import inspect
import os
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Callable, TextIO

from . import __version__, catalog, complications, fonts, icons, series as series_catalog, term
from .build import (
    BUILD_INFO, MAX_DEFAULT_JOBS, BuildResult, Toolchain, build as run_build, load, resolve_all,
    select_devices, slug,
)
from .simulate import SimulatorError, push, screenshot
from .devices import (DEVICE_REFERENCE, Device, DeviceDatabase, DeviceError,
                      DeviceReferenceMissing, FontMetric, reference_sdk_version)
from .diagnostics import Bag, Severity
from .lint import MemoryStats

DEFAULT_OUTPUT = Path("build")
DEFAULT_PROFILE_REPS = 10


def _error(message: str, *, file: TextIO | None = None) -> None:
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


def _verdict(bag: Bag, stream: TextIO, word: str, *styles: str, before: str = "",
             after: str = "") -> None:
    """Print a command's closing ``<before><word> -- <diagnostic counts><after>``
    line to ``stream``, coloured only when ``stream`` is."""
    color = term.should_color(stream)
    print(f"{before}{term.style(word, *styles, enabled=color)} -- "
          f"{bag.summary(color=color)}{after}", file=stream)


def _format_built(products: dict[str, Path], memory: dict[str, MemoryStats], *,
                  color: bool) -> list[str]:
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
        code: int = args.handler(args)
        return code
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
    if parser._subparsers is None:
        return {}
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


def _command(sub: "argparse._SubParsersAction[argparse.ArgumentParser]", name: str,
             handler: Callable[[argparse.Namespace], int]) -> argparse.ArgumentParser:
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


def _help(args: argparse.Namespace) -> int:
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
    build.add_argument("-v", "--verbose", action="store_true",
                       help="show every note in full, with its source line and details")
    build.add_argument("design", type=Path, help="the .yaml design file")
    build.add_argument("-d", "--device", action="append", dest="devices",
                       help="build only this device (repeatable); any installed device, "
                            "not just a listed target; defaults to all targets")
    build.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                       help=f"build directory (default: {DEFAULT_OUTPUT})")
    build.add_argument("--no-compile", action="store_true",
                       help="generate the project but do not run monkeyc")
    build.add_argument("--profile", nargs="?", type=int, const=DEFAULT_PROFILE_REPS,
                       metavar="REPS",
                       help="time every element's draw on the watch and show the average "
                            f"per call over it (default: {DEFAULT_PROFILE_REPS} repetitions "
                            "per sample) -- a build for measuring, not for wearing")
    build.add_argument("-j", "--jobs", type=_positive_int, metavar="N",
                       help="compile up to N devices at once (default: one per device, "
                            f"at most one per CPU and at most {MAX_DEFAULT_JOBS})")
    build.add_argument("--sdk", help="Connect IQ SDK root (default: $CIQ_SDK)")
    build.add_argument("--key", help="developer key .der (default: ~/ciq/developer_key.der)")
    build.add_argument("--devices-dir", help="device definitions directory")

    check = _command(sub, "validate", _validate)
    check.add_argument("-v", "--verbose", action="store_true",
                       help="show every note in full, with its source line and details")
    check.add_argument("design", type=Path)
    check.add_argument("-d", "--device", action="append", dest="devices",
                       help="check only this device (repeatable); any installed device, "
                            "not just a listed target; defaults to all targets")
    check.add_argument("--devices-dir")

    preview = _command(sub, "preview", _preview)
    preview.add_argument("-v", "--verbose", action="store_true",
                       help="show every note in full, with its source line and details")
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
    preview.add_argument("--scale", type=int, default=2,
                         help="enlarge the native-resolution frame this many times, each "
                              "watch pixel a SCALE x SCALE block (default: 2)")
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
    preview.add_argument("--units", choices=("metric", "statute"),
                         help="the watch's unit setting to render a 'units: auto' "
                              "element under (default: metric)")
    preview.add_argument("--asleep", action="store_true",
                         help="hide every awake-only second hand, simulating a sleeping "
                              "glance (no mode/aod-set switch: 'always_on' membership "
                              "used to do that too, but was removed -- see --aod)")
    preview.add_argument("--aod", action="store_true",
                         help="render the AMOLED always-on-display frame: the resolved "
                              "'aod:' set, restyled, with every awake-only second hand "
                              "hidden")
    preview.add_argument("--minute", type=int, metavar="N",
                         help="render minute N of the day (0-1439); sugar for --time, "
                              "and mutually exclusive with it")
    preview.add_argument("--heatmap", action="store_true",
                         help="sum the AOD frame (implies --aod) over every minute of the "
                              "day into one PNG where a pixel lit every minute is white, "
                              "and print the largest share of minutes any pixel was lit")
    preview.add_argument("--skin", action="store_true",
                         help="draw the watch round the screen: the simulator skin from "
                              "the device files; a device without one renders the bare "
                              "screen, with a warning")
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
    simulate.add_argument("-v", "--verbose", action="store_true",
                       help="show every note in full, with its source line and details")
    simulate.add_argument("design", type=Path)
    simulate.add_argument("-d", "--device", dest="device",
                          help="which device to run, target or not (default: the "
                               "first target)")
    simulate.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    simulate.add_argument("--screenshot", type=Path,
                          help="capture the simulator window to this PNG")
    simulate.add_argument("-f", "--follow", action="store_true",
                          help="stay attached and print the face's console output "
                               "(System.println) until Ctrl-C")
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

    studio = _command(sub, "studio", _studio)
    studio.add_argument("--host", default="127.0.0.1",
                        help="the address to listen on (default: 127.0.0.1, loopback only)")
    studio.add_argument("-p", "--port", type=int, default=8765,
                        help="the port to listen on (default: 8765)")
    studio.add_argument("--state-dir", type=Path,
                        help="where the history of every face is kept (default: "
                             "$XDG_STATE_HOME/wfb/studio, or ~/.local/state/wfb/studio)")
    studio.add_argument("--snapshot-minutes", type=float, default=5.0,
                        help="snapshot a changed face this often (default: 5)")
    studio.add_argument("--keep-snapshots", type=int, default=50,
                        help="on start, keep each face's newest N snapshots (default: 50)")
    studio.add_argument("--single-user", action="store_true",
                        help="every browser sees and edits the same faces, as one person "
                             "(default: each browser has its own)")
    studio.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                        help="also answer requests addressed to NAME (a proxy's or a LAN "
                             "name); repeatable. Loopback names are always answered")
    studio.add_argument("--devices-dir")
    studio.add_argument("--fonts", dest="fonts_dir",
                        help="Garmin ConnectIQ Fonts directory, as for `wfb preview`")

    devices = _command(sub, "devices", _devices)
    devices.add_argument("--devices-dir")

    fonts_cmd = _command(sub, "fonts", _fonts)
    fonts_cmd.add_argument("devices", nargs="*", metavar="DEVICE",
                           help="device(s) to inspect (repeatable; default: all installed "
                                "devices, summarised)")
    fonts_cmd.add_argument("-d", "--device", action="append", dest="device_flags",
                           metavar="DEVICE",
                           help="another device to inspect (repeatable; alternative or "
                                "addition to the positional form)")
    fonts_cmd.add_argument("--devices-dir", help="device definitions directory")

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


def _build(args: argparse.Namespace) -> int:
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

    The devices compile in parallel, each `monkeyc` in its own directory;
    `-j/--jobs N` caps how many run at once (`-j 1` compiles one at a
    time). Diagnostics are reported in device order either way.
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
        profile=args.profile,
        jobs=args.jobs,
    )
    shown = bag
    if result is not None and not args.verbose:
        # the "built" lines below give each built device's measured memory
        shown = bag.only(lambda d: not (d.code == "memory" and d.severity is Severity.NOTE
                                        and d.message.split(":", 1)[0] in result.products))
    shown.print(verbose=args.verbose)
    if result is None or not bag.ok():
        _verdict(bag, sys.stderr, "failed", "bold", "red", before="\nbuild ")
        return 1

    color_out = term.should_color(sys.stdout)
    print()
    print(f"{_status('generated', color=color_out)}  {result.output_dir}")
    for line in _format_built(result.products, result.memory, color=color_out):
        print(line)
    if not result.products and args.no_compile:
        print("           (not compiled: --no-compile)")
    if result.sdk_version is not None:
        print(f"{_status('sdk', color=color_out)}        Connect IQ {result.sdk_version}, "
              f"recorded in {BUILD_INFO}")
    if args.profile and result.products:
        _print_profile_report(result, args.profile)
    _verdict(bag, sys.stdout, "succeeded", "bold", "green", before="\nbuild ",
             after=f" in {result.duration:.1f}s")
    return 0


def _print_profile_report(result: BuildResult, reps: int) -> None:
    """`--profile`'s code-size table for the first target built -- the
    view is shared, so its methods are the same on every target -- also
    written to `profile.txt` beside the `.prg` files."""
    from .build import method_code_sizes
    from .emit.monkeyc import profile

    device_id, prg = next(iter(result.products.items()))
    debug = prg.with_name(prg.name + ".debug.xml")
    if not debug.exists():
        return
    plan = profile.plan_for(result.project.resolved[device_id], reps)
    lines = profile.code_report(plan, result.face, method_code_sizes(debug))
    (result.output_dir / "profile.txt").write_text("\n".join(lines) + "\n")
    print(f"\ncode per entry ({device_id}; draw time is on the watch), "
          f"also in {result.output_dir / 'profile.txt'}:")
    for line in lines:
        print(f"  {line}")


def _validate(args: argparse.Namespace) -> int:
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
        else:
            devices = select_devices(face, db, bag, args.devices)
            if devices:
                resolve_all(face, devices, bag)
    bag.print(verbose=args.verbose)
    if face is None or not bag.ok():
        _verdict(bag, sys.stderr, "invalid", "red", before="\n")
        return 1
    _verdict(bag, sys.stdout, "ok", "bold", "green", before=f"{args.design}: ")
    return 0


def _positive_int(text: str) -> int:
    """An argparse type: a whole number of at least 1."""
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of at least 1")
    return int(text)


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


def _preview_time(args: argparse.Namespace, minutes_per_day: int) -> tuple[int, int, int] | None:
    """Check `wfb preview`'s flag combinations and return the moment to
    render (``None``: the sample time).  Raises `ValueError` with the message
    to print for a conflicting or malformed flag."""
    # Each group names several answers to one question (which panel; which
    # moment), so at most one of each may be given.
    exclusive = (
        (("--style", args.style is not None), ("--all-styles", args.all_styles)),
        (("--time", args.time is not None), ("--minute", args.minute is not None),
         ("--heatmap", args.heatmap)),
    )
    for flags in exclusive:
        given = [name for name, on in flags if on]
        if len(given) > 1:
            raise ValueError(f"{' and '.join(given)} are mutually exclusive")
    if args.heatmap and args.all_styles:
        raise ValueError("--heatmap renders one panel; use --style to pick it, not --all-styles")
    if args.time is not None:
        time = _parse_preview_time(args.time)
        if time is None:
            raise ValueError(f"--time {args.time!r} is not HH:MM or HH:MM:SS")
        return time
    if args.minute is not None:
        if not 0 <= args.minute < minutes_per_day:
            raise ValueError(f"--minute {args.minute} is not 0..{minutes_per_day - 1}")
        return (args.minute // 60, args.minute % 60, 0)
    return None


def _render_preview(args: argparse.Namespace, db: DeviceDatabase, *, blurb: bool = True) -> tuple[int, list[Path]]:
    """Render once.  Returns the exit code and the design's dependencies.

    ``blurb`` is watch mode's suppression of the closing note alone -- it
    still wants to see each re-render's line.  ``--quiet``, and the stdout
    marker that implies it, silence stdout completely; diagnostics are
    unaffected either way, because `Bag.print` writes to stderr.
    """
    from .preview import (
        MINUTES_PER_DAY, PreviewOptions, UnknownStyleError, render, render_all_styles,
        has_skin, mono_guess_warning, render_aod_heatmap, save, skin_missing_warning,
    )
    from .preview import stand_in_warning as preview_stand_in_warning

    to_stdout = _is_stdout(args.output)
    quiet = to_stdout or args.quiet
    style, all_styles, heatmap = args.style, args.all_styles, args.heatmap
    try:
        time = _preview_time(args, MINUTES_PER_DAY)
    except ValueError as exc:
        _error(str(exc))
        return 1, [args.design]

    bag = Bag()
    face = load(args.design, bag)
    if face is None:
        bag.print(verbose=args.verbose)
        return 1, [args.design]
    # Font sources are watched too: re-baking on a font change is the whole point
    # of watching, and the design file alone would not notice.
    watched = [args.design] + [spec.source for spec in face.fonts.values()]

    devices = select_devices(face, db, bag, args.devices)
    if not devices:
        bag.print(verbose=args.verbose)
        return 1, watched
    if to_stdout:
        # One stream, one image: the first device asked for with -d, or the
        # design's first target.  `select_devices` keeps that order.
        devices = devices[:1]
    resolved, _ = resolve_all(face, devices, bag)
    bag.print(verbose=args.verbose)
    if not bag.ok():
        return 1, watched

    sample: dict[str, object] | None = None
    if args.units is not None:
        setting = 1 if args.units == "statute" else 0
        sample = {f"device.{name}_units": setting
                  for name in ("distance", "elevation", "temperature", "pace")}
    options = PreviewOptions(scale=args.scale, quantise=not args.no_quantise, style=style,
                             time=time, asleep=args.asleep, aod=heatmap or args.aod,
                             sample=sample,
                             fonts_root=args.fonts_dir, skin=args.skin)
    color_out = term.should_color(sys.stdout)
    label = _status("preview", color=color_out)
    # Collects every distinct face this whole call resolves, across every
    # device and (with --all-styles) every panel, so the stand-in warning
    # below fires once per run rather than once per device.
    used_faces: dict[FontMetric, fonts.fallback.SystemFace] = {}
    try:
        for device_id, result in resolved.items():
            # Every mode produces one image, a file-name suffix and a note;
            # where the image goes is decided once, below, for all of them.
            note = f"{result.device.width}x{result.device.height} at {args.scale}x"
            if heatmap:
                image, peak = render_aod_heatmap(result, options, used_faces=used_faces)
                suffix = "--heatmap"
                note += f", max {peak * 100:.1f}% of minutes any one pixel was lit"
            elif all_styles:
                image = render_all_styles(result, options, used_faces=used_faces)
                suffix = "--all-styles"
            else:
                image = render(result, options, used_faces=used_faces)
                suffix = ""
            if style is not None:
                suffix = f"--{style}{suffix}"
            if args.skin and has_skin(result.device):
                suffix += "--skin"
                note += ", in the simulator skin"
            if to_stdout:
                image.save(sys.stdout.buffer, format="PNG")
                sys.stdout.buffer.flush()
                continue
            path = save(image, args.output / f"{device_id}{suffix}.png")
            if not quiet:
                print(f"{label}    {path}  ({note})", flush=True)
    except UnknownStyleError as exc:
        _error(str(exc))
        return 1, watched
    # Not suppressed by -q/-o -: those silence stdout progress, and a
    # wrong typeface is a correctness warning, not progress.  Always to
    # stderr, always after every device/panel has had a chance to record a
    # face, so it names everything the whole run drew with, not just the
    # first device.
    warning = preview_stand_in_warning(used_faces)
    if warning:
        print(warning, file=sys.stderr)
    mono = mono_guess_warning((r.device for r in resolved.values()), options.quantise)
    if mono:
        print(mono, file=sys.stderr)
    bare = skin_missing_warning((r.device for r in resolved.values()), options.skin)
    if bare:
        print(bare, file=sys.stderr)
    if blurb and not quiet:
        print()
        for line in (
            "Rendered from the same resolved geometry the generated code uses, so the",
            "two cannot disagree about position.  Glyph rendering and arc caps are",
            "approximations -- the simulator is authoritative for those.",
        ):
            print(term.style(line, "dim", enabled=color_out))
    return 0, watched


def _preview(args: argparse.Namespace) -> int:
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
    element) at that time instead of the sample 10:09:42. `--asleep` hides
    every `awake`-only second hand, simulating a sleeping glance, on any
    device shape, with no mode switch. `--aod` renders the AMOLED always-on-display frame -- the
    resolved `aod:` set, restyled -- and implies `--asleep` too, the same
    choice the generated `_aod` branch makes. `--minute N`
    (0-1439) is `--time` given as a minute of the day. `--heatmap` implies
    `--aod`, renders every minute of the day and sums them into one PNG in
    which a pixel lit every minute is white, printing the largest share of
    minutes any one pixel was lit -- a stand-in for the simulator's Screen
    Heat Map. It takes `--style`, but not `--all-styles`, `--time` or
    `--minute`. `--units metric|statute` sets the watch's unit settings a
    `units: auto` element follows (metric by default).

    `--skin` draws the watch round the screen: the render is set into the
    simulator skin, the watch image the device files ship, on any mode.
    The skin is optional: a device whose files lack it renders the bare
    screen, as without the flag, and one warning names it.

    Every mode writes
    `<device>[--<style>][--all-styles|--heatmap][--skin].png` under `-o`,
    or its one image to stdout with `-o -`.

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
    # `fonts_root=args.fonts_dir` is the same value `_render_preview` below
    # hands `PreviewOptions.fonts_root` -- one CLI flag, so the geometry this
    # resolves (`Device.fonts_root`, what `wfb.layout` measures with) and
    # what the render then draws with can never come from two different
    # roots.
    db = DeviceDatabase.discover(args.devices_dir, fonts_root=args.fonts_dir)
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


def _simulate(args: argparse.Namespace) -> int:
    """launch the Connect IQ simulator and push a built face to it

    Builds the design (like `wfb build`), starts the simulator if it is not
    already running, and pushes the build for `-d`, or the first target,
    with `monkeydo`. On macOS, where this works, the simulator is the SDK's
    `ConnectIQ.app`, opened for you. Other systems are untested; on Linux
    the simulator needs a display (`DISPLAY`), and in a container it
    crashes as soon as an app is pushed to it (docs/limitations.md), which
    is the gap `wfb preview` covers.

    The command returns once the face is running. `monkeydo` stays behind,
    writing the face's console output (`System.println`) to `simulator.log`
    beside the built .prg, until the face is replaced or the simulator is
    closed. `-f/--follow` also prints it here, until Ctrl-C, which leaves
    the face running.

    `--screenshot` captures the simulator window to a PNG once the face is
    running. On macOS the terminal needs the Screen Recording permission.
    """
    bag = Bag()
    toolchain = Toolchain.discover(args.sdk, args.key)
    result = run_build(
        args.design,
        output=args.output,
        bag=bag,
        devices_only=[args.device] if args.device else None,
        db=DeviceDatabase.discover(args.devices_dir),
        toolchain=toolchain,
        compile_prg=True,
    )
    bag.print(verbose=args.verbose)
    if toolchain is None or result is None or not result.products:
        print("\nnothing to run -- the build produced no .prg", file=sys.stderr)
        return 1

    device_id = args.device or result.devices[0].id
    prg = result.products.get(device_id)
    if prg is None:
        print(f"\nno build for {device_id}", file=sys.stderr)
        return 1

    try:
        session = push(toolchain, prg, device_id)
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
            path, note = screenshot(args.screenshot)
            print(f"{_status('screenshot', color=color_out)} {path}")
            if note:
                print(f"  {note}", file=sys.stderr)
        except (SimulatorError, OSError, subprocess.CalledProcessError) as exc:
            print(f"screenshot failed: {exc}", file=sys.stderr)
            return 1
    if not args.follow:
        print(f"console output: {session.log}")
        return 0
    print("following the face's console output (Ctrl-C to stop)", flush=True)
    try:
        for chunk in session.follow():
            print(chunk, end="", flush=True)
    except KeyboardInterrupt:
        print(f"\nstopped following; the face is still running, and its output "
              f"still goes to {session.log}")
    return 0


def _studio(args: argparse.Namespace) -> int:
    """edit faces in the browser: a local web app

    Serves the visual editor on http://127.0.0.1:8765/ until Ctrl-C. Open
    that address in a browser to create a face from a template or open one
    (a .zip with face.yaml and assets/, or a plain .yaml), edit it, and
    download it to save. In the container, publish the port to the host's
    loopback (`docs/container.md`).

    Every face's history is kept under `--state-dir`, outside the
    temporary directories the editor builds faces in, so closing the tab
    or stopping the server loses nothing: every change is recorded as it is
    made, so undo and redo survive a restart, and a changed face is
    snapshotted every `--snapshot-minutes` and on every download. A face is
    kept until it is deleted from the home screen; on start, each keeps its
    newest `--keep-snapshots` snapshots.

    A face is opened from the editor's home screen, never from the command
    line. `--host` other than loopback warns, since the server writes files.

    Each browser has its own faces, kept by a cookie. The address printed
    on start carries a one-time claim: the browser that opens it gets every
    face made before faces had owners. Another
    browser joins with a link from **Use my faces in another browser** on
    the home screen. `--single-user` gives every browser the same faces.
    Only requests addressed to a loopback name, `--host` or an
    `--allow-host` name are answered.
    """
    from .studio import serve
    from .studio.store import StoreError, default_root

    try:
        db = DeviceDatabase.discover(args.devices_dir, fonts_root=args.fonts_dir)
    except DeviceError as exc:
        _error(str(exc))
        return 1
    try:
        if args.snapshot_minutes <= 0 or args.keep_snapshots < 1:
            _error("--snapshot-minutes must be positive, --keep-snapshots at least 1")
            return 1
        serve(host=args.host, port=args.port, state_dir=args.state_dir or default_root(),
              db=db, snapshot_minutes=args.snapshot_minutes,
              keep_snapshots=args.keep_snapshots,
              single_user=args.single_user, allow_hosts=args.allow_host)
    except StoreError as exc:
        _error(str(exc))
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _new(args: argparse.Namespace) -> int:
    """start a design from a known-good template

    Copies one of the bundled templates (`--list` shows them, with a
    one-line blurb each) to a new YAML file, substituting a fresh UUID and
    the given name. Two faces sharing a UUID are the same app to the watch
    -- installing the second replaces the first -- so every call mints its
    own.
    """
    from . import starters

    templates = starters.names()
    if args.list_templates:
        for name in templates:
            print(f"  {name:<12} {starters.TEMPLATE_BLURB.get(name, '')}")
        return 0

    if not args.name:
        _error("a face name is required")
        print(f"       usage: wfb new \"My Face\" [--template {'|'.join(templates)}]",
              file=sys.stderr)
        return 1

    if args.template not in templates:
        _error(f"no template {args.template!r}")
        print(f"       available: {', '.join(templates)}", file=sys.stderr)
        return 1

    destination = args.output or Path(f"{slug(args.name)}.yaml")
    if destination.exists():
        _error(f"{destination} already exists")
        return 1

    text = starters.instantiate(args.template, args.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")

    print(f"created {destination}  (from the {args.template!r} template)")
    print()
    print("next:")
    print(f"  wfb preview {destination} --watch     # render as you edit")
    print(f"  wfb build   {destination}             # compile it")
    return 0


#: How far `wfb doctor`'s explanatory lines are indented: past the status
#: marker and the name column, under the detail.
_DOCTOR_INDENT = " " * 19


def _doctor_system_fonts(device_ids: list[str], devices_root: Path, fonts_root: Path | None,
                         *, ok: str, absent: str, hint: Callable[..., None]) -> None:
    """Print `wfb doctor`'s one-line system-font summary over every installed
    device: where each distinct font name a device needs would come from,
    and which devices still lack a stand-in. Never downloads, never blocks --
    a missing name falls back to a substitute face."""
    fetch_system = fonts.fetch_system
    # "unmapped" is a deliberate registry decision (a CJK/RTL-only face),
    # not something an install could fix, so it never counts as missing.
    tier_of: dict[str, str] = {}
    lacking: list[str] = []
    for device_id in device_ids:
        device_missing = False
        for name, face in fetch_system.device_needed_names(device_id, devices_root=devices_root):
            if name not in tier_of:
                # `garmin_any_file` counts a `.cft` bitmap hit as usable too --
                # the same lookup `fetch_system.locate` uses, so this summary
                # and the measure/preview path agree on what counts as "found".
                if fonts_root is not None and fetch_system.garmin_any_file(name, fonts_root):
                    tier_of[name] = "garmin"
                else:
                    key = fetch_system.resolve(name, face)
                    tier_of[name] = ("unmapped" if key is None
                                     else fetch_system.tier_for(key) or "missing")
            device_missing |= tier_of[name] == "missing"
        if device_missing:
            lacking.append(device_id)
    counts = Counter(tier_of.values())
    summary = ", ".join(f"{counts[label]} {label}"
                        for label in ("garmin", "installed", "cached", "missing", "unmapped")
                        if counts[label])
    if not lacking:
        print(f"{ok} system fonts     all {len(device_ids)} devices covered ({summary} font names)")
        return
    shown = ", ".join(lacking[:4]) + (" ..." if len(lacking) > 4 else "")
    print(f"{absent} system fonts     {len(lacking)} of {len(device_ids)} devices lack a "
          f"stand-in: {shown}")
    hint(f"({summary} font names) -- run python3 tools/fetch-system-fonts.py;",
         "not blocking, falls back to a substitute face at build time")


def _doctor(args: argparse.Namespace) -> int:
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

    def hint(*lines: str) -> None:
        for line in lines:
            print(_DOCTOR_INDENT + line)

    def fail(fix: str, *hints: str, blocks: bool = True) -> None:
        """Explain a missing piece and record ``fix`` for the verdict."""
        nonlocal blocking
        hint(*hints)
        problems.append(fix)
        blocking += blocks

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
            fail(f"pip install {package}")

    print(f"{ok if SCHEMA_PATH.exists() else missing} schema           {SCHEMA_PATH}")

    # -- the SDK device reference (generated from the SDK, never committed) --
    have_reference = DEVICE_REFERENCE.is_dir()
    print(f"{ok if have_reference else missing} device reference {DEVICE_REFERENCE.parent}")
    if not have_reference:
        fail("generate the SDK device reference",
             "run tools/setup-env.sh, or python3 tools/extract-device-reference.py")

    # -- the icon font ----------------------------------------------------
    have_icons = icons.FONT_PATH.is_file()
    print(f"{ok if have_icons else missing} icon font        {icons.FONT_PATH}")
    if not have_icons:
        fail("install the icon font",
             "run tools/setup-env.sh, or python3 tools/fetch-icon-font.py")

    # -- Garmin's own font files (optional; outrank the registry when found) --
    # Never triggers a download: doctor only reports what is already there.
    # Both branches state the *consequence* of the finding: what an absence
    # costs is `wfb preview` drawing every non-exact-matched face with a
    # stand-in typeface (`wfb.preview.stand_in_warning` says which ones).
    fetch_system = fonts.fetch_system
    fonts_root = fetch_system.garmin_font_root(args.fonts_dir)
    if fonts_root is not None:
        print(f"{ok} Garmin fonts     {fonts_root}  (previews draw exact glyph shapes)")
    else:
        print(f"{absent} Garmin fonts     not found (optional; previews draw stand-in "
              "typefaces for any face the registry has no exact match for)")
        if os.environ.get("WFB_CONTAINER") == "1":
            # vendor/ never reaches the image (.dockerignore): a mount is the
            # only way in, at the WFB_FONTS the Dockerfile sets.
            mount = os.environ.get("WFB_FONTS") or "/fonts"
            hint("mount the SDK Manager's Fonts directory:",
                 f"  -v <SDK Manager's Fonts dir>:{mount}:ro",
                 "-- see docs/container.md")
        else:
            hint("copy the SDK Manager's Fonts directory into vendor/fonts/,",
                 "or set WFB_FONTS / pass --fonts DIR -- see docs/container.md")

    # -- device definitions -----------------------------------------------
    try:
        db = DeviceDatabase.discover(args.devices_dir)
        ids = db.ids()
        print(f"{ok} devices          {len(ids)} installed: {', '.join(ids[:4])}"
              f"{' ...' if len(ids) > 4 else ''}")
        hint(str(db.root))
        _doctor_system_fonts(ids, db.root, fonts_root, ok=ok, absent=absent, hint=hint)
    except DeviceReferenceMissing:
        print(f"{absent} devices          not checked: the device reference above is missing")
    except DeviceError:
        print(f"{missing} devices")
        fail("install the device definitions",
             "they cannot be downloaded -- api.gcs.garmin.com returns HTTP 401.",
             "copy them from a machine where the Connect IQ SDK",
             "Manager has installed them:",
             "  macOS  ~/Library/Application Support/Garmin/ConnectIQ/Devices",
             "  Linux  ~/.Garmin/ConnectIQ/Devices",
             "then set WFB_DEVICES to that directory.")

    # -- the Garmin toolchain ---------------------------------------------
    can_compile = False
    toolchain = Toolchain.discover()
    if toolchain is None:
        print(f"{missing} Connect IQ SDK")
        fail("install the Connect IQ SDK", "set CIQ_SDK, or run tools/setup-env.sh",
             blocks=False)
    else:
        print(f"{ok} Connect IQ SDK   {toolchain.version}  ({toolchain.sdk})")
        extracted = reference_sdk_version()
        if extracted is not None and extracted != toolchain.version:
            print(f"{missing} device reference extracted from SDK {extracted}")
            fail("extract the device reference from this SDK",
                 "run tools/setup-env.sh, or python3 tools/extract-device-reference.py",
                 blocks=False)
        key_dir = toolchain.key.parent
        can_compile = True
        if toolchain.key.exists():
            print(f"{ok} developer key    {toolchain.key}")
        elif os.access(key_dir, os.W_OK):
            # Not missing: the first build that needs a key creates it, and a
            # build is what a caller is usually about to run.
            print(f"{ok} developer key    will be generated at {toolchain.key}")
        else:
            can_compile = False
            print(f"{missing} developer key    expected at {toolchain.key},")
            fail("generate a developer key",
                 f"and {key_dir} is not writable.  Create one with:",
                 "  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \\",
                 "    -out key.pem",
                 "  openssl pkcs8 -topk8 -inform PEM -outform DER \\",
                 f"    -in key.pem -out {toolchain.key} -nocrypt",
                 blocks=False)

    # -- verdict -----------------------------------------------------------
    print()
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


def _schema(args: argparse.Namespace) -> int:
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


def _devices(args: argparse.Namespace) -> int:
    """list installed device definitions

    Reads the device files (`~/.Garmin/ConnectIQ/Devices` by default; see
    `--devices-dir`/`WFB_DEVICES`) and prints each device's screen, shape,
    display type, colour count, API level and watch-face memory limit. These
    files cannot be downloaded unauthenticated -- run `wfb doctor` for how
    to get them onto this machine.
    """
    db = DeviceDatabase.discover(args.devices_dir)
    color_out = term.should_color(sys.stdout)
    header = (f"{'id':<24} {'screen':<12} {'shape':<12} {'display':<8} "
              f"{'colors':<7} {'api':<8} {'watch face':<10} family")
    print(term.style(header, "bold", enabled=color_out))
    for device_id in db.ids():
        device = db.get(device_id)
        limit = f"{device.watchface_memory_limit // 1024} KB" if device.supports_watchface else "-"
        colors = str(device.display_colors) if device.display_colors else "?"
        print(f"{device.id:<24} {device.width}x{device.height:<8} {device.shape:<12} "
              f"{device.display_type:<8} {colors:<7} {device.api_level:<8} {limit:<10} "
              f"{device.device_family}")
    return 0


def _dim(text: str, *, color: bool) -> str:
    """Style ``text`` the muted way every "none"/"not published" line in
    `wfb fonts` uses -- centralised so the summary and detailed views cannot
    drift on how they grey out an absence."""
    return term.style(text, "dim", enabled=color)


#: The vector-text entry points `wfb fonts` reports, by the name it prints.
_VECTOR_GATES = (
    ("getVectorFont", Device.VECTOR_FONT_SYMBOL),
    ("drawRadialText", Device.DRAW_RADIAL_TEXT_SYMBOL),
    ("drawAngledText", Device.DRAW_ANGLED_TEXT_SYMBOL),
)


def _print_all_device_fonts_summary(db: DeviceDatabase) -> None:
    """Print every installed device's id, vector-text API gates, scalable
    (vector) faces and system (bitmap) font symbols, one paragraph each.

    A device that cannot run a watch face at all (`Device.supports_
    watchface`) gets a one-line note instead of font data -- there is
    nothing to show. A device that publishes scalable faces but lacks
    `Graphics.getVectorFont` says so explicitly rather than listing them as
    usable: without that symbol, nothing in `face.yaml` can reach them.
    """
    color_out = term.should_color(sys.stdout)
    device_ids = db.ids()
    if not device_ids:
        print("no installed devices found")
        return

    for i, device_id in enumerate(device_ids):
        if i > 0:
            print()
        device = db.get(device_id)
        title = term.style(device.id, "bold", enabled=color_out)
        meta = f"({device.width}x{device.height} {device.shape}, CIQ {device.api_level})"
        print(f"{title} {meta}")

        if not device.supports_watchface:
            print("  cannot run a watch face")
            continue

        gates = [name for name, symbol in _VECTOR_GATES if device.has_symbol(symbol)]
        has_vector = "getVectorFont" in gates
        gates_str = ", ".join(gates) if gates else _dim("none", color=color_out)
        print(f"  vector text:   {gates_str}")

        if device.scalable_faces and has_vector:
            count = len(device.scalable_faces)
            label = f"  scalable ({count}): "
            print(textwrap.fill(label + ", ".join(device.scalable_faces), width=88,
                                subsequent_indent="    "))
        elif device.scalable_faces:
            count = len(device.scalable_faces)
            print(f"  scalable:      {_dim('none', color=color_out)} usable "
                  f"({count} published, no Graphics.getVectorFont)")
        else:
            print(f"  scalable:      {_dim('none', color=color_out)} (no vector fonts)")

        if device.system_fonts:
            count = len(device.system_fonts)
            symbols_str = ", ".join(
                f"{m.symbol} ({m.size_px}px)" for m in device.system_fonts.values())
            label = f"  system ({count}):   "
            print(textwrap.fill(label + symbols_str, width=88, subsequent_indent="    "))
        else:
            print(f"  system:        {_dim('none', color=color_out)}")

    hint = term.style(
        "\nrun `wfb fonts <device>` for full metrics and font files for a specific device",
        "dim",
        enabled=color_out,
    )
    print(hint)


def _print_device_fonts_detailed(device: Device) -> None:
    """Print one device's full font breakdown: scalable (vector) faces with
    their `Graphics.getVectorFont`/`curve:` gating, then system (bitmap)
    font symbols with their measured metrics.

    A device that cannot run a watch face at all prints only the header and
    a one-line note. Otherwise, the scalable section states not just
    whether `Graphics.getVectorFont` exists but which of `Dc.drawRadialText`
    /`Dc.drawAngledText` it can pair with -- getVectorFont alone does not
    promise either, so a `curve:` element needs the gate checked
    independently -- and the face table is only shown as usable when
    getVectorFont itself is present.
    """
    color_out = term.should_color(sys.stdout)
    title = term.style(device.id, "bold", enabled=color_out)
    parts = [f"{device.width}x{device.height} {device.shape}", f"CIQ {device.api_level}"]
    if device.display_type:
        parts.append(device.display_type.upper())
    if device.display_colors:
        parts.append(f"{device.display_colors} colors")
    print(f"{title} ({', '.join(parts)})")

    if not device.supports_watchface:
        print()
        print("  cannot run a watch face")
        return

    has_vector = device.has_symbol(Device.VECTOR_FONT_SYMBOL)
    has_radial = device.has_symbol(Device.DRAW_RADIAL_TEXT_SYMBOL)
    has_angled = device.has_symbol(Device.DRAW_ANGLED_TEXT_SYMBOL)

    print()
    scal_header = term.style(
        f"Scalable (vector) fonts ({len(device.scalable_faces)}):",
        "bold",
        enabled=color_out,
    )
    print(scal_header)
    if has_vector:
        if has_radial and has_angled:
            print("  Graphics.getVectorFont: yes (Dc.drawRadialText, Dc.drawAngledText)")
        elif has_radial:
            print("  Graphics.getVectorFont: yes; curve: {style: radial} available "
                  "(Dc.drawRadialText); angled unavailable (no Dc.drawAngledText)")
        elif has_angled:
            print("  Graphics.getVectorFont: yes; curve: {style: angled} available "
                  "(Dc.drawAngledText); radial unavailable (no Dc.drawRadialText)")
        else:
            print("  Graphics.getVectorFont: yes, but curve: (radial/angled text) is "
                  "unavailable on this device")
        print("  Use in face.yaml: under 'fonts:' with 'face: [<name>, ...]' "
              "(required for radial/angled text)")
    else:
        print("  Graphics.getVectorFont: not available on this device")

    if device.scalable_faces and has_vector:
        print()
        col_hdr = f"  {'Face Name':<32} {'File / Stem':<30}".rstrip()
        print(term.style(col_hdr, "bold", enabled=color_out))
        print(f"  {'-' * 30:<32} {'-' * 28:<30}".rstrip())
        for face in device.scalable_faces:
            stem = device.scalable_face_files.get(face, "-")
            print(f"  {face:<32} {stem:<30}".rstrip())
    elif device.scalable_faces:
        count = len(device.scalable_faces)
        print(f"  {_dim('none usable', color=color_out)} ({count} published, "
              "no Graphics.getVectorFont)")
    else:
        print(f"  {_dim('none (no vector fonts published)', color=color_out)}")

    print()
    sys_header = term.style(
        f"System fonts ({len(device.system_fonts)}):",
        "bold",
        enabled=color_out,
    )
    print(sys_header)
    print("  Use in face.yaml: directly as 'font: <symbol>' (e.g. font: FONT_SMALL)")
    if device.system_fonts:
        print()
        col_hdr = (f"  {'Symbol':<24} {'Line Height':<12} {'Em Size':<10} "
                  f"{'File / Stem':<28} {'Face Name':<20}").rstrip()
        print(term.style(col_hdr, "bold", enabled=color_out))
        dashes = (f"  {'-' * 22:<24} {'-' * 11:<12} {'-' * 8:<10} "
                 f"{'-' * 26:<28} {'-' * 18:<20}").rstrip()
        print(dashes)
        for m in device.system_fonts.values():
            em_str = f"{m.em_px:.1f} px" if m.em_px is not None else "-"
            sz_str = f"{m.size_px} px"
            row = f"  {m.symbol:<24} {sz_str:<12} {em_str:<10} {m.font:<28} {m.face:<20}"
            print(row.rstrip())
    else:
        print(f"  {_dim('none recorded in reference database', color=color_out)}")


def _fonts(args: argparse.Namespace) -> int:
    """list fonts available per device, or a detailed font breakdown for one or more

    With no device named, lists every installed device definition alongside
    its scalable (vector) faces, system (bitmap) font symbols, and which of
    `Graphics.getVectorFont`/`Dc.drawRadialText`/`Dc.drawAngledText` it
    publishes -- a face is only usable when `Graphics.getVectorFont` itself
    is present, called out explicitly whenever a device publishes faces
    without it.

    Naming one or more devices -- as positional arguments, `-d/--device`
    (repeatable), or both mixed together, merged in the order given and
    de-duplicated -- prints a detailed breakdown for each instead (e.g. `wfb
    fonts fenix8solar47mm fr955`), separated by a blank line:
      * Scalable (vector) fonts -- faces published to `Graphics.getVectorFont`
        (for use in `face.yaml` under `fonts:` with `face: [...]`), plus
        which of `curve: {style: radial|angled}` the device can pair it
        with, since getVectorFont alone does not guarantee either;
      * System (bitmap) fonts -- `Graphics.FONT_*` symbols, their exact line
        heights (`size_px`), em sizes, file stems, and face names.

    A device that cannot run a watch face at all (`wfb devices`) is named
    with a one-line note instead of font data, in either view. Naming an
    unknown device is a clean error (`wfb devices` lists what is installed)
    and nothing is printed, even when an earlier name on the command line
    is valid -- every name is resolved before anything is shown.
    """
    db = DeviceDatabase.discover(args.devices_dir)
    names: list[str] = []
    for name in list(args.devices) + list(args.device_flags or []):
        if name not in names:
            names.append(name)

    if not names:
        _print_all_device_fonts_summary(db)
        return 0

    # Resolve every name before printing anything, so a typo in the second
    # name cannot leave the first device's output already on stdout.
    devices = [db.get(name) for name in names]
    for i, resolved in enumerate(devices):
        if i > 0:
            print()
        _print_device_fonts_detailed(resolved)
    return 0


#: The colours a design declares, listed by `wfb sources` after the
#: catalogue: declared per design, not read from a device API, so not in
#: `wfb.catalog`.
_CONFIG_SOURCES = (
    ("color.<swatch>", "color",
     "a 'resources: palette:' swatch, fixed at build time"),
    ("color.<role>", "color",
     "a 'theme: schemes:' role, following the active 'config: style:' entry's "
     "'scheme:' (<styles>, Settings.styleId)"),
    ("color.accent", "color",
     "the role the one accent-colour axis binds, 'config: accent_color:' "
     "(<accentColors>, Settings.accentColor); 'role:' renames it"),
    ("color.data", "color",
     "the role the one data-colour axis binds, 'config: data_color:' "
     "(<dataColors>, Settings.complicationColor); 'role:' renames it"),
)


def _sources(args: argparse.Namespace) -> int:
    """list the data-source catalogue: every value a design may bind

    For each source: its type, whether it is nullable, any permission
    binding it implies, its conventional `on_hold: auto` launch target (if
    it has one), and the SDK page it was taken from. Every read is a plain
    per-frame read now -- there is no refresh-tier concept left to show.
    This is the authoritative, always-current list -- never bind a path
    that is not listed here, and never trust a copy of this list pasted
    into prose, which goes stale the moment the catalogue grows.

    Also lists the `color.*` names -- palette swatches, scheme roles that
    follow Styles, and the native on-device colour axes' roles -- even
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
          "'config:' -- fēnix 8 Solar's native editor only, see docs/guide/configuration.md)")
    for path, kind, doc in _CONFIG_SOURCES:
        print(f"  {path:<34} {kind:<8} {doc}")
    print(f"\nicons: {', '.join(icons.names())}")
    print("\nrun `wfb complications` for the full list of on_hold: targets")
    return 0


def _complications(args: argparse.Namespace) -> int:
    """list the complication type table: what `on_hold:` may launch, what
    `complication.*` may read, and what a `config: slots:` slot may show

    A watch face cannot open an arbitrary app. The platform offers exactly
    one exit -- `Complications.exitTo`, "launches the app associated with
    the complication" -- so an interactive element names a complication
    type and the watch opens whichever glance or app owns it. The same 42
    types are also readable directly as `complication.<name>` data sources
    (see `wfb sources`), and are what a `config: slots:` slot's own
    `default:`/`choices:` name -- this is the one table all three draw from.

    Printed for each, grouped as the editor lists them: the name a design
    writes, its name for people, the catalogue icon a `data` element's
    `icon:` draws for it by default (`wfb.icons.COMPLICATION_ICON`; a slot's
    `choices:` mapping-form entry can override this per design), the Monkey C
    constant it compiles to, and the API level, when it is later than the
    others'. An API level is not a promise the watch has it; a hold on a
    type the watch does not know simply does nothing, which is why `wfb
    validate` also checks each target's own symbol table (and, for a slot,
    each target's own ConnectIQ ceiling -- see `api-gated` in
    docs/guide/configuration.md).

    Binding one of these -- as `on_hold:`, as `complication.<name>`, or via
    `on_hold: auto` -- adds the ComplicationSubscriber permission
    automatically, the same way a data binding derives its own
    requirements. A `config: slots:` slot does too, even though it reads no
    catalogue source directly. A target that lacks `Toybox.Complications`
    (fenix6 and fr245, among the installed devices) has the generated code
    guard every use of it at runtime (`wfb.availability`), so the binding
    simply reads as absent there.
    """
    names = complications.names()
    width = max(len(name) for name in names)
    label_width = max(len(complications.label(name)) for name in names)
    icon_width = max(len(icons.COMPLICATION_ICON.get(name, "")) for name in names)
    for group in complications.CATEGORIES:
        print(f"{group}:")
        for name in (n for n in names if complications.category(n) == group):
            entry = complications.TYPES[name]
            since = "" if entry.since == complications.EXIT_TO_API_LEVEL else f"  (since {entry.since})"
            icon_name = icons.COMPLICATION_ICON.get(name, "")
            print(f"  {name:<{width}}  {complications.label(name):<{label_width}}  "
                  f"icon: {icon_name:<{icon_width}}  Complications.{entry.constant}{since}")
    print(f"\n{len(complications.TYPES)} complication types. "
          f"Use one as `on_hold:` on any element:")
    print("  hr:\n    type: icon\n    icon: heart\n    on_hold: heart_rate")
    print("\n...or let the compiler pick one from the element's own value binding:")
    print("  hr:\n    type: icon\n    icon: heart\n    on_hold: auto")
    return 0


def _series(args: argparse.Namespace) -> int:
    """list the time-series catalogue: every `series:` a `graph` element may plot

    A `graph` plots a series, not a scalar -- a different kind of binding
    from `wfb sources`' data-source catalogue, acquired and cached on-device
    rather than read fresh every frame (`docs/guide/progress-and-graphs.md`'s `graph` section).
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
    print("    hr_graph:\n      type: graph\n      series: heart_rate\n"
          "      range: 4h\n      style: line\n      color: color.accent")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
