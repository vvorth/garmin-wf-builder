# The icon font

`SymbolsNerdFont-Regular.ttf` is the "Symbols Only" build from
[Nerd Fonts](https://www.nerdfonts.com) v3.5.1, vendored so `icon:` elements
build offline and the icon vocabulary is not limited to a hand-drawn set.

Icons are baked into a per-size BMFont sheet at build time by the same
pipeline that bakes an author's custom text font (`wfb/fonts/bmfont.py`), so
only the glyphs a design actually uses ever reach the `.prg` — see
`wfb/icons.py` for the sizing/resolution logic and `wfb/icon_catalog.py` for
the catalogue data itself (name, codepoint, description).

## Licensing

The Nerd Fonts patching and aggregation is MIT-licensed
(`LICENSE-nerd-fonts.txt`). Nerd Fonts aggregates several separately-licensed
icon sets; the ones this project's catalogue draws from are:

| Icon set | Used for | Upstream | License |
|---|---|---|---|
| Material Design Icons | `heart`, `flame`, `alarm`, `dnd`, `notification`, `battery`, `floors`, `distance`, `phone` | github.com/Templarian/MaterialDesign (Pictogrammers) | Apache License 2.0 |
| Font Awesome Free | `steps` | github.com/FortAwesome/Font-Awesome | CC BY 4.0 |
| Weather Icons | `weather_*` | github.com/erikflowers/weather-icons | SIL OFL 1.1 |

Material Design Icons is preferred for a new catalogue entry whenever a glyph
reads at least as well as an alternative -- it is the largest, most
consistently-drawn set in this font. `steps` is the deliberate exception (see
`wfb/icon_catalog.py`'s comment above `CATALOG` for why), and weather icons come from the
dedicated Weather Icons set rather than MDI's own `weather_*` glyphs, because
it has more distinct conditions and day/night pairs -- and, unusually for this
font, its codepoints fit in the Basic Multilingual Plane (see "Codepoints
above U+FFFF" below).

CC BY 4.0 and Apache 2.0 both require attribution, which this file provides:
Font Awesome Free icons by Fonticons, Inc.; Material Design Icons by the
Pictogrammers project; Weather Icons by Erik Flowers, SIL OFL 1.1.

## Adding an icon to the catalogue

Any glyph in this font can be used directly in a design without a code change
at all -- `glyph: "U+XXXX"` takes any codepoint, checked against this font's
own character map at build time, in addition to the maintained names in
`wfb/icon_catalog.py` that `icon:` takes. Adding a *name* for one (so `wfb sources`/`wfb new`
document it, and so an author does not have to go hunting for a codepoint)
means adding one `Icon(...)` entry to `wfb/icon_catalog.py`'s single
`CATALOG` -- there is one catalogue for every icon, general-purpose and
weather alike, not a separate table per kind, and not a separate table on the
Monkey C side either: `source/IconGlyphs.mc` (generated fresh each build, see
`wfb/emit/monkeyc.py`) is where a catalogue name becomes a drawn character
on-device, for every icon, so adding a name here is what a dynamic
(`icon_for:`) lookup sees too. A new weather condition also needs an entry in
`wfb.icons.GARMIN_WEATHER_CONDITION_ICON` mapping the raw `Weather.CONDITION_*`
value to that `CATALOG` name, and its on-device twin,
`runtime-lib/WfbWeather.mc`'s `chooseIcon()`.

Every codepoint in `wfb/icon_catalog.py` is written as a Python
`\uXXXX`/`\U000XXXXX` escape, not a pasted character -- the glyph is invisible
in most editors and terminals, so the escape is what stays readable and safe
to hand-edit; a pasted character that fails to paste correctly still parses as
valid Python (silently becoming an empty string), so the mistake only
surfaces later as a blank tile. Each entry also carries the real character in
a trailing `# preview: <char> (<font glyph name>)` comment -- not for the code
to use, just so an editor that can render the font (most can) shows what the
escape next to it is supposed to produce. Look codepoints up against the
font's own cmap (`fontTools.ttLib.TTFont(...).getBestCmap()`) rather than
typing them from memory or a website table, the same "never invent an API"
rule CLAUDE.md applies to Monkey C symbols.

To find a codepoint by browsing rather than by name: extract this font with
`fonttools ttx -l` or a font inspector, or browse
https://www.nerdfonts.com/cheat-sheet.

## Codepoints above U+FFFF

Material Design Icons' glyphs (and MDI's own `weather_*` glyphs, though this
catalogue does not use those -- see above) live entirely above the Basic
Multilingual Plane, needing a Python `\U000XXXXX` escape (8 hex digits) rather
than `\uXXXX` (4). `monkeyc` compiles a string literal containing one without
complaint. The one real problem was in the *resource compiler*: a generated
`<font filter="...">` attribute is parsed as Java UTF-16 code units, so such a
codepoint splits into a surrogate pair that matches no real glyph, and the
build fails with "does not have characters in the given filter".
`wfb/emit/resources.py` fixes this by omitting `filter` for any font that
needs such a glyph -- the `.fnt` file itself, already subsetted to the right
glyphs by this project's own baking, does not need it. Confirmed against a
real build and in `wfb preview`, not just compiled.

## Proportional, not monospaced

This is the "Regular" (proportional) build, not "Mono" -- confirmed via
`font["post"].isFixedPitch == 0`. That is not a problem for this project: an
icon element draws exactly one glyph, independently positioned by the layout
engine from its own declared size, never packed edge-to-edge against another
character the way a row of monospaced text would be. Advance-width vs. ink
bounding-box overhang was checked across every catalogue glyph at several
sizes and stays under 2% either side, so there is no overlap risk even if a
future feature ever drew two icons close together.
