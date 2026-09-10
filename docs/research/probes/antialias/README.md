# Probe: anti-aliasing, fonts and primitives

Run before any anti-aliasing work was written, so the design below rests on
measurements rather than on what the API surface suggests.  **Read §3 before
emitting a `has` guard for anything** -- the trap there costs a warning-free
build and is invisible until a real `monkeyc` runs.

## 1. What the SDK actually says

Two entirely separate mechanisms, gated in two entirely different ways.

**Fonts** -- a *resource* attribute, `$CIQ_SDK/doc/docs/Core_Topics/Resources.html`
("Fonts"), quoted:

> Since bitmap fonts can take a lot of runtime memory, the font converter
> defaults to non-anti-aliased 1-bit fonts to save memory. If you know you will
> have the runtime RAM available, you can turn on font anti-aliasing with the
> antialias option.

```xml
<font id="font_id" filename="roboto.fnt" antialias="true" />
```

`$CIQ_SDK/bin/resources.xsd:62` types it `xs:boolean`, optional, on `fontType`.

**Font anti-aliasing needs no device gating.**  `doc/docs/Readme/History.html`
(v3.1.0.beta2, Compiler Changes) records that the toolchain gates it itself:

> Reduce memory consumption of fonts that have the antialias attribute set to
> true for devices that do not have the ability to render anti-aliased fonts by
> **overriding the attribute**. These devices include the Forerunner 45, the
> Forerunner 920XT, and the Edge 130.

**Primitives** -- a *runtime* `Dc` call, API 3.2.0.
`doc/Toybox/Graphics/Dc.html`:

> `setAntiAlias(enabled as Lang.Boolean) as Void`
> Enable anti-aliased drawing for primitives. **This method is not supported for
> a BufferedBitmap that has a palette.**

Listed for **113 of 164** devices (`docs/research/data/capability-matrix.json`,
`setAntiAlias`).  `doc/docs/Core_Topics/Graphics.html` gives the gating idiom
verbatim, and it is a `has` check rather than an API-level comparison:

```monkeyc
function draw(dc) {
  if(dc has :setAntiAlias) {
    dc.setAntiAlias(true);
  }
  dc.drawPolygon()
}
```

A build-time gate is not an option regardless: `wfb/emit/project.py` generates
**one view shared across every target device**, so the decision cannot be a
per-device constant.

> **Corrected (2026-09-10):** this paragraph used to add "and
> `dc.setAntiAlias(...)` would not typecheck under `-l 3` on a device whose
> `api.debug.xml` lacks the symbol". It would typecheck --
> `../device-symbol-gate/` shows a symbol absent from `fr955.api.debug.xml`
> compiling warning-free for `fr955`. The runtime `has` guard is still
> required; only that second reason for it was wrong.

`Dc.setAntiAlias` resolves through `Device.has_symbol` on all nine vendored
devices, so **this repo has no negative control**: the false branch of the `has`
guard is unexercised here and is trusted on Garmin's own documented idiom.

The `BufferedBitmap` restriction does not bite: `wfb/emit/monkeyc.py`'s
`_emit_static_allocation` already allocates without `:palette`, and says why.

## 2. Font anti-aliasing already worked -- measured, not assumed

`examples/slice/` built twice, identical but for `antialias: true` on the
`clock` font.  `monkeyc … -w -l 3`, all three targets, `BUILD SUCCESSFUL`:

| | `clock.png` | `.prg` (fenix8solar47mm) | `--build-stats` |
|---|---|---|---|
| `antialias: false` | 1,321 B, **2** grey levels | 96,108 B | 833 B data, 1,317 B code |
| `antialias: true` | 4,936 B, **256** grey levels | 96,780 B | 833 B data, 1,317 B code |

The resource compiler is genuinely consuming the grey ramp, not thresholding
it away -- which is the point this table proves, and it stands.

Note which number moved.  `--build-stats` is **unchanged** -- font pixels are a
resource, not foreground data, so the cost is invisible to the memory check
`wfb build` reports and shows up only in the `.prg`.  Any claim about what
anti-aliasing costs has to be made against file size, and the *runtime* RAM the
Resources page warns about is measured by neither and stays unquantified here.

> **The `.prg` figures in this section are contaminated and the exact delta
> here (+672 B) is wrong.**  The two builds were made at output paths of
> different lengths, and a `.prg` embeds the path it was built at -- see §6.
> The corrected figure is **+656 B**, and §6 carries the controlled table for
> both halves of the feature.  Left visible rather than silently rewritten,
> because the mistake is the transferable part.

`wfb/fonts/bmfont.py` needed nothing: `_rasterise` already skips its 1-bit
threshold when `antialias` is set, and supersamples at 16x either way.

## 3. The trap: do not name the helper `setAntiAlias`

A guard helper on the view named `setAntiAlias` compiles, and warns on **every**
target -- `:setAntiAlias` resolves against the view's own private method rather
than against `Dc`:

```
WARNING: fenix8solar47mm: SliceView.mc:40,8: The private symbol 'setAntiAlias'
will not be found when using the indirect lookup syntax ':setAntiAlias'.
Consider making 'setAntiAlias' public / protected or use a direct reference
'self.setAntiAlias'.
```

Renamed `applyAntiAlias`, the identical code is `BUILD SUCCESSFUL` and
**warning-free** under `-l 3` on all three targets.  The shape that was verified:

```monkeyc
private function applyAntiAlias(dc as Dc, on as Boolean) as Void {
    if (dc has :setAntiAlias) {
        dc.setAntiAlias(on);
    }
}
```

A direct, unguarded `dc.setAntiAlias(false)` also builds clean on all three --
they all have the symbol -- which is exactly why the guard cannot be judged by
building here, and why it is kept.

## 4. Task A: the format surface and font-baking plumbing

Built on top of §§1-3 above, which stand as measured.  This section records
what §§1-3 did not already answer, from the session that built the
`antialias:` key itself (top-level default, per-element resolution, `text`'s
rejection, and threading it through `wfb.icons.font_key`) -- everything that
touches `Dc.setAntiAlias` directly is a separate, later task and is not here.

**A single icon's cost, measured, not just a font's.**  An anti-aliased icon
is cheaper than an eleven-glyph font but not nearly as cheap as this section
originally claimed: it first reported **+48 B**, taken from two builds at
output paths of different lengths, and the controlled figure in §6 is
**+256 B** for the 30px `steps` icon.  `--build-stats` does not move for the
icon case either, for the same reason it did not for the font: an icon's
baked sheet is a resource, exactly like a declared font's.

**A combined design -- a declared font, a static icon, a dynamic
(`icon_for:`) icon and a carousel, all anti-aliased at once, all three
targets -- builds `BUILD SUCCESSFUL` and warning-free.**  Checked against the
`Bag` directly (`wfb.build.build`'s own `WARNING:` → diagnostic conversion),
not just the CLI's summary line: zero `Severity.WARNING` entries, three
`note[memory]` entries only.  This is the evidence R4's icon-font threading
(`font_key`, `icon_font_specs`, a carousel's per-item fonts) and R5's
font-inherits-the-face-default path do not interact badly when several of
them fire in the same view class.

**`antialias:` had to be accepted by the schema on a `text` element, not
rejected by it, for the same reason `on_tap:` is.**  The obvious reading of
"not accepted on text" is `additionalProperties: false` doing the rejecting.
That produces `wfb`'s generic "unknown key" diagnostic (code `schema`, a note
listing every allowed key) -- true, but not what CLAUDE.md's own working
agreement asks for here ("a clear error whose note points at
`fonts: <name>: antialias:`... naming the actual font"). So the schema's
`textElement` branch carries the same `$defs/antialias` `$ref` every other
branch does, and `wfb/ir.py`'s `Builder._reject_text_antialias` -- run from
`_build_text`, *after* `_resolve_font` has turned `font:` into a real
`element.font`/`element.font_is_custom` pair -- reports the bespoke error
instead.  Confirmed by disabling the check directly (`monkeypatch.setattr`)
and rebuilding the same design: it builds silently, with `resolved_antialias`
set to `True` on a `Text` element that never reads it -- correct-looking IR
state hiding a design that asked for something it did not get, exactly the
silent-gap shape CLAUDE.md already records twice.

**`font_key`'s new `antialias` parameter had to default to `False` and be
*appended*, not always included, in the returned string.**  The hard gate is
that every existing golden file stays byte-identical, and every one of them
was generated before this parameter existed.  Suffixing `_aa` only when
`antialias` is true means a design that never mentions the key produces the
exact string it always did (`icon_20pctr_uf02d1`, not
`icon_20pctr_uf02d1_False`); confirmed by asserting
`font_key(length, glyph) == font_key(length, glyph, False)` and by a full
`pytest -m "not slow"` / `pytest -m "slow"` run showing zero `git diff` in
`tests/golden/`.

**The collision this key exists to prevent reproduces cleanly by calling the
old two-argument form directly, no code reversion needed.**  Two icon
elements agreeing on `size:` and codepoint but not on `antialias:` still both
compute a real `font_key` value under the old signature -- it is just the
*same* value for both, so `wfb.emit.resources.icon_font_specs`'s `by_key`
dict (keyed by that string) drops one of the two `FontSpec`s silently: the
one built later in `face.walk()` order wins, and whichever icon asked for the
other setting gets that icon's sheet instead.  This is now a permanent test
(`tests/test_antialias.py::
test_two_icons_same_size_and_glyph_collide_without_the_antialias_key`) that
calls `icons.font_key(el.size, el.codepoint)` (no third argument) directly on
both elements and asserts the two calls return the same string, alongside
asserting the *fixed* `icon_font_specs` produces two distinct resources for
the same design -- so the regression is pinned from both directions without
needing to check out an earlier commit to reproduce it.

## 5. Task B: wiring `Dc.setAntiAlias` into the primitive side

Built on top of §§1-4. This is the piece §3's helper shape and §4's
`resolved_antialias` were both waiting for -- what actually calls
`applyAntiAlias` and where.

**The invariant that makes "set at the start, restore at the end" safe.**
`_emit_element_method` (`wfb/emit/monkeyc.py`) emits every guard -- `visible:`,
the value's `when_absent`, a nullable colour/track_color/max -- *before* the
call to `_emit_shape`/`_emit_progress`, and every one of them can `return`
early. Wrapping the *whole* generated method in a set/restore pair, as the
task's own wording ("at the start of that element's draw method... at the
end") reads most literally, would leave the Dc's anti-alias state changed on
a frame where a guard fired and nothing was actually drawn -- breaking the
invariant every other element's draw method silently relies on, that Dc is
already at the face default by the time its own drawing runs. Confirmed by
inspection that no guard sits *inside* `_emit_shape`/`_emit_progress`
themselves (a `progress` arc's internal early `return` happens **after** it
has already drawn both the track and the fill, not before), so wrapping only
the call site -- after every guard, immediately around the actual drawing --
is equivalent to "start/end of the drawing" and never leaves a dangling
override behind a guard's `return`. This is why `docs/format.md`'s section on
this says "sets and restores... around its own drawing", not "around its own
method".

**Reported cost, measured, not estimated -- and it is the opposite shape from
the font/icon side.** A declared font or icon's anti-aliasing is baked at
build time into a resource, so it moves the `.prg` and never `--build-stats`
(§§2/4 above). The primitive side is emitted *code*, so it is `--build-stats`
that moves, and the `.prg` moves with it for the same reason. On a controlled
two-element design (a filled rectangle, a stroked circle), identically on all
three targets:

| | `--build-stats` |
|---|---|
| off (no `antialias:` anywhere) | 460 B data, 260 B code |
| face default `true`, no element overrides | 469 B data, 299 B code |
| + one element overriding back to `false` | 469 B data, 323 B code |

So: the guarded helper plus one reset call in `onUpdate` is **+9 B data, +39 B
code**, and each element that overrides the face default adds a further
**+24 B code, +0 B data** for the two extra calls that set and restore around
its own drawing. Identical across all three targets, which is expected: this
is pure generated code, not a per-device resource, so nothing about screen
size or `deviceFamily` enters into it.

The `.prg` column this table originally carried (+192 B, then +176 B more) has
been dropped rather than corrected: those two builds were at output paths of
different lengths (§6), and `--build-stats` -- which is both deterministic and
the figure that actually counts against the 128 KB budget -- says everything
this side of the feature needs said.  §6 carries a controlled `.prg` figure
for the primitive side against a real example.

**Neither the visual softening nor any CPU/battery cost is measured, and this
probe does not claim otherwise.** There is no simulator (finding 11,
`CLAUDE.md`) or device in this container, so "does the edge actually look
softer" and "is a `has`-guarded call plus a state toggle per element
meaningfully slower per frame" are both open questions this repository cannot
answer from inside the sandbox. What is confirmed is only what real `monkeyc`
confirms: it compiles, and it is silent.

**`renderStatic`'s reset needed no special case, confirmed rather than
assumed.** `_emit_static_allocation` already allocates the buffer without
`:palette` (a reduced palette cannot take an anti-aliased font -- the reason
predates this task). `Dc.setAntiAlias`'s own doc entry says it is "not
supported for a BufferedBitmap that has a palette" -- read directly rather
than inferred -- so the same `applyAntiAlias(dc, ...)` call is legal on both
the buffer's own Dc (from `onLayout`) and the screen's (from `onUpdate` when
there is no buffer), and putting the reset inside `renderStatic` itself, once,
is what keeps that true without a second copy of the reasoning at each call
site. Verified with a real design whose *entire* static subtree draws
anti-aliased (`tests/test_antialias_primitives.py`'s `DESIGN_STATIC`
scenario): `BUILD SUCCESSFUL`, warning-free, on all three targets.

**The suppression target for `antialias-dither` is "first user in draw
order", and getting this wrong produces a real false negative, not a
crash.** Early in building the R4 lint check, a scratch design suppressed the
warning on the *wrong* element (the one an author might reach for first,
rather than the one `resolved.items` lists first) and the warning fired
anyway -- correctly, per the documented contract, but a reminder that
`check_graphics_pool`'s "report against the first representative, in draw
order" shape is a real contract an author has to follow, not an arbitrary
implementation detail. `docs/format.md` and `docs/limitations.md` both say
"first element, in draw order" explicitly for this reason.


## 6. A `.prg`'s size depends on the path it was built at

Found while checking §§4-5's reported figures, and it invalidates several of
them.  **The same generated source, built to two output directories whose
names differ in length, produces `.prg` files 80 B apart** -- verified with
`diff -r` reporting the `source/` trees byte-identical:

```
$ wfb build examples/slice/face.yaml --output …/p_short
$ wfb build examples/slice/face.yaml --output …/p_muchlonger_dirname
96,076 B   vs   96,156 B          # identical source/
```

A `.prg` embeds the paths of the files it was built from, so the build
directory's own name is inside it.  Repeated `monkeyc` invocations on one
fixed directory *are* byte-stable (eight runs, all 96,044 B), so this is not
non-determinism -- it is a dependency on an input nobody thinks of as one.

**Consequence for methodology, and it is the reusable part: a `.prg` size
comparison is only valid between builds whose output paths are the same
length.**  Prefer `--build-stats`, which has no such dependency and is also
the number that counts against the 128 KB budget -- but note it moves only for
emitted code, so the font/icon half of this feature has no honest instrument
except file size, taken carefully.

### The controlled numbers

All output paths held to equal length (`…/m/o_d1`, `…/m/o_d2`, `…/m/o_d3`,
`…/m/o_p1`, `…/m/o_p2`).  `fenix8solar47mm`; the other two targets move by the
same amounts.

**Fonts and icons**, on `examples/slice/`:

| | `.prg` | vs. previous | `--build-stats` |
|---|---|---|---|
| no `antialias:` anywhere | 96,076 B | — | 833 B data, 1,317 B code |
| + the eleven-glyph 68px `clock` font | 96,732 B | **+656 B** | *unchanged* |
| + the 30px `steps` icon | 96,988 B | **+256 B** | *unchanged* |

**Primitives**, on `examples/antialias/` -- the face default on, with
`background` overriding it back to `false`, against the same design with the
feature fully off:

| | `--build-stats` | total | `.prg` |
|---|---|---|---|
| no primitive anti-aliasing | 833 B data, 1,317 B code | 2,150 B | 96,876 B |
| face default on, one override | 842 B data, 1,380 B code | 2,222 B | 97,148 B |

**+72 B against the 128 KB budget, +272 B in the `.prg`**, decomposing exactly
as §5 says (+9 data / +39 code for the helper and its reset, +24 code for the
one override).  §5's decomposition was right; only its `.prg` column was not.

The R3 gate was re-checked here rather than taken on trust: the "off" row is
`examples/antialias/` with the *face default still `true`* and every
`shape`/`progress` element overriding back to `false`, and its generated view
contains zero occurrences of `AntiAlias` -- so the emitter really does skip
the whole feature, rather than emitting `applyAntiAlias(dc, false)` calls that
would be legal and would move every golden file.
