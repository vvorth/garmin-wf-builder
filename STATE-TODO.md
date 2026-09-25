# STATE-TODO: handoff for the next session

Written 2026-09-25 to hand off an in-progress refactor to a fresh session.
**Delete this file once its work is done.** It is a handoff note, not
project documentation.

Branch: `claude/magical-brahmagupta-vmmn8m`. Everything below is committed
and pushed, and the working tree is clean.

## 1. Where things stand

**Plan 18** (`docs/plans/18-review-bug-fixes.md`) is built except §2.1, which
needs a user decision, and §2.2, which is optional. Nothing is in progress.

**Plan 19** (`docs/plans/19-architecture-refactor.md`):

- A0–A3 are done.
- A4 (the kind registry) is approved and **in progress** (see §2 below).
- A5 was approved with the "union" choice, but **the user said not to start
  A5**: "after a4 is done, do not start a5 task yet, i have something else in
  mind for you." Finish A4, then stop and ask the user what's next.
- A6, A7 and the P6 comment rule are still open questions for the user
  (plan 19 §5).

### A4 commits so far (all output-identical, fast suite at baseline)

| Commit | Step |
|---|---|
| `60a8769` | A4 design written into plan 19; A4 and A5 (union) approved |
| `901f90d` | scaffolding: `wfb/kinds/` registry, every per-kind switch site asks it |
| `3631f3f` | `progress` moved |
| `2126318` | `icon` moved |
| `8f76928` | `graph` moved |
| `f3c5807` | `shape` moved |
| `e44a5dd` | `text` moved |
| `929df0e` | `hands` moved (with `HAND_ANGLES`) |
| `d633b68` | `pattern` moved (with `PatternTextAngle`, `pattern_text_anchor`) |

## 2. What is left of A4

1. **Move `complication_slot`** into `wfb/kinds/complication_slot.py`. Its
   hooks still point at stage code:
   - `Builder._build_complication_slot` (via a lambda);
   - `Resolver._resolve_complication_slot`;
   - `_Renderer._complication_slot`;
   - `complication_slot_mod._emit_complication_slot`;
   - `layout_constants._complication_slot_constants`.

   `wfb/emit/monkeyc/complication_slot.py` is already a module for this kind
   alone. Leave it in place and have `emit_draw` call into it, the same way
   `graph` treats `wfb/emit/monkeyc/graph.py`. Things that also stay put:
   `Builder._resolve_icon_name`/`_resolve_icon_glyph`/`_ICON_SIZE_NOTE`
   (shared with `icon`), `_longer` (shared with `text`), and anything that
   `onLayout`, the delegate or the Data-axis config code reads for every
   slot. Plan 19's rule is that a site about one kind's own feature stays
   as it is.
2. **Move `group`** into `wfb/kinds/group.py`. Its hook is
   `build=Builder._build_group`. Group resolution is structural recursion
   inside `Resolver` and stays there (plan 19 A4 design). Move
   `_build_group` only if nothing else calls it. If `group` has nothing to
   move, record that and skip the commit.
3. **A4 docs close-out**, in one commit (root `CLAUDE.md` §7, same-commit
   rule):
   - `docs/plans/19-architecture-refactor.md`:
     - add A4 to the §1 Done table with the commits above;
     - fix the A1 row, which still says `layout.PatternTextAngle` and
       `layout.HAND_ANGLES`. Those now live at
       `wfb.kinds.pattern.PatternTextAngle` and `wfb.kinds.hands.HAND_ANGLES`;
     - rewrite §3 A4 as built, or cut it to a pointer;
     - update the status line and the §5 decisions table.
   - `docs/development.md`: add `wfb/kinds/` to the repo layout, with
     "adding a 10th kind = IR class + `Placed` class + one kind module +
     schema".
   - Root `CLAUDE.md` §6 pipeline table: `wfb/kinds/` spans every stage.
     Add one line, keeping it short.
   - `docs/lore/codegen.md`: most function paths were already renamed per
     kind. Re-grep `docs/` for the old names (below) as a final check.
   - Consider a dated amendment to ADR 0003 or 0004 naming `wfb/kinds/` as
     the per-kind home. The A4 rounds also changed a few code paths inside
     ADRs 0005 and 0008 in place, as one-token pointer fixes. Check that is
     acceptable under `docs/CLAUDE.md`'s "amend with a dated note" rule.
     They are pointer fixes, not decision changes.

## 3. How each move was done (the recipe)

The pattern to copy is `git show 3631f3f` (progress). Each finished kind
module is a worked example.

- A function moves into `wfb/kinds/<kind>.py` **if and only if only this
  kind uses it**. Grep every candidate for other callers, tests included,
  before moving it.
- The moved code is otherwise verbatim:
  - `self` becomes `b` (builder), `r` (resolver) or `renderer` (preview);
  - continuation lines are re-aligned wherever the rename moved the
    opening parenthesis;
  - imports are fixed;
  - no "moved from" comments are added.
- Hook signatures:
  - `build(b, node, common, path)`
  - `resolve(r, element, parent, depth)`
  - `draw_preview(renderer, placed)`
  - `emit_draw(w, resolved, placed, value_guards, plan, aod=NO_AOD)`
  - `layout_constants(prefix, placed)`
- Kind modules import stage modules at the top level and may call their
  underscored helpers. **Stage modules never import a kind submodule** and
  never read the registry at import time.
- Update every reference to a moved name:
  - tests that import or **monkeypatch** a moved function. Two rounds
    needed real fixes here: `test_antialias`'s monkeypatch target and
    `test_hand_angles`'s import;
  - docstrings and comments in `wfb/`, `tests/` and `tools/`;
  - one-token path mentions in `docs/`, excluding `docs/plans/` (handled by
    the close-out).
- Remove imports that become unused in the stage modules.

### Verifying each step (do this yourself; never trust a subagent's report)

```sh
# import-cycle sanity
for m in wfb.layout wfb.preview wfb.ir.builder wfb.emit.monkeyc.view wfb.lint wfb.validate wfb.kinds; do
  ./.venv/bin/python -c "import $m; import wfb.kinds as k; k.all()" || echo FAIL $m; done
# output identity (~3 min): must end "357 unchanged, 0 changed, 0 added, 0 removed"
env -u CIQ_SDK ./.venv/bin/python tools/snapshot.py compare <BASE> --no-garmin-fonts -j4
# fast suite (~1 min)
./.venv/bin/python -m pytest -m "not slow" -p no:cacheprovider --tb=short
```

**The snapshot baseline must be regenerated in a new session.** The old one
was under `/tmp` and does not survive. Every A4 commit is output-identical,
so a baseline saved at HEAD is valid:

```sh
env -u CIQ_SDK ./.venv/bin/python tools/snapshot.py save /tmp/base --no-garmin-fonts -j4
```

Save and compare with the same settings: `--no-garmin-fonts` and no
`CIQ_SDK` in the environment.

**Known fast-suite failures in this container**, all pre-existing and
environmental:

- `tests/test_cli.py::test_doctor_reports_a_working_environment`
- `tests/test_font_registry.py::test_every_installed_ww_filename_resolves_or_is_unmapped`
- `tests/test_templates.py::test_example_is_clean_on_every_target[showcase]`

Any other failure is new.

## 4. Working agreement for this work (user's instructions)

- Act as an orchestrator. A Sonnet subagent may do the implementation:
  plan the work, write requirements, get the results, **don't trust the
  report**, check everything yourself, and commit only when the repo is
  stable.
- Subagents must not run `git stash`, `commit`, `checkout`, `reset`,
  `restore`, `add` or `apply`, and must spawn no helpers. Run them one at a
  time.
- Commit and push after each step once it is verified. Commit trailer lines:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UxMMFfgsv4bjhbdU5vLUmb
  ```
- Don't open a PR unless asked. Push only to the branch above.
- Leave these alone:
  - `examples/dashboard/face.yaml`;
  - `vendor/devices/` and `vendor/fonts/`: gitignored licensed copies,
    never commit them.
- Subagents hit usage limits twice mid-round. Their partial work in the
  tree was sound both times. Check what is in the tree, finish or resume,
  then verify as above.

## 5. Open user decisions (don't act without an answer)

- Plan 18 §2.1: complication `ALTITUDE`/`CURRENT_TEMPERATURE` typed as
  Float vs Number on API 4.2–5.0 devices.
- Plan 18 §2.2: an optional `contrast` check for `track_color`/`icon_color`.
  It adds new warnings.
- Plan 19: the A6 items, A7 (only on explicit request), and the P6 comment
  rule in `CLAUDE.md`.
- After A4: **ask the user what's next. Don't start A5.**
