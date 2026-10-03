# Colours: palette, roles and schemes

Colours are named once and referenced everywhere else as `color.<name>`, so
a design's whole colour story lives in one place and a lint can catch a
colour that doesn't belong. A name is either a **palette swatch** (a fixed
colour under `resources: palette:`) or a **role** (a colour that follows the
wearer's choice: a scheme's `colors:` or a `config:` colour axis). Any
`color:` key can also be a full expression, picked at runtime from live
data. **The display is a 64-colour MIP panel: every channel must land on
`0x00`/`0x55`/`0xAA`/`0xFF`, or the firmware dithers it.**

![status row and battery arcs](../screenshots/showcase-status.png)
*Conditional colour and arc progress, from `examples/showcase/face.yaml`.*

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `palette:` | `resources:` | name → colour | — | [Named colours, short form](#palette) |
| a `palette:` entry, long form | `resources: palette:` | `{value, label}` | — | [colour plus an editor label](#long-form-a-label-for-the-on-device-editor) |
| `schemes:` | `theme:` | name → `{label?, colors}` | — | [named role → colour sets](#colour-schemes) |
| `color:` and every other colour key | element, part, scheme | `#RRGGBB`, `color.<name>`, or an expression | — | [Colour references](#colour-references) |

## Example

```yaml
notification_badge:
  type: icon
  icon: notification
  color: "device.notification_count > 0 ? color.accent : color.dark"

notification_count:
  type: text
  text: "{device.notification_count}"
  visible: device.notification_count > 0

battery_arc_l:
  type: gauge
  style: arc
  value: system.battery
  max: 100
  radius: 97%r
  thickness: 3%r
  start_angle: 180deg                # 6 o'clock
  sweep: 30deg                       # a negative sweep mirrors it (battery_arc_r)
```

A `color:` key takes the same expression language as any other value, so the
notification badge switches between the accent colour and a dimmed one based
on `device.notification_count`, and the whole badge hides itself with
`visible:` when the count is zero. See [Data binding, expressions and
formats](data.md) for the expression language, and [Gauges and
graphs](progress-and-graphs.md) for `type: gauge` and `style: arc`.

## Colour references

`color.<name>` resolves to:

1. **a role**, if one has that name: a key of every scheme's `colors:`, or
   the role a `config:` colour axis binds (`accent_color` binds `accent`,
   `data_color` binds `data`). A role's value follows the active style's
   scheme, or the wearer's pick;
2. otherwise, **a palette swatch**.

**A name that is both a role and a swatch is an error**, reported at both
declarations: one reference never quietly means one of two colours. So is a
scheme role named `accent` or `data` while the matching colour axis is
declared. A name that is neither is an error suggesting the nearest declared
one.

**Some places need a colour that is known at build time**: a scheme's role
values, a colour axis's `default:` and `choices:`, and a palette entry's own
value. There `color.<name>` must name a swatch, or be a `#RRGGBB` literal. A
role there is an error saying why: a role has no single value until the
watch runs.

Inside an expression `color.<name>` is a reference like any other:
`"activity.steps > 9000 ? color.accent : color.fg"`.

## Palette

```yaml
resources:
  palette:
    bg: "#000000"
    text: "#FFFFFF"
    orange: "#FF5500"
    aqua: { value: "#00FFFF", label: "Aqua" }   # long form -- see below
```

Elements reference `color.orange`, never a raw hex value. [The 64 MIP
colours, named](mip-palette.md) lists every colour the panel shows exactly,
as palette entries ready to paste; the editor's colour picker offers the
same 64 and adds the one you pick ([the editor](studio.md#the-colour-picker)). A literal colour is
accepted but produces a note, because a palette is what makes a colour change
one edit and a lint one rule.

**On a 64-colour panel each channel must be `0x00`, `0x55`, `0xAA` or `0xFF`.**
Anything else is dithered by the firmware and looks grainy. The linter warns and
names the nearest legal colour; `lint: {allow: [palette-dither], reason: "..."}`
on an element silences it for a deliberate choice.

**On a 2-colour panel (the Instinct family) only `#000000` and `#FFFFFF` are
safe.** The panel shows black and one "on" colour, and the device files list
exactly those two. What the watch does with any other colour is unverified, so
`palette-mono` warns and names whichever of the two is nearer by contrast
ratio. `wfb preview` snaps the image to black and white by the same rule, and
says it is guessing. 8- and 14-colour panels have no known rule; the linter
reports them "not checked".

<img src="../screenshots/instinct.png" width="260" alt="a black-and-white face on an Instinct 2">

*[`examples/features/instinct`](../../examples/features/instinct/face.yaml) on
an Instinct 2: black and white only, with the bezel's chamfers and the ring
round the subscreen window greyed out.*

**A palette entry is a literal.** It compiles to a Monkey C `const`, so its
value is a `#RRGGBB`/`#RGB` colour in either spelling below; `color.accent`
there is a schema error. Reference the role directly on the element instead:
`color: color.accent`.

### Long form: a label for the on-device editor

```yaml
resources:
  palette:
    aqua: { value: "#00FFFF", label: "Aqua" }
```

`{value, label}` is an alternative spelling of a palette entry, not a
different kind of thing -- `value:` means exactly what the short form's colour
means, and every check (the 64-colour rule, the literal rule above) applies
to it identically. The only thing the long form adds is `label:`, which does
nothing on its own: it surfaces only when this swatch is used from a
`config:` axis's `default:` or `choices:` as `color.<name>` (see
[Configuration](configuration.md#configuration)), where it becomes the same `<color
label="@Strings...">` and generated `<string>` an inline `label:` on a
`config:` choice already produces. A long-form entry with no `label:` behaves
exactly like the short form.

## Colour schemes

```yaml
resources:
  palette:
    black: { value: "#000000", label: "Black" }
    white: { value: "#FFFFFF", label: "White" }
    dark_gray: { value: "#555555", label: "Dark Gray" }
    light_gray: { value: "#AAAAAA", label: "Light Gray" }

theme:
  schemes:
    dark:
      label: "Dark"
      colors: { bg: color.black, fg: color.white, dim: color.dark_gray }
    light:
      label: "Light"
      colors: { bg: color.white, fg: color.black, dim: color.light_gray }
```

A named set of role → colour, picked on-device through a `config: style:`
entry's `scheme:` (`scheme: dark`). `label:` on the scheme itself is shown
in the editor's Styles list when the style entry that names it has none of
its own; it is optional, as a label is everywhere else, and a scheme with
none, named by an entry with none, produces a generated `<style>` with no
`label` attribute. Each role's colour must be known at build time: a
`#RRGGBB`/`#RGB` literal or a `color.<swatch>`, never a role.

**Every scheme must declare the identical set of roles.** `dark` declaring
`bg`/`fg`/`dim` and `light` declaring only `bg`/`fg` is an error naming the
missing role and the scheme that lacks it -- otherwise `color.dim` would be
undefined the moment the wearer picked `light`.

Reference a role as an ordinary colour, exactly like a swatch:

```yaml
color: color.fg
color: "heart_rate.current > 120 ? color.hot : color.fg"
```

This is why a role and a swatch may not share a name: `color.fg` above has
to mean exactly one thing. Naming a scheme that was never declared (in a
style entry's `scheme:`), or was declared and rejected (a bad role colour, a
role-set mismatch), is an error at that `config: style:` `choices:` entry,
naming the schemes `theme: schemes:` actually declares.

See [Configuration](configuration.md#configuration) for `config: style:` itself -- the axis that lets
the wearer pick between author-named entries, each naming a declared scheme.
On a watch without the native editor (fr955), the same entries are picked
from the generated settings menu
([Configuration](configuration.md#the-settings-menu-on-a-watch-without-the-native-editor)).

## See also

- [The 64 MIP colours, named](mip-palette.md) — every legal colour as a palette entry; `wfb new -t palette` starts with all of them.
- [`examples/showcase/face.yaml`](../../examples/showcase/face.yaml) — the status row and battery arcs shown above.
- [Configuration](configuration.md) — `config: style:`, `accent_color`, `data_color`.
- [Data binding, expressions and formats](data.md) — the expression language a `color:` key uses.
- [Gauges and graphs](progress-and-graphs.md) — `type: gauge`, `style: arc`.
- [Text](text.md#outline--the-stamped-ring) — see `outline:`'s own colour rules; `outline.color` is exactly this same grammar.
