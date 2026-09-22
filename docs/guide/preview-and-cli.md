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
| `devices` | list installed device definitions |
| `fonts` | list fonts available per device, or a detailed font breakdown for one or more |
| `doctor` | check the environment and say what is missing |
| `schema` | print the JSON Schema, or where it lives, for editor setup |
| `sources` | list the data-source catalogue: every value a design may bind |
| `complications` | list the complication type table: what `on_hold:` may launch, what `complication.*` may read, and what `config: data:` may offer a slot |
| `series` | list the time-series catalogue: every `series:` a `graph` element may plot |
| `help` | show help for wfb, or for one command |

```sh
wfb new       "My Face" [-t minimal|dashboard]   # start from a known-good template
wfb build     design.yaml [-d DEVICE] [-o DIR] [--no-compile]
wfb validate  design.yaml [-d DEVICE]  # everything except codegen; no toolchain needed
wfb preview   design.yaml [-d DEVICE] [--watch] [-q] [-o -]  # render to PNG; no simulator
wfb simulate  design.yaml          # launch the simulator and push the built face
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

`wfb preview -o -` (or `-o --`) writes **one** PNG — the device `-d` names, or
the design's first target — to stdout instead of to files, and prints nothing
else, so a face can go straight into a terminal image viewer:

```sh
wfb preview my-face.yaml -o -- | chafa
```

`-q/--quiet` alone keeps the files and silences stdout; either way warnings
and errors still go to stderr.

`wfb help <command>` and `wfb <command> help` print the same thing as
`wfb <command> --help`, byte for byte, because all three are read from that
command's handler docstring rather than from a hand-written string that could
drift from it.

The quickest start:

```sh
wfb new "My Face"
wfb preview my-face.yaml --watch   # leave this running while you edit
```

`wfb preview` renders from the **same resolved geometry** the generated Monkey C
uses, so the two cannot disagree about position — which is what makes it a useful
check and not a second implementation. Why a visual GUI builder is deferred is
in [`docs/research/06-authoring-ergonomics.md`](../research/06-authoring-ergonomics.md).

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
- **`complication.*` read by a `text` or `progress` element has no sample
  value.** It shows as absent. For example, the showcase's Body Battery
  readout shows `--` right next to a slot showing `62`, and
  [`examples/features/sun`](../../examples/features/sun/face.yaml) renders as a blank screen.
- **An `icon_for:` weather icon always draws.** Weather has no sample value,
  so the readout beside it shows `--°`. On the watch, the icon is hidden when
  there is no weather data.
- **Graphs always draw a synthetic curve**, even for a series whose other
  readings are absent (the forecast).

The screenshots on this page were drawn on a fēnix 8 47 mm with sample data at
10:09:42. To regenerate them, run `./.venv/bin/python tools/docs-shots.py`.
