# The fixture device `wfbtest`

A watch that does not exist, written by this project so the compiler, the
fast suite's fixture test and the editor can run with **no Garmin device
file anywhere**: a clean clone, a fork's pull request in CI, a machine
without the SDK Manager.

**No Garmin file is included.** Every byte here was written for this
project: the two JSON files by hand, in the shapes
`ts/src/devices/device.ts` reads; the symbol table from the project's own
catalogue (`ts/src/data/catalog.json`) and gate symbols; the skin drawn as
a flat grey ring; the reference page by hand, in the shape
`ts/tools/extract-device-reference.ts` writes.
Garmin's own device definitions are the user's licensed copy and are never
committed (root `CLAUDE.md` §2).

| File | What it gives the compiler |
|---|---|
| `wfbtest/compiler.json` | a round 260x260 MIP screen, `deviceFamily` `round-260x260`, a 131 072 B watch-face limit, Connect IQ 5.2.0, no alpha blending |
| `wfbtest/simulator.json` | the panel's place in the skin (`display.location`), `ppi`, the graphics pool, and the `ww` font set: nine `FONT_*` system fonts and two scalable faces, each naming a file the font registry's free stand-ins cover (`RobotoCondensed-Regular`, `RobotoCondensed-Bold`, `Roboto-Black`) |
| `wfbtest/wfbtest.png` | the simulator skin: a 380 px grey ring, transparent where the panel shows |
| `wfbtest/wfbtest.api.debug.xml` | its own symbol table: every module, function and field the compiler asks a device about, so the device has them all (`test/fixture-device.test.ts` fails when a catalogue source needs one it lacks) |
| `reference/wfbtest.json` | its device-reference page: the `FONT_*` pixel heights, 64 display colours, the watch-face limit |

The SDK-wide `bin/api.debug.xml` does not serve as the symbol table: it
has no module rows (`<dataEntry type="module">`), so every module would
read as absent and a design reading complications or weather would lint
with `api-gated` warnings.

## Using it

`test/fixture-device.test.ts` reads it directly. Anything else sees it, and
only it, through two environment variables:

```sh
export WFB_DEVICES="$PWD/ts/test/fixtures/devices"
export WFB_DEVICE_REFERENCE="$PWD/ts/test/fixtures/devices/reference"
./wfb preview design.yaml        # a design whose targets: name wfbtest
./wfb studio                     # the editor, with wfbtest its only watch
```

`monkeyc` does not know the id (`Invalid device id specified: 'wfbtest'`),
so a build stays on real devices. What runs on the fixture alone is listed
in `docs/development.md`, "Continuous integration".
