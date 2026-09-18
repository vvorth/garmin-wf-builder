# Monkey C and `monkeyc` behaviour

Moved verbatim out of `CLAUDE.md` on 2026-09-13 (§6 "Hard-won facts") so the file every
session loads stays small. `CLAUDE.md` keeps a short summary and the **same
numbering**, so an older citation such as "CLAUDE.md §6" or "CLAUDE.md
constraint 6" for this material resolves here. Keep adding to this file,
not back into `CLAUDE.md`.

---

Confirmed by real builds. Read before writing or generating any Monkey C.
Jungle/manifest/compiler-flag findings are in `docs/lore/codegen.md`.

**Monkey C / compiler behaviour:**

- `Graphics.Point2D` is a fixed-size **tuple**, not `Array<Number>` —
  declaring the generated constant `Array<Array<Number>>` compiles the
  constant fine and then fails at the `fillPolygon` **call site**.
- Type narrowing must go through a **local**, never a repeated field access —
  `_staticBuffer.getDc()` fails even after a null check on the field itself;
  `pulled.value` must be captured into a local first, every time.
- Monkey C has **no explicitly-typed local**: `var x as String? = null` is
  rejected outright.
- An unused **parameter** does not warn; an unused **member variable** does.
  (This is why a delegate takes a `view` parameter unconditionally but only
  holds a `_view` field when something actually reads it.)
- `switch` on a `String` case label compiles cleanly under `-l 3`.
- A typed `catch (ex instanceof ...)` clause works under `-l 3`, and catches
  both a thrown exception and a plain `false` return can be handled uniformly
  by wrapping the call, regardless of *why* a device declines.
- `BufferedBitmapReference.get` is absent from every `api.debug.xml` because
  it is inherited from `ResourceReference` — absence there does not mean the
  method does not exist.
- A helper method must not share a name with the API it wraps: a private
  `setAntiAlias` makes `:setAntiAlias` resolve to **itself**, and warns on
  every target ("will not be found when using the indirect lookup syntax").
  `applyAntiAlias` is warning-free.
- `WatchUi.animate` is documented to **crash the app** in low power mode, and
  the animated property must be public or protected — `animate()` looks it up
  indirectly through a `Symbol`, which a `private` member fails silently
  under (builds, but the lookup fails at runtime).
- `private` genuinely blocks a cross-class method call (confirmed by building
  both ways: dropping the modifier turns `Cannot find symbol ':method'` into
  a clean build) — a generated dispatcher that another generated class must
  call needs to be `public`, even when every other method like it stays
  `private`.
- Switching on `Complications.Id.getType()` — the type the *wearer* picked —
  typechecks under `-l 3` like any other enum switch, which is what lets one
  authored template serve every choice in a re-pointable complication slot
  instead of needing one generated variant per possible choice.
- **`Math.sin`/`Math.cos` are declared to return `Float or Double`** (checked
  in `bin/api.debug.xml`), not `Float` — a helper parameter meant to receive
  either result must be typed `Lang.Decimal` (`Float or Double`), not
  `Float`. A `Float`-typed parameter fails strict typing with a "Passing
  'PolyType<...Double or ...Float>' as parameter ... of non-poly type
  '...Float'" error, confirmed by building both ways
  (`docs/research/probes/analog-hands/`, finding 2) — the same
  compiles-fine-until-the-call-site shape `Graphics.Point2D` already caught
  for `Array<Array<Number>>` vs. `Array<Graphics.Point2D>`. Plain rotated
  vertex/coordinate `Float`s, by contrast, satisfy `fillPolygon`/`drawLine`/
  `fillCircle` under strict typing with no cast at all — it is specifically
  a *parameter declared `Float`* that a `Decimal`-typed value cannot narrow
  into, not `Float` values in general.
- **A nullable local's early-return narrowing survives *inside* a `for`
  loop body**, not just a straight-line method tail. `wfb.emit.monkeyc`'s
  pattern codegen (2026-09-15, `when_absent: hide` + per-copy part
  `visible:`) declares a nullable source's local once, guards it with
  `if (x == null) { return; }` **before** the copy loop, then reads that
  same local unguarded *inside* `for (var i = 0; ...) { ... }` — both in
  the loop's own gate condition (`if (i <= activityMoveBarLevel - 1)`) and
  through arithmetic on it. Confirmed warning-free under `-l 3` on all
  three targets, for a directly-nullable source (`activity.move_bar_level`)
  and one reached through a `Toybox.Complications` pull
  (`complication.battery`) alike — the local is never reassigned inside
  the loop, which is presumably why the narrowing holds; not tested with a
  local that *is* reassigned there.
- **A field *initialiser* runs before any `has` guard could ever matter.**
  `private var x as Complications.Id = new Complications.Id(...);` inline on
  a field declaration executes at construction, on every device, full stop —
  there is no way to wrap a field initialiser itself in `if (Toybox has
  :Complications)`. A value that needs a runtime guard before it can be
  built therefore has to be declared nullable and left `null` at the field,
  with the guarded construction moved into the constructor body instead
  (`wfb/emit/monkeyc/view.py`'s `_emit_config_fields`/`_emit_initialize`,
  2026-09-15, for a `config: data:` slot's `Complications.Id` on a target
  lacking `Toybox.Complications`). Obvious in hindsight, easy to reach for
  the field-initialiser spelling out of habit and get a construction-time
  crash on the very device the guard exists to protect.
- **A function cannot declare more than 9 parameters, and CIQ 3.x enforces
  it even though newer devices silently don't.** `runtime-lib/WfbGeom.mc`'s
  `drawTextRotated(dc as Dc, x as Number, y as Number, cx as Number, cy as
  Number, sin as Decimal, cos as Decimal, font as Graphics.FontType, text as
  String, justify as Graphics.TextJustification or Lang.Number) as Void` --
  10 parameters -- built warning-free on fenix7pro/fr255/fr955/fenix8+ (API
  5.2.0+) and every other device this project had tested until 2026-09-18,
  then failed outright on fenix6 (3.4.5), fenix6xpro (3.4.5) and fr245
  (3.3.6) with:
  ```
  Too many arguments passed to method 'drawTextRotated'. Only 9 arguments are allowed.
  ```
  No lint or `has_symbol` check catches this ahead of a real `monkeyc` run
  for the affected device, because it isn't a missing-symbol problem
  (6d above) -- the *function itself* fails to typecheck on that API level,
  before anything calls it. Fixed by splitting the function into two
  5-parameter halves (`rotatedX`/`rotatedY`), each returning one already-
  rounded scalar axis that the caller feeds straight into `dc.drawText`;
  folding parameters together (e.g. `cx`/`cy` into a `Point2D`) was rejected
  instead, since it would allocate a pair on every call inside a pattern's
  per-copy draw loop. `tests/test_parameter_limits.py` scans every
  `runtime-lib/*.mc` function and, for a few representative examples, every
  function the emitter generates, so a future helper cannot grow a 10th
  parameter unnoticed.
- **`Toybox has :ModuleName` works on a bare module name, the same operator
  used for a function or field** (`$CIQ_SDK/doc/docs/Monkey_C/
  Functions.html`'s own example, `Toybox has :Magnetometer`) — no special
  syntax for "does this module exist at all" versus "does this symbol on an
  object I already have exist". `wfb.devices.Device.has_module` mirrors the
  same check at build time, off a device's `<dataEntry type="module">` rows
  rather than `<functionEntry>`/`<symbolTable>` (`docs/research/probes/
  api-gating/`, 2026-09-15). UNVERIFIED at runtime on real hardware that
  lacks the module — the SDK docs' idiom, not observed (no simulator in
  this container).
