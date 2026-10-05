"""Compares parity.mjs's and native.py's outputs: PNG pixels, exit codes and
diagnostics, face by face.

    ./.venv/bin/python docs/research/probes/standalone-browser/compare.py \
        <native outdir> <native.jsonl> <wasm outdir> <wasm.jsonl>
"""
import json, sys
from pathlib import Path
from PIL import Image, ImageChops

nat_dir, nat_log, wasm_dir, wasm_log = sys.argv[1:5]

def rows(path):
    return {r["face"]: r for r in map(json.loads, (l for l in open(path) if l.startswith('{"face"')))}

nat, wasm = rows(nat_log), rows(wasm_log)
images = same = 0
total_n = total_w = 0
for face in sorted(nat):
    n, w = nat[face], wasm.get(face)
    if w is None:
        print(f"{face}: missing in wasm"); continue
    total_n += n["ms"]; total_w += w["ms"]
    sub = face.replace("/", "__")
    bad = []
    for png in sorted(Path(nat_dir, sub).glob("*.png")):
        other = Path(wasm_dir, sub, png.name)
        images += 1
        if not other.exists():
            bad.append(f"{png.name} missing"); continue
        a, b = Image.open(png).convert("RGBA"), Image.open(other).convert("RGBA")
        if a.size != b.size:
            bad.append(f"{png.name} size {a.size} vs {b.size}"); continue
        diff = ImageChops.difference(a, b)
        box = diff.getbbox()
        if box is None:
            same += 1
        else:
            count = sum(1 for p in diff.getdata() if p != (0, 0, 0, 0))
            bad.append(f"{png.name} {count} px differ in {box}")
    flags = []
    if n["code"] != w["code"]: flags.append(f"exit {n['code']} vs {w['code']}")
    if n["stderr"] != w["stderr"]: flags.append("stderr differs")
    status = "identical" if not bad and not flags else "; ".join(flags + bad)
    print(f"{face:40} native {n['ms']:5} ms  wasm {w['ms']:5} ms  x{w['ms']/max(n['ms'],1):.1f}  {status}")
print(f"\n{same}/{images} images pixel-identical; total native {total_n} ms, wasm {total_w} ms (x{total_w/total_n:.2f})")
