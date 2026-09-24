# Plan 18: bug fixes from the 2026-09-24 code review

**Status: items 1–8 and all of item 9 but §2.1 done (2026-09-24), one commit
per item (`d7fd497`..`2b99dfd`). Two small items remain (§2): one needs a
user decision, the other is optional.**
Read the full plan as written with `git show 8862941:docs/plans/18-review-bug-fixes.md`.
Delete this file once both items below are built or explicitly dropped
(`docs/CLAUDE.md`).

**Where these came from.** A seven-part review/refactor pass (commits
`6aacfee`..`f2efa36`) found behaviour bugs it deliberately did not fix.
Architecture proposals from the same review are in plan 19. Its A1–A3,
now built, are the structural follow-ups to items 3–4, 6 and 9: a slow
parity test, `Element.color_roles()`, and the barrel set scanned from the
generated code.

## 1. Done

| # | Item | Commit |
|---|---|---|
| 1 | `aod: {format}` with `%h` failed to compile | `d7fd497` |
| 2 | Weather readers lacked `requires_module`; built as a general `Guards.modules` `has`-guard, forecast graphs included | `d0eab80` |
| 3–4 | `round`/`percent`/`clamp`/`%` host ≠ device; `%` on a Float refused | `a2f63b4` (evidence: `docs/research/probes/math-parity/`) |
| 5 | Group-inherited unsupported `aod:` keys | `10fde7c` |
| 6 | Colour users missed `outline.color`/`aod:` colours | `6ffa2ad` |
| 7 | `_backdrop` per mode and layout | `05719ae` |
| 8 | `wfb preview --fonts` measured with one root, drew with another | `2b99dfd` |
| 9 | Minor batch, except §2.1 | `56d8142`, `d1a27a5`, `a85ed93`, `b50a3f7`, `5ced2d0`, `101b73a` |

Still UNVERIFIED on hardware: `Math.round` of a negative exact half. The
build never constant-folds that input (`docs/lore/monkeyc.md`).

## 2. Remaining

### 2.1 Complication value types across API levels (item 9) — needs a decision

`wfb/complications.py` types `ALTITUDE` and `CURRENT_TEMPERATURE` as `Float`.
The SDK (`$CIQ_SDK/doc/Toybox/Complications.html`) says they were `Number`
before 5.1.0 and 5.0.0 respectively. `as Float?` is a compile-time assertion,
not a conversion. On a 4.2.0–5.0.x device a `Number` arrives at runtime while
the expression compiler trusts `Float`, so `altitude / 1000` would skip its
`.toFloat()` coercion and truncate there.

Every installed device with `Toybox.Complications` is API 5.2.0 or newer, so
no installed device can show the old shape, and nothing here can be verified
on one. The candidate fix is device-independent: read these two as
`Numeric` and emit `.toFloat()`, so the value really is a `Float`
everywhere. It changes complication read codegen. The alternative is to
narrow the claim in `docs/limitations.md` and wait for a real 4.2–5.0 device
file.

### 2.2 `contrast` for `track_color` and `icon_color` (optional, from item 7)

`check_contrast` never judges a progress `track_color` or a
`complication_slot` `icon_color` against its backdrop. Since plan 19 A2 it
is a small change: `_contrast_subjects`' plain branch reads
`Element.color_roles()` and takes only the `ink`/`ring` roles, so adding
`track`/`icon` there is the whole code change. It adds new warnings, so
`tools/snapshot.py compare` would list exactly which.
