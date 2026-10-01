# gui-editor probe

Backs `docs/research/26-gui-editor.md`. Host-side only: it needs the device
files that `tools/setup-env.sh` installs, but no Garmin toolchain and no
simulator.

    ./.venv/bin/python docs/research/probes/gui-editor/probe.py

`results.txt` holds three experiments:

1. **Latency.** Times load (parse, schema, lower, desugar, IR), resolve (font
   bake, layout, lint) and preview render, in process, for four faces of
   increasing size. Run 0 is cold.
2. **Round trip.** Checks whether ruamel's round-trip `load` → `dump`
   reproduces each example face byte for byte. It runs twice: once with
   defaults, and once tuned the way `wfb migrate` tunes it.
3. **Span patch.** For up to three elements per face, rewrites only the text
   of `at.dy` in place, located by the composed node's `start_mark`/
   `end_mark`, to its value plus 10 in the author's own unit. It then checks
   that the diff is one line and that the resolved element moved down with
   its x unchanged.

Four more probes back `docs/research/28-editor-open-questions.md`:

- `structural.py` (`structural_results.txt`): every element found by its
  `span` in the composed tree, then the structural text patches (add or
  remove a key, delete, duplicate, reorder and add an element), each
  accepted only if it parses to exactly the intended data and loads with no
  error.
- `overrides.py` (`overrides_results.txt`): an `fr955` override inserted
  as a text patch, then a drag on each target patching the most specific
  source of `at.dy`, checking which devices move.
- `bake_cache.py` (`bake_cache_results.txt`): the pipeline per edit with
  font baking memoised, and the render checked pixel-identical.
- `schema-dialect/` (`results.txt`): `cases.py` writes valid and broken
  documents with `wfb`'s own verdict; `npm install && node check.mjs`
  validates them with the two drafts `codemirror-json-schema` uses.

`examples/dashboard` is skipped (it is the user's playground). Experiment 3
writes a temporary `.gui-probe.yaml` beside each face, so relative font paths
resolve, and deletes it afterwards.
