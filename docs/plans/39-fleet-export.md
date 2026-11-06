# Plan 39 — a fleet-wide Store export: `fallback:` on a `face:` font, and `--all-devices` that drops what a device cannot draw

**Status:** in progress (2026-11-06). Two slices, built in parallel by two
agents, merged by the orchestrator. Decisions D1–D12 below are made.

## 1. The problem

`wfb export --all-devices` means "every installed device that can run a
watch face at the 3.1.0 floor". It is a device filter, not "every device
this design can run on": one device the design fails on fails the whole
export (`cli_help.ts`, `docs/guide/preview-and-cli.md`, the
`docs/limitations.md` §2 row). Solaria (`examples/other/solaria.yaml`)
exports to no device at all that way, with 56 `font-unavailable` errors from
one cause: every text in it uses `face: RobotoCondensedBold`, which only 41
of the 136 face-capable devices publish, and a `face:` font has no fallback
of any kind. Fonts cannot be overridden per device either (`overrides:`
patches geometry, colour and visibility only).

Two changes, which compose:

- **Slice A (option 3): a baked `fallback:` on a `face:` font.** On a
  device that publishes none of the faces, the entry bakes a sheet from the
  author's own TTF instead, exactly as a `source:` font would. Plain
  (upright) text then draws everywhere. `curve:` text cannot use it
  (`drawAngledText`/`drawRadialText` take a `VectorFont` only), so on such
  a device a curved element is still unavailable and `unsupported:`
  decides, as today.
- **Slice B (option 2): `--all-devices` drops what a device cannot draw.**
  An error that exists only because a particular device lacks a capability
  (no usable face for a curved text, no subscreen, an AMOLED target with
  low-power elements, an unguardable API, memory over the device's limit)
  drops that device from the export, with a note naming it and why, and the
  export carries on with the rest. A design error (anything not attributed
  to devices) still fails the export, as does any error at all without
  `--all-devices`: an explicit `targets:` or `-d` list is the author's
  statement, and the compiler does not second-guess it.

Together: Solaria with `fallback:` on its four fonts exports upright text to
the whole fleet, and every device that cannot draw its curved rim numerals
is dropped (or, with `unsupported: hide`, kept without them).

## 2. Decisions

- **D1. Format.** A `face:` font entry (named under `resources: fonts:`, or
  written inline as a text's own `font:`) takes an optional `fallback:`
  mapping with the baked-font keys: `source:` (required), `size:`
  (optional; defaults to the entry's own `size:`), `glyphs:`, `antialias:`,
  `monospace:`, `align:`. Inside it `face:`, `unsupported:` and `fallback:`
  are schema errors. `fallback:` on a `source:` entry is a build error
  ("a baked font is never unsupported, so it has nothing to fall back
  from"), raised like `unsupported:` on a baked font is today. The schema
  (`schema/wfb-face-2.schema.json`, normative) gains `$defs.fallbackFont`
  and the `vectorFont.properties.fallback` reference; its descriptions say
  what the key promises and what it cannot (curved text).
- **D2. Per-device mode.** For each `face:` font and device:
  `vector` when the device has `Graphics.getVectorFont` and publishes one of
  the listed faces (the existing `vectorFontFace`); otherwise `fallback`
  when the entry declares one; otherwise `none`. The mode is a property of
  the font on the device, independent of any element's `curve:`.
  An element's availability on a device: in `vector` mode, gates 1–3 as
  today (a `curve:` still needs `drawAngledText`/`drawRadialText`); in
  `fallback` mode, available without `curve:`, unavailable with it; in
  `none` mode, unavailable. Unavailable keeps today's meaning:
  `unsupported: error` fails, `unsupported: hide` hides the element on that
  device (`HIDDEN_BY_FONT`).
- **D3. Diagnostics.** `font-unavailable`'s error keeps its text, and its
  "set `unsupported: hide` …" note also offers `fallback:` when the font has
  none (and, when the font has one, says the fallback cannot serve `curve:`).
  A new note, `font-fallback` (one per font, confidence exact), names the
  devices on which the fallback bakes. New codes go in `ALL_CODES` and
  `docs/guide/lints.md`; neither new code is suppressible with
  `lint: {allow:}` (a note is not noise an author needs to accept).
- **D4. Generated code.** One shared view serves every device
  (`shared-source`). A font with a fallback is loaded into one view field
  that can hold either a `VectorFont` or a loaded `FontResource`
  (`Graphics.FontType?`); `onLayout` constructs the vector font where the
  per-device `Layout` says it is available, and loads the baked resource
  otherwise. The shared view must never name a `Rez.Fonts.<id>` that some
  device in the build does not have: the resource reference lives in the
  per-device `Layout.mc` (a function returning the loaded resource, or
  `null` on a vector-mode device; or a constant, if `monkeyc` accepts a
  `Rez` symbol in a `const` — confirmed by a real build either way). The
  resource is baked only on fallback-mode devices. A curved draw keeps a
  `VectorFont`-typed value (a cast through a local, or a second field):
  under `-l 3` a `FontType` does not pass to `drawAngledText`. Every
  existing design's generated sources are byte-identical (the goldens hold
  this): the new shape appears only for a font that declares `fallback:`.
  Gate 4 (a null font at draw time) keeps its null check on every draw.
- **D5. Rings.** A text in a fallback font rings by the stamp on every
  device, as a vector font's text does today (one shared code shape); no
  ring companion sheet is baked for it.
- **D6. `aod: {font:}` naming a `face:` font** stays refused, fallback or
  not (`docs/limitations.md` §2 already lists it).
- **D7. The editor.** `wfb studio` round-trips a design with `fallback:`
  (load, inspect, patch an unrelated key: the YAML keeps the key), the
  Properties tree shows it as the schema gives it, and a download bundles
  the fallback's `source:` file as it bundles a baked font's.
- **D8. The preview.** On a fallback-mode device `wfb preview` draws the
  text from the baked sheet; on a vector-mode device from the face's
  outlines, as today. Layout measures the element against whichever the
  device uses, so `text-overflow` and friends read the real box.
- **D9. Device attribution.** `Diagnostic` gains `devices: string[] | null`
  (through `DiagnosticOptions`): the devices whose absence from the build
  would remove the finding. Set by: `font-unavailable` (error form; the
  failing devices), `subscreen` (error form; the lacking devices),
  `partial-update` (a target without `onPartialUpdate` and low-power
  elements), `api-gated-unguardable` (both forms), `memory` (share ≥ 1,
  measured after the compile). Nothing else: a `resolve` error, a
  `missing-glyph`, a `shared-source` or a `monkeyc` error is the design's.
  `mergedAcrossDevices` and `Bag.only` keep the field.
- **D10. The drop loop.** `exportApp` with `allDevices`: resolve and lint
  the candidate set; if every error carries `devices`, remove their union
  from the set and resolve again (guards, the shared view and the
  cross-device lints depend on the set), until a pass has no error or has
  an error with no attribution (then the export fails as today, the
  dropped devices still reported). After `monkeyc -e`, a device whose
  measured memory is over its limit is dropped the same way and the export
  recompiles without it; one more pass suffices because removing a device
  never grows another's code. Each dropped device gets one
  `note[device-dropped]`: the device, the codes and the first line of each
  dropped error's message (the author must see why without `-v`), and the
  final bag holds no diagnostic that named only dropped devices. Dropping
  every device is an error (`devices`: nothing left to export). Without
  `--all-devices` nothing changes.
- **D11. Reporting.** The export's `exported` line counts the devices
  shipped; a `dropped` line follows it (`N devices: id (codes), …`), and
  `export-info.json` records `dropped: {id: [codes]}`. `cli_help.ts`, the
  guide's export chapter and the `docs/limitations.md` §2 row say the new
  truth.
- **D12. Example and tests.** A new example,
  `examples/features/font-fallback/face.yaml`, targets `fenix8solar47mm`,
  `fr955` (vector mode) and `fr255` (no `getVectorFont`: fallback mode),
  with an upright text in a fallback font and a curved text in the same
  font under `unsupported: hide`; it builds warning-free on all three (the
  slow suite builds every example) and enters the goldens. Slice B's drop
  loop is covered by a fast test over installed devices (no `monkeyc`) and
  one slow export.

## 3. Slices

### Slice A — `fallback:` on a `face:` font (compiler, preview, editor, docs)

Files: `schema/`, `ts/src/ir/model.ts` (`FontSpec`), `ts/src/ir/builder/fonts.ts`,
`ts/src/layout.ts` (`textFont`, `LayoutFont`, `ResolvedFont`),
`ts/src/availability.ts` (`vectorFontFace`, `Guards.vector_fonts`),
`ts/src/lint.ts` (`checkVectorFontAvailability`), `ts/src/emit/resources.ts`
(`glyphSet`, `bakeFonts`), `ts/src/emit/monkeyc/{view,layout_constants,common}.ts`,
`ts/src/kinds/{text,data,pattern,base}.ts`, `ts/src/draw/`, `ts/src/preview.ts`,
`ts/src/studio/{inspect,bundle}.ts`, tests, `docs/guide/fonts.md`,
`docs/guide/text.md`, `docs/guide/lints.md`, `docs/limitations.md`,
`docs/lore/roadmap.md`, `docs/lore/codegen.md`, the new example.

Every consumer of a font's vector-ness is audited and classified: a
design-level fact (the shape of the shared code: `FontSpec.isVector`,
`TextRun.isVector(face)`) or a device-level fact (what this device draws
with: `ResolvedFont`/`LayoutFont`). The audit list is in the commit message.

### Slice B — `--all-devices` drops unsupported devices (diagnostics, export, CLI, docs)

Files: `ts/src/diagnostics.ts`, `ts/src/lint.ts` (the five attributing
sites), `ts/src/build.ts`/`ts/src/node_build.ts` (`exportApp`, `prepare`),
`ts/src/cli.ts`, `ts/src/cli_help.ts`, tests (`export.test.ts`,
`diagnostics.test.ts`, the slow suite), `docs/guide/preview-and-cli.md`,
`docs/guide/lints.md`, `docs/limitations.md`, `docs/lore/roadmap.md`.

### Close

Merge both, run the fast, slow and browser suites, re-run Solaria with
`fallback:` on its fonts under `--all-devices`, delete this file and add
its row to `docs/plans/README.md`, merge to `main`.
