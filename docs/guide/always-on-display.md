# Always-on display

**AMOLED forbids `onPartialUpdate` outright** (`modes-and-interaction.md`),
so a MIP-style low-power layout is not an option there. Instead, an
AMOLED target draws a constrained **always-on-display (AOD)** frame while
asleep, and Garmin's own guidance treats an absent one as a defect, not an
optional extra (`docs/research/11-always-on-display.md` §1.3). `aod:` is
how a design says what that frame looks like: overrides on the *one*
design, not a second layout to maintain.

`aod:` replaces the earlier `modes: [always_on]` outright (no shim):
`modes:` now means only the two MIP partial-update modes,
`active`/`low_power` (see [Power modes and touch-and-hold](modes-and-interaction.md)).

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `aod:` | any element, `group` | `hide` \| `show` \| an override block | inherited (see [Resolution](#resolution)) | this element's AOD behaviour |
| `aod:` | top level, beside `elements:` | `{default, dim, jitter, lint}` | — | face-wide AOD defaults |

## Per element or group

```yaml
aod: hide                          # not drawn in AOD
aod: show                          # drawn, unchanged (same as an empty block)
aod:                               # an override block: drawn, restyled
  color: "#555555"
  visible: battery.level < 20
```

An override block reuses the element's **own property names** — there is
no second vocabulary — restricted to a per-kind allowlist:

| Kind | Overridable |
|---|---|
| every kind | `visible` (conjoined with the element's own `visible:`, not replacing it) |
| `text` | `color`, `font`, `format` |
| `shape` | `color`, `thickness`, `filled` |
| `progress` | `color`, `track_color`, `thickness` |
| `icon` | `color` |
| `graph` | `color`, `thickness`, `bar_width` |
| `complication_slot` | `color`, `icon_color`, `font` |
| `hands` | `color`, `thickness` — applied to **every part of every hand** in the set |
| `pattern` | `color`, `thickness`, `font` — applied to **every part** |
| `group` | the union of whatever its descendants allow, pushed down |

An unknown or disallowed key for that kind is a schema error on the
author's own line — the schema reuses each kind's own property `$ref`s, so
there is nothing new to typo.

**Out of scope on purpose:** geometry (`at:`, `size:`, `radius:` — moving
things is jitter's job, a later slice) and data bindings (`value:`,
`series:`, `text:` — they would change what the sleep frame reads, and so
its cost).

## Face level

```yaml
aod:                  # top-level, beside elements:
  default: hide        # hide (default) | show — for elements whose ancestry says nothing
  dim: 0.4              # not implemented yet — see "What slice 1 does not do"
  jitter: 4              # not implemented — see "What slice 1 does not do"
  lint:                   # suppress a face-level AOD lint (aod-empty)
    allow: [aod-empty]
    reason: "prototype face, AOD comes later"
```

`default: hide` is the safe choice: an unconverted design lights nothing
extra in AOD. It fills an element's AOD visibility **only where nothing in
that element's own ancestry — itself, every ancestor group — ever mentions
`aod:` at all.**

## Resolution

Three rules, checked in order, for **each key independently** (`color`,
`thickness`, `visible`, …):

1. **The element's own `aod:` wins**, key by key, over its ancestors'.
2. **Otherwise the nearest ancestor group's `aod:` applies** — the nearest
   one that actually wrote something, walking up past a silent group.
3. **Otherwise the face's `aod: default:`** fills in — `hide` unless the
   face says `show`.

```yaml
aod: {default: hide}      # face-wide: hidden by default
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    color: palette.white
    aod: {color: palette.dim}   # the one element turned back on
```

That's the whole shape of "everything off but the time" — one line.

**One deliberate asymmetry.** An explicit `aod: hide` on a `group` hides
its **whole subtree unconditionally**, and no descendant can undo it — the
same way a group's `visible:` conjoins into everything beneath it, one
step stricter (nothing below can turn it back on). The face `default:` is
different: it is not explicit, so it only ever fills silence. This is what
lets a `default: hide` design still show a stray element with its own
`aod: show`, while a group's explicit `hide` really means it.

```yaml
elements:
  - id: complications
    type: group
    aod: hide              # sticky: nothing inside can override this
    children:
      - id: hr
        type: complication_slot
        slot: config.data.top
        aod: show            # has no effect -- warns: aod-unreachable
```

`visible:` follows the same conjunction it always did: `aod: {visible:
...}` is **ANDed with the element's own `visible:`**, not a replacement for
it — an element hidden while awake stays hidden in AOD too.

## What slice 1 does not do yet

This slice resolves, validates and stores every `aod:` key, and gates
*which* elements draw in AOD at all (`docs/limitations.md` §2). It does
**not** yet:

- apply an override's `color:`/`font:`/`thickness:`/etc. in the generated
  sleep frame — the AOD frame currently draws with the element's *awake*
  styling, unrestyled;
- load a separate AOD font;
- bypass a `static:` buffer for a static element's own `aod:` override —
  static content simply does not appear in AOD yet, whatever it declares;
- implement `dim:` or `jitter:` — both are accepted by the schema and
  rejected by the builder with a friendly "not implemented" error naming
  the slice that will build them.

Restyling, the AOD font and the static bypass land together in a later
slice; `dim:`/`jitter:` follow after that. See `docs/limitations.md` §2 for
the authoritative status.

## When the AOD frame runs

`_aod` (an internal field in the generated view) is true while the watch is
asleep **and** the device requires burn-in protection
(`System.getDeviceSettings().requiresBurnInProtection`, checked at
runtime, per device — never by API level). Two gates, from two different
moments:

- **Build time:** the AOD field, its sleep-hook bookkeeping and the
  `onUpdate` branch are emitted at all only when **some target in the
  build is AMOLED**. A face whose targets are all MIP generates the exact
  same source with or without `aod:` keys present — checked by a
  byte-identical test (`tests/test_aod.py`).
- **Runtime:** with a mixed target list (an AMOLED device alongside MIP
  ones, since the generated view is shared across every target in one
  build), the same generated code runs on every device, and
  `requiresBurnInProtection` is what tells them apart at runtime. A MIP
  device's sleep frame therefore stays **exactly the awake design** — AOD
  simply never applies there.

The AOD frame always starts by clearing the screen to black before drawing
anything, since `Dc` keeps its contents between `onUpdate` calls and the
awake frame's own background (if any) never draws there.

## Preview

```sh
wfb preview face.yaml --aod
```

Renders the resolved `aod:` set — unrestyled, matching slice 1's own
codegen — with every `awake`-only second hand hidden (AOD only ever runs
asleep). A design with no `aod:` anywhere renders blank under the face
default (`hide`).

`--asleep` is the narrower, older flag: it only hides an `awake`-only
second hand (`seconds: awake`), on any device shape, without touching AOD
set membership at all — useful for previewing analog hands with no `aod:`
declared. `--aod` implies it.

## Lints

- **`aod-unreachable`** (warning, suppressible) — an element's own `aod:`
  (a `show` or an override) that can never draw because an ancestor group
  already writes `aod: hide`.
- **`aod-empty`** (warning, suppressible on the face's own `aod: {lint:
  ...}`) — an AMOLED target where nothing in the design draws in AOD at
  all. Since the face default is `hide`, an unconverted design triggers
  this on every AMOLED target until at least one element opts in.

See [Lints and suppression](lints.md) for the general mechanism.

## See also

- [`examples/features/aod/face.yaml`](../../examples/features/aod/face.yaml) — the "everything off but the time" shape, on `fenix847mm`.
- [Power modes and touch-and-hold](modes-and-interaction.md) — `modes:`, the orthogonal MIP partial-update axis.
- `docs/research/11-always-on-display.md` — Garmin's own AMOLED rules and the design options this plan chose between.
- `docs/plans/14-aod.md` — the plan this chapter documents, slice by slice.
