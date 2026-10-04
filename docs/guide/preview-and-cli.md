# Preview and the command line

`wfb preview` renders a design to a PNG on your computer, with no simulator
and no watch needed, so you can see a change before you build. The rest of
`wfb`'s subcommands validate, build, inspect and sideload a face; this
chapter lists every one of them, and the specific ways a preview differs
from what the watch itself shows.

## Running `wfb`

There is no installed `wfb` command. `wfb` in these docs means `wfb.py` at the
repository root. It is executable, and it re-runs itself under the project's
`.venv` when the Python that started it lacks the dependencies. That means an
alias works from any directory, with no venv to activate:

```sh
alias wfb="/path/to/garmin-wf-builder/wfb.py"
```

`./.venv/bin/python wfb.py …` is the same thing, spelled out. In the Docker
image, `wfb` is a real command and is the entrypoint. On a Mac, alias it to the
whole `docker run …` line ([Step 2: install](getting-started.md#step-2-install)), and run it from the folder that
holds your face, because the container sees only the directory mounted at
`/work`.

## Commands

`wfb help <command>` (or `wfb <command> help`, or `wfb <command> --help`) is
authoritative for a command's own flags. One line each, taken from `wfb
--help`:

| Command | What it does |
|---|---|
| `build` | validate, generate and compile a design into a sideloadable .prg |
| `validate` | validate a design without generating or compiling anything |
| `preview` | render the design to a PNG on the host, with no simulator |
| `simulate` | launch the Connect IQ simulator and push a built face to it |
| `new` | start a design from a known-good template |
| `studio` | edit faces in the browser: a local web app |
| `devices` | list installed device definitions |
| `fonts` | list fonts available per device, or a detailed font breakdown for one or more |
| `doctor` | check the environment and say what is missing |
| `schema` | print the JSON Schema, or where it lives, for editor setup |
| `sources` | list the data-source catalogue: every value a design may bind |
| `complications` | list the complication type table: what `on_hold:` may launch, what `complication.*` may read, and what `config: data:` may offer a slot |
| `series` | list the time-series catalogue: every `series:` a `graph` element may plot |
| `help` | show help for wfb, or for one command |

```sh
wfb new       "My Face" [-t TEMPLATE] [--list]   # start from a known-good template
wfb studio    [-p PORT]            # the editor, on http://127.0.0.1:8765/
wfb build     design.yaml [-d DEVICE] [-o DIR] [-j N] [--no-compile] [--profile [REPS]]
wfb validate  design.yaml [-d DEVICE]  # everything except codegen; no toolchain needed
wfb preview   design.yaml [-d DEVICE] [--watch] [--skin] [-q] [-o -]  # render to PNG; no simulator
wfb simulate  design.yaml [-d DEVICE] [-f] [--screenshot PNG]  # run it in the simulator
wfb devices                        # installed device definitions and their limits
wfb fonts     [DEVICE ...] [-d DEVICE]  # fonts per device: scalable (vector) and system (bitmap)
wfb sources                        # the data-source catalogue, and the icon names
wfb complications                  # what an element's `on_hold:` may launch
wfb schema    [--path]             # the JSON Schema, for editor setup
wfb doctor                         # what is installed, what is missing, what to do
wfb help      [command]            # every command's own help, from its own docstring
```

`-d DEVICE` (repeatable) replaces the design's `targets:` with the devices
named. It accepts any installed device (`wfb devices`), not only a listed
target; an unlisted one draws a `target` note, and the generated manifest
lists exactly the devices asked for.

`wfb build` compiles the devices in parallel: one `monkeyc` per device, at
most one per CPU and at most four at once. `-j N` sets the limit, and `-j 1`
compiles one device at a time. Each `monkeyc` is its own Java process, so
lower it on a machine short of memory. The diagnostics come out in device
order however the runs interleave.

**Notes are one line each.** `build`, `validate`, `preview` and `simulate`
print a note (a measured memory figure, the static buffer's share of the
graphics pool) as its one header line; `-v`/`--verbose` prints it in full,
with its source line and details, as warnings and errors always are. A
successful `wfb build` leaves out each built watch's memory note, since
its `built` line gives the same figure.

`wfb preview` draws the face at the watch's own resolution, then enlarges
it `--scale` times (default 2) with each watch pixel as a square block, so
a jagged diagonal or a thin ring looks as it will on the panel, never
smoother. Only the skin round the screen (`--skin`) is resized smoothly.

`wfb preview -o -` (or `-o --`) writes **one** PNG — the device `-d` names, or
the design's first target — to stdout instead of to files, and prints nothing
else, so a face can go straight into a terminal image viewer:

```sh
wfb preview my-face.yaml -o -- | chafa
```

`-q/--quiet` alone keeps the files and silences stdout; either way warnings
and errors still go to stderr.

`wfb preview --skin` draws the watch round the screen: the render is set
into the simulator's own picture of the device (its *skin*, which ships in
the device files), where the simulator shows the screen, and written as
`<watch>--skin.png`. It works with every other preview flag, including
`--all-styles` and `--heatmap`:

```sh
wfb preview my-face.yaml --skin -d fr955
```

The skin is optional. If a device's files don't include it, that device
renders the bare screen, as it would without `--skin`, under its usual
file name, and one warning names it. Around the watch, the image keeps the
skin's own background, which is white on most devices.

`wfb simulate` builds the design, starts the Connect IQ simulator if it is
not already running (on macOS it opens the SDK's `ConnectIQ.app`), and loads
the face into it. It works on macOS; other systems are untested, and in a
Linux container the simulator crashes when the face is loaded
([limitations](../limitations.md#the-simulator-crashes-when-an-app-is-pushed)). It returns once the face is
running. The face's console output (`System.println`) keeps going to
`simulator.log` beside the built `.prg`; `-f/--follow` prints it in the
terminal too, until Ctrl-C, which leaves the face running. `--screenshot
face.png` captures the simulator window. On macOS that needs the terminal to
have the Screen Recording permission (System Settings → Privacy & Security),
or the capture shows only the desktop.

`wfb help <command>` and `wfb <command> help` print the same thing as
`wfb <command> --help`.

The quickest start:

```sh
wfb new "My Face"
wfb preview my-face.yaml --watch   # leave this running while you edit
```

`wfb preview` renders from the **same resolved geometry** the generated Monkey C
uses, so the two cannot disagree about position — which is what makes it a useful
check and not a second implementation. A visual GUI builder is not built; if it is,
it will be a thin client over the preview.

## Profiling

`wfb build --profile` builds a face that measures itself on the watch.
It is a build for measuring, not for wearing.

- **Draw time, on the watch.** Each frame times one element: it draws it
  `REPS` times in a row (10 by default) between two reads of the watch's
  millisecond timer, and adds the result to that element's running total.
  The next frame times the next element. The average per call, in
  microseconds, appears above each element. It sharpens the longer the face
  runs, as the timer's rounding averages out.
- **The header line** shows the last frame's time in milliseconds, the
  app's memory in KiB (used / available), and the empty-loop baseline.
  That baseline is the timing overhead, already subtracted from every
  reading.
- **Groups.** An outlined group's ring pass is timed as an entry of its own.
- **Layouts.** Only the layout on screen is timed and shown, so a face with
  several layouts compares them one at a time: switch with the style
  setting.
- **Static content.** The static buffer is off in a profiled build, so
  static elements are drawn live every frame and timed like the rest.
- **Code size, at build time.** After compiling, the build prints each
  element's code in bytes and each layout's total, measured from the
  `.prg.debug.xml` that `monkeyc` writes. The same table is saved as
  `profile.txt` in the build directory.

Only the active frame is instrumented, not the always-on frame or a partial
update. The simulator's timings are the host's, not the watch's: sideload
to measure.

[`examples/features/profile/face.yaml`](../../examples/features/profile/face.yaml)
is built for this. It draws the same sixteen drawables three times, in
layouts with no `outline:`, a 1 px ring and a 2 px ring; its text is once in
a baked font and once in a system font, so both ring paths are timed. It is
generated by
`tools/gen-profile-face.py`.

## Preview caveats

`wfb preview` runs on your computer, without the watch's fonts or data, so
it isn't what the watch or the Connect IQ simulator shows. Positions are exact,
because the preview uses the same resolved geometry as the compiled face.
Glyphs and data are not:

- **System fonts (`FONT_*`) are stand-ins.** Garmin doesn't ship its watch
  typefaces, and it publishes only each font's height. The preview draws
  system-font text in a generic face scaled to that height, so its width is an
  estimate. Text can look wider or narrower than on the watch, and can spill
  out of a box even where it would fit on the watch (the "Wed" in
  [the analog example](analog-hands.md)'s panels). The text-overflow lint uses the same estimate. Custom fonts from
  `fonts:` are baked from your TTF and do match the watch. To check
  system-font text exactly, use the simulator or the watch.
- **`complication.*` read by a `text` or `gauge` element has no sample
  value.** It shows as absent. For example, the showcase's Body Battery
  readout shows `--` right next to a slot showing `62`, and
  [`examples/features/sun`](../../examples/features/sun/face.yaml) renders as a blank screen.
- **An `icon: {for:}` weather icon draws rain.** The preview's sample
  condition is rain, the glyph the icon's size is measured with. The rest of
  weather has no sample value, so the readout beside it shows `--°`. On the
  watch, the icon follows the forecast and is hidden when there is no
  weather data.
- **Graphs always draw a synthetic curve**, even for a series whose other
  readings are absent (the forecast).

The screenshots on this page were drawn on a fēnix 8 47 mm with sample data at
10:09:42. To regenerate them, run `./.venv/bin/python tools/docs-shots.py`.
