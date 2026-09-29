# The design file

The normative definition is [`schema/wfb-face-2.schema.json`](../../schema/wfb-face-2.schema.json).
This page explains the parts the schema cannot: *why* a key exists, and what the
platform does with it. A face written in format 1 is moved to format 2 with
one command, `wfb migrate` ([Moving a face to format 2](format-2-migration.md)).

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `format` | top level | `2` | — | format version; the compiler refuses a version it does not know |
| `face.id` | `face:` | UUID | — | the Connect IQ application UUID — generate once, keep stable |
| `face.name` | `face:` | string | — | the face's display name |
| `face.version` | `face:` | string | `1.0.0` | the face's version string |
| `face.entry` | `face:` | identifier | from `face.name` | the Monkey C entry class name |
| `targets` | `build:` | list of device ids | — | the default device set; `-d` may name others |
| `antialias`, `min_1px`, `aod` | `defaults:` | see each | `false`, `false`, `hide` | the per-element defaults every element inherits: [`antialias:`](elements.md#antialias--soften-an-edge), [`min_1px:`](elements.md#min_1px--never-let-a-relative-length-round-to-nothing), [`aod:`](always-on-display.md) |
| `aod` | top level | `{dim, mask, lint}` | — | the face-wide always-on frame settings: [Always-on display](always-on-display.md) |
| `fonts` | `resources:` | TTF files → device fonts | — | [Fonts](fonts.md) |
| `palette` | `resources:` | named colours | — | [Colours](colors.md) |
| `hand_sets` | `resources:` | named analog hand sets | — | [Analog hands](analog-hands.md) |
| `schemes` | `theme:` | named sets of colour roles | — | [Colours](colors.md#colour-schemes) |
| `config` | top level | wearer-editable axes | — | [Configuration](configuration.md) |
| `static` | top level | elements that never change | — | [`static:`](elements.md#static--draw-it-once-then-blit-it) |
| `elements` | top level | mapping keyed by element id | — | [Elements](elements.md) |
| `layouts` | top level | alternative static/elements sets, picked by a style | — | [Styles and layouts](styles-and-layouts.md) |

## Minimal shape

```yaml
format: 2               # the compiler refuses a version it does not know
face:
  id: <uuid>            # the Connect IQ application UUID -- generate once, keep stable
  name: Slice
  version: 1.0.0
  entry: Slice          # optional: the Monkey C entry class name, from `name` if omitted
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]   # the default device set; `-d` may name others
resources:
  palette: { ... }
  fonts: { ... }
static: { ... }         # optional: elements that never change -- see below
elements: { ... }       # a mapping keyed by element id
```

**Unknown keys are an error, not a warning.** Silently ignoring a misspelled key
is how a design quietly loses an element. (The GUI, when it exists, has the
opposite rule: it must *preserve* keys it does not understand, so an older editor
cannot destroy a newer file. See ADR 0009.) A format 1 key in a format 2
file is reported with the format 2 key that replaced it.

## Annotated skeleton (from the showcase)

```yaml
format: 2                                              # required
face: { id: <uuid>, name: Showcase, version: 1.1.0 }   # required
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]   # required
defaults: { antialias: true }                          # inherited by every element

# optional
resources:
  fonts: { ... }        # TTF files -> device fonts
  palette: { ... }      # named colours (MIP: each channel 00/55/AA/FF)
  hand_sets: { ... }    # analog hand sets
theme:
  schemes: { ... }      # named sets of colour roles: bg, fg, dim, ...
config: { ... }         # what the wearer can change on the watch
static: { ... }         # drawn once, then copied: backgrounds, cards
elements: { ... }       # redrawn every update
layouts: { ... }        # alternative static/elements sets, picked by a style
```

`static:`, `elements:` and a group's `children:` are mappings: the key is
the element's id.

The snippets in this guide refer to values by prefix. `color.<name>` is a
colour: a swatch from your `palette:`, or a role that follows a scheme or
the wearer's pick ([Colours](colors.md#colour-references)). `font.<name>`
points to your own `fonts:`. Everything else, such as `time.*`,
`activity.*` or `weather.*`, is live watch data; `wfb sources` lists it all.

See [`docs/limitations.md`](../limitations.md) §2 for what is not built yet,
and for the vocabulary format 2 reserves for later.
