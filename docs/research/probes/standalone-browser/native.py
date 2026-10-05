"""The native half of the parity probe: the same loop as parity.mjs.

    ./.venv/bin/python docs/research/probes/standalone-browser/native.py <outdir>
"""
import contextlib, io, json, os, sys, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
os.environ["WFB_OFFLINE"] = "1"
out = sys.argv[1]
t = time.perf_counter(); from wfb import cli
print(json.dumps({"import_wfb_ms": round((time.perf_counter() - t) * 1000)}))
faces = sorted(str(p.parent) for p in Path("examples").rglob("face.yaml") if p.parent.name != "dashboard")
for face in faces:
    dest = f"{out}/{face.replace('/', '__')}"
    os.makedirs(dest, exist_ok=True)
    err = io.StringIO(); t = time.perf_counter()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(["preview", f"{face}/face.yaml", "-o", dest, "-q"])
    print(json.dumps({"face": face, "code": code, "ms": round((time.perf_counter() - t) * 1000),
                      "stderr": err.getvalue()[-400:]}))
