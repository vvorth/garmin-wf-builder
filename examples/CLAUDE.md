# examples/

Loaded automatically when working in `examples/`. `README.md` here is the
user-facing index.

**Layout.** Four faces at the top level are built to be worn --
`dashboard/`, `showcase/`, `analog-custom/` and `enduro/` (work in
progress). `features/` holds one face per format feature, `system-fonts/`
the three calibration faces, and `generated_by_skill/` faces made from a
reference picture by the `skill/watchface-from-image` branch's skill (with
`prompts.md` and the reference PNGs beside them). Anything that walks the
examples must recurse (`exampleDesigns` in `ts/tools/goldens.ts` does), and a
flat `examples/*/face.yaml` glob sweeps up only the four wearable faces.

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
(`feature-graph-fr955.prg`). The table in `README.md` says which face covers
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

### `examples/dashboard/face.yaml` is the user's own playground

The user edits this file directly between sessions and has said explicitly:
**it is a playground, leave it alone.** Do not proactively "fix" its lint
warnings, geometry or content — even a broken `wfb validate` or a failing
`test_example_is_clean_on_every_target[dashboard]` is not, by itself, a
defect to correct unless asked. When in doubt here, ask rather than assume —
this is the one file in the repo where "the test suite is red" is not
automatically a bug report.
