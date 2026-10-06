// Each command's help: the first line is its summary in `wfb --help`, the
// whole text what `wfb help <command>` prints.

/** `wfb --help`'s description. */
export const MAIN = `wfb -- build a Garmin Connect IQ watch face from a YAML design.

    wfb validate design.yaml     # fast feedback: schema + semantic checks, no toolchain
    wfb preview  design.yaml     # render to a PNG, with no simulator
    wfb build    design.yaml     # generate Monkey C, resources and manifest, then compile

Run \`wfb help\` for the full command list, or \`wfb help <command>\` /
\`wfb <command> help\` for one command's own help. \`wfb doctor\` reports what is installed and what to do about anything
missing; \`wfb sources\`, \`wfb devices\` and \`wfb fonts\` list what a design
may bind and which watches and fonts it may use.

Every subcommand takes \`--color {auto,always,never}\` (default auto), either
before or after the command name -- \`wfb --color never build x\` and \`wfb
build --color never x\` both work.`;

export const COMMANDS: Record<string, string> = {
  build: `validate, generate and compile a design into a sideloadable .prg

Runs the full pipeline: YAML load -> schema validation -> semantic
checks (types, null policy) -> per-device layout resolve -> lint ->
Monkey C + resources + jungle + manifest generation -> \`monkeyc\`. Every
stage's diagnostics are reported against the design file's own lines.

\`--no-compile\` stops after generating the project, before invoking
\`monkeyc\` -- useful with no Garmin toolchain installed, or to inspect
the generated Monkey C directly. \`-d/--device\` builds one or more
devices instead of every target the design lists; it may name any
installed device (\`wfb devices\`), not only a listed target, which
draws a note and needs no edit to the design.

The devices compile in parallel, each \`monkeyc\` in its own directory;
\`-j/--jobs N\` caps how many run at once (\`-j 1\` compiles one at a
time). Diagnostics are reported in device order either way.`,
  validate: `validate a design without generating or compiling anything

The cheapest, fastest feedback loop: schema and semantic checks plus a
per-device layout resolve and lint, with no font baking, no Monkey C
generation, and no Garmin toolchain required. Call this after every
edit; reach for \`wfb build\` only once this is clean.`,
  preview: `render the design to a PNG on the host, with no simulator

Resolves the same per-device geometry \`wfb build\` would generate code
from, then rasterises it directly with Pillow -- so a preview and a
compiled face cannot disagree about *position*. Glyph shapes and arc
caps are approximations; the Connect IQ simulator is authoritative for
those, when it can run at all (see docs/limitations.md).

A system or vector font is drawn with the user's own licensed Garmin
font file when \`--fonts DIR\` (or \`WFB_FONTS\`, or \`vendor/fonts/\`) finds
one; otherwise it falls back to a free stand-in, or even Pillow's own
bundled default, silently as far as the image goes -- except that this
command then prints one warning to stderr naming every font that
happened to, and what to do about it (\`wfb doctor\` reports the same
root). See \`docs/lore/toolchain.md\`.

\`--style <entry>\` renders one \`config: style:\` entry -- its scheme's
colours and only the shared content plus that entry's own layout --
naming an unknown entry is a clean error listing the declared ones.
\`--all-styles\` renders every entry side by side in one PNG per device,
each panel captioned with the entry's label. Neither needs a \`config:
style:\` axis to exist for an ordinary preview with neither flag.

\`--time HH:MM[:SS]\` renders analog hands (and any \`time.*\`-bound
element) at that time instead of the sample 10:09:42. \`--asleep\` hides
every \`awake\`-only second hand, simulating a sleeping glance, on any
device shape, with no mode switch. \`--aod\` renders the AMOLED always-on-display frame -- the
resolved \`aod:\` set, restyled -- and implies \`--asleep\` too, the same
choice the generated \`_aod\` branch makes. \`--minute N\`
(0-1439) is \`--time\` given as a minute of the day. \`--heatmap\` implies
\`--aod\`, renders every minute of the day and sums them into one PNG in
which a pixel lit every minute is white, printing the largest share of
minutes any one pixel was lit -- a stand-in for the simulator's Screen
Heat Map. It takes \`--style\`, but not \`--all-styles\`, \`--time\` or
\`--minute\`. \`--units metric|statute\` sets the watch's unit settings a
\`units: auto\` element follows (metric by default).

\`--skin\` draws the watch round the screen: the render is set into the
simulator skin, the watch image the device files ship, on any mode.
The skin is optional: a device whose files lack it renders the bare
screen, as without the flag, and one warning names it.

Every mode writes
\`<device>[--<style>][--all-styles|--heatmap][--skin].png\` under \`-o\`,
or its one image to stdout with \`-o -\`.

\`-w/--watch\` re-renders whenever the design file or any font it
references changes, polling every \`--interval\` seconds (default 0.4).

\`-o -\` -- or \`-o --\`, which reads better next to a pipe -- writes the
PNG bytes to stdout instead of to files, and renders exactly one image:
the device \`-d\` names, or the design's first target. It implies
\`-q/--quiet\`, so stdout carries the image and nothing else; warnings and
errors still go to stderr. That makes a terminal preview a one-liner:

    wfb preview face.yaml -o -- | chafa
    wfb preview face.yaml -d fr955 -o - > face.png

\`-q/--quiet\` on its own silences stdout while still writing the PNG
files, for a script that only cares about the exit code.`,
  simulate: `launch the Connect IQ simulator and push a built face to it

Builds the design (like \`wfb build\`), starts the simulator if it is not
already running, and pushes the build for \`-d\`, or the first target,
with \`monkeydo\`. On macOS, where this works, the simulator is the SDK's
\`ConnectIQ.app\`, opened for you. Other systems are untested; on Linux
the simulator needs a display (\`DISPLAY\`), and in a container it
crashes as soon as an app is pushed to it (docs/limitations.md), which
is the gap \`wfb preview\` covers.

The command returns once the face is running. \`monkeydo\` stays behind,
writing the face's console output (\`System.println\`) to \`simulator.log\`
beside the built .prg, until the face is replaced or the simulator is
closed. \`-f/--follow\` also prints it here, until Ctrl-C, which leaves
the face running.

\`--screenshot\` captures the simulator window to a PNG once the face is
running. On macOS the terminal needs the Screen Recording permission.`,
  new: `start a design from a known-good template

Copies one of the bundled templates (\`--list\` shows them, with a
one-line blurb each) to a new YAML file, substituting a fresh UUID and
the given name. Two faces sharing a UUID are the same app to the watch
-- installing the second replaces the first -- so every call mints its
own.`,
  studio: `edit faces in the browser: a local web app

Serves the visual editor on http://127.0.0.1:8765/ until Ctrl-C. Open
that address in a browser to create a face from a template or open one
(a .zip with face.yaml and assets/, or a plain .yaml), edit it, and
download it to save. In the container, publish the port to the host's
loopback (\`docs/container.md\`).

The editor runs in the browser, compiler and all. Every face and its
history are kept in that browser's own storage, so closing the tab or
stopping the server loses nothing, and undo and redo survive a reload.
A changed face is snapshotted every few minutes and on every download.
Each browser has its own faces: to edit one in another browser, download
it and open it there.

The server sends the device files and fonts the editor reads, and builds
a .prg with \`monkeyc\` when the editor's Build asks. \`--host\` other than
loopback warns, since anyone who can reach the port can run builds.`,
  devices: `list installed device definitions

Reads the device files (\`~/.Garmin/ConnectIQ/Devices\` by default; see
\`--devices-dir\`/\`WFB_DEVICES\`) and prints each device's screen, shape,
display type, colour count, API level and watch-face memory limit. These
files cannot be downloaded unauthenticated -- run \`wfb doctor\` for how
to get them onto this machine.`,
  fonts: `list fonts available per device, or a detailed font breakdown for one or more

With no device named, lists every installed device definition alongside
its scalable (vector) faces, system (bitmap) font symbols, and which of
\`Graphics.getVectorFont\`/\`Dc.drawRadialText\`/\`Dc.drawAngledText\` it
publishes -- a face is only usable when \`Graphics.getVectorFont\` itself
is present, called out explicitly whenever a device publishes faces
without it.

Naming one or more devices -- as positional arguments, \`-d/--device\`
(repeatable), or both mixed together, merged in the order given and
de-duplicated -- prints a detailed breakdown for each instead (e.g. \`wfb
fonts fenix8solar47mm fr955\`), separated by a blank line:
  * Scalable (vector) fonts -- faces published to \`Graphics.getVectorFont\`
    (for use in \`face.yaml\` under \`fonts:\` with \`face: [...]\`), plus
    which of \`curve: {style: radial|angled}\` the device can pair it
    with, since getVectorFont alone does not guarantee either;
  * System (bitmap) fonts -- \`Graphics.FONT_*\` symbols, their exact line
    heights (\`size_px\`), em sizes, file stems, and face names.

A device that cannot run a watch face at all (\`wfb devices\`) is named
with a one-line note instead of font data, in either view. Naming an
unknown device is a clean error (\`wfb devices\` lists what is installed)
and nothing is printed, even when an earlier name on the command line
is valid -- every name is resolved before anything is shown.`,
  doctor: `check the environment and say what is missing

Written for someone -- or something -- arriving with no context: each failure
names the command that fixes it, and the exit code says whether a build is
possible at all.  Everything except the last two checks is needed only to
*compile*; validation and preview work without them.`,
  schema: `print the JSON Schema, or where it lives, for editor setup

With no flags, prints the schema itself -- for piping into a validator,
or reading by eye. \`--path\` prints only the file's path, for pointing an
editor's \`yaml-language-server\` schema mapping at it.`,
  sources: `list the data-source catalogue: every value a design may bind

For each source: its type, whether it is nullable, any permission
binding it implies, its conventional \`on_hold: auto\` launch target (if
it has one), and the SDK page it was taken from. Every read is a plain
per-frame read now -- there is no refresh-tier concept left to show.
This is the authoritative, always-current list -- never bind a path
that is not listed here, and never trust a copy of this list pasted
into prose, which goes stale the moment the catalogue grows.

Also lists the \`color.*\` names -- palette swatches, scheme roles that
follow Styles, and the native on-device colour axes' roles -- even
though, unlike everything above, these are not read from any device API:
a design that declares \`config:\` binds them the same way, as an ordinary
colour expression.`,
  complications: `list the complication type table: what \`on_hold:\` may launch, what
\`complication.*\` may read, and what a \`config: slots:\` slot may show

A watch face cannot open an arbitrary app. The platform offers exactly
one exit -- \`Complications.exitTo\`, "launches the app associated with
the complication" -- so an interactive element names a complication
type and the watch opens whichever glance or app owns it. The same 42
types are also readable directly as \`complication.<name>\` data sources
(see \`wfb sources\`), and are what a \`config: slots:\` slot's own
\`default:\`/\`choices:\` name -- this is the one table all three draw from.

Printed for each, grouped as the editor lists them: the name a design
writes, its name for people, the catalogue icon a \`data\` element's
\`icon:\` draws for it by default (\`ts/src/icons.ts\`; a slot's
\`choices:\` mapping-form entry can override this per design), the Monkey C
constant it compiles to, and the API level, when it is later than the
others'. An API level is not a promise the watch has it; a hold on a
type the watch does not know simply does nothing, which is why \`wfb
validate\` also checks each target's own symbol table (and, for a slot,
each target's own ConnectIQ ceiling -- see \`api-gated\` in
docs/guide/configuration.md).

Binding one of these -- as \`on_hold:\`, as \`complication.<name>\`, or via
\`on_hold: auto\` -- adds the ComplicationSubscriber permission
automatically, the same way a data binding derives its own
requirements. A \`config: slots:\` slot does too, even though it reads no
catalogue source directly. A target that lacks \`Toybox.Complications\`
(fenix6 and fr245, among the installed devices) has the generated code
guard every use of it at runtime (\`ts/src/availability.ts\`), so the binding
simply reads as absent there.`,
  series: `list the time-series catalogue: every \`series:\` a \`graph\` element may plot

A \`graph\` plots a series, not a scalar -- a different kind of binding
from \`wfb sources\`' data-source catalogue, acquired and cached on-device
rather than read fresh every frame (\`docs/guide/progress-and-graphs.md\`'s \`graph\` section).
Four families, and neither solar nor anything backed by
\`Toybox.SensorHistory\` (pressure, stress, elevation, Body Battery) is one
of them -- see \`docs/limitations.md\`.

Printed for each: its value type, the natural interval \`range:\` as a
duration divides by (none for \`heart_rate\`, which bins by real time
instead), the documented maximum sample count if the SDK states one, and
the SDK page it was taken from.`,
  help: `show help for wfb, or for one command

\`\`wfb help\`\` alone is the same as \`\`wfb --help\`\`. \`\`wfb help <command>\`\`
-- or, equivalently, \`\`wfb <command> help\`\` -- is the same as
\`\`wfb <command> --help\`\`.`,
};
