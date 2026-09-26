# Wearer settings

`settings:` declares values the wearer can change after the face is
installed. Examples are whether to show seconds, or what a ring measures.
Each setting is stored on the watch as an `Application.Properties` value,
and any expression reads it as `settings.<name>`.

A setting is a different mechanism from [`config:`](configuration.md), the
fēnix 8's native face editor:

| | `config:` | `settings:` |
|---|---|---|
| Stored by | the native editor | `Application.Properties` |
| Reaches | fēnix 8 and newer only | every target, fr955 included |
| Holds | colours, a Styles entry, complication slots | a Boolean, one of named choices, or a colour scheme |
| Per saved configuration | yes, up to four | no: one value for all of them |

**How the wearer changes a setting: a menu on the watch.** The build
generates a settings menu, which the watch opens from its Watch Face menu
(`AppBase.getSettingsView`). A `boolean` is a toggle. A `choice` or a
`color_scheme` shows its current label, and selecting it moves to the next
one. The change applies
at once. Garmin Connect cannot do this for a sideloaded face: it edits
settings only for apps installed from the Connect IQ Store, private beta
included (`docs/research/17-phone-settings.md` §2).

Every installed device has the menu except `fenix5`/`fenix5x`, which keep
each `default:` and get a `settings-menu-unsupported` note. **Not yet seen
on a watch:** that the menu entry appears on `fr955`, and on a fēnix 8
beside the native editor, and that a change applies at once. There is no
simulator here, so this needs a sideload.

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `<name>:` | `settings:` | an identifier | — | read as `settings.<name>` |
| `label:` | a setting | string | required | the name the wearer sees |
| `type:` | a setting | `boolean` / `choice` / `color_scheme` | required | what the setting holds |
| `default:` | a setting | a Boolean; a key or scheme of `choices:` | required | the value until the wearer changes it |
| `choices:` | a `choice` setting | mapping of key → label, at least two | required | the options, in the order shown |
| `choices:` | a `color_scheme` setting | list of `color_scheme:` names, at least two | required | the schemes, in the order shown; each labelled by its own `label:`, or its name |
| `lint:` | a `color_scheme` setting | `{allow: [...], reason: ...}` | — | accepts `settings-scheme-overlap` |
| `edit:` | `settings:` | list of `watch`, `phone` | `[watch]` | where the wearer edits them: the [menu on the watch](#editing-on-the-watch-and-on-the-phone), Garmin Connect, or both |

## Example

```yaml
settings:
  show_seconds:
    label: "Show seconds"
    type: boolean
    default: true
  ring:
    label: "Ring shows"
    type: choice
    choices: { steps: "Steps", battery: "Battery" }
    default: steps

elements:
  - id: seconds
    type: text
    value: time.second
    visible: settings.show_seconds
  - id: steps_ring
    type: progress
    # ...
    visible: settings.ring == "steps"
  - id: battery_ring
    type: progress
    # ...
    visible: settings.ring == "battery"
```

## Editing on the watch and on the phone

`edit:` lists where the wearer edits the settings:

- **`watch`** (the default) generates the settings menu above.
- **`phone`** also generates `resources/settings/settings.xml`, which
  Garmin Connect reads to show the settings on the phone: a `boolean` as a
  switch, a `choice` as a list of its labels. **Garmin Connect edits
  settings only for a face installed from the Connect IQ Store, private
  beta included. It never does for a sideload,** so `phone` does nothing on
  a sideloaded face. This project does not package or upload to the Store.
  `phone` costs about 80 B, so it can stay on in case you ever do.
- `edit: [phone]` alone generates no menu, and draws a note: on a sideload,
  nothing can change these settings then.

```yaml
settings:
  edit: [watch, phone]
  show_seconds: { label: "Show seconds", type: boolean, default: true }
```

## Colour schemes

A `color_scheme` setting picks one of several declared
[`color_scheme:`](colors.md#color-scheme) entries, and any colour reads one
role of it as `settings.<name>.<role>`:

```yaml
color_scheme:
  day:   { label: "Day",   colors: { hours: palette.white, minutes: palette.white } }
  night: { label: "Night", colors: { hours: palette.red,   minutes: palette.orange } }

settings:
  theme:
    label: "Colours"
    type: color_scheme
    choices: [day, night]
    default: day

elements:
  - id: clock
    type: text
    value: time.hour
    color: settings.theme.hours
```

It is the same thing `config: style:` does with `config.colors.<role>`, but
through the settings menu, so it works on every target with the menu,
`fr955` included. A bare `settings.theme`, or a role the schemes do not
declare, is an error naming the roles.

When a scheme is offered both by a `color_scheme` setting and by a
`config: style:` entry, the `settings-scheme-overlap` warning fires: the
wearer would get two controls for one set of colours, in two places, and
nothing keeps the two in step. Accept it with the setting's own
`lint: {allow: [settings-scheme-overlap], reason: ...}`.

## Reading a setting

- A `boolean` setting is a Boolean anywhere an expression takes one:
  `visible: settings.show_seconds`, or
  `color: settings.bold ? palette.fg : palette.dim`.
- A `choice` setting can only be compared with one of its keys, as a quoted
  string, with `==` or `!=`: `settings.ring == "steps"`. Anything else is an
  error, including a key it does not have, which gets a "did you mean".
  The generated code compares a Number index, not a string.
- A setting is never absent. It needs no `when_absent:`, and it is not a
  data source, so it is allowed inside [`static:`](elements.md#static--draw-it-once-then-blit-it) content.
  When a setting changes, the static buffer is repainted.

## What it generates

- `resources/settings/properties.xml`, one property per setting: a
  `boolean` property for `boolean`, and a `number` property holding the
  default key's index for `choice`. A phone `list` setting accepts only a
  `number` property, so the index is the one storage both the watch and a
  phone could edit.
- One view field per setting, and `applySettings()`, which the view's
  constructor calls. Every read is type-checked, not only null-checked,
  because Garmin's developer FAQ reports the phone sending values of the
  wrong type. A value of the wrong type, or a `choice` index out of range,
  falls back to `default:`.
- `onSettingsChanged` in the app, which re-reads every setting and redraws.
- With `edit: phone`, `resources/settings/settings.xml` and a string
  resource for every title and choice label. `monkeyc` checks it and writes
  `<face>-<device>-settings.json` beside each `.prg`, the file the Store
  reads.
- The menu: `settingsMenu()` and `selectSetting()` on the view, a
  `<Face>SettingsDelegate` class, and `getSettingsView()` on the app. A
  selection writes the property and then runs `applySettings()`, the same
  path as a Garmin Connect push, because a write on the watch does not call
  `onSettingsChanged`.

Measured on the verification devices, for a face with one `boolean` and one
`choice` setting read by `visible:` guards on three elements: the settings
add 279 B (1,761 B to 2,040 B) and the menu another 619 B (to 2,659 B). On
`fenix5`, which never opens the menu, the two add 372 B and 1,044 B. In
`examples/features/settings/`, a `color_scheme` setting with two roles adds
373 B (499 B on `fenix5`), and `edit: phone` about 80 B.

## Things to know

- **Reordering or removing `choices:` changes what an installed face reads
  back.** The watch stores the index. A stored index past the end falls back
  to `default:`; one that is still in range now names a different key.
- **Renaming a setting resets it.** The name is the property key.
- **`edit` cannot name a setting**: it is the one reserved key under
  `settings:`.
- **One value for all saved configurations.** Nothing tells a face which of
  the wearer's four saved native-editor configurations is active, so a
  setting cannot differ between them.
- **Previewing a non-default value:** `wfb preview face.yaml --set
  show_seconds=false --set ring=battery`. A boolean takes `true`/`false`; a
  choice takes one of its keys.
