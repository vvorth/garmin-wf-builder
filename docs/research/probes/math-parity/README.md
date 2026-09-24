# Probe: what do Monkey C's `%` and `Math.round` compute, so the host can match?

**Why.** `wfb/expr.py` evaluates every expression function and operator on
the host twice: to constant-fold (the answer is baked into generated code)
and to draw the preview. Plan 18 items 3–4 found the host using Python's
semantics (half-to-even `round`, floor-modulo `%`) where the device may not.
There is no simulator in the container (`docs/lore/codegen.md` finding 11),
so a Connect IQ unit test cannot run. This probe gets as far as the compiler
can take it. SDK 9.2.0, `fenix8solar47mm`, 2026-09-24.

## Method

Build any generated face, add `Probe.mc` to its `source/`, and rebuild with
the generated jungle plus `-l 3 --debug-log-level 3 --debug-log-output
dbg.zip`. `dbg.zip` holds `optimizer.mir` and `assembler.txt`, the code
after `-O 3z`'s constant-folding pass.

## Findings

1. **`%` truncates: the remainder takes the dividend's sign.** VERIFIED
   against the compiler's own constant folder. `optimizer.mir` folds
   `-7 % 3` to `-1`, and `assembler.txt` has `7 % -3` as `ipush1 1`.
   Python's `-7 % 3` is `2`. Not observed on a running VM. The compiler
   folding one way and the VM computing another would make `-O 0` and
   `-O 3z` builds of the same source disagree.
2. **`%` refuses a Float operand on either side** under `-l 3`: `Cannot
   perform operation 'mod' on types '$.Toybox.Lang.Float' and
   '$.Toybox.Lang.Number'` (and the mirror image). VERIFIED (compile error).
   `Long % Number` compiles.
3. **`Math.round` is not folded.** It stays an `invokem` of
   `Toybox_Math round` at run time, so the compiler says nothing about it.
   `$CIQ_SDK/doc/Toybox/Math.html` says "Decimal values >= .5 will be rounded
   up", which settles non-negative input (2.5 is 3, not Python's 2).
   **UNVERIFIED: a negative exact half.** -2.5 "rounded up" is -2, and
   rounded away from zero it is -3. The doc does not say which.

## What the compiler does with it

- `%` is folded and evaluated with truncation (`wfb.expr._mod`), and a
  Float operand is an `ExprError` at `wfb validate` time.
- `round` uses half-up (`wfb.expr._round`). A negative exact half is never
  constant-folded (`_round_foldable`): the call stays in the generated code
  so the device decides. The preview uses half-up there too, a guess.
