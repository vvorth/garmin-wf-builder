# ring-on-device probe

Backs `docs/research/28-editor-open-questions.md` §7: does the watch draw a
filled shape's `outline:` ring as the generated code's one grown copy, or as
the preview's stamp?

    ./.venv/bin/python docs/research/probes/ring-on-device/make_face.py   # writes face.yaml
    ./.venv/bin/python wfb.py build docs/research/probes/ring-on-device/face.yaml -o build/ring-probe

Run `build/ring-probe/ring-probe/ring-probe-fenix8solar47mm.prg` in the
Connect IQ simulator on the host (fenix8solar47mm), save a screen capture,
then:

    ./.venv/bin/python docs/research/probes/ring-on-device/compare.py CAPTURE.png

It writes `compare_results.txt`: per shape and width, grown vs stamp on the
simulator, and each against the draw program's evaluator and today's
preview.
