# Icons

`type: icon` draws a single glyph — a metric's conventional icon, any glyph
from the vendored Nerd Fonts font, or one chosen on-device from live data —
as cheaply as a line of text, since that's exactly what it is under the hood.

![icon clusters and progress bar](../screenshots/showcase-clusters.png)
*Icon clusters, from `examples/showcase/face.yaml` — see also the
[data slots](data.md) screenshot for the steps icon and heartbeat glyph.*

## At a glance

| Key | Values | Default | Meaning |
|---|---|---|---|
| `icon:` | a catalogue name (`steps`, `heart`, `weather_<condition>`, …) | — | [`icon`](#icon) — mutually exclusive with `glyph:`/`icon_for:` |
| `glyph:` | a codepoint, `"U+XXXX"` | — | [Beyond the named icons](#icon) — any glyph the catalogue doesn't name |
| `icon_for:` | `weather.condition`/`.condition_today`/`.condition_tomorrow` | — | [A dynamic icon: `icon_for`](#a-dynamic-icon-icon_for) — chosen on-device |
| `size:` | `Length` (`px`/`%r` only) | — | [`icon`](#icon) |
| `color:` | colour expression | — | [Colours](colors.md) |
| `align:` / `vertical_align:` | `left`/`center`/`right`, `top`/`center`/`bottom` | `center` | [Placement: `at:` and `align:`](placement.md#placement-at-and-align) |

## Example

Icons are glyphs from the [Nerd Fonts](https://www.nerdfonts.com) "Symbols
Only" font, about 10,000 of them. `tools/setup-env.sh` downloads the font; it
isn't stored in this repository. The build bakes only the glyphs you use into
the face, the same way it bakes a custom text font. Each icon costs one small
bitmap, and no image files ship.

```yaml
steps_icon:                          # a named icon: `wfb sources` lists the names
  type: icon
  icon: steps
  size: 9%r                          # px or %r
  color: config.colors.fg

hr_graph_icon:                       # any Nerd Fonts glyph, by codepoint
  type: icon
  glyph: "U+F21E"                    # nf-fa-heartbeat
  size: 9%r

weather_icon:                        # chosen on the watch from live data
  type: icon
  icon_for: weather.condition_today
```

The [data slots](data.md) screenshot shows the steps icon and the heartbeat glyph, and the [placement](placement.md)
screenshot shows the weather icon.

- **Named icons** (`icon:`) cover the common metrics: steps, heart, flame,
  battery, notification, alarm, and so on, plus a `weather_*` set.
- **Any other glyph:** find it on the
  [Nerd Fonts cheat sheet](https://www.nerdfonts.com/cheat-sheet), then write
  its code as `glyph: "U+XXXX"`. The build checks that the font has it.
- **`icon_for:`** picks the weather glyph on the watch at runtime.

### `icon`

```yaml
- id: steps_icon
  type: icon
  icon: steps               # alarm | battery | distance | dnd | flame | floors | heart |
                             # notification | phone | steps, plus one `weather_<condition>`
                             # per Weather.CONDITION_* bucket and a `weather_<condition>_night`
                             # variant for most of them -- run `wfb sources` for the full,
                             # current list (53 names as of this writing)
  size: 30px                # px or %r only -- see below
  color: palette.accent
```

An icon is a single glyph from an icon font
([Nerd Fonts](https://www.nerdfonts.com)' "Symbols Only" build, which
`tools/setup-env.sh` downloads; it is not committed), baked into a
bitmap font sheet at build time — the same pipeline that bakes a `fonts:`
entry, subsetted to exactly the glyphs a design uses. Drawing an icon is
drawing text: one `drawText` call against that baked font. No image ships in
the `.prg`; the resource cost is the same small per-glyph bitmap a custom text
font pays.

`align`/`vertical_align` follow the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align) — an icon is
a glyph kind, so it places the same way `text` does, by a runtime justify on
the device, not a moved build-time box.

**`size:` accepts only `px` and `%r`, not `%` or `pt`.** The icon's font has to
be baked once, before layout runs, so its size cannot depend on a parent box
(`%`) or another element's own font (`pt`) — both are only known once layout
has already happened. `%r` is recommended, for the same reason it is
recommended everywhere else: it means the same thing regardless of screen size.

**The catalogue prefers Material Design Icons** (`nf-md`, the icon font's
largest and most consistent set) whenever a glyph reads at least as well as an
alternative — the one deliberate exception is `steps`, which keeps a Font
Awesome glyph because MDI's walking/running figures read as "activity" rather
than "step count" at a glance. Weather icons (`weather_*`) come from the font's
dedicated Weather Icons set instead, because it covers more distinct conditions
and day/night pairs than MDI's own `weather_*` glyphs and — unlike them — its
codepoints fit in the Basic Multilingual Plane (see the comment above
`CATALOG` in `wfb/icon_catalog.py`). `wfb.icons.GARMIN_WEATHER_CONDITION_ICON` maps every
`Toybox.Weather.CONDITION_*` value (0–53) to one of these.

**Beyond the named icons**, the icon font has on the order of ten thousand
glyphs, including codepoints above the Basic Multilingual Plane (all of MDI's
own icons live there). Reach one with **`glyph:`**, which takes a codepoint in
Unicode's own notation:

```yaml
- id: repo
  type: icon
  glyph: "U+F09B"     # nf-fa-github; find codepoints at nerdfonts.com/cheat-sheet
  size: 12%r
  color: palette.dim
```

`glyph:` is the **only** way to use an icon the catalogue does not name.
`icon:` once accepted a bare character pasted straight into the YAML; that was
removed. `U+F09B` is greppable, reviewable in a diff and survives copy-paste,
where the character itself renders as a blank box — or as nothing at all — in
most editors, and a paste that silently fails still parses as valid YAML. That
is the same hazard `wfb/icon_catalog.py` warns about for this project's own
source, and it applies just as much to a design file.

`icon:`, `glyph:` and `icon_for:` are mutually exclusive — an icon element uses
exactly one. Writing `glyph:` for a codepoint the catalogue *does* name is
accepted with a note pointing at the name, which is the better spelling: a name
keeps meaning if the catalogue moves that icon to a different codepoint, which
has already happened once (the Font Awesome → Material Design Icons switch).

A codepoint the font does not carry is a build error, checked against the
font's own character map — the same way a custom font's glyph coverage is
checked, and for the same reason: the alternative is a blank tile discovered on
the wrist. A codepoint above the Basic
Multilingual Plane builds and renders correctly; the generated `<font>`
resource simply omits its `filter` attribute, because the resource compiler
parses that attribute as UTF-16 code units and a surrogate pair would not
survive it (see `wfb/emit/resources.py`). See `wfb/assets/icons/README.md` for
how to find a codepoint, and its licensing (the font aggregates several
separately-licensed icon sets under Nerd Fonts' MIT patcher; the ones the named
catalogue draws from are attributed there).

#### A dynamic icon: `icon_for`

`icon:` names a fixed glyph, chosen at build time. `icon_for:` instead chooses
the glyph on-device, at runtime, from a bound value — mutually exclusive with
`icon:`:

```yaml
- id: weather_now
  type: icon
  icon_for: weather.condition   # or weather.condition_today / .condition_tomorrow
  size: 20%r
  color: palette.text
```

This currently accepts only a bare `weather.condition*` source (see `wfb
sources`) — not an expression over one (`weather.condition + 1` is rejected;
the lookup needs the raw `Weather.CONDITION_*` value). The generated code
resolves the glyph in two steps, mirroring `wfb.icons` exactly: `WfbWeather.
chooseIcon()` (a hand-written barrel function, day glyphs only for now — there
is no sunrise/sunset source yet to pick the night variant on-device) turns the
condition into a catalogue *name*, and `IconGlyphs.glyph()` — generated fresh
each build directly from the icon catalogue, not hand-written — turns that
name into the actual character. A weather condition is not a special case on
the device side any more than it is in the catalogue: the same `IconGlyphs`
table is where any dynamic icon's name becomes a glyph. Because the actual
glyph is not known until runtime, its font bakes *every* glyph the lookup
could return rather than one — still cheap: baking is still a small per-glyph
bitmap, just several of them sharing one font instead of one glyph having its
own.

When the bound value is absent (no cached weather data yet), the icon simply
does not draw — the same `hide`-by-default behaviour any other nullable
binding without an explicit `when_absent:` has, deliberately: a placeholder
"unknown" glyph on first launch, before Weather has ever synced, would read
as a real (if odd) forecast rather than as "not ready yet".

### Your own icon font

**Your own icon font** also works, through a plain `text` element. Add any TTF,
such as a full Nerd-patched font, to `fonts:`, and write the glyph as a YAML
escape:

```yaml
fonts:
  myicons: { source: assets/MyIcons.ttf, size: 20%r }
elements:
  github:
    type: text
    text: "\uF09B"                   # use "\U000F140B" above U+FFFF
    font: font.myicons
```

A text element doesn't get the icon's size correction or the build's
glyph-exists check. Also avoid spaces between glyphs: a symbols-only font has
no space character, and the preview draws it as an empty box.

## See also

- [`examples/showcase/face.yaml`](../../examples/showcase/face.yaml) — the icon clusters shown above.
- [`wfb/assets/icons/README.md`](../../wfb/assets/icons/README.md) — finding a codepoint, licensing, and adding a name to the catalogue.
- [Fonts](fonts.md#fonts) — the same TTF-to-bitmap pipeline an icon font uses.
- [Elements: common keys and groups](elements.md) — `visible:`, `static:`, and the other keys an icon element shares with every other kind.
