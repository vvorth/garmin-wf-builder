# Plan 40 — `fallback: auto`: a universal free stand-in for every device-resident face

**Status:** in progress (2026-11-06). Two slices built in parallel by two
agents, merged by the orchestrator. Decisions D1–D10 below are made.
Builds on plan 39 (`fallback:` on a `face:` font, now shipped: a `face:`
entry can name a baked `fallback: {source: ...}` of the author's own).

## 1. The problem

A `fallback:` today needs a font file beside the design. The user prefers
one YAML to a zip of assets. For most device-resident faces the exact free
file exists (Garmin ships Google's Roboto Condensed unchanged; the Noto,
Nanum, Kosugi and Pridi faces are OFL or Apache fonts), and for the few
proprietary ones (Garmin's Bionic, Microsoft's Sakkal Majalla, Bitstream's
Swiss 721) a close free substitute can be chosen once, by look, weight and
style, and recorded with its reasoning. The free-font registry
(`ts/src/data/font-registry.json`, built by research 10 for measuring and
previewing *system* fonts) already has the shape for this: pinned sources
with licences, `names` from a face name to a key, and `fonts` keyed entries
with a `match` kind. It covers the Latin families and leaves the script
faces deliberately unmapped. This plan completes it for every scalable face
and lets a design say `fallback: auto`.

The survey, from the SDK 9.3.0 device reference (`.cache/device-reference`:
178 devices, 150 face-capable, 58 publishing a scalable face): 32 face
names in 14 families. Roboto Condensed (Bold, Regular, RegularItalic),
Roboto (Regular, Italic, Medium, Black), Bionic (Bold, SemiBold, Medium),
Exo SemiBold, Tomorrow Bold; and the script faces Noto Sans SC Medium,
Kosugi Regular, Noto Naskh Arabic (Regular, Bold), Noto Sans Hebrew
(Regular, Bold), Noto Sans Armenian (Regular, Bold), NanumGothic (Regular,
Bold, ExtraBold), Pridi (Regular, RegularGarmin, SemiBoldGarmin), Sakkal
Majalla (Bold, Roman), Swiss 721 (Regular, Bold), Yantramanav Regular.

## 2. Decisions

- **D1. Format.** `fallback: auto` on a `face:` entry (named or inline) is
  short for `fallback: {source: auto}`; the mapping form takes the other
  baked keys (`size:`, `glyphs:`, `antialias:`, `monospace:`, `align:`)
  beside `source: auto`. `fallback: {source: <path>}` stays exactly as
  plan 39 built it. The schema (normative) accepts the scalar and the
  `auto` value, with descriptions saying what each promises.
- **D2. Resolution.** For a font in fallback mode on a device, `auto` takes
  the first face in the entry's author order that the registry maps
  (`resolveRegistryKey(faceName)`), and bakes that key's file, at the
  entry's `size:` unless the mapping says otherwise. The file comes from
  the registry only (`FontFiles.registry(key)`): never from `vendor/fonts/`
  or the SDK Manager's Garmin fonts, even when they are present, because an
  `auto` sheet ships inside a Store `.iq` and only a redistributable file
  may. Every registry source carries its licence; `auto` refuses a key whose
  source has none.
- **D3. Errors.** No listed face maps to a registry key: a build error at
  the `fallback:` key naming the faces, saying to write `fallback: {source:
  <your file>}` instead. A key whose file is not installed: a build error
  naming the key and the command that installs it (`./tools/setup-env.sh`,
  or `node ts/tools/fetch-system-fonts.ts --registry`). Both driven red.
- **D4. The note.** `font-fallback` names, besides the devices, the registry
  key, its match kind (`exact`, `family` or `substitute`) and licence, so an
  author sees when a substitute stands in for a proprietary face.
- **D5. The registry gains every scalable face.** `names` maps each of the
  32 face names (and their file stems, `-2`/`-3`/`-Outdoor`/`_Garmin`
  variants included) to a key; `fonts` has a key per distinct file with its
  `match` and a note; `sources` pins each file (URL, archive member, SHA-256,
  size, licence, licence URL). `unmapped` keeps only what is genuinely
  unresolvable, if anything. Exact where the foundry's file is free
  (Roboto, Roboto Condensed, Noto, Nanum, Kosugi, Pridi, Yantramanav, Exo,
  Tomorrow), `family` where the free file is the same family at another
  weight or version (a Garmin-tweaked `_Garmin`/`-Outdoor` build of a free
  font), `substitute` where the face is proprietary (Bionic, Sakkal
  Majalla, Swiss 721 Hebrew).
- **D6. Substitutes are chosen by look, with evidence.** For each
  proprietary face the research doc lists the candidates considered, renders
  the same sample (digits and caps for Bionic, the script's sample for the
  others) in each candidate beside the real face wherever a licensed copy
  or a simulator capture of it exists on this machine, and picks the closest
  in letterform, weight and width. Garmin's own reference names Bionic
  Medium's family as Rajdhani; research 10 picked Roboto Black for Bionic
  on the grounds that `fr955` uses it in the same `FONT_NUMBER_*` role.
  This plan decides by appearance for the fallback and keeps one mapping
  per face: if the research changes Bionic's stand-in, the preview goldens
  that draw Bionic move with it, and the commit explains each.
- **D7. Prefetch.** `tools/setup-env.sh` installs every registry source on
  initialisation (the fetch tool's `--registry`), script faces included, so
  `fallback: auto` needs no download at build time. The research doc states
  the total download size. The Docker image does the same already.
- **D8. Browser.** `wfb studio` bakes an `auto` fallback through the same
  `FontFiles.registry` answer the worker already gets from the server for
  previewing system fonts; a bundle download references no file for it.
- **D9. Example and docs.** `examples/features/font-fallback/face.yaml`
  gains a second font with `fallback: auto` (Roboto Condensed Bold, so the
  sheet is the device's own letterforms on fr955 and fr255). The guide's
  `fallback:` section, `lints.md`, the schema, `limitations.md`,
  `roadmap.md`, `toolchain.md` (the prefetch) and the root `CLAUDE.md` §2
  line about setup say the new truth. A new research file,
  `docs/research/40-vector-face-stand-ins.md`, is the record of the survey
  and the choices.
- **D10. End to end.** Solaria with `fallback: auto` on its fonts exports
  with `--all-devices`: curved rim text under the default drops the devices
  that cannot curve, under `unsupported: hide` every installed device ships.

## 3. Slices

### Slice R — the stand-ins: research, registry, prefetch

Files: `docs/research/40-vector-face-stand-ins.md` (+ `docs/research/data/`
or `probes/` for the comparison renders), `docs/research/00-summary.md`,
`ts/src/data/font-registry.json`, `ts/tools/fetch-system-fonts.ts`,
`tools/setup-env.sh`, `docs/lore/toolchain.md`, `docs/container.md`,
`CLAUDE.md` §2, tests over the registry.

### Slice F — `fallback: auto` in the compiler, the editor and the guide

Files: `schema/`, `ts/src/ir/builder/fonts.ts`, `ts/src/ir/model.ts`,
`ts/src/emit/resources.ts` (the bake through `FontFiles.registry`),
`ts/src/lint.ts` (the note), `ts/src/studio/`, the example, tests,
`docs/guide/fonts.md`, `docs/guide/lints.md`, `docs/limitations.md`,
`docs/lore/roadmap.md`.

### Close

Merge both, run the fast, slow and browser suites, export Solaria with
`fallback: auto` under `--all-devices`, delete this file and add its row to
`docs/plans/README.md`, merge to `main`.
