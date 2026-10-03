# Probes for research 30 (editor gaps)

Run from the repository root with `./.venv/bin/python <probe>`; results are
the matching `*_results.txt`.

| Probe | What it shows |
|---|---|
| `schemes.py` | twelve single scheme edits through the editor's own patch functions and `Gate`: which are accepted, which refused, and why |
| `compound.py` | the compound scheme edits (make switchable, add a scheme, add a role everywhere, delete a scheme, remove the theme keeping one) as one `chain`ed patch each, through the same gate; and C2's two options for removing the theme from the showcase, with the design lints run on the second |
| `unused_swatches.py` | `wfb new -t minimal` built for fenix8solar47mm with 3 swatches and with the 64 MIP swatches added unused: the measured memory of each |
| `origin.py` | the editor app, through Starlette's test client, accepting a request with a foreign `Host` and `Origin` and a `text/plain` body |
