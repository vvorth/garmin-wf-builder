"""Which symbols referenced by a generated project are absent on a device?

usage: absent_scan.py <project_dir> <rich_device> <poor_device>

<project_dir> is a build output directory (e.g. build/dashboard), containing
source*/*.mc and runtime-lib/*.mc. Device api.debug.xml files are read from
vendor/devices/<device>/<device>.api.debug.xml, resolved relative to the repo
root (override with the CIQ_VENDOR_DEVICES env var).
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VENDOR = Path(os.environ.get("CIQ_VENDOR_DEVICES", REPO_ROOT / "vendor" / "devices"))


def syms(dev):
    text = (VENDOR / dev / f"{dev}.api.debug.xml").read_text()
    funcs = set(re.findall(r'<functionEntry[^>]*name="([^"]+)" parent="([^"]+)"', text))
    funcs = {(p, n) for n, p in funcs}
    mods = set(re.findall(r'<dataEntry [^>]*symbolId="([^"]+)" type="module"', text))
    classes = set(re.findall(r'<apiScopeEntry classId="([^"]+)"', text))
    return funcs, mods, classes


proj, rich, poor = sys.argv[1:4]
rf, rm, rc = syms(rich)
pf, pm, pc = syms(poor)
absent_funcs = rf - pf
absent_names = {n for _, n in absent_funcs} - {n for _, n in pf}  # names wholly absent
absent_mods = rm - pm
absent_classes = rc - pc
print(f"{rich} - {poor}: {len(absent_funcs)} functions, modules {sorted(absent_mods)}, "
      f"{len(absent_classes)} classes")

files = sorted(Path(proj).glob("source*/*.mc")) + sorted(Path(proj).glob("runtime-lib/*.mc"))
for f in files:
    for i, line in enumerate(f.read_text().splitlines(), 1):
        code = line.split("//", 1)[0]
        hits = []
        for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", code):
            parent, name = m.groups()
            if (parent, name) in absent_funcs:
                hits.append(f"fn {parent}.{name}")
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", code):
            w = m.group(1)
            if w in absent_mods:
                hits.append(f"module {w}")
            elif w in absent_classes:
                hits.append(f"class {w}")
            elif w in absent_names and not any(w in h for h in hits):
                hits.append(f"fn? {w}")
        if hits:
            print(f"{f.relative_to(proj)}:{i}: {sorted(set(hits))}  | {line.strip()[:110]}")
