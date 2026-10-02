# ring-on-device probe

Backs `docs/research/28-editor-open-questions.md` §7: does the watch draw a
filled shape's `outline:` ring as the generated code's one grown copy, or as
the preview's stamp?  Five rows, each grown (left of a pair) beside a
hand-built stamp (right), 1 px then 2 px: a circle, a rectangle, a rounded
rectangle, a gauge bar (its ring a rounded rectangle whose corner radius is
the ring's width) and a filled circle part (ringed through
`WfbGeom.fillCircleRotated`, as a needle's, a hand's or a pattern's is).

    ./.venv/bin/python docs/research/probes/ring-on-device/make_face.py   # writes face.yaml
    ./.venv/bin/python wfb.py build docs/research/probes/ring-on-device/face.yaml -o build/ring-probe

Run `build/ring-probe/ring-probe/ring-probe-fenix8solar47mm.prg` in the
Connect IQ simulator on the host (fenix8solar47mm), save a screen capture,
then:

    ./.venv/bin/python docs/research/probes/ring-on-device/compare.py CAPTURE.png

It writes `compare_results.txt`: per shape and width, grown vs stamp on the
simulator, and each against the draw program's evaluator and today's
preview.
