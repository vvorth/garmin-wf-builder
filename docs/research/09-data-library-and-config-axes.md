# 09 — A colour library, colour schemes, and a selectable data library

- **Date:** 2026-09-11
- **Ask:** a YAML sketch (reproduced in §1) proposing a reusable `data_library`
  of authored groups, a labelled `color:` library, named `color_scheme:`s, and
  a `config:` block with four axes — `colors`, `accent_color`, `data_color` and
  a `data:` block holding several independent selectors — plus the on-watch UI
  the stock fēnix faces have: *Apply, Data, Accent Color, Data Color, Bkgd.
  Color*, each with instant preview and an animated highlight.
- **Backed by:** `probes/config-axes/`, which builds all of it at once,
  warning-free, on all three targets. Every "verified" below is a real
  `monkeyc` result; every "UNVERIFIED" is a behavioural claim this container
  cannot test.

**Short answer.** Four of the five menu entries map exactly onto what Garmin
offers, and the fifth — a *library of authored groups* the wearer picks between
on the watch — is the one thing the native editor structurally cannot do.
Nothing about that is a spelling problem in the sketch; it is the shape of the
`<watchface-config>` resource. There are three ways to get it anyway, and they
have genuinely different costs. §6 recommends one.

---

## 1. The sketch, and what each part costs

| Sketch | Verdict | Where |
|---|---|---|
| `color:` — named colours with a `label:` | **Yes**, and it should extend `palette:` rather than sit beside it | §2 |
| `color_scheme:` — named role→colour sets | **Yes**, riding the **Styles** axis | §3 |
| `config.colors` — a scheme picker | **Yes**, but the editor's menu is labelled *Styles*, not *Bkgd. Color* | §3 |
| `config.accent_color` / `config.data_color` | **Already shipped**; only the `choices:` spelling changes | §2 |
| `config.data.<selector>` over **Garmin metrics** | **Yes** — this is the native Data axis, and it is exactly the UI described | §4 |
| `config.data.<selector>` over **`data_library` groups** | **Not on the Data axis, ever.** Three workarounds, all with real costs | §5 |
| `elements: { type: config.data }` — a slot placed in the layout | **Yes**, as one authored *template* per slot rather than N library items | §4 |
| The five-entry on-watch menu, with previews | **Yes**, and `getComplicationDrawable` is what makes the highlight animate | §4 |
| Any of the above on **`fr955`** | **No.** fr955 has no editor. Phone settings is the only route | §5.2, §7 |

---

## 2. The colour library is pure sugar, and it belongs in `palette:`

`<color>` inside `<accentColors>`/`<dataColors>` takes a **string resource
reference** for its label (`label="@Strings.aqua"`), so a labelled colour
already implies a generated `<string>` entry — the compiler emits these today
(`ConfigDataColor0`, …). What the sketch adds is a *name* for the colour so the
same entry can be reused by several axes and by elements, instead of being
retyped per choice as it is in `examples/config/face.yaml`.

The design note that matters: **this project already has a colour namespace**,
`palette:`, and a second one would be a drift hazard of exactly the kind
`$defs/commonElement` was (CLAUDE.md §6). `palette:` is `name: "#RRGGBB"`
today; accepting `name: { value: "#RRGGBB", label: "Aqua" }` alongside the
short form costs one `oneOf` in the schema, keeps every existing design valid,
and lets `config:` choices become `- palette.aqua`. The sketch's `color.white`
and this project's `palette.white` would otherwise be two spellings of one
concept.

Two things fall out for free once labels live on the entry:

* `default:` can be a `palette.<name>` reference too, so the "default must be
  one of `choices:`" check (already implemented) becomes an identity test
  rather than a colour-value comparison.
* The existing `palette-dither` lint keeps working unchanged — it checks the
  colour, and the colour has not moved.

---

## 3. A colour *scheme* must ride Styles, because no colour axis carries more
   than one colour

`Settings` has exactly four fields — `styleId`, `complicationSettings`,
`accentColor`, `complicationColor` (`Toybox/Application/WatchFaceConfig/
Settings.html`) — and `resources.xsd`'s `watchfaceConfigType` is an `xs:all`
of exactly four optional children. **There is no background-colour axis and no
fifth axis of any kind.** A "Bkgd. Color" entry on a stock Garmin face is
native firmware, not something a Connect IQ face can add.

`accentColor` and `complicationColor` each carry **one** colour. A scheme is
several colours moving together (`bg`, `fg`, `dim`), so it cannot ride either.

**Styles is the only axis Garmin gives no meaning to.** `styleId` is an opaque
`Number`; what it selects is the face's business. So:

```yaml
config:
  colors:
    default: color_scheme.dark
    choices: [color_scheme.dark, color_scheme.light]
```

becomes one `<style id="N" label="@Strings.…"/>` per scheme, and a generated
`resolveScheme()` that sets one view field per role. Verified in the probe;
every `color: config.colors.fg` then compiles to a field read instead of a
constant, which is the only codegen consequence.

**Cost, measured at a fixed path:** +9 B data and +61 B `.prg` per style, and
**zero** code growth. Styles are as close to free as anything in this project.

Three consequences worth writing into the format up front:

1. **Every scheme must declare the same role set**, or `config.colors.dim` is
   sometimes undefined. A build-time check, cheap, and the diagnostic writes
   itself.
2. **A `static:` buffer holding scheme colours must repaint on a config
   change.** The machinery exists — `examples/config/face.yaml` exists
   precisely to exercise it — but a scheme touches far more of a face than one
   accent ring, so this stops being an edge case.
3. **The editor's menu entry will read whatever Garmin calls the Styles axis**,
   not "Bkgd. Color". `<styles>` has no label attribute (only each `<style>`
   does), so the group name is not author-controllable. The list *contents*
   will read "Dark", "Light" as intended.

---

## 4. The Data axis is exactly the UI described — for Garmin metrics

The sketch's description of the flow — *"cycle through all data fields to
change (animated pulsing like on native watchface), on select gives the ability
to cycle through possible options for selected data field (with instant
preview)"* — is a precise description of Garmin's own complication-slot
editor, and all of it is available:

| Piece of the flow | Mechanism | Status |
|---|---|---|
| several independently-editable data fields | `<data><complication id="1"/><complication id="2"/>…` | verified |
| which field the wearer pointed at | `WatchFaceDelegate.onTap` + `setSelectedComplication` | verified, shipped for the colour axes already |
| the animated highlight on that field | `getComplicationDrawable` → `ComplicationDrawableRef` | **verified buildable in this probe; previously a documented gap** |
| the option list for that field | `<type>Complications.COMPLICATION_TYPE_*</type>` | verified |
| instant preview of a change | `onWatchFaceConfigEdited` → re-read → `requestUpdate` | verified |
| remembering it per saved configuration | the axis itself | inherent |

Two findings make the authored side much smaller than the sketch assumes.

**`Complications.Id.getType()` works on the id the wearer picked.** So one
authored *template* can serve every metric in the slot's list: the icon comes
from a generated `switch` over the chosen type (the same shape as
`WfbWeather.chooseIcon`, feeding the existing `IconGlyphs.glyph` and
`METRIC_ICON` machinery), and only the glyphs the slot's `choices:` can
actually produce need baking. Verified under `-l 3`.

**`Complication.shortLabel` and `.unit` come back with the value**, so a slot
can label itself without the author enumerating labels at all.

Together those collapse the sketch's `data_library: {item1, item2, item3}` into
a single authored group per slot — which is also why the element should
probably be spelled as one element type (`complication_slot`, already on the
Phase 3 list) rather than a `config.data` indirection into a library.

**The one piece of real work** is `getComplicationDrawable`. This project draws
straight to the `Dc` and owns no `Drawable` subclasses, so the probe generates
a tiny one that delegates back to the view's own per-slot draw method — one
implementation of what a slot looks like, two callers. `+134 B data, +414 B
code`. The SDK sample is what makes it non-optional if the animation is wanted:
its own comment says the view must **hide** the slot while the system pulses
it, or it is drawn twice.

---

## 5. Author-defined selectable content: three routes, none of them the Data axis

`<complication>`'s children are `Complications.COMPLICATION_TYPE_*` values or
`allowAny="true"`, and nothing else (`resources.xsd`, `complicationWatchfaceType`).
**There is no way to put author-defined content in that list.** This is the
same finding as research 08 §4, re-confirmed against the grammar rather than
the prose.

So a `data_library` of authored groups — an icon-and-text in one option, a
graph in another — needs one of these:

### 5.1 The Styles cross-product

One `styleId` decoded by arithmetic into several independent axes:
`scheme = id / 4`, `pick1 = (id / 2) % 2`, `pick2 = id % 2`. Verified in the
probe with 12 styles.

* **Memory is a non-issue**: ~9 B data per style, no code growth. Even 64
  combinations cost under 600 B.
* **The UX is the problem.** The editor shows one flat list, so 3 schemes × 2 ×
  2 is twelve entries reading "Dark / Ring / A". The wearer cannot change one
  axis without re-finding the right combination, and the *label text* is
  combinatorial too.
* It also **competes with §3**: schemes and content selection cannot both own
  the axis without multiplying.

Honest verdict: fine for **one** author-defined axis with a handful of options
(and then schemes must give up Styles, or be folded into the same product).
Bad as the general mechanism.

### 5.2 Phone-side settings (`properties.xml` + `settings.xml`)

`<settingConfig type="list">` with `<listEntry value="0">@Strings.…</listEntry>`
against a `number` property (`Core_Topics/Properties_and_App_Settings.html`) is
a labelled dropdown per selector, with **no cap on the number of selectors, no
cap on options, and no cross-product**. It is also the **only** mechanism in
this document that works on **`fr955`**.

* Not on the watch — edited in Garmin Connect or Garmin Express.
* `onSettingsChanged` fires only for Connect pushes (CLAUDE.md constraint 12),
  which is exactly when these change, so the existing invalidation rule is
  already right.
* **Not per-configuration.** See §5.4.
* Still unbuilt in this project (Phase 3 item 4), so this is new work — but it
  is the work that closes fr955's "no configuration at all" gap, which is
  currently the largest user-facing hole in the format.

### 5.3 Hold-to-cycle, i.e. the existing `carousel`

Already shipped, already persists in `Application.Storage`, already works on
every target, and is the only on-watch route for author-defined content on
`fr955`. Research 08 §4 records that the user declined hold-to-cycle **for the
Styles axis** specifically, on the grounds that a second invisible selection
mechanism competing with the editor is worse than one story. That reasoning
still holds; it is listed here for completeness, not as a recommendation.

### 5.4 A hard limit worth knowing before choosing

**There is no way to ask which saved configuration is active.**
`getSettings(null)` returns the active `Settings`, and `Settings` carries no
id; `getIds()` returns ids, and `Id` exposes only `equals`. Therefore:

* everything on the **four axes** is per-configuration — the wearer's four
  saved faces genuinely differ;
* anything the face persists **itself** (Storage, properties) is **global
  across all four**.

So §5.2 and §5.3 both leak between the wearer's saved configurations, and §5.1
does not. That is a structural difference, not a quality-of-implementation one,
and it is the strongest argument for spending Styles on the thing the wearer
most expects to differ between saved faces.

---

## 6. Recommendation

Take the sketch almost whole, and move exactly one thing.

1. **`palette:` grows an optional `{ value, label }` long form.** The sketch's
   `color:` block, merged into the namespace that already exists. Small, safe,
   independently useful.
2. **`color_scheme:` + `config.colors` ship on the Styles axis, one style per
   scheme.** This is the best available use of the one free-form axis, it is
   what the wearer most expects to vary between saved configurations, and it
   is nearly free.
3. **`config.accent_color` / `config.data_color` keep working**, with
   `choices:` accepting `palette.<name>`.
4. **`config.data.<selector>` ships as native complication slots**, with one
   authored template per slot, the icon inferred from `Id.getType()` and the
   label available from `shortLabel`. Add `getComplicationDrawable` so the
   editor's highlight animates. This is the sketch's "Data" menu entry, exactly
   as described, and the `data_library` collapses into one template per slot.
5. **Author-defined *layout* alternatives (a graph here, a ring there) go to
   phone settings (§5.2), not to the editor.** That also gives `fr955` its
   first configuration of any kind, and it is the only option with no
   combinatorial blow-up.

What that costs the sketch: `data_library` stops being "N interchangeable
groups the watch editor cycles" and becomes either one template per slot (on
the watch, for metrics) or a phone-side list (anywhere, for layouts). Everything
else survives.

**Ordering, if all of it is wanted:** (1) and (3) are hours; (2) is the
interesting one and is self-contained; (4) is the largest because it needs a
new element type plus the `Drawable` seam; (5) is a separate feature
(`settings.xml`/`properties.xml`) that stands on its own merits.

---

## 7. What this does not answer

Everything about how the editor **behaves**. No simulator runs in this
container (`docs/limitations.md` §2) and there is no watch, so whether the
highlight animates, whether previews are instant, whether the Data axis lists
slots usefully, and whether four saved configurations behave as expected are
all **UNVERIFIED**. What is verified is that every mechanism above compiles
warning-free under `-l 3` on all three targets, what it costs, and that none of
it can crash `fr955`.

One further unknown, flagged because it looks like a shortcut and may not be:
deriving a scheme from a colour the wearer picked on the **data-colour** axis
(matching the returned `ColorType` against the declared choices) would free
Styles for content selection. It depends on the returned value being exactly
the declared one, which is undocumented, and it puts a background choice under
a menu labelled "Data Color". Not recommended, recorded so it is not
rediscovered as a clever idea.
