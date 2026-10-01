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

`examples/dashboard` is skipped (it is the user's playground). Experiment 3
writes a temporary `.gui-probe.yaml` beside each face, so relative font paths
resolve, and deletes it afterwards.
