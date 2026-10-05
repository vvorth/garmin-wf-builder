// Renders every example face (except the dashboard playground) with
// `wfb preview` inside Pyodide, for parity.py to compare with native output.
// npm install pyodide@314.0.7, then, from the repository root:
//   node docs/research/probes/standalone-browser/parity.mjs <outdir>
// The host's HOME and the repository are mounted at their own paths, so
// the compiler finds devices, fonts and caches exactly where it does natively.
import { loadPyodide } from "pyodide";
import { readdirSync, existsSync } from "node:fs";
const repo = process.cwd(), home = process.env.HOME, out = process.argv[2];
const t0 = performance.now();
const py = await loadPyodide({ env: { HOME: home, WFB_OFFLINE: "1" } });
const tStart = performance.now() - t0;
const t1 = performance.now();
await py.loadPackage(["pillow", "ruamel-yaml", "jsonschema", "fonttools", "rpds-py",
                      "referencing", "attrs", "jsonschema-specifications"]);
const tPkgs = performance.now() - t1;
for (const dir of [home, repo, out]) {
  py.FS.mkdirTree(dir);
  py.FS.mount(py.FS.filesystems.NODEFS, { root: dir }, dir);
}
const faces = [];
const walk = (d) => { for (const e of readdirSync(d, { withFileTypes: true })) {
  if (e.isDirectory()) walk(`${d}/${e.name}`);
  else if (e.name === "face.yaml" && !d.endsWith("/dashboard")) faces.push(d.slice(repo.length + 1)); } };
walk(`${repo}/examples`);
py.globals.set("FACES", py.toPy(faces.sort()));
py.globals.set("REPO", repo); py.globals.set("OUT", out);
console.log(JSON.stringify({ startup_ms: Math.round(tStart), packages_ms: Math.round(tPkgs) }));
await py.runPythonAsync(`
import os, sys, time, json, io, contextlib
os.chdir(REPO); sys.path.insert(0, REPO)
from PIL import features, Image
print(json.dumps({"pillow": Image.__version__, "freetype2": features.check("freetype2"),
                  "raqm": features.check("raqm"), "zlib": features.check("zlib")}))
t = time.perf_counter(); from wfb import cli; print(json.dumps({"import_wfb_ms": round((time.perf_counter()-t)*1000)}))
for face in FACES:
    dest = f"{OUT}/{face.replace('/', '__')}"
    os.makedirs(dest, exist_ok=True)
    err = io.StringIO(); t = time.perf_counter()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["preview", f"{face}/face.yaml", "-o", dest, "-q"])
    except BaseException as e:
        code = f"{type(e).__name__}: {e}"
    ms = round((time.perf_counter()-t)*1000)
    print(json.dumps({"face": face, "code": code if isinstance(code, int) else str(code), "ms": ms, "stderr": err.getvalue()[-400:]}))
`);
