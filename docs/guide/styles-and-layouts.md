# Styles and layouts

A `layouts:` entry is a named set of widgets — a whole alternate clock face
or panel — that the wearer switches between on-device, riding the Styles
axis alongside (or instead of) a colour scheme. Combine a `layouts:` entry
and a `color_scheme:` entry in one `config: style:` entry to give the wearer
both at once, such as "Big · Dark" versus "Compact · Dark" below.

![three styles: Big · Dark, Big · Light, Compact · Dark](../screenshots/styles.png)
*From [`examples/features/styles`](../../examples/features/styles/face.yaml), rendered with `--all-styles`.*

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `layouts:` | top-level | mapping of named layout entries | — | [Styles and layouts](#styles-and-layouts) |
| `layouts: <name>: static:` | one layout | list or mapping of elements (Form A) | — | this layout's own fixed furniture |
| `layouts: <name>: elements:` | one layout | list or mapping of elements (Form A) | — | this layout's own per-frame elements |
| `layouts: <name>: lint:` | one layout | `{allow: [...], reason: ...}` | — | suppress `unreachable-layout` on this layout |
| `layout:` | a `config: style:` entry | bare `layouts:` name | — | required once `layouts:` is declared |
| `colors:` | a `config: style:` entry | bare `color_scheme:` name | — | see [Configuration](configuration.md); all-or-none per `choices:` list |
| `label:` | a `config: style:` entry | string | falls back to the scheme's own `label:` | shown in the editor's Styles list |
| `lint:` | a `config: style:` entry | `{allow: [duplicate-style], reason: ...}` | — | suppress `duplicate-style` on this entry |

## Styles and layouts

```yaml
layouts:                       # ordered; layout index = declaration order
  digital:
    static:
      steps_track: { type: shape, shape: arc, ... }
    elements:
      clock:     { type: text, value: time.clock, format: "{:%H:%M}", ... }
      steps_arc: { type: progress, style: arc, value: activity.steps, ... }
  analog:
    elements:
      mini_clock: { type: text, value: time.clock, format: "{:%H:%M}", ... }
      pin:        { type: shape, shape: circle, ... }

config:
  style:
    default: digital
    choices:
      digital: { label: "Digital", layout: digital, colors: dark }
      analog:  { label: "Analog",  layout: analog,  colors: dark }
```

A named set of widgets, drawn on top of whatever the design's shared
`static:`/`elements:` already draw, while the wearer has the matching
`config: style:` entry active. **Form A
only -- there is no element-level membership key.** An element belongs to
exactly one layout by being written inside that layout's own `static:`/
`elements:`, or to every layout by being written in the design's ordinary,
top-level `static:`/`elements:` instead. At build time each layout's
`static:`/`elements:` are folded into two synthetic groups appended to the
top-level `elements:` (`wfb/desugar.py`), so a layout's own content accepts
the same two spellings -- a list, or a mapping keyed by id -- that `elements:`
and the top-level `static:` do.

**`layout:` on a `config: style:` entry** names one declared `layouts:` entry
by its bare name (`layout: digital`, not `layouts.digital`), the same
spelling `colors:` uses for a `color_scheme:` entry. It is required on every
entry once a design declares `layouts:` at all, and rejected when it does
not -- an entry that named no layout in a design that has them would leave
the wearer looking at a face with only the shared content on it, silently.
Every entry still needs at least one of `layout:`/`colors:`, and `colors:`
stays all-or-none across every entry in one `choices:` (see [Configuration](configuration.md#configuration)) -- a colour scheme and a layout are independent choices an entry can
mix freely, so `digital_dark`/`digital_light`/`analog_dark` (two layouts,
two schemes, three entries) is exactly as legal as the two-entry example
above. **`layouts:` declared with no `config: style:` entry ever naming one
is an error** -- nothing would let the wearer pick it.

**The z rule is fixed, not authored.** Layout content always draws above the
design's shared content, in its own layer -- static and dynamic alike --
regardless of `z:`. A shared element with `z: 50` still draws *before* every
layout element, including one with no `z:` at all; `z:` only orders content
*within* the shared layer or *within* one layout's own layer. There is no way
to interleave a layout's content with the shared content by `z:` -- writing
one is the escape route a later phase does not build (plan 02 §12.3).

**A `complication_slot` may not appear inside a `layouts:` body, in either
`static:` or `elements:`.** The Data axis is face-wide -- one `<complication
id=...>` in the generated resource, however many layouts read it -- so a
slot belongs in the shared top-level `elements:` only. This also keeps the
editor's own hit-testing and `getComplicationDrawable` simple: there is
exactly one element that ever draws a given slot, never one per layout (plan
02 §12.5).

**`unreachable-layout` (suppressible).** A declared layout no `config: style:`
entry's `layout:` ever names can never be drawn -- but its elements, fonts and
code still ship in the `.prg`, the same "content is not free" point plan 02
§1 makes about every layout. Warned once per design, at the layout's own
line, and suppressed with `lint: {allow: [unreachable-layout], reason: ...}`
on the **layout body** (`layouts: <name>: { lint: {...} }`) -- a layout has
no element of its own to hang `lint:` on otherwise.

**Codegen.** `resolveStyle` (see [Color scheme](colors.md#color-scheme)) decodes one `styleId`
into *two* things now: the scheme colours (if the entry has `colors:`) and
`_configLayout` (if it has `layout:`) -- a layout-only entry emits no colour
lines, and a colour-only entry emits no `_configLayout` line. Every draw call
-- `onUpdate`, `onPartialUpdate`, and each static root's call inside
`renderStatic` -- is guarded by `if (_configLayout == N)` for a layout
element, and left unguarded for shared content; consecutive calls that share
one layout share one guard block. An `on_hold:` target with a layout gets its
hit test folded into the same guard, through a public `configLayout()`
accessor the generated delegate calls. Nothing here needs a second buffer or
new repaint logic: a style edit already reaches `applyConfig`, which already
calls `repaintStatic()` for a static config colour -- a layout switch is just
another field `applyConfig` sets before that call.

**On fr955** (no native editor, CLAUDE.md constraint 6): `applyConfig` is
never called, so the compiled-in default entry's layout is what the wearer
sees forever -- the same "keeps every declared default" behaviour every
other `config:` axis already has there, `config-unsupported` included.

**Preview.** `wfb preview --style <entry>` renders one entry -- its scheme's
colours and only the shared content plus that entry's own layout, exactly
what the wearer would see with it active; omitted, it renders the default
entry. `--all-styles` renders every entry side by side in one PNG per
device, each panel captioned with the entry's label. Both are the same
renderer, run once per entry -- there is no second rendering path to drift
from the device (ADR 0004).

![all seven showcase styles: three layouts times three colour schemes](../screenshots/showcase-styles.png)
*The showcase face's own `--all-styles` render — see [Configuration](configuration.md).*

## See also

- [`examples/features/styles/face.yaml`](../../examples/features/styles/face.yaml) — two layouts, each with its own static and dynamic content.
- [Configuration](configuration.md) — the `config: style:` block itself, and the two colour axes.
- [Colors](colors.md) — `color_scheme:` entries, referenced here as `colors:`.
