# outline-everything probe

Backs `docs/research/19-outline-everything.md`. Host-side only: a Pillow
model of rasterisation, not a Connect IQ build, so every number is a model
of the device, not a measurement of it.

    ./.venv/bin/python docs/research/probes/outline-everything/probe.py

- `results.txt`: analytic polygon/line offsets vs. true dilation over 60
  rotations; icon openings kept after a stamped ring; group union by two
  passes vs. per member.
- `icons.png`: five catalogue icons at 40 px, ring width 0 / 1 / 2.
- `group.png`: a circle + bar group, per-member rings (left) vs. two passes
  (right).

Needs numpy and scipy in `.venv` (installed for the stamped-ring probe; not
in `requirements.txt`, nothing under `wfb/` imports them).
