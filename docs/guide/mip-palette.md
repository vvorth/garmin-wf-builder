# The 64 MIP colours, named

A MIP panel shows exactly 64 colours: each of red, green and blue at
`0x00`, `0x55`, `0xAA` or `0xFF`. Any other colour is dithered (see
[Colours](colors.md#palette)). This page lists all 64 with a name for each,
so a palette can say `color.cornflower_blue` instead of `"#55AAFF"`.

The names come from [apps.bliemel.net/colors](https://apps.bliemel.net/colors/),
in that page's order. It calls both `#00FF00` and `#005500` *Green*, so
the darker one is `dark_green` here.

To start a face with the whole palette already in it, run
`wfb new -t palette` ([Getting started](getting-started.md)). The editor's
colour picker offers the same 64 by name, and adds the one you pick to the
face ([the editor](studio.md#the-colour-picker)). The table itself is
`MIP64_NAMED` in `ts/src/palette.ts`; this page and the template are checked
against it.

## Copy into a face

Paste the lines you want under `resources: palette:`. Each entry uses the
[long form](colors.md#long-form-a-label-for-the-on-device-editor):
`label:` is the name the watch shows when a `config:` colour axis offers the
swatch, and it is ignored otherwise.

```yaml
resources:
  palette:
    white:                { value: "#FFFFFF", label: "White" }
    shalimar:             { value: "#FFFFAA", label: "Shalimar" }
    laser_lemon:          { value: "#FFFF55", label: "Laser Lemon" }
    yellow:               { value: "#FFFF00", label: "Yellow" }
    lavender_rose:        { value: "#FFAAFF", label: "Lavender Rose" }
    sundown:              { value: "#FFAAAA", label: "Sundown" }
    texas_rose:           { value: "#FFAA55", label: "Texas Rose" }
    web_orange:           { value: "#FFAA00", label: "Web Orange" }
    pink_flamingo:        { value: "#FF55FF", label: "Pink Flamingo" }
    brilliant_rose:       { value: "#FF55AA", label: "Brilliant Rose" }
    sunset_orange:        { value: "#FF5555", label: "Sunset Orange" }
    international_orange: { value: "#FF5500", label: "International Orange" }
    magenta_fuchsia:      { value: "#FF00FF", label: "Magenta Fuchsia" }
    hollywood_cerise:     { value: "#FF00AA", label: "Hollywood Cerise" }
    razzmatazz:           { value: "#FF0055", label: "Razzmatazz" }
    red:                  { value: "#FF0000", label: "Red" }
    pale_turquoise:       { value: "#AAFFFF", label: "Pale Turquoise" }
    mint_green:           { value: "#AAFFAA", label: "Mint Green" }
    conifer:              { value: "#AAFF55", label: "Conifer" }
    spring_bud:           { value: "#AAFF00", label: "Spring Bud" }
    perano:               { value: "#AAAAFF", label: "Perano" }
    silver_chalice:       { value: "#AAAAAA", label: "Silver Chalice" }
    olive_green:          { value: "#AAAA55", label: "Olive Green" }
    citrus:               { value: "#AAAA00", label: "Citrus" }
    medium_purple:        { value: "#AA55FF", label: "Medium Purple" }
    violet_blue:          { value: "#AA55AA", label: "Violet Blue" }
    apple_blossom:        { value: "#AA5555", label: "Apple Blossom" }
    rust:                 { value: "#AA5500", label: "Rust" }
    electric_violet:      { value: "#AA00FF", label: "Electric Violet" }
    dark_magenta:         { value: "#AA00AA", label: "Dark Magenta" }
    jazzberry_jam:        { value: "#AA0055", label: "Jazzberry Jam" }
    bright_red:           { value: "#AA0000", label: "Bright Red" }
    baby_blue:            { value: "#55FFFF", label: "Baby Blue" }
    medium_aquamarine:    { value: "#55FFAA", label: "Medium Aquamarine" }
    screamin_green:       { value: "#55FF55", label: "Screamin' Green" }
    bright_green:         { value: "#55FF00", label: "Bright Green" }
    cornflower_blue:      { value: "#55AAFF", label: "Cornflower Blue" }
    cadet_blue:           { value: "#55AAAA", label: "Cadet Blue" }
    fruit_salad:          { value: "#55AA55", label: "Fruit Salad" }
    kelly_green:          { value: "#55AA00", label: "Kelly Green" }
    neon_blue:            { value: "#5555FF", label: "Neon Blue" }
    rich_blue:            { value: "#5555AA", label: "Rich Blue" }
    emperor:              { value: "#555555", label: "Emperor" }
    verdun_green:         { value: "#555500", label: "Verdun Green" }
    electric_indigo:      { value: "#5500FF", label: "Electric Indigo" }
    indigo:               { value: "#5500AA", label: "Indigo" }
    tyrian_purple:        { value: "#550055", label: "Tyrian Purple" }
    maroon:               { value: "#550000", label: "Maroon" }
    aqua:                 { value: "#00FFFF", label: "Aqua" }
    medium_green:         { value: "#00FFAA", label: "Medium Green" }
    malachite:            { value: "#00FF55", label: "Malachite" }
    green:                { value: "#00FF00", label: "Green" }
    azure_radiance:       { value: "#00AAFF", label: "Azure Radiance" }
    persian_green:        { value: "#00AAAA", label: "Persian Green" }
    pigment_green:        { value: "#00AA55", label: "Pigment Green" }
    japanese_laurel:      { value: "#00AA00", label: "Japanese Laurel" }
    navy_blue:            { value: "#0055FF", label: "Navy Blue" }
    cobalt:               { value: "#0055AA", label: "Cobalt" }
    mosque:               { value: "#005555", label: "Mosque" }
    dark_green:           { value: "#005500", label: "Dark Green" }
    blue:                 { value: "#0000FF", label: "Blue" }
    midnight_blue:        { value: "#0000AA", label: "Midnight Blue" }
    navy:                 { value: "#000055", label: "Navy" }
    black:                { value: "#000000", label: "Black" }
```

## The table

| # | Hex | Name | Reference |
|---|---|---|---|
| 1 | `#FFFFFF` | White | `color.white` |
| 2 | `#FFFFAA` | Shalimar | `color.shalimar` |
| 3 | `#FFFF55` | Laser Lemon | `color.laser_lemon` |
| 4 | `#FFFF00` | Yellow | `color.yellow` |
| 5 | `#FFAAFF` | Lavender Rose | `color.lavender_rose` |
| 6 | `#FFAAAA` | Sundown | `color.sundown` |
| 7 | `#FFAA55` | Texas Rose | `color.texas_rose` |
| 8 | `#FFAA00` | Web Orange | `color.web_orange` |
| 9 | `#FF55FF` | Pink Flamingo | `color.pink_flamingo` |
| 10 | `#FF55AA` | Brilliant Rose | `color.brilliant_rose` |
| 11 | `#FF5555` | Sunset Orange | `color.sunset_orange` |
| 12 | `#FF5500` | International Orange | `color.international_orange` |
| 13 | `#FF00FF` | Magenta Fuchsia | `color.magenta_fuchsia` |
| 14 | `#FF00AA` | Hollywood Cerise | `color.hollywood_cerise` |
| 15 | `#FF0055` | Razzmatazz | `color.razzmatazz` |
| 16 | `#FF0000` | Red | `color.red` |
| 17 | `#AAFFFF` | Pale Turquoise | `color.pale_turquoise` |
| 18 | `#AAFFAA` | Mint Green | `color.mint_green` |
| 19 | `#AAFF55` | Conifer | `color.conifer` |
| 20 | `#AAFF00` | Spring Bud | `color.spring_bud` |
| 21 | `#AAAAFF` | Perano | `color.perano` |
| 22 | `#AAAAAA` | Silver Chalice | `color.silver_chalice` |
| 23 | `#AAAA55` | Olive Green | `color.olive_green` |
| 24 | `#AAAA00` | Citrus | `color.citrus` |
| 25 | `#AA55FF` | Medium Purple | `color.medium_purple` |
| 26 | `#AA55AA` | Violet Blue | `color.violet_blue` |
| 27 | `#AA5555` | Apple Blossom | `color.apple_blossom` |
| 28 | `#AA5500` | Rust | `color.rust` |
| 29 | `#AA00FF` | Electric Violet | `color.electric_violet` |
| 30 | `#AA00AA` | Dark Magenta | `color.dark_magenta` |
| 31 | `#AA0055` | Jazzberry Jam | `color.jazzberry_jam` |
| 32 | `#AA0000` | Bright Red | `color.bright_red` |
| 33 | `#55FFFF` | Baby Blue | `color.baby_blue` |
| 34 | `#55FFAA` | Medium Aquamarine | `color.medium_aquamarine` |
| 35 | `#55FF55` | Screamin' Green | `color.screamin_green` |
| 36 | `#55FF00` | Bright Green | `color.bright_green` |
| 37 | `#55AAFF` | Cornflower Blue | `color.cornflower_blue` |
| 38 | `#55AAAA` | Cadet Blue | `color.cadet_blue` |
| 39 | `#55AA55` | Fruit Salad | `color.fruit_salad` |
| 40 | `#55AA00` | Kelly Green | `color.kelly_green` |
| 41 | `#5555FF` | Neon Blue | `color.neon_blue` |
| 42 | `#5555AA` | Rich Blue | `color.rich_blue` |
| 43 | `#555555` | Emperor | `color.emperor` |
| 44 | `#555500` | Verdun Green | `color.verdun_green` |
| 45 | `#5500FF` | Electric Indigo | `color.electric_indigo` |
| 46 | `#5500AA` | Indigo | `color.indigo` |
| 47 | `#550055` | Tyrian Purple | `color.tyrian_purple` |
| 48 | `#550000` | Maroon | `color.maroon` |
| 49 | `#00FFFF` | Aqua | `color.aqua` |
| 50 | `#00FFAA` | Medium Green | `color.medium_green` |
| 51 | `#00FF55` | Malachite | `color.malachite` |
| 52 | `#00FF00` | Green | `color.green` |
| 53 | `#00AAFF` | Azure Radiance | `color.azure_radiance` |
| 54 | `#00AAAA` | Persian Green | `color.persian_green` |
| 55 | `#00AA55` | Pigment Green | `color.pigment_green` |
| 56 | `#00AA00` | Japanese Laurel | `color.japanese_laurel` |
| 57 | `#0055FF` | Navy Blue | `color.navy_blue` |
| 58 | `#0055AA` | Cobalt | `color.cobalt` |
| 59 | `#005555` | Mosque | `color.mosque` |
| 60 | `#005500` | Dark Green (the source says *Green*) | `color.dark_green` |
| 61 | `#0000FF` | Blue | `color.blue` |
| 62 | `#0000AA` | Midnight Blue | `color.midnight_blue` |
| 63 | `#000055` | Navy | `color.navy` |
| 64 | `#000000` | Black | `color.black` |

## See also

- [Colours](colors.md): `color.<name>`, palettes, schemes, and the dither lint.
- [On-device configuration](configuration.md): offering swatches on the
  `accent_color:` and `data_color:` axes.
