# The design file

The normative definition is [`schema/wfb-face-1.schema.json`](../../schema/wfb-face-1.schema.json).
This page explains the parts the schema cannot: *why* a key exists, and what the
platform does with it.

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `format` | top-level | integer, major version only | — | format version; the compiler refuses a version it does not know |
| `face.id` | `face:` | UUID | — | the Connect IQ application UUID — generate once, keep stable |
| `face.name` | `face:` | string | — | the face's display name |
| `face.version` | `face:` | string | `1.0.0` | the face's version string |
| `face.entry` | `face:` | identifier | from `face.name` | the Monkey C entry class name |
| `targets` | top-level | list of device ids | — | the default device set; `-d` may name others |
| `palette` | top-level | named colours | — | [Colours](colors.md) |
| `fonts` | top-level | TTF files → device fonts | — | [Fonts](fonts.md) |
| `color_scheme` | top-level | named sets of colour roles | — | [Colours](colors.md) |
| `config` | top-level | wearer-editable axes | — | [Configuration](configuration.md) |
| `hands` | top-level | named analog hand sets | — | [Analog hands](analog-hands.md) |
| `static` | top-level | elements that never change | — | [`static:`](elements.md#static--draw-it-once-then-blit-it) |
| `elements` | top-level, required | list, or mapping keyed by element id | — | [Elements](elements.md) |
| `layouts` | top-level | alternative static/elements sets, picked by a style | — | [Styles and layouts](styles-and-layouts.md) |
| `antialias` | top-level | `true`/`false` | `false` | [`antialias:`](elements.md#antialias--soften-an-edge) |
| `min_1px` | top-level | `true`/`false` | `false` | [`min_1px:`](elements.md#min_1px--never-let-a-relative-length-round-to-nothing) |

## Minimal shape

```yaml
format: 1               # major only; the compiler refuses a version it does not know
face:
  id: <uuid>            # the Connect IQ application UUID -- generate once, keep stable
  name: Slice
  version: 1.0.0
  entry: Slice          # optional: the Monkey C entry class name, from `name` if omitted
targets: [fenix8solar47mm, fenix8solar51mm, fr955]   # the default device set; `-d` may name others
palette: {...}
fonts:   {...}
static:   [...]        # optional: elements that never change -- see below
elements: [...]        # a list, or a mapping keyed by element id -- see below
```

**Unknown keys are an error, not a warning.** Silently ignoring a misspelled key
is how a design quietly loses an element. (The GUI, when it exists, has the
opposite rule: it must *preserve* keys it does not understand, so an older editor
cannot destroy a newer file. See ADR 0009.)

## Annotated skeleton (from the showcase)

```yaml
format: 1                                              # required
face: { id: <uuid>, name: Showcase, version: 1.1.0 }   # required
targets: [fenix8solar47mm, fenix8solar51mm, fr955]     # required

# optional
fonts:    { ... }   # TTF files -> device fonts
palette:  { ... }   # named colours (MIP: each channel 00/55/AA/FF)
color_scheme: { ... }   # named sets of colour roles: bg, fg, dim, ...
config:   { ... }   # what the wearer can change on the watch
hands:    { ... }   # analog hand sets

static:   { ... }   # optional: drawn once, then copied: backgrounds, cards
elements: { ... }   # required: redrawn every update
layouts:  { ... }   # optional: alternative static/elements sets, picked by a style
```

You can write element lists as a mapping, where the key is the id (as the
showcase does), or as a list of items that each carry an `id:`. Both mean the
same thing.

The snippets below refer to values by prefix. `palette.<name>` and
`font.<name>` point to your own `palette:` and `fonts:`. `config.*` are values
the wearer picks on the watch ([configuration](configuration.md)), such as `config.colors.fg` from the chosen
colour scheme or `config.accent_color`. Everything else, such as `time.*`,
`activity.*` or `weather.*`, is live watch data; `wfb sources` lists it all.

See [`docs/limitations.md`](../limitations.md) §2 for what is not built yet.
