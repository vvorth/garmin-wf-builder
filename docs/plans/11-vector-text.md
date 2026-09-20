# Plan 11 — Vector fonts, and angled/radial text

**Status: slices 1 and 2 built (§5). Slice 3 open.** Delete this file when
slice 3 lands (`docs/CLAUDE.md`). What slices 1 and 2 shipped is documented
in `docs/format.md`, `docs/limitations.md` §2 and `docs/lore/codegen.md`;
this file remains only as the design record for the slice still to come.

Builds the capability `docs/research/12-vector-fonts.md` §5.2 identifies as
otherwise unreachable: **text that turns**. `Dc.drawAngledText` and
`Dc.drawRadialText` accept a `Graphics.VectorFont` and refuse a resource font,
so rotated and curved text needs a device-resident scalable face and nothing
else will do.

**The user's decisions** (asked and answered before this plan was written):

| Question | Decision |
|---|---|
| how a face is declared | a `fonts:` entry with `face:` instead of `source:` |
| how rotation is spelled | one `curve:` block on `text`, with `style: angled\|radial` |
| the unavailability opt-in | `if_unavailable:` on **both** the font and the element; the element wins |
| scope | all three slices below |

**No automatic fallback.** §5.3 of the research proposed a `fallback:` to a
baked font on the 92 devices that have no vector fonts. That is explicitly
**rejected**: a design that asks for a face a target does not have is a build
error. An author who wants the element to be optional says so, in one word,
per element.

---

## 1. The four gates, and where each is decided

`docs/research/12-vector-fonts.md` §3 enumerates them. This plan assigns each
to a stage:

| # | Gate | Decided | Mechanism |
|---|---|---|---|
| 1 | `Graphics.getVectorFont` exists on the device | build, per device | `Device.has_symbol` |
| 2 | the device publishes ≥1 scalable face | build, per device | `simulator.json` `type: "system_ttf"` |
| 3 | the *specific* face is one of them | build, per device | the `name` field of those entries |
| 4 | the call returns non-null | **runtime** | `if (font != null)` |

Gates 1–3 are build-time truth, per device, and this is what `if_unavailable:`
governs. Gate 4 is not: the platform offers no way to fail at runtime, so a
null font draws nothing, in **both** modes. `error` is a build-time
guarantee, not a runtime one, and the docs must say so plainly rather than
implying the element can never go missing.

**Verified** (`~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml` and
`simulator.json`, 2026-09-20): gates 1–3 move together on every installed
device — `fenix8solar47mm`, `fenix8solar51mm`, `fenix7pro` and `fr955` have
`getVectorFont`, `drawAngledText`, `drawRadialText` and ≥11 `system_ttf`
faces; `fenix6`, `fenix6xpro`, `fr245` and `fr255` have none of the three
symbols and zero `system_ttf` entries. They are still checked independently:
nothing in the SDK promises they stay in lockstep across 164 devices.

---

## 2. Format

### 2.1 A second kind of `fonts:` entry

```yaml
fonts:
  clock:                                  # unchanged: baked from a TTF
    source: assets/ChivoMono-Bold.ttf
    size: 22%r
  bezel:                                  # new: device-resident, scalable
    face: [RobotoCondensedBold, RobotoCondensedRegular]
    size: 6%r
    if_unavailable: hide                  # default: error
```

* `source:` and `face:` are **mutually exclusive and jointly required** —
  a `oneOf` in the schema, so the error names the missing half rather than
  reading as an unknown key.
* `face:` takes a string or a **list tried in order**. The list is resolved
  at build time, per device, to the one face that device actually publishes —
  `:face` is emitted as that single resolved string, never the array. Garmin's
  own array fallback is deliberately not used: it picks at runtime, so the
  build could not say which face renders, and the layout box could not be
  measured against it.
* `size:` keeps its existing meaning and its existing `Length` rules
  (`px`/`%r` only, a bare number is an error naming the conversion). It is
  `:size` in pixels, per device, which is the whole point of a scalable face.
* **`glyphs:`, `monospace:`, `align:` and `antialias:` are build errors on a
  `face:` entry.** All four are properties of baking a sheet, and there is no
  sheet. Each error must name why, not merely reject the key.

### 2.2 `curve:` on a `text` element

```yaml
- id: brand
  type: text
  text: "GARMIN"
  font: font.bezel
  at: { anchor: center, dy: -30%r }
  curve:
    style: angled
    angle: 45deg              # the design's own convention: 12 o'clock = 0, clockwise
```

```yaml
- id: bezel
  type: text
  value: date.weekday
  font: font.bezel
  at: { anchor: center }      # radial: `at:` is the CENTRE OF THE CIRCLE
  curve:
    style: radial
    angle: 90deg
    radius: 44%r
    direction: clockwise      # or counter_clockwise; default clockwise
```

* `style:` is a required discriminator, following `progress`'s precedent
  (`docs/format.md` §`progress`: "one element with a `style` discriminator,
  because the *binding* semantics are identical and only the rendering
  differs"). `radius:`/`direction:` are rejected on `angled`, so a typo
  cannot silently change what `at:` means.
* **`angle:` is an `Angle`** in the design's own convention — 12 o'clock = 0,
  clockwise positive (`docs/format.md` §Angles). Both SDK calls take degrees
  counter-clockwise from 3 o'clock, so `Angle.to_garmin()` converts, and the
  generated `Layout` constant carries both values in a comment, exactly as
  `arc` already does.
* **`curve:` requires a `face:` font.** On a baked font or a system font it is
  a build error quoting the SDK: "These APIs only support scalable fonts and
  do not support custom fonts loaded as resources"
  (`$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` §Scalable Fonts).
* Everything else on `text` keeps working untouched — `value:`/`text:`,
  `format:`, `color:`, `visible:`, `when_absent:`, `fallback:`, `modes:`,
  `on_hold:`, `static:`.

### 2.3 `align:` and `vertical_align:` under `curve:`

Both SDK calls take a `justification` parameter, so `align:` maps straight
onto `TEXT_JUSTIFY_LEFT`/`CENTER`/`RIGHT` — the same device-side justify an
upright `text` already uses, with no build-time box move.

`vertical_align:` is the one that does **not** carry over. An upright
`text`'s `bottom` is implemented by subtracting `dc.getFontHeight(font)` from
the anchor *in screen space*; once the baseline is rotated that subtraction
no longer points along the text's own vertical axis, so honouring it would
place the ink somewhere the compiler cannot predict.

**The implementer must verify, in the SDK docs and `api.debug.xml`, whether
`TEXT_JUSTIFY_VCENTER` may be OR'd into the `justification` argument of these
two calls** (the parameter is typed `TextJustification, Lang::Number`, which
suggests a flag word). Then:

* if it is supported: `vertical_align: center` emits
  `TEXT_JUSTIFY_<h> | TEXT_JUSTIFY_VCENTER`, and `top` omits the flag.
* either way: **`vertical_align: bottom` is a build error under `curve:`**,
  naming the rotated-baseline reason and pointing at `center`/`top`.
* if `VCENTER` turns out not to be supported here, `vertical_align:` is
  rejected entirely under `curve:` rather than silently ignored.

Do not guess. `docs/lore/working-agreement.md`: never invent an API — confirm
the symbol or mark it an open question.

### 2.4 `if_unavailable:`

`error` (the default) or `hide`, on a `face:` font entry and on any element
that uses one. **The element's own value wins outright** over the font's —
the same "a descendant's own value wins over its group's" rule `antialias:`
already follows, and the same inheritance helper (`_resolve_inherited_flag`)
should resolve it, not a second copy.

* **`error`**: if *any* target device fails gates 1–3, the build fails,
  naming the device, the face(s) asked for, and the faces that device does
  publish. This is the default because a missing clock is not a cosmetic
  problem.
* **`hide`**: the element simply does not draw on the devices that fail. Every
  other device is unaffected.
* `if_unavailable:` on a **baked** font entry, or on an element whose font is
  baked or system, is a build error: there is nothing that can be unavailable,
  so accepting it would promise a check that never runs.

---

## 3. Generated code

The view is shared across every target in a build; only `Layout.mc` is
per device (`wfb/emit/jungle.py`: `source-<device>/`). That split is what
makes this cheap.

**When every target passes gates 1–3** — always the case in `error` mode,
since the build would otherwise have failed — the code is plain:

```monkeyc
// onLayout
_fontBezel = Graphics.getVectorFont({:face => Layout.FONT_BEZEL_FACE,
                                     :size => Layout.FONT_BEZEL_SIZE});
// draw
if (_fontBezel != null) {
    dc.drawAngledText(Layout.BRAND_X, Layout.BRAND_Y, _fontBezel, "GARMIN",
                      Graphics.TEXT_JUSTIFY_CENTER, Layout.BRAND_ANGLE);
}
```

`FONT_BEZEL_FACE` and `FONT_BEZEL_SIZE` are per-device `Layout` constants: the
resolved face name (§2.1) and the pixel size. The null check is gate 4 and is
**never** omitted.

**When some target fails a gate** (only reachable under `hide`), one extra
per-device constant gates the load, and the aggregate `has` guard appears
exactly as `wfb.availability.compute_guards` already decides such things:

```monkeyc
if (Layout.FONT_BEZEL_AVAILABLE && (Graphics has :getVectorFont)) {
    _fontBezel = Graphics.getVectorFont({...});
}
```

`Layout.FONT_BEZEL_AVAILABLE` is `false` on a device that fails gates 1–3, and
`_fontBezel` stays null there, so the existing null check already hides every
element. **Do not rely on `-O 3z` folding a cross-module `const` away** — the
null check is what actually guarantees correctness; the constant is what keeps
a device from calling a symbol it lacks.

Follow the existing philosophy: **no guard is emitted for a thing every target
has.** A design whose targets all support everything generates the plain form.

---

## 4. Layout, lint and preview

**Measurement.** A vector font's advances are not knowable the way a baked
sheet's are, but they are estimable the same way a *system* font's already
are: `vendor/fonts/` holds Garmin's own `RobotoCondensed-Bold.ttf` and
friends, and `wfb/fonts/registry.json` already pins free stand-ins for hosts
without them. Reuse `wfb.fonts.fallback.measure`/`line_height` and set
`width_is_estimated=True`. Do not invent a second measurement path.

**Boxes.** The lint box (`off-screen`, `overlap`, safe area) must be
conservative, never optimistic:

* `angled`: the rotated bounding box of the measured extent about the anchor.
* `radial`: the bounding box of the arc the text sweeps — centre ±
  (`radius` + `line_height`) is acceptable and honest. A tighter box needs
  per-glyph advance sums this plan does not ask for.

**Lint.** At least: `curve:` on a non-scalable font; a face no target
publishes (under `hide`, a *warning* naming each device, since the build is
deliberately allowed to continue); `vertical_align: bottom` under `curve:`;
and the baking keys of §2.1. Per
`docs/lore/working-agreement.md`, **drive every new diagnostic red before
believing it** — a guard nobody has watched fail is not a guard.

**Preview.** `wfb preview` must draw both styles, because the simulator does
not run in this environment (`CLAUDE.md` §3) and preview is therefore the only
way the change can be seen at all. Angled text is one rotated text layer
composited onto the canvas; radial text is per-glyph placement around the arc,
each glyph rotated to its own tangent. Both draw through the located Garmin
TTF where `wfb.fonts.fetch_system` finds one, exactly as `_approximate_text`
already does for system fonts.

---

## 5. Slices, each its own commit

**Slice 1 — vector fonts and angled/radial `text`.**
Device layer (`Device.scalable_faces`), `FontSpec`, `Text.curve`, schema,
builder diagnostics, per-device resolution, layout boxes, lint, codegen,
preview, tests, and the doc set of §6. Warning-free `monkeyc -w -l 3` on
`fenix8solar47mm`, `fenix8solar51mm` and `fr955`.

**Slice 2 — pattern text parts. Built.**
`pattern`'s `shape: text` parts gain the same `curve:`, which is what finally
answers `docs/limitations.md`'s "a bitmap font cannot turn, so only the anchor
turns": rotated hour numerals around a dial, each tangent to its own radius.
The one real design decision beyond reusing slice 1's font machinery
wholesale: the authored `angle:` is in the **template's own local frame**
(for copy 0), and a radial pattern composes it with each copy's own
rotation at codegen/preview time -- the same "local angle plus the copy's
own rotation" arithmetic a pattern's own `arc` part's `start_angle:`
already performs against `start:`/`step:` -- so twelve numerals share one
authored angle, not twelve. A linear pattern's copies never rotate, so they
simply keep the part's own angle unchanged; no special-casing needed, the
formula reduces on its own. The other real difference from a standalone
element: gate 4's null check cannot stay "load once, early-return before
the loop" the way a baked custom font's does -- that would cancel every
*other* part of the same pattern too -- so a vector font's local is loaded
once but the null check wraps each copy's own draw call instead
(`docs/lore/codegen.md` has the full account). Warning-free `monkeyc -w -l
3` on `fenix8solar47mm`, `fenix8solar51mm` and `fr955`.

**Slice 3 — an example and its screenshots.**
`examples/features/vector-text/face.yaml`, named "Feature vector text" to
match its siblings, plus `tools/readme-shots.py` output and whatever
`README.md` needs.

---

## 6. Documentation that goes stale with this change

Per `CLAUDE.md` §7, in the **same commit** as the code:

* `docs/format.md` — a `curve:` section under `text`, the second kind of
  `fonts:` entry, `if_unavailable:`, and the honest note that `error` is a
  build-time guarantee only.
* `schema/wfb-face-1.schema.json` — **normative**, so it moves with the prose.
* `CLAUDE.md` §4 constraint 15 and §6's "not implemented" list — vector fonts
  and rotated/curved text stop being "researched, not built".
* `docs/limitations.md` §2 (**authoritative**) — the "a bitmap font cannot
  turn" entry gains its answer; the 44-of-136 reach is a limitation in its
  own right.
* `docs/research/12-vector-fonts.md` §5 — rewrite the recommendation in place
  as the decision that was taken, including the rejected `fallback:`.
* `docs/lore/roadmap.md`, `docs/lore/codegen.md`, `docs/lore/monkeyc.md` as
  each is touched.

Delete this plan file when slice 3 lands (`docs/CLAUDE.md`).
