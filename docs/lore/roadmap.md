# Roadmap: what exists, what was removed, what is missing

`docs/limitations.md` §2 is the **authoritative** list of what is missing.
This file is a turn-one summary; if the two disagree, `limitations.md` is
right and this file needs updating. `docs/format.md` documents everything
listed as shipped.

## Shipped

- **All nine element types:**
  - `group`, `text`, `icon`, `complication_slot`;
  - `shape` (`rectangle`, `rounded_rectangle`, `circle`, `line`, `arc`,
    `ellipse`, `polygon`);
  - `progress` (`arc`, `bar`);
  - `graph` (`line`, `area`, `bars`);
  - `hands` (analog hands, plan 04);
  - `pattern` (plan 05; its text parts come from plan 06).

  `hands` and `pattern` are the two exceptions to "the device does no layout
  arithmetic": the watch rotates or transforms the resolved geometry each
  frame (ADR 0004; `runtime-lib/WfbHands.mc`, `WfbGeom.mc`). Baked pattern
  copies measured about 30× the memory (`docs/research/probes/pattern-cost/`).
- **Placement and drawing:**
  - `align:`/`vertical_align:` on every element with a placement box (plans
    06–07);
  - `static:` (paint-once buffering), `antialias:`, `visible:`,
    `monospace:`, and `min_1px:` (opt-in 1 px floor for relative lengths,
    plan 08);
  - the mapping form of `elements:`.
- **Data:**
  - the full source catalogue, including all 42 `COMPLICATION_TYPE_*` values
    under `complication.*`;
  - the Nerd Fonts icon catalogue, downloaded by setup;
  - every source is a plain per-frame pull read. There are no refresh tiers.
- **Interactivity:**
  - `on_hold:` on every element, touch-and-hold only (constraint 6c);
  - `on_hold: auto`, which picks the launch target from the element's own
    bound value;
  - `Complications.exitTo`.
- **Configuration: all four native axes (ADR 0006):**
  - `accent_color` and `data_color`;
  - Styles, carrying `color_scheme:` and `layouts:` (form A: a container;
    plan 02);
  - the Data axis as `complication_slot`, with icons for all 42 types
    (plan 03).
- **Per-device API gating:**
  - the shared manifest floor stays 3.2.0;
  - every complication touch and every missing field is `has`-guarded at
    runtime (`wfb/availability.py`);
  - an unavailable binding reads as absent, and lint `api-gated` warns.

  UNVERIFIED on a real pre-4.2.0 device: that a guarded reference to an
  absent module is harmless at load time. A reader *function* that a device
  lacks would still be a hard build error.
- **System fonts in preview and measurement** (plans 09–10):
  - Garmin's own font files first, then pinned free stand-ins, then
    Pillow's default;
  - `.cft` bitmap fonts decoded for the fenix 6/7 family, fr245 and fr255
    (`docs/research/10-system-fonts.md`).
- **Vector fonts and `curve:` on `text`** (plan 11): a `fonts:` entry can
  name a device-resident scalable face (`face:`) instead of baking one, and
  a `text` element can bend it along a line or around a circle
  (`Dc.drawAngledText`/`drawRadialText`) — the only way to rotate or curve
  text, since a baked font cannot. Reaches 44 of the 136 watch-face-capable
  devices; `if_unavailable: error` (default) fails the build per device,
  `hide` lets the element disappear there instead — both are build-time-only
  guarantees, since the platform can still return a null font at runtime.
  **Not** built: the same on a pattern's `shape: text` part (plan 11 §5
  slice 2).

Nothing config-, hands- or pattern-related is verified on a watch or in the
simulator. What is verified is a warning-free real `monkeyc` build and
`wfb preview`.

## Removed outright (no shim; the old spelling is an ordinary error)

- `type: carousel`.
- `on_tap:`, now `on_hold:`. `WatchFaceDelegate.onTap` never fires on a live
  face.
- A font `size:` given as a bare number, and `scale:`. Lengths are always
  `%r`/`px`.
- A pasted raw character in `icon:`. Use a catalogue name or
  `glyph: "U+XXXX"`.
- Refresh tiers (`WfbCache.mc`, `catalog.Tier`).
- `config: colors:`. Use `config: style:`.
- `vertical_align: baseline`, renamed `bottom`.

## Not implemented

See `docs/limitations.md` §2 for the full table and the ADR or plan that
specifies each item.

1. `image` elements and the `raw` escape hatch (ADR 0007). Both give a
   friendly error.
1b. A pattern's `shape: text` part cannot take `curve:` (rotated/radial
   text) yet — a `text` **element**'s own can (Shipped, above; plan 11 §5
   slice 2). Shipping an author's own `.ttf` for the watch to rasterise
   remains impossible on every device regardless — that is a platform
   constraint (§4.15), not a gap.
2. Per-device `overrides`: writing one is a build error.
3. `segments`/`scale` progress styles.
4. Automatic unit conversion (ADR 0005 §4). Authors convert by hand.
5. **Phone-side settings**, the only route to any on-device config on fr955.
   The work is frozen and incomplete on `wip/phone-settings`, with a safety
   pointer at `backup/pre-integrate`. Treat none of it as working, and do not
   resume without asking the user.
6. Catalogue generation from the SDK (ADR 0005 §1).
7. `catalog.Source.requires` is read by nothing. ADR 0008's check 2 is only
   partly built.
8. **The GUI** (ADR 0002). Unit round-tripping and schema churn make it
   premature (`docs/research/06-authoring-ergonomics.md` §4). If it is ever
   built, build it as a thin client over `wfb/preview.py`, not a second
   renderer.
9. `mypy --strict` and CI. Neither exists.
10. `wfb install`, `package`, `migrate`.
