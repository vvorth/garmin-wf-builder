# The icon font

`SymbolsNerdFont-Regular.ttf` is the "Symbols Only" build from
[Nerd Fonts](https://www.nerdfonts.com) v3.5.1, vendored so `icon:` elements
build offline and the icon vocabulary is not limited to a hand-drawn set.

Icons are baked into a per-size BMFont sheet at build time by the same
pipeline that bakes an author's custom text font (`wfb/fonts/bmfont.py`), so
only the glyphs a design actually uses ever reach the `.prg` — see
`wfb/icons.py`.

## Licensing

The Nerd Fonts patching and aggregation is MIT-licensed
(`LICENSE-nerd-fonts.txt`). Nerd Fonts aggregates several separately-licensed
icon sets; the two this project's catalogue draws from are:

| Icon set | Used for | Upstream | Version | License |
|---|---|---|---|---|
| Font Awesome Free | `heart`, `steps`, `alarm`, `notification` | github.com/FortAwesome/Font-Awesome | 6.5.1 | CC BY 4.0 |
| Codicons | `flame`, `dnd` | github.com/microsoft/vscode-codicons | 0.0.45 | CC BY 4.0 |

CC BY 4.0 requires attribution, which this file provides: Font Awesome Free
icons by Fonticons, Inc.; Codicons by Microsoft.

## Adding an icon to the catalogue

Any glyph in this font can be used directly in a design without a code change
at all -- `icon:` accepts a single literal character, checked against this
font's own character map at build time, in addition to the maintained names in
`wfb/icons.py`. Adding a *name* for one (so `wfb sources`/`wfb new` document
it, and so an author does not have to go hunting for a codepoint) means adding
one line to `wfb/icons.py`'s `CATALOG`.

To find a codepoint: extract this font with `fonttools ttx -l` or a font
inspector, or browse https://www.nerdfonts.com/cheat-sheet.
