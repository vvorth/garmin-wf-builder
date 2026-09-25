# Plan 18: bug fixes from the 2026-09-24 code review

**Status: items 1–9 done (§2.1 on 2026-09-25, the user chose "always
convert"). §2.2 (optional) is approved and next.**
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

### 2.1 Complication value types across API levels (item 9) — built

Every `Float` complication is read as `Numeric?` and converted with
`.toFloat()` (`wfb.catalog.Source.to_float`, `ReadPlan._declare_paths`),
so `ALTITUDE` and `CURRENT_TEMPERATURE` are real Floats on API 4.2–5.0 too.

### 2.2 `contrast` for `track_color` and `icon_color` (optional, from item 7)

`check_contrast` never judges a progress `track_color` or a
`complication_slot` `icon_color` against its backdrop. Since plan 19 A2 it
is a small change: `_contrast_subjects`' plain branch reads
`Element.color_roles()` and takes only the `ink`/`ring` roles, so adding
`track`/`icon` there is the whole code change. It adds new warnings, so
`tools/snapshot.py compare` would list exactly which.
