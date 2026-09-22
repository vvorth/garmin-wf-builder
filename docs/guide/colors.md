# Colours: palette and colour schemes

Colours are named once in `palette:` and referenced everywhere else, so a
design's whole colour story lives in one place and a lint can catch a colour
that doesn't belong. A `color_scheme:` groups palette entries into named
roles the wearer can switch on-device, and any `color:` key can be a full
expression, picked at runtime from live data. **The display is a 64-colour
MIP panel: every channel must land on `0x00`/`0x55`/`0xAA`/`0xFF`, or the
firmware dithers it.**

![status row and battery arcs](../screenshots/showcase-status.png)
*Conditional colour and arc progress, from `examples/showcase/face.yaml`.*

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `palette:` | top level | name → colour | — | [Named colours, short form](#palette) |
| `palette.<name>` (long form) | top level | `{value, label}` | — | [colour plus an editor label](#long-form-a-label-for-the-on-device-editor) |
| `color_scheme:` | top level | name → `{label?, colors}` | — | [named role → colour sets](#color-scheme) |
| `color:` / role colours | element, scheme entry | literal, `palette.<name>`, `config.*`, or an expression | — | [Conditional colour](#example) |

## Example

```yaml
notification_badge:
  type: icon
  icon: notification
  color: "device.notification_count > 0 ? config.accent_color : config.colors.dark"

notification_count:
  type: text
  value: device.notification_count
  visible: device.notification_count > 0

battery_arc_l:
  type: progress
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
formats](data.md) for the expression language, and [Progress bars, arcs and
graphs](progress-and-graphs.md) for `type: progress` and `style: arc`.

## Palette

```yaml
palette:
  bg: "#000000"
  text: "#FFFFFF"
  accent: "#FF5500"
  aqua: { value: "#00FFFF", label: "Aqua" }   # long form -- see below
```

Elements reference `palette.accent`, never a raw hex value. A literal colour is
accepted but produces a note, because a palette is what makes a colour change
one edit and a lint one rule.

**On a 64-colour panel each channel must be `0x00`, `0x55`, `0xAA` or `0xFF`.**
Anything else is dithered by the firmware and looks grainy. The linter warns and
names the nearest legal colour; `lint: {allow: [palette-dither], reason: "..."}`
on an element silences it for a deliberate choice.

**A `palette:` entry may not reference `config.*`.** A palette entry compiles
to a Monkey C `const`, and a config value is not known until the watch reads
it, so `bg: config.accent_color` is an error. Reference the config entry
directly instead: `color: config.accent_color`. This applies to either
spelling below -- `aqua: { value: config.accent_color }` is rejected the same
way `aqua: config.accent_color` is.

### Long form: a label for the on-device editor

```yaml
palette:
  aqua: { value: "#00FFFF", label: "Aqua" }
```

`{value, label}` is an alternative spelling of a palette entry, not a
different kind of thing -- `value:` means exactly what the short form's colour
means, and every existing check (the 64-colour rule, the `config.*` ban above)
applies to it identically. The only thing the long form adds is `label:`,
which does nothing on its own: it surfaces only when this entry is used from a
`config:` axis's `default:` or `choices:` as `palette.<name>` (see
[Configuration](configuration.md#configuration)), where it becomes the same `<color
label="@Strings...">` and generated `<string>` an inline `label:` on a
`config:` choice already produces. A long-form entry with no `label:` behaves
exactly like the short form.

## Color scheme

```yaml
palette:
  black:      { value: "#000000", label: "Black" }
  white:      { value: "#FFFFFF", label: "White" }
  dark_gray:  { value: "#555555", label: "Dark Gray" }
  light_gray: { value: "#AAAAAA", label: "Light Gray" }

color_scheme:
  dark:
    label: "Dark"
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  light:
    label: "Light"
    colors: { bg: palette.white, fg: palette.black, dim: palette.light_gray }
```

A named set of role -> colour, picked on-device via a `config: style:` entry's
own `colors:` (below) -- the bare scheme name, e.g. `colors: dark`, not
`color_scheme.dark` (that qualified form is for expressions only).
`label:` on the scheme itself is shown in the editor's Styles list when the
style entry that names it has none of its own (the label fallback below) --
optional, same as everywhere else a label is: a scheme with none, referenced
by an entry with none, produces a generated `<style>` with no `label`
attribute. Each role's colour is resolved exactly like a `config:` axis's own
`default:` -- a literal `#RRGGBB`/`#RGB` or a `palette.<name>` reference,
never `config.*` (there is no build-time value for a runtime-editable field).

**Every `color_scheme:` entry must declare the identical set of roles.** `dark`
declaring `bg`/`fg`/`dim` and `light` declaring only `bg`/`fg` is an error
naming the missing role and the scheme that lacks it -- otherwise
`config.colors.dim` would be undefined the moment the wearer picked `light`.

Reference a role as an ordinary colour expression, exactly like a palette or
`config:` entry -- a **role**, never the scheme itself:

```yaml
color: config.colors.fg
color: heart_rate.current > 120 ? palette.hot : config.colors.fg
```

`color: config.colors` (naming the scheme, not a role) is an error saying a
colour scheme is not a colour and listing the declared roles; `config.colors.
<role>` naming a role no scheme declares is an error listing the roles that
are declared. The roles it may name come from the **default `config: style:`
entry's** own `colors:` scheme. Naming a `color_scheme` entry (in a style
entry's `colors:`) that was never declared, or was declared and rejected (a
bad role colour, a role-set mismatch), is an error at that `config: style:`
`choices:` entry, naming the schemes `color_scheme:` actually declares.

See [Configuration](configuration.md#configuration) for `config: style:` itself -- the axis that lets
the wearer pick between author-named entries, each naming a declared scheme.

## See also

- [`examples/showcase/face.yaml`](../../examples/showcase/face.yaml) — the status row and battery arcs shown above.
- [Configuration](configuration.md) — `config: style:`, `config.accent_color`, `config.colors.*`.
- [Data binding, expressions and formats](data.md) — the expression language a `color:` key uses.
- [Progress bars, arcs and graphs](progress-and-graphs.md) — `type: progress`, `style: arc`.
- [Text](text.md#outline--the-stamped-ring) — see `outline:`'s own colour rules; `outline.color` is exactly this same grammar.
