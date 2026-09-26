# 21 — `settings:`: wearer settings on the watch, and on the phone

**Status: proposed (2026-09-26), not started. It waits on decisions D1–D3.**
Delete this file once every slice has shipped (`docs/CLAUDE.md`).

Research: `docs/research/17-phone-settings.md`, with its probe at
`docs/research/probes/phone-settings/`. In short:

- Phone settings (`settings.xml`) **do not reach a sideloaded app**. Garmin
  Connect only edits settings for Store apps, private beta included.
- An on-watch settings menu (`AppBase.getSettingsView`, API 3.2.0) does
  reach a sideload, and reaches `fr955`. It costs about 0.5 KB.
- The frozen WIP (`wip/phone-settings`, re-pinned from an orphaned stash
  commit) is design reference only; none of its code is reused.

## 1. Decisions for the user

- **D1: allow a generated on-watch settings menu.** This reverses ADR
  0006's 2026-09-04 decision ("No generated on-device settings menu"),
  whose premise was that phone settings would reach `fr955`. Research 17 §2
  shows that premise is false for a sideload. *Recommended: yes.* Without
  it, `settings:` only changes compiled-in defaults, which a rebuild
  already does.
- **D2: stay sideload-only, or also target a private Store beta.** A beta
  makes phone editing work, but needs `wfb package` (a `.iq` export), a
  developer account and a manual upload per version. *Recommended: build
  `settings.xml` anyway* (it costs nothing and is ready for an upload), but
  do not build `wfb package` in this plan.
- **D3: no `.SET` file writer.** The format is binary and undocumented.
  It is only worth reverse-engineering if swappable settings files matter
  more than rebuilding. *Recommended: no.*

## 2. The format

```yaml
settings:
  show_seconds:
    label: "Show seconds"
    type: boolean
    default: true
  ring:
    label: "Ring shows"
    type: choice
    choices: { steps: "Steps", battery: "Battery", hr: "Heart rate" }
    default: steps
  night_scheme:
    label: "Night colours"
    type: color_scheme          # picks a declared color_scheme: entry
    choices: [dark, red]
    default: dark
  edit: [watch, phone]          # optional; default [watch]
```

- **Read as `settings.<name>`** in any expression: `boolean` is a
  Boolean; `choice` compares with its keys (`settings.ring == "steps"`,
  compiled to a `Number` index compare); `color_scheme` exposes
  `settings.<name>.<role>`, the same shape `config.colors.<role>` has.
- **`number`** (with `min:`/`max:`) is left out of the first slice: `Menu2`
  has no numeric entry widget, so it would be phone-only.
- **`complication`** (the WIP's third kind) is left out: the Data axis
  already does it on the fēnix 8, and a phone-side picker over 42
  complication types is a large, separate list.
- `edit: watch` emits `getSettingsView` and `edit: phone` emits
  `settings.xml`. `properties.xml` (the defaults) is emitted whenever
  `settings:` exists.
- Every reader type-checks the stored value and falls back to `default:`
  (research 17 §1, the FAQ's wrong-type warning). A setting is never
  absent.

## 3. What it emits

| Piece | Where | Notes |
|---|---|---|
| `resources/settings/properties.xml` | shared | `boolean` → `boolean`, `choice`/`color_scheme` → `number` (the list index, since `list` requires `number`) |
| `resources/settings/settings.xml` + strings | shared, `edit: phone` | `<settingConfig type="boolean">`, `type="list"` with `<listEntry>`; labels become string resources |
| View fields + `applySettings()` | shared view | one read per setting, called from `initialize` and after any change |
| `onSettingsChanged` | app | `applySettings()`, invalidate `static:` buffers, `requestUpdate()` (constraint 12) |
| `getSettingsView` + a `Menu2` delegate | app, `edit: watch` | `ToggleMenuItem` for `boolean`; a `MenuItem` whose sublabel is the current choice for `choice`/`color_scheme`, cycling on select. The delegate writes `Properties.setValue` and then calls the same path as `onSettingsChanged` |

`wfb preview --set show_seconds=false` renders a non-default setting,
sharing the `--set` flag with sample-data overrides if those land first.

## 4. Slices

1. **`settings:` with `boolean` and `choice`, `properties.xml` only.**
   Schema, IR (`wfb/ir/builder/`), `settings.<name>` in `wfb/expr.py`,
   emitted reads, `onSettingsChanged`, preview `--set`, guide chapter
   `docs/guide/settings.md`. A face without `settings:` is byte-identical
   (`tools/snapshot.py`). Warning-free on the three targets, and memory
   measured against the probe's +112 B.
2. **`edit: watch`**, the `getSettingsView` menu (needs D1). Measured
   against the probe's +459 B. Friendly lint `settings-menu-unsupported`
   (a note) for a target without `getSettingsView`, e.g. `fenix5`: that
   device keeps the defaults.
3. **`edit: phone`**, `settings.xml` and strings. Checked against the
   generated `-settings.json`. The guide says plainly that phone editing
   needs a Store (beta) install.
4. **`color_scheme` settings**, sharing `color_scheme:`'s resolution with
   the Styles axis. A lint warns when one scheme set is chosen both by the
   Styles axis and by a setting.

## 5. Docs, in the same commits

ADR 0006 gets a dated amendment when D1 is decided, closing its "Open"
phone-settings bullet. Also update `docs/limitations.md` §2 (the
phone-settings row), `docs/guide/configuration.md` (a pointer),
`docs/lore/roadmap.md`, and root `CLAUDE.md` §5 (user decisions) and §6.
Delete `wip/phone-settings` once slice 1 lands.

## 6. Checks only the user can run

- That the face's settings entry appears in the watch's Watch Face menu on
  `fr955`, and on a fēnix 8 next to the native editor, and that a change
  applies at once.
- Which memory limit the settings view runs under.
