# 0.6 — Authoring ergonomics: how a design gets written

The Phase 2 slice proved the compiler works: a YAML design becomes a signed
`.prg` that runs on the watch. The next constraint is not the compiler — it is
that **writing the YAML by hand is harder than it should be**.

This document establishes what is actually hard, evaluates the two options
proposed (a visual GUI builder, and an LLM skill that works from a sketch),
researches the alternatives, and recommends an order.

Four experiments were run against the real toolchain; each is reproducible and
the commands are given.

---

## 1. What is actually hard

Not "YAML is hard". The friction is specific, and worth separating into
**essential** difficulty (the platform is genuinely like this) and **accidental**
difficulty (the tool could just be nicer).

A deliberately naive design was written — the kind of first attempt a competent
author or model produces *before* reading the format reference — and the errors
were catalogued:

| Friction | Kind | What it looks like |
|---|---|---|
| Element vocabulary is not guessable | accidental | wrote `type: rectangle`, `type: digital_clock`; the format wants `type: shape` + `shape: rectangle` |
| Positional keys are not guessable | accidental | wrote `x/y/width/height`; the format wants `at:` and `size:` |
| Required-key clusters | essential | `progress` with `style: arc` needs `radius`, `thickness`, `start_angle` **and** `sweep` |
| `when_absent` is mandatory and unfamiliar | **essential** | every `ActivityMonitor` field is nullable; the format refuses to guess |
| Data-source paths must be exact | essential | wrote `value: steps`, needs `activity.steps` |
| Format specs | accidental | wrote `format: "HH:MM"`, needs `"{:%H:%M}"` |
| Expression fields reject bare numbers | **accidental** | `max: 10000` is rejected; must be `max: "10000"` |
| Unit choice (`px` / `%` / `%r`) | **essential** | invisible on one device, wrong on another — see §4 |
| Palette legality | essential | `#FF6600` dithers on a 64-colour panel; unknowable without the tool |
| The blank page | accidental | no starting point that is not the one example |

The essential items are the platform being genuinely awkward, and the compiler
already handles them the only honest way — by refusing to guess. The accidental
items are ours, and several are cheap to fix.

---

## 2. What already exists that bears on this

The Phase 2 work left more authoring infrastructure in place than it looks:

| Asset | Bearing |
|---|---|
| **Published JSON Schema** | drives editor autocomplete today, via `yaml-language-server` |
| **Diagnostics with source spans** | every error names file, line, column, *and the fix* |
| **`wfb validate`** — 413 ms | a correctness oracle that needs no toolchain |
| **`wfb preview`** — 615 ms | a visual oracle that needs no toolchain and no simulator |
| **The lint's confidence labels** | teaches platform facts an author cannot know |
| **`wfb sources`** | the data-source catalogue, self-describing |

That combination is unusual, and it changes the analysis below: **the project
already owns a fast, honest feedback loop.** The question is who or what drives
it.

---

## 3. Experiment: can the compiler's own errors drive a correction loop?

The naive design above was corrected using **only** what `wfb validate` printed —
no reference to the format documentation.

```sh
wfb validate naive.yaml   # then fix only what it names, and repeat
```

| Round | What the compiler reported | Enough to fix? |
|---|---|---|
| 1 | unknown element types `rectangle`, `digital_clock`; `max` wrong type; `progress` missing 3 keys | ✔ — it lists the five valid types |
| 2 | unknown keys `x`, `y`, `width`, `height` | ✔ — it lists every key allowed there |
| 3 | bad time format; unknown source `steps`; `when_absent` required | ✔ — *"did you mean: activity.steps?"*, *"choose one of: hide \| placeholder \| fallback"* |
| 4 | remaining `when_absent` | ✔ |
| 5 | **valid**, with a warning: `#FF6600` will dither, *"nearest legal colour: #FF5500"* | — |

**Four correction rounds from a naive start, and every message named the fix.**
Total wall-clock: under three seconds of tool time.

This is the single most important finding in this document. The diagnostics were
written to serve a human author, and they turn out to be an *excellent* machine
correction signal — because ADR 0008 required each one to state what to do and
how confident it is, rather than merely what is wrong.

The palette warning is worth singling out: it taught a fact — that each channel
must be `0x00/0x55/0xAA/0xFF` — that no author and no model knows unprompted.

---

## 4. Experiment: the unit-round-trip problem (decides the GUI's architecture)

A GUI's core gesture is dragging. A drag produces **pixels**. The format's value
is **proportional**. These are not interchangeable:

```
A drag to 80.6 px above centre on the 47 mm can be written three ways.
All three are identical there, and all three differ on the 51 mm:

written as      fenix8solar47mm    fenix8solar51mm
-80.6px                 49.4 px            59.4 px
-31%                    49.4 px            53.2 px
-62%r                   49.4 px            53.2 px
```

A GUI that writes `px` back on every drag is not merely less elegant — it
**silently destroys the cross-device correctness the whole coordinate model
exists to provide** (ADR 0004). The design still compiles; it is just wrong on
every device but the one it was dragged on, and nothing reports it.

There are three ways out, and a GUI must pick one deliberately:

1. **Preserve the authored unit** and rewrite only the number. Correct for
   editing; says nothing about *creating* an element.
2. **Expose the unit** as a per-property control. Honest, and puts the format's
   most important concept in front of the author — but it is a lot of UI.
3. **Infer** (`%r` for radial, `%` for box-relative). Convenient, wrong
   sometimes, and wrong invisibly.

This is a genuine design problem, not a detail, and it is the strongest argument
that a GUI is *harder* than it appears rather than easier.

---

## 5. Experiment: sketch → YAML → preview

A deliberately crude sketch was drawn — wobbly bezel, a ring open at the bottom,
big time, an HR cluster and a step cluster side by side, a battery bar, and a
handwritten annotation reading *"steps goal ring"*.

It was converted by reading positions **as fractions of the dial radius**, which
map directly onto `%r`, and rendered with `wfb preview`.

**Result: structurally faithful on the first attempt.** Ring geometry, the open
bottom, the vertical stack order, and the side-by-side clusters all landed where
the sketch put them.

Two findings:

- **A sketch is proportional, and `%r` is the proportional unit.** The
  conversion is close to mechanical — *"this sits about 60 % of the way from the
  centre to the edge"* becomes `dy: 60%r`. The unit that makes the GUI hard (§4)
  is the one that makes the sketch workflow easy, because a sketch has no pixels
  to be seduced by.
- **The preview's system-font rendering is the weak link.** Custom baked fonts
  render with their real glyphs; **system fonts** (`FONT_SMALL` etc.) draw as an
  outlined box plus a default typeface, because the device faces — Pridi,
  Roboto Condensed, Bionic — are not on the host and **are not shipped in the
  SDK** (checked: it contains three sample fonts, none of them device faces).
  The *extent* is exact, from the published per-device metrics; only the glyphs
  are approximate. For visual comparison against a sketch, those boxes are noise.

**Honest caveat.** This experiment was run by a model that had just written the
compiler. It demonstrates that the format is *expressible* from a sketch; it
does **not** measure how a cold model performs. §3 is the better evidence for
that, because it deliberately started from ignorance.

---

## 6. Option A — a visual GUI builder

ADR 0002 already accepted this in principle: *"the GUI is a bidirectional editor
over that file… deferred to Phase 3.8, once the schema has stabilised."* So the
question is not whether, but **when** and **in what form**.

### What it genuinely solves

The blank page; element vocabulary and required-key clusters (a form cannot omit
a required field); palette legality (a picker that snaps to the 64 legal
colours); and immediate visual feedback with no command to run.

### What it does not solve, or makes worse

- **Unit round-tripping** (§4) — the format's hardest concept, and direct
  manipulation actively pushes toward the wrong answer.
- **`when_absent`** — a required dropdown per bound element. A form can enforce
  it, but cannot make the author understand why.
- **Expressions** — a text box in a GUI is still a text box.

### The two costs that are easy to underestimate

**The third-renderer problem.** ADR 0004's anti-drift guarantee holds because
the preview consumes *the same resolved IR* the code generator does. A GUI that
draws its own HTML-canvas rendering creates a **third** renderer — device Monkey C,
`preview.py`, and the canvas — and the guarantee is gone.

> The way out is architectural and cheap: make the GUI a **thin client over
> `preview.py`**. Render server-side to PNG, overlay hit regions computed from
> the resolved geometry the compiler already produces, and keep exactly two
> renderers. This is strictly better than a canvas reimplementation and is how a
> GUI should be built here whenever it is built.

**Schema churn.** Measured against what Phase 3 adds:

```
element vocabulary: 6 now -> 9 planned (50% growth)
per-element property counts today: shape 15, text 17, progress 19, icon 10, group 9
planned subsystems: config, per-device overrides, interactivity, segments/scale styles
```

A property panel is per-property work. Building it against a schema about to grow
by half — plus three subsystems that introduce entirely new UI concepts
(per-device override scoping, the four-axis config editor, tap/hold binding) —
means building much of it twice. **This is exactly why ADR 0002 put the GUI
last, and the measurement confirms the ordering was right.**

### Verdict

Right eventually, wrong now. Its cheapest correct form is a thin client over the
existing preview, and it should wait until the schema stops moving.

---

## 7. Option B — an LLM skill

The proposal is a skill that takes an image of a desired watch face, asks what
each element represents, and produces the YAML.

### What the evidence says

The image is the *easy* half. The valuable half is the **feedback loop the
project already owns** (§2, §3): a model that can run `wfb validate` and
`wfb preview` and read the results has a correctness oracle and a visual oracle,
both sub-second, both needing no Garmin toolchain.

Reframed, the skill is not *"turn a picture into YAML"*. It is:

> **Drive the compiler's own loop, using the image as the starting point and the
> preview as the check.**

That framing matters because it is what makes the output trustworthy rather than
plausible.

### Feasibility

| Question | Answer |
|---|---|
| Can a cold model converge from a naive draft? | Yes — four rounds, on error messages alone (§3) |
| Is a sketch expressible in the format? | Yes, and `%r` maps onto sketch proportions almost mechanically (§5) |
| How much reference material must it carry? | **~3.7 k tokens**: `docs/format.md` (2.7 k) + `wfb sources` (0.4 k) + one worked example (0.6 k). The schema (3.4 k) substitutes for the format doc |
| How fast is the loop? | validate 413 ms · preview 615 ms · build 1.7 s |
| Does it need special tooling? | No — a shell and the ability to view a PNG |

~4 k tokens of context and a sub-second loop is a comfortable fit for any
current model. Nothing about this requires a frontier model or a specific vendor.

### Risks, and what they need

1. **The model must be able to see its own preview.** Fine in Claude Code and
   any harness with image input; not universal. Without it the model is limited
   to `validate`, which still catches every *correctness* error but no layout
   mistakes.
2. **Preview text fidelity** (§5) is the weak link for visual comparison. Wants
   fixing before the skill leans on it heavily.
3. **A model will invent plausible-looking sources.** `activity.stps` is caught
   exactly; the danger is a *real* path bound to the wrong thing (`activity.calories`
   where the sketch meant floors). Only the question-asking step catches that,
   which is why the user's instinct to ask about each element is correct.
4. **Over-confident placement.** A model will produce a design that validates but
   looks wrong. The preview check is the mitigation, and the skill must make it
   non-optional rather than a suggestion.

### Verdict

High value, low cost, available now, and it does not depend on the schema
settling — the skill is a markdown file that names the current vocabulary, and a
schema change is a documentation edit rather than a rewrite.

---

## 8. Alternatives

Researched beyond the two proposed. Several are **prerequisites** that make
either option better, and are far cheaper than either.

| # | Alternative | Solves | Cost | Note |
|---|---|---|---|---|
| 1 | **Wire up schema autocomplete properly** — `.vscode/settings.json`, the modeline in every example, a documented setup | vocabulary, required keys | hours | The schema is already published and normative; almost nothing is needed to make editors use it |
| 2 | **`wfb preview --watch`** | feedback delay | small | Re-render on save. Turns "edit, run, look" into "edit, look". Helps humans *and* the skill |
| 3 | **`wfb new` templates** | the blank page | small | Two or three known-good starting designs beat an empty file and give a model a correct scaffold |
| 4 | **Fix the accidental frictions** (§1) | several at once | small | Accept `max: 10000` unquoted; consider `type: rectangle` sugar. Each one removes a correction round |
| 5 | **Improve preview text fidelity** | visual comparison | small–medium | Extents are already exact; render with a metric-scaled fallback face instead of a box. Prerequisite for B |
| 6 | **An MCP server** exposing validate/preview/build/sources | tool access | medium | *Packaging*, not a competitor to B: a skill is instructions, MCP is access. They compose |
| 7 | **A snippet library** — reusable fragments (`step ring`, `HR cluster`) | blank page, idiom | medium | Natural precursor to a real `include:` mechanism |
| 8 | **A TUI** | — | medium | Rejected: the value of a GUI is *visual* direct manipulation, which a TUI cannot offer |
| 9 | **Import from WFF / Facer** | migration | large | No corpus this project cares about. Not worth it |

Items 1–5 total to roughly the effort of a single afternoon each, and every one
of them improves both proposed options.

---

## 9. Recommendation

**Do B, after doing 1–5. Defer A until the schema stops moving.**

The reasoning in one paragraph: the project already owns the expensive half of an
authoring solution — a fast, honest, self-explaining feedback loop. A GUI would
*replace* that loop with direct manipulation and, in doing so, run straight into
the unit-round-trip problem (§4) and a schema that is about to grow by half (§6).
A skill *drives* the loop that already exists, costs a markdown file, works today,
and gets better every time a diagnostic improves.

Suggested order:

1. **The cheap frictions first** — alternatives 1–5. They are prerequisites, they
   help manual authoring immediately, and they shorten every correction round the
   skill will run.
2. **The skill.** Packaged as `SKILL.md` with YAML frontmatter (the convention
   in this environment) but written as plain, model-agnostic markdown so any
   reasonable model can follow it. It must:
   - interrogate the image *before* writing anything — what each element is, what
     data it shows, what happens when that data is absent;
   - read positions as fractions of the dial and write them as `%r`;
   - treat `wfb validate` and `wfb preview` as **mandatory** steps, not advice;
   - compare the preview against the source image and iterate;
   - never invent a data source — check `wfb sources`;
   - stop and ask rather than guess when the image is ambiguous.
3. **Revisit A after Phase 3**, when config, overrides and the remaining elements
   have settled — and build it as a thin client over `preview.py`, not as a
   second renderer.

The two are complementary in the end: a model produces a structurally correct
first draft in seconds, and a GUI nudges it into place. Doing them in that order
means the GUI is built against a stable schema and a corpus of real designs,
instead of guessing at both.

---

## 10. Open questions

- **How does a genuinely cold model perform on §5?** The sketch experiment was
  run by a model that had just written the compiler. The right test is a fresh
  session given only the skill and an image.
- **Where is the ambiguity ceiling for a sketch?** Structure and proportion
  transfer well. Colour, font choice, and which of several plausible data sources
  an element means do not — hence the question-asking step. Worth measuring how
  many questions a typical sketch actually needs.
- **Does the skill need per-device output?** A sketch is one image; a design
  targets three screens. The current answer is that `%r` handles it and the
  linter catches what does not — but per-device overrides (Phase 3) will want
  representing somehow.
- **Should the format grow sugar** (`type: rectangle`) or stay strict? Sugar
  removes a correction round; strictness keeps one obvious way to express a
  thing. Leaning strict, since the diagnostic already names the fix.

---

## Reproducing the experiments

```sh
# §3 -- the correction loop
wfb validate naive.yaml            # fix only what it names; repeat

# §4 -- unit ambiguity
wfb build design.yaml -d fenix8solar47mm --no-compile
wfb build design.yaml -d fenix8solar51mm --no-compile
diff build/*/source-fenix8solar47mm/Layout.mc build/*/source-fenix8solar51mm/Layout.mc

# §5 -- sketch round trip
wfb preview design.yaml -d fenix8solar47mm --scale 2

# timings
time wfb validate design.yaml
time wfb preview  design.yaml -d fenix8solar47mm
```
