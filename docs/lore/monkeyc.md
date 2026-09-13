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
