"""Apply scheme edits through the editor's own patch + gate and report each outcome."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from wfb import starters
from wfb.edit.spans import index_for, Refused
from wfb.edit.patch import set_value, remove, rename_reference
from wfb.edit.gate import Gate, load_text

d = Path(tempfile.mkdtemp()); p = d / "face.yaml"
text = starters.instantiate("minimal", "X"); p.write_text(text)

def step(label, make, keep=True):
    global text
    try:
        patch = make(index_for(text))
        after = Gate(p, text).check(patch)
        print(f"ACCEPT  {label}  (loads={after.face is not None}, n_errors={len(after.errors)})")
        if keep: text = patch.text
    except Refused as e:
        print(f"REFUSE  {label}: {e}")

step("add theme with scheme 'dark' {fg: #FFFFFF}", lambda i: set_value(i, ("theme",), {"schemes": {"dark": {"colors": {"fg": "#FFFFFF"}}}}))
step("element uses color.fg with no style", lambda i: set_value(i, ("elements","clock","color"), "color.fg"))
step("add scheme 'light' with only 'other' role (mismatch)", lambda i: set_value(i, ("theme","schemes","light"), {"colors": {"other": "#000000"}}), keep=False)
step("add scheme 'light' {fg: #000000}", lambda i: set_value(i, ("theme","schemes","light"), {"colors": {"fg": "#000000"}}))
step("add role 'bg2' to dark only (one scheme at a time)", lambda i: set_value(i, ("theme","schemes","dark","colors","bg2"), "#000000"), keep=False)
step("role named like a swatch ('dim')", lambda i: set_value(i, ("theme","schemes","dark","colors","dim"), "#555555"), keep=False)
step("add style choosing scheme dark", lambda i: set_value(i, ("config",), {"style": {"default": "d", "choices": {"d": {"scheme": "dark"}, "l": {"scheme": "light"}}}}))
step("remove scheme 'light' while a style names it", lambda i: remove(i, ("theme","schemes","light")), keep=False)
step("remove whole theme while color.fg used", lambda i: remove(i, ("theme",)), keep=False)
step("remove last role fg from dark", lambda i: remove(i, ("theme","schemes","dark","colors","fg")), keep=False)
step("rename scheme light->day (plain key rename)", lambda i: __import__('wfb.edit.patch',fromlist=['x']).rename_key(i, ("theme","schemes","light"), "day"), keep=False)
step("rename role fg->ink via color. prefix", lambda i: rename_reference(i, ("theme","schemes","dark","colors","fg"), "ink", "color."), keep=False)
print("---- final text tail"); print(text[text.index("theme:"):] if "theme:" in text else text[-400:])
