# examples/

Loaded automatically when working in `examples/`. `README.md` here is the
user-facing index.

**Layout.** Three faces at the top level are built to be worn --
`showcase/`, `analog-custom/` and `navy-classic/` (made from a photo by the
watchface-from-image skill). `features/` holds one face per format feature
and `system-fonts/` the three calibration faces. `other/` is a git
submodule (`vvorth/wfb-watchfaces`), the user's own faces, `dashboard/`
among them: another repository, empty in a clone made without
`--recurse-submodules` (continuous integration's included). Anything that
walks the examples must recurse and must skip it: `isSubmodule` in
`ts/src/node.ts` is the test, and `exampleDesigns` in `ts/tools/goldens.ts`
and every test that walks `examples/` use it, so no golden, test or docs
check ever reads the submodule. A flat `examples/*/face.yaml` glob sweeps up
only the three wearable faces.

Every example, template and fixture is format 2; a format 1 face no longer
loads. Every example lints clean on every target. Where a design
deliberately touches the bezel or accepts a platform gap (no
Complications), the element says so with `lint: {allow: [...], reason:}`.
No verification target needs a `config-unsupported` allow: fr955 edits
`config:` from the settings menu.

## `features/`

Each face's header comment explains what it exercises, and every face here
is named `Feature <thing>` so a sideloaded build is obviously a demo on the
watch -- keep that convention for new ones; it also decides the `.prg` name
(`feature-graph-1.0.0-fr955.prg`). The table in `README.md` says which face covers
which feature. Rules that are not obvious from the files:

- **`features/analog/` stays the generated analog-hands design**:
  its goldens and `ts/test/parameter-limits.test.ts` read it. Hand-tuning
  belongs in the wearable `analog-custom/`.
- **`features/profile/` is generated** by `ts/tools/gen-profile-face.ts`: edit
  the generator and rerun it, never the YAML.
- **`features/aod/` is the only example with an AMOLED target**
  (`fenix847mm`, a fourth target). Its `info` group's `aod: {visible: false}`
  deliberately shadows its child's `aod: {visible: true}`, which is why that child
  carries `lint: {allow: [aod-unreachable]}`. Because it mixes an AMOLED
  target in, its MIP targets' generated source is not byte-identical to a
  build with no `aod:` keys; only an all-MIP `targets:` holds that
  guarantee.
- `features/rings/` is the `docs/screenshots/outlines.png` shot.

## `system-fonts/`

`text/`, `numbers/` and `numbers-large/` are calibration faces, not design
showcases: every `FONT_*` system font this project measures
(`Device.systemFonts` in `ts/src/devices/device.ts`) drawn as a short literal sample on a 1px
guide line, `align: left` at a common `px` x, so left edges compare across a
real simulator screenshot and `wfb preview`'s PNG pixel-for-pixel (still
open until the user sends screenshots). The four `FONT_NUMBER_*` sizes do
not fit one screen together (the heaviest pair is up to 129px tall, checked
by brute-force search over the placement), so they split into `numbers/`
(MILD, MEDIUM) and `numbers-large/` (HOT, THAI_HOT). `fr245` is a target
only so its `.cft` fonts can be measured; its smaller screen crops rows the
other targets fit, accepted per element with `lint: {allow}`.

## The wearable four

`showcase/` is the widest single face here: three `layouts:` switched by
Styles (a classic `analog` dial, a data-rich `digital` dashboard and a
vintage `roman` dial with curved `face:`-font numerals and a day/date
aperture), two shared `data` registers on the Data axis, several schemes
and both colour axes. Its own comments record the design choices (for
example `skip: [2, 10]` on the numeral ring, because the registers sit on
those spokes).

The Phase 2 slice is no longer an example: it is the test fixture
`ts/test/fixtures/slice/`.

### `examples/other/` is the user's own collection

The user edits these faces directly between sessions, and
`examples/other/dashboard/face.yaml` is the playground they named:
**leave the submodule alone** unless asked. Do not proactively "fix" a
face's lint warnings, geometry or content, and never commit inside it from
this repository; a change there is a commit in `vvorth/wfb-watchfaces`.
Nothing here tests its faces, so a red test never points at one.
