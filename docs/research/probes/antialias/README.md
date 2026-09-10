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
per-device constant, and `dc.setAntiAlias(...)` would not typecheck under `-l 3`
on a device whose `api.debug.xml` lacks the symbol.

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

**+672 B in the `.prg` for eleven glyphs at 68 px.**  The resource compiler is
genuinely consuming the grey ramp, not thresholding it away.

Note which number moved.  `--build-stats` is **unchanged** -- font pixels are a
resource, not foreground data, so the cost is invisible to the memory check
`wfb build` reports and shows up only in the `.prg`.  Any claim about what
anti-aliasing costs has to be made against file size, and the *runtime* RAM the
Resources page warns about is measured by neither and stays unquantified here.

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

**A single icon's cost, measured, not just a font's.**  §2 measured an
eleven-glyph *font* at 68px (+672 B).  One anti-aliased *icon* at 14%r costs
**+48 B**, identically on `fenix8solar47mm`, `fenix8solar51mm` and `fr955` --
smaller than the font case because it is one glyph's grey ramp rather than
eleven's, and identical across targets because the three screens differ only
in resolved pixel size, not in how a grey ramp compresses.  `--build-stats`
does not move for the icon case either, for the same reason it did not for
the font: an icon's baked sheet is a resource, exactly like a declared font's.

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
