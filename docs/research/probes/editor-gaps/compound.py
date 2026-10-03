"""Compound scheme operations, composed with `chain`, through the real gate."""
import sys, tempfile, shutil, time
from pathlib import Path
sys.path.insert(0, ".")
from wfb import starters
from wfb.edit.spans import index_for, Refused
from wfb.edit.patch import set_value, remove, rename_key, chain, Patch, _repoint, _ended_patch
from wfb.edit.gate import Gate

def run(label, path, text, make):
    t0 = time.perf_counter()
    try:
        patch = make(index_for(text))
        after = Gate(path, text).check(patch)
        print(f"ACCEPT  {label}  ({(time.perf_counter()-t0)*1000:.0f} ms, loads={after.face is not None})")
        return patch.text
    except Refused as e:
        print(f"REFUSE  {label}: {e}")
        return None

def seq(index, steps):
    """Apply each (fn, args) in order as one chained patch."""
    fn, *args = steps[0]
    patch = fn(index, *args)
    for fn, *args in steps[1:]:
        patch = chain(patch, lambda i, fn=fn, args=args: fn(i, *args))
    return patch

# --- A. promote palette swatches to roles of a new scheme (minimal starter)
d = Path(tempfile.mkdtemp()); p = d / "face.yaml"
text = starters.instantiate("minimal", "X"); p.write_text(text)
promoted = run("A1 promote bg,text,dim -> scheme 'dark' + style", p, text, lambda i: seq(i, [
    (remove, ("resources",)),
    (set_value, ("theme",), {"schemes": {"dark": {"colors": {"bg": "#000000", "text": "#FFFFFF", "dim": "#AAAAAA"}}}}),
    (set_value, ("config",), {"style": {"default": "dark", "choices": {"dark": {"scheme": "dark"}}}}),
]))
print(promoted[promoted.index("theme"):] if promoted else "")
# A2: add a second scheme copied from the first
if promoted:
    two = run("A2 duplicate scheme dark -> light, + style entry", p, promoted, lambda i: seq(i, [
        (set_value, ("theme","schemes","light"), {"colors": {"bg": "#FFFFFF", "text": "#000000", "dim": "#555555"}}),
        (set_value, ("config","style","choices","light"), {"scheme": "light"}),
    ]))
    run("A3 add a role to every scheme at once", p, two, lambda i: seq(i, [
        (set_value, ("theme","schemes","dark","colors","accent2"), "#FF5500"),
        (set_value, ("theme","schemes","light","colors","accent2"), "#FF5500"),
    ]))
    run("A4 remove a scheme and the style entries naming it", p, two, lambda i: seq(i, [
        (remove, ("config","style","choices","light")),
        (remove, ("theme","schemes","light")),
    ]))
    run("A5 a theme whose style is deleted (roles orphaned)", p, two, lambda i: remove(i, ("config",)))

# --- B. flatten the showcase's theme into the palette (keep 'dark')
src = Path("examples/showcase"); d2 = Path(tempfile.mkdtemp()) / "showcase"; shutil.copytree(src, d2)
p2 = d2 / "face.yaml"; text2 = p2.read_text()
idx = index_for(text2)
keep = idx.data["theme"]["schemes"]["dark"]["colors"]
choices = idx.data["config"]["style"]["choices"]
steps = [(remove, ("theme",))]
pal = idx.data["resources"]["palette"]
def hexof(v):
    while isinstance(v, str) and v.startswith("color."):
        e = pal[v[6:]]; v = e["value"] if isinstance(e, dict) else e
    return v
for role, value in keep.items():
    steps.append((set_value, ("resources","palette",role), hexof(value)))
by_layout = {}
for name, e in choices.items():
    if "layout" in e and e["layout"] not in by_layout:
        by_layout[e["layout"]] = name
for name, e in choices.items():
    if by_layout.get(e.get("layout")) == name:
        steps.append((remove, ("config","style","choices",name,"scheme")))
    else:
        steps.append((remove, ("config","style","choices",name)))
default = idx.data["config"]["style"]["default"]
if by_layout and default not in by_layout.values():
    steps.append((set_value, ("config","style","default"), next(iter(by_layout.values()))))
print(f"B: {len(keep)} roles -> swatches; {len(choices)} style entries -> {len(by_layout)} (one per layout)")
flat = run("B1 flatten showcase theme, keeping 'dark'", p2, text2, lambda i: seq(i, steps))
if flat:
    i=flat.index("\n  style:"); print(flat[i:i+400]); print([l for l in flat.splitlines() if l.strip().startswith(("bg:","fg:","notify:"))])

# --- C. C2's other option: remove the theme but keep every style entry
steps_all = [s for s in steps if s[0] is not remove or s[1][:3] != ("config", "style", "choices")
             or len(s[1]) == 5]
steps_all += [(remove, ("config","style","choices",n,"scheme")) for n in choices
              if (remove, ("config","style","choices",n,"scheme")) not in steps]
kept = run("C1 flatten showcase theme, keeping all 7 style entries", p2, text2, lambda i: seq(i, steps_all))
if kept:
    from wfb.edit.gate import load_text
    loaded = load_text(p2, kept)
    from wfb.diagnostics import Bag
    from wfb.lint import run_design
    lints = Bag(); run_design(loaded.face, lints)
    dup = [d for d in lints.items if d.code == "duplicate-style"]
    print(f"   design lints: {len(dup)} duplicate-style warnings (the gate does not run lints)",
          *(f"{d.message}" for d in dup), sep="\n   ")
