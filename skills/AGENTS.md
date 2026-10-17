# skills/: agent skills that use wfb

This directory holds instructions for AI agents that *use* this repository's
`wfb` tool, as opposed to working on it. There is one skill today,
**watchface-from-image**.

| File | What it is |
|---|---|
| `watchface-builder.md` | the procedure, model-agnostic: any agent with a shell and file access can follow it |
| `face-compare.py` | target picture vs `wfb preview`, as one sheet (target, preview, overlay, difference) with a score per region; needs `python3` with Pillow |
| `../.claude/skills/watchface-from-image/SKILL.md` | the Claude Code adapter: registers the skill and adds what is specific to Claude Code |

## The branch rule

The skill lives on the branch **`skill/watchface-from-image`**, which is kept
minimal so it rebases onto `main` without conflicts:

- **The branch changes `skills/` and nothing else**, apart from the one
  adapter file Claude Code needs at `.claude/skills/watchface-from-image/`.
  No edits to `CLAUDE.md`, `README.md`, `docs/`, `ts/`, `schema/` or
  `examples/`, not even a one-line mention: those files change on `main`
  all the time and every such edit is a future rebase conflict.
- **When `main` changes the format, update the skill here**: rebase onto
  `main`, then fix `watchface-builder.md` and `face-compare.py` to match.
  The guide (`docs/guide/`), `wfb schema` and the compiler's own error
  messages are the truth; the skill follows them, never the reverse.
- **Something the skill needs from the compiler** (a new flag, a new
  preview mode, a fixed bug) is a separate change made on `main`, not on
  this branch.
- **No tests, by the user's decision.** Check an update by hand instead:
  1. extract the Quick reference YAML from `watchface-builder.md` (give it
     a real UUID and copy `examples/dashboard/assets/ChivoMono-Bold.ttf`
     beside it into `assets/`), and `./wfb validate` it: clean apart from
     notes;
  2. do the same with the AMOLED snippet on an AMOLED target
     (`fenix847mm`);
  3. do the same with the slot snippet (`left_slot`), under a header that
     declares a `face:` font `reading` and the palette entries it names;
  4. run `python3 skills/face-compare.py` on an
     `examples/generated_by_skill/` face and its PNG: it must render, crop,
     score and write a sheet.

## Scope of watchface-from-image

**What it does:** turns a picture of a watch face (a screenshot, a photo, a
mockup, a sketch) or a description into a format 2 `face.yaml` that looks
as close to the picture as the platform allows, then into signed `.prg`
files. The steps are: check the environment (`wfb doctor`), take the picture
apart and measure it in `%r`, ask once about what the picture cannot say,
start from a `wfb new` template, loop on `wfb validate` until clean, loop on
preview-and-compare (`face-compare.py`) until the render matches, check the
hands at a second time, and finish with a warning-free `wfb build` and a
report.

**What it writes:** one new face directory (the one the person names, else
`build/faces/<name>/`): `face.yaml`, any font it copies into `assets/`, and
compare sheets and previews under `build/`. Nothing else.

**Out of scope:**

- changing the compiler, the schema, the runtime library, the docs or the
  examples (`examples/dashboard/face.yaml` is the user's playground, and is
  never edited); a missing feature is reported, with the closest thing that
  exists, not built;
- putting the `.prg` on a watch: the person copies it over USB;
- the Connect IQ simulator: it does not run in a Linux container, so the
  preview is the loop's renderer;
- other companies' logos and wordmarks, unless the person says they own
  them;
- a picture it cannot see: the agent asks for a description instead of
  guessing.

**Inputs it depends on:** the repository's `wfb` and its environment
(`./tools/setup-env.sh`; Garmin's device files, which only the person can
supply), and, for the compare loop, `python3` with Pillow.
