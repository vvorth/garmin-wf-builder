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
