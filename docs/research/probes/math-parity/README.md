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
   **A negative exact half rounds up too**: -2.5 is -2. VERIFIED on the
   simulator by `../text-of-values/` (2026-10-07).

4. **A `Number` wraps at 32 bits.** VERIFIED against the compiler's own
   constant folder (SDK 9.2.0, `fr955`, 2026-10-04): `2147483647 + 1`
   folds to `-2147483648`, `-2147483647 - 2` to `2147483647`,
   `100000 * 100000` to `1410065408` and `65536 * 65536` to `0`, two's
   complement. A literal past the range is a compile error: `The literal
   '4000000000' of type '$.Toybox.Lang.Number' is out of range.` Not
   observed on a running VM.
5. **A literal zero divisor is a compile error.** VERIFIED: `7 / 0`,
   `7 % 0` and `7.0f / 0` each fail with `Cannot divide by zero`.
   `(7).toFloat() / 0` compiles (the folder does not see through the call),
   so a divisor that is zero only at run time is never caught. What the VM
   does with one is not observed.

## What the compiler does with it

- `%` is folded and evaluated with truncation (`wfb.expr._mod`), and a
  Float operand is an `ExprError` at `wfb validate` time.
- An integer `+`, `-` or `*` whose constant result leaves the 32-bit range,
  a whole-number literal past it, and a divisor that folds to zero are each
  an `ExprError` at `wfb validate` time. The preview wraps a run-time
  overflow at 32 bits (finding 4).
- A divisor read at run time goes through `WfbMath.div`/`WfbMath.mod`,
  which give 0 for a zero divisor; the preview does the same (finding 5
  leaves the VM's own behaviour unknown, so the face never relies on it).
- `round` uses half-up (`wfb.expr._round`). A negative exact half is never
  constant-folded (`_round_foldable`): the call stays in the generated code
  so the device decides. The preview uses half-up there too, a guess.

`tests/test_expr_parity.py` (slow) makes findings 1 and 2 permanent. It
folds a table of operator cases through `monkeyc` and compares
`optimizer.mir` with the host, and it compiles every expression function
with Number and Float arguments under `-l 3`.
