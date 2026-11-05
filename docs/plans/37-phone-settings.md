# 37 — Phone-side settings for a Store export

**Status: planned 2026-11-05, D1–D6 decided (the orchestrator's
recommendations, the user having asked for the feature outright).** Delete
this file once both slices have shipped (`docs/CLAUDE.md`).

## 0. Why now

`wfb export` packages a face for the Connect IQ Store, and a Store install
is exactly the case where Garmin Connect *does* edit an app's settings
(`docs/limitations.md` §1, "Garmin Connect does not edit a sideloaded
face's settings"; SDK `Core_Topics/Properties_and_App_Settings.html`).
The project generates no `settings.xml`, a decision made when its scope
was sideload only (root `CLAUDE.md` §5: "Phone settings never reach a
sideload; no `.SET` writer" — still true, and no longer the whole story).
Plan 21 built a `settings:` block with `edit: phone` in 2026-09 and it was
removed the same week in favour of the generated on-watch `config:` menu;
its finding stands: `settings.xml` costs about 80 B and is read by Garmin
Connect for a Store install, private beta included.

What exists today, per device class (`ts/src/availability.ts`
`config_menu`/`editor_level`):

| device | edits `config:` with | stores it in |
|---|---|---|
| native editor (API 5.1.0+, fēnix 8…) | Garmin's own face editor (`resources-<device>/configs/watchface.xml`) | `WatchFaceConfig.getSettings` |
| settings menu, no native editor (fr955…) | the generated `getSettingsView` menu (`ts/src/emit/monkeyc/config_menu.ts`) | `Application.Properties`, one `number` per axis, `resources/settings/properties.xml`, `-1` = never chosen |
| neither (fenix5) | nothing; compiled-in defaults | — |

## 1. Decisions (2026-11-05)

- **D1: phone settings edit the same `config:` axes, nothing else.** No
  new YAML; `settings.xml` is derived from `config:` exactly as the menu
  is (`menuAxes`): Style, each colour axis, each data slot, in that order.
  A face without `config:` ships no settings. (Plan 21's author-defined
  `settings:` block is not revived; ADR 0006's amendment of 2026-09-27
  stands.)
- **D2: shipped only to devices that use the settings menu.** The file
  is a per-device resource, `resources-<device>/settings/settings.xml`,
  emitted for each target with the menu and no native editor (the same
  predicate as `config_menu`, per device), and for no other. A
  native-editor device keeps one editing surface, Garmin's, and no
  precedence rule between a phone push and `WatchFaceConfig` has to be
  invented; a device with neither keeps the defaults. If a later need
  wants phone settings beside the native editor, the storage is ready and
  only the read order is to decide.
- **D3: one storage, one reader.** Garmin Connect writes the same
  `Application.Properties` keys the menu writes (`config_style`,
  `config_<colour>`, `config_data_<slot>`), and `applyStoredConfig` stays
  the one place they are read. The app's `onSettingsChanged` (constraint
  12: it fires for a Garmin Connect push, never for an on-watch edit) calls
  the view's `applyStoredConfig()` then `WatchUi.requestUpdate()`; the
  static buffer repaint is already inside `applyStoredConfig`. Guarded like
  `getSettingsView`: inside `if (!(Application has :WatchFaceConfig))`
  where the build also has native-editor targets.
- **D4: `properties.xml` goes per device too, defaulting to the declared
  default's index**, not `-1`. A data slot's option list is per device
  (`Layout.CONFIG_DATA_<slot>_TYPES`), so the index of the declared
  default differs per device, and Garmin Connect's list control needs the
  stored value to be one of its entries to show the right one. The file
  moves from `resources/settings/` to `resources-<device>/settings/` for
  every menu device; `applyStoredConfig`'s range check is unchanged, so an
  out-of-range or wrong-typed value still keeps the default. A build whose
  menu devices all share one option list still gets one file per device;
  simplicity over de-duplication.
- **D5: labels are string resources, shared.** `settings.xml` must name
  strings (`title`, `listEntry`), so `resources/strings/strings.xml`
  (`sharedStrings`) gains: one title per axis (`ConfigTitle<Axis>`), the
  existing style labels (`configLabelStrings` ids reused), one string per
  colour option label per axis, and one per complication-type label any
  menu device's slot can offer (`ConfigType<Constant>`, `humanise(type)`,
  the union over devices — one shared file, the few unused strings on a
  device cost bytes in the resource section only). Strings are shared
  because per-device string files would duplicate the Style and colour
  labels on every device.
- **D6: `wfb export` says so.** Its summary gains one line naming the
  devices that carry phone settings and how many axes (`phone settings:
  3 axes on fr955`), or `phone settings: none (every device has the
  native editor)`; `wfb build` prints nothing new, since phone settings
  never reach a sideload. No new lint.

## 2. What is emitted

For each menu device `D` (`!has(CONFIG_SYMBOL) && has(SETTINGS_MENU_SYMBOL)`):

```xml
<!-- resources-D/settings/properties.xml -->
<properties …>
    <property id="config_style" type="number">1</property>          <!-- the declared default's index -->
    <property id="config_accent" type="number">0</property>
    <property id="config_data_top" type="number">2</property>        <!-- index into Layout.CONFIG_DATA_TOP_TYPES on D -->
</properties>

<!-- resources-D/settings/settings.xml -->
<settings …>
    <setting propertyKey="@Properties.config_style" title="@Strings.ConfigTitleStyle">
        <settingConfig type="list">
            <listEntry value="0">@Strings.ConfigStyle0</listEntry>   <!-- configLabelStrings' ids -->
            …
        </settingConfig>
    </setting>
    <setting propertyKey="@Properties.config_accent" title="@Strings.ConfigTitleAccent">
        <settingConfig type="list">
            <listEntry value="0">@Strings.ConfigAccent0</listEntry>
            …
        </settingConfig>
    </setting>
    <setting propertyKey="@Properties.config_data_top" title="@Strings.ConfigTitleDataTop">
        <settingConfig type="list">
            <listEntry value="0">@Strings.ConfigTypeSteps</listEntry>  <!-- D's slotTypes order -->
            …
        </settingConfig>
    </setting>
</settings>
```

The `.iq` an export writes carries each device's compiled settings; the
slow suite's export test lists the archive (`7z l`) and expects a settings
entry for a menu device and none for a native-editor device — that is the
check that D2's per-device file is honoured by the toolchain. Behaviour in
Garmin Connect itself is a §5 check on the user's phone.

## 3. Slices

Two agents at once; both read this file.

1. **Emission and runtime** (`ts/src/emit/resources.ts` per-device bundle,
   `ts/src/emit/monkeyc/config_menu.ts` for the two resources and the
   strings, `ts/src/emit/project.ts` to drop the shared `properties.xml`,
   `ts/src/emit/monkeyc/app.ts` for `onSettingsChanged`): D2–D5.
   Byte-identical output for a face without `config:` and for a build
   whose targets all have the native editor (goldens prove it); a build
   with a menu device changes its `properties.xml` location and default,
   gains `settings.xml` and strings, and the app gains `onSettingsChanged`
   — the golden diff is listed by cause in the commit message. Tests
   (`ts/test/phone-settings.test.ts`): the two resources' text for
   `examples/features/config` on fr955 and on a two-device build where the
   slot lists differ; no settings for `fenix8solar47mm`; `onSettingsChanged`
   present only with a menu device, guarded when native targets are in the
   build; every `@Strings.` and `@Properties.` reference resolves to an
   emitted id (parse both files). `./wfb build examples/features/config`
   and `examples/features/slots` warning-free on the three devices, memory
   before/after on fr955 in the commit message; `wfb export` of `config`
   and the `.iq` listed with `7z l`. The slow suite's export test extended
   per §2.
2. **The CLI line and the record** (`ts/src/cli.ts` export summary,
   `docs/`): D6; `docs/guide/configuration.md` gains "Phone settings, for
   a Store install" beside "The settings menu…" (what is edited, where it
   shows in Garmin Connect, that a sideload never sees it, that native-
   editor watches use Garmin's editor instead); `docs/guide/preview-and-cli.md`'s
   export section gets the summary line; `docs/limitations.md` §1's
   "Garmin Connect does not edit a sideloaded face's settings" rewritten
   to the current truth and §2's phone-settings row removed; ADR 0006
   amended with a dated note (phone settings return, derived from
   `config:`, for menu devices on a Store export); root `CLAUDE.md` §5's
   "Phone settings never reach a sideload; no `.SET` writer" extended with
   the export; `docs/lore/roadmap.md` line; `docs/README.md` hub if it
   lists config surfaces. A `cli.test.ts` case for the export line's two
   wordings (the export itself needs `monkeyc`, so the line's text is
   tested through the function that composes it, extracted for that).

## 4. Out of scope, recorded

- Phone settings on a native-editor device (precedence with
  `WatchFaceConfig`): not built, D2.
- Author-defined settings beyond `config:` (plan 21's `settings:`).
- Numeric or free-text settings: `config:` has none.
- A `.SET` writer for sideloads: the format is undocumented (plan 21 D3).

## 5. Checks before "done"

- `npm test`, `npm run typecheck`, `npm run test:slow` (the export test
  included), on the merged tree.
- By the user, with a Store beta of `examples/features/config` on the
  fr955: Garmin Connect shows the three axes, a change applies without
  restarting the face (`onSettingsChanged`), the on-watch menu shows the
  phone's choice afterwards and vice versa, and the fēnix 8 shows no phone
  settings. Record the outcome in `docs/limitations.md` §1.
