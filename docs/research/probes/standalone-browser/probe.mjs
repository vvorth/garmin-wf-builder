// Times ruamel.yaml's round-trip parse of the showcase in Pyodide.
// npm install pyodide@314.0.7, then:
//   RUAMEL=<venv>/lib/python3.14/site-packages/ruamel REPO=<repo> node probe.mjs
// Compare: the same loop under ./.venv/bin/python (results.txt).
import { loadPyodide } from "pyodide";
const t0 = performance.now();
const py = await loadPyodide();
console.log("startup ms", Math.round(performance.now()-t0));
py.FS.mkdirTree("/sp"); py.FS.mount(py.FS.filesystems.NODEFS, {root: process.env.RUAMEL}, "/sp");
py.FS.mkdirTree("/site/ruamel");
py.FS.mkdirTree("/repo"); py.FS.mount(py.FS.filesystems.NODEFS, {root: process.env.REPO}, "/repo");
await py.runPythonAsync(`
import sys, os, shutil, time
shutil.copytree("/sp", "/site/ruamel", dirs_exist_ok=True)
sys.path.insert(0, "/site")
from ruamel.yaml import YAML
src = open("/repo/examples/showcase/face.yaml").read()
best = 1e9
for i in range(5):
    t=time.perf_counter(); YAML(typ="rt").load(src); best=min(best,time.perf_counter()-t)
print("wasm ruamel rt parse showcase ms", round(best*1000))
`);
