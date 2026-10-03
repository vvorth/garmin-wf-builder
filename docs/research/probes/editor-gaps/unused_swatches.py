"""Build the minimal starter twice, with its 3 swatches and with all 64 MIP
swatches added unused, and print each build's measured memory."""
import re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from wfb import starters
from wfb.edit.spans import index_for

base = starters.instantiate("minimal", "Swatches")
mip = index_for(Path("wfb/templates/palette.yaml").read_text()).data["resources"]["palette"]
extra = "".join(f'    {n}: {{ value: "{e["value"]}", label: "{e["label"]}" }}\n'
                for n, e in mip.items() if n not in ("bg", "text", "dim"))
full = base.replace('    dim: "#AAAAAA"\n', '    dim: "#AAAAAA"\n' + extra)
assert full != base
for label, text in (("3 swatches", base), (f"3 + {len(mip)} unused", full)):
    d = Path(tempfile.mkdtemp()); (d / "face.yaml").write_text(text)
    out = subprocess.run([sys.executable, "wfb.py", "build", str(d / "face.yaml"),
                          "--device", "fenix8solar47mm", "-o", str(d / "out")],
                         capture_output=True, text=True)
    mem = [l for l in (out.stdout + out.stderr).splitlines() if re.search(r"memory|bytes|warning", l, re.I)]
    print(f"{label}: exit {out.returncode}", *mem[:6], sep="\n  ")
