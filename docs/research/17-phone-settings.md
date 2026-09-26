# 17 — Phone-side settings, and what reaches a sideloaded face

**Question.** Research 09 §5.2 found phone-side settings (`properties.xml` +
`settings.xml`) to be the only configuration mechanism that reaches `fr955`,
and ADR 0006 left it "Open". A first implementation was started and frozen
(§5). Before resuming it: does the mechanism work for **this project's own
use**, which is personal sideload (root `CLAUDE.md` §1)? If not, what does?

**Status:** research; fed plan 21 (`git show 0e741d9:docs/plans/21-phone-settings.md`), now built as `settings:` (`docs/guide/settings.md`). Every
behavioural claim is marked **VERIFIED** (SDK, device files, or the probe
at `probes/phone-settings/`) or **UNVERIFIED**.

---

## 1. The mechanism

`$CIQ_SDK/doc/docs/Core_Topics/Properties_and_App_Settings.html`
(VERIFIED):

- A **property** is a typed key/value compiled into the app from
  `<properties>` (`number`, `long`, `float`, `double`, `boolean`, `string`,
  `array`). It is read with `Application.Properties.getValue` (API 2.4.0)
  and written with `setValue`.
- A **setting** describes how the phone shows one property: `<setting
  propertyKey title [prompt]>` with one `<settingConfig type=…>`. `list`,
  `numeric` and `date` require a `number` property; `boolean` requires
  `boolean`; the text types require `string`. `list` takes `<listEntry
  value>@Strings.X</listEntry>` children. Settings can sit in a `<group>`,
  which can hide itself unless a boolean is on (`enableIfTrue`).
- The phone pushes a change; the running app gets
  `AppBase.onSettingsChanged()`. This is the existing constraint 12, which
  already says to invalidate caches there.
- `monkeyc` writes a `<device>-settings.json` next to the `.prg`,
  describing every setting (key, type, default, title string, options)
  (VERIFIED, probe).
- The Garmin developer FAQ warns that the phone has returned values of the
  wrong type, so a read should be type-checked, not just null-checked
  (`forums.garmin.com/developer/connect-iq/w/wiki/4/new-developer-faq`,
  "My app uses app settings, and it sometimes crashes").

Research 09 §5.4's structural point still holds (VERIFIED there): nothing
reports which of the wearer's four saved configurations is active, so **a
property is global across all four**, while the native editor's axes are
not.

## 2. The finding: phone settings do not reach a sideloaded app

The developer FAQ says it directly (VERIFIED, fetched 2026-09-26):

> App settings allow user to configure an app via the Connect IQ Store app,
> Garmin Express, or Garmin Connect Mobile, and depend on the Connect IQ
> App Store to function properly. When an app is side loaded, this
> connection to the Connect IQ App Store is never established. If you have
> an app that uses app settings that needs to be tested, you may submit the
> app to the Connect IQ App Store and test out the settings features while
> the app is either in a beta state or pending approval.

Forum threads agree, across the years (VERIFIED, fetched 2026-09-26):
`…/f/discussion/6338/prg-and-settings`,
`…/f/discussion/253496/is-there-any-way-to-change-settings-in-sideloaded-app`,
`…/f/discussion/374864/settings-file-for-custom-not-published-garmin-watchface-app-in-prg-format`,
`…/f/discussion/429848/solved-settings-connect-iq-app-for-sideloaded-app---is-this-possible`.

So research 09 §5.2's "only route to fr955" is true for a **Store** app.
For this project's sideload-only scope, as things stand, **a `settings:`
block would compile, ship its defaults, and never be editable.** That is the
fact the frozen WIP did not know, and it changes the plan.

## 3. Three routes that do reach a sideloaded face

### 3.1 A private beta app in the Connect IQ Store

Upload the face as a **beta** app: only the uploading account can see and
install it, and settings then work through the Connect IQ app (FAQ above;
thread 374864: "only you"). VERIFIED as documented behaviour; not tried.

- **Cost to this project:** a `.iq` package (`monkeyc -e`, one export
  covering every target) is exactly the unbuilt `wfb package`
  (`docs/limitations.md` §2). Also a Garmin developer account, a manual
  upload per version, and an app id that stays stable across versions
  (the manifest `id` already is).
- **Scope:** it changes "personal sideload" into "private Store beta".
  That is the user's call (root `CLAUDE.md` §7: scope changes are asked,
  not assumed).
- **Reach:** every target, `fr955` included, since this is the phone path.

### 3.2 A hand-made `.SET` file copied next to the `.prg`

The watch keeps an app's property values in `GARMIN/APPS/SETTINGS/<NAME>.SET`,
where `<NAME>` matches the sideloaded `.prg`'s file name, case-sensitive.
Copying a `.SET` there with the `.prg` makes the app start with those values
(thread 429848, a user confirming it worked; thread 6338; thread 253496).
VERIFIED as reported by several developers; not tried here.

- **How people make one:** run the app in the simulator, edit values in
  *File > Edit Persistent Storage > Edit Application.Properties data*, and
  copy the `.SET` the simulator writes to its temp directory
  (`…/com.garmin.connectiq/GARMIN/APPS/SETTINGS/`, thread 374864). **The
  simulator does not run in this project's environments at all** (root
  `CLAUDE.md` §3). The user could use it on their host only if app pushes
  worked there, and they do not.
- **The format is binary and undocumented.** One developer wrote an editor
  (thread 429848, linked on pastebin.com, which the sandbox firewall
  blocks). Generating `.SET` files from `wfb` means reverse-engineering the
  format, from that tool or from real `.SET` files on the user's watch.
  UNVERIFIED how hard that is.
- **UX:** editing means building a file, plugging the watch in and copying
  it. That is no better than rebuilding the face with different defaults,
  which works today (`properties.xml` defaults are compiled in). So a
  `wfb` `.SET` writer's only real advantage is keeping one `.prg` and
  swapping settings files.

### 3.3 An on-device settings menu (`AppBase.getSettingsView`)

`getSettingsView() as [Views] or [Views, InputDelegates] or Null`: "Override
to provide the settings View and Input Delegate of the application. This
function is only applicable to watch faces and data fields." API 3.2.0
(`$CIQ_SDK/doc/Toybox/Application/AppBase.html`, VERIFIED). The SDK chapter
says the watch face's settings are "available to the user in the system
Watch Face menu" (VERIFIED). It needs no phone and no Store, so **it is the
one route that works for a sideload with no extra tooling.**

- **Availability** (per-device `api.debug.xml`, VERIFIED): `getSettingsView`
  is present on `fr955` and `fenix8solar47mm` and absent on `fenix5`.
  `WatchUi.Menu2` is present on all three. Like every other target-only
  API here (constraint 6d), an app that overrides it still compiles
  warning-free for a device that lacks it, where it is simply never called
  (VERIFIED, probe variant C on `fenix5`).
- **It is the watch's own menu UI**, driven by `Menu2`/`ToggleMenuItem`/
  `MenuItem`, writing `Properties.setValue` and then applying the value
  itself. `onSettingsChanged` is not called for a local write; the probe
  calls it by hand.
- **It reverses a recorded user decision.** ADR 0006 (2026-09-04): "target
  the native editor plus phone-side settings only. **No generated
  on-device settings menu.**" That decision was taken on the belief that
  phone settings would reach `fr955`. §2 removes that premise. The user
  reversed it on 2026-09-27 (ADR 0006 tenth amendment).
- **Whether a watch face's settings view is subject to the watch-face memory
  limit, or to another one, is UNVERIFIED.** The code counts toward the
  face's own `.prg` either way (below).
- **Whether the Watch Face menu entry appears on `fr955` and a fēnix 8 that
  also has the native editor**, and how the two coexist, is UNVERIFIED:
  there is no simulator, and neither has been tried on a watch.

## 4. What it costs: the probe

`docs/research/probes/phone-settings/` is a minimal face showing the time,
built in three variants from one source set by annotation
(`excludeAnnotations`), each `-l 3 -O 3z`, typecheck strict, manifest
3.1.0. **VERIFIED**, `--build-stats`, 2026-09-26:

| Variant | fr955 / fēnix 8 data + code | vs. A | fenix5 data + code |
|---|---|---|---|
| A: no properties | 376 + 285 = 661 B | — | 887 + 383 |
| B: one boolean property + setting, read in `initialize`/`onSettingsChanged` | 400 + 373 = 773 B | **+112 B** | 931 + 493 |
| C: B plus `getSettingsView` with a one-toggle `Menu2` and its delegate | 503 + 617 = 1 120 B | **+459 B** | 1 207 + 803 |

Builds are warning-free on all of `fenix8solar47mm`, `fenix8solar51mm`,
`fr955` and `fenix5`, except variant A's own "`_view` is not used" warning:
A is a control, and the field exists only for B and C. Per-setting cost
beyond the first is not measured. The generated `-settings.json` confirms
the setting was compiled in.

So the mechanism itself is cheap: roughly a tenth of a kilobyte for the
property plumbing, and under half a kilobyte for a basic on-watch menu,
against a 128 KB limit on the verification devices.

## 5. The frozen work

The docs said this work was on a branch, `wip/phone-settings`. **That
branch had been deleted.** The work survived only as an unreachable stash
commit, `1984415` ("WIP on main: a0fd35d", 2026-09-11), older than git's
default two-week prune window. It was one `gc` away from being lost. It is
pinned again as `wip/phone-settings` (2026-09-26).

What it contains (VERIFIED, `git show --stat 1984415`): about 1 000 lines
across the schema, `wfb/ir.py`, `wfb/emit/{monkeyc,resources,project,
manifest}.py`, `wfb/layout.py` and `wfb/lint.py`. It adds a top-level
`settings:` block with three kinds (`boolean`, `color_scheme` stored as a
`number` list index, and `complication`), read through `settings.<name>`
in expressions and `slot: settings.<name>`. It also emits `properties.xml`/
`settings.xml` shared across devices and adds an `applySettings` re-read on
`onSettingsChanged`.

It **cannot be merged or rebased usefully**. It predates the builder split
(`wfb/ir.py` is now the `wfb/ir/` package), the emitter split
(`wfb/emit/monkeyc/`) and the kinds registry, and it references
`type: carousel`, which has since been removed. Its value is the design:
the schema shapes, the XSD facts in its docstrings (`list` only on a
`number` property) and the "global across saved configurations" caveat.
The plan reuses those and none of its code.

## 6. Recommendation

1. **The declaration is the same whatever the route:** a top-level
   `settings:` of typed entries (`boolean`, `choice` over author labels,
   `number` with min/max, `color_scheme`), read as `settings.<name>` in
   expressions. Always emit `properties.xml` for defaults, and emit
   `settings.xml` too, since it costs nothing and is ready for a Store
   upload.
2. **Make the edit route explicit per face**, since only the user knows
   which one they use: `edit: [phone]`, `[watch]` or both. `watch` emits the
   `getSettingsView` menu. That reverses ADR 0006's no-menu decision; the
   user approved it on 2026-09-27, along with items 3 and 4.
3. **Recommended default for this project: `edit: [watch]`**, the on-device
   menu. It is the only route that works for a sideload today, it reaches
   `fr955` (which has no native editor), and it costs about 0.5 KB. `phone`
   becomes useful the day `wfb package` and a beta upload exist, and then
   costs nothing extra.
4. **Do not build a `.SET` writer** unless the user wants swappable
   settings files enough to justify reverse-engineering an undocumented
   binary format.
5. Keep documenting that a setting is **global across the four saved
   configurations** and that `fenix5` gets defaults only (no
   `getSettingsView`).
