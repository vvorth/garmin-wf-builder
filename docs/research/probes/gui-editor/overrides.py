"""A drag on a device with an `overrides:` entry: which key must the editor
patch, and does patching it move only that device?

Backs docs/research/28-editor-open-questions.md §4. Host-side only.

    ./.venv/bin/python docs/research/probes/gui-editor/overrides.py

On `examples/features/shapes/face.yaml` (targets fenix8solar47mm,
fenix8solar51mm, fr955), for every element with a cartesian `at:` that has
a `dy:`:

1. insert `overrides: { fr955: { at: { dy: <own dy + 5> } } }` as a text
   patch (a new block key after the element's last key);
2. **patch target rule**: for each device, the most specific source of
   `at.dy` -- the device-id override, else a `shape:` override, else the
   element's own key;
3. "drag" each device's view: +10 on the targeted scalar, in its own unit;
4. check that the element moved down on the dragged device and stayed put
   on every other device.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.nodes import MappingNode, ScalarNode  # noqa: E402

from structural import entries, line_end  # noqa: E402
from wfb.build import load, resolve_all, select_devices  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402
from wfb.units import Length  # noqa: E402

FACE = Path("examples/features/shapes/face.yaml")
DEVICES = ["fenix8solar47mm", "fenix8solar51mm", "fr955"]
OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def centres(db: DeviceDatabase, text: str) -> dict[str, dict[str, tuple[int, int]]]:
    probe = FACE.with_name(".gui-probe.yaml")
    probe.write_text(text, encoding="utf-8")
    try:
        bag = Bag()
        face = load(probe, bag)
        assert face is not None, [d.message for d in bag.errors]
        resolved, _ = resolve_all(face, select_devices(face, db, bag, DEVICES), bag)
        assert not bag.errors, [d.message for d in bag.errors]
    finally:
        probe.unlink()
    return {d: {p.id: p.center for p in r.items} for d, r in resolved.items()}


def find(root, path: tuple) -> ScalarNode | MappingNode | None:
    for e in entries(root):
        if e.path == path:
            return e.value
    return None


def bump(text: str, scalar: ScalarNode, by: float) -> str:
    raw = text[scalar.start_mark.index:scalar.end_mark.index]
    length = Length.parse(scalar.value)
    unit = "" if length.unit == "px" and "px" not in raw else length.unit
    new = f"{length.value + by:g}{unit}"
    return text[:scalar.start_mark.index] + new + text[scalar.end_mark.index:]


def target(root, element: str, device: str, shape: str) -> tuple:
    """The most specific author path that sets `at.dy` on ``device``."""
    for selector in (device, f"shape:{shape}"):
        path = ("elements", element, "overrides", selector, "at", "dy")
        if find(root, path) is not None:
            return path
    return ("elements", element, "at", "dy")


def main() -> None:
    db = DeviceDatabase.discover()
    shapes = {d: db.get(d).shape for d in DEVICES}
    text0 = FACE.read_text(encoding="utf-8")
    root0 = YAML().compose(io.StringIO(text0))
    candidates = []
    for e in entries(root0):
        if len(e.path) == 2 and e.path[0] == "elements" and isinstance(e.value, MappingNode):
            at = find(root0, e.path + ("at",))
            if isinstance(at, MappingNode) and any(k.value == "dy" for k, _ in at.value):
                candidates.append(e)
    say("## a drag under `overrides:`: patch the most specific source of the key")
    ok = tried = 0
    for e in candidates:
        element = e.path[1]
        own = find(root0, e.path + ("at", "dy"))
        dy = Length.parse(own.value)
        unit = "" if dy.unit == "px" else dy.unit
        indent = e.value.value[0][0].start_mark.column
        end = line_end(text0, e.value.value[-1][1].end_mark.index - 1)
        text = (text0[:end] + " " * indent
                + f"overrides: {{ fr955: {{ at: {{ dy: {dy.value + 5:g}{unit} }} }} }}\n"
                + text0[end:])
        root = YAML().compose(io.StringIO(text))
        base = centres(db, text)
        for device in DEVICES:
            tried += 1
            path = target(root, element, device, shapes[device])
            moved = centres(db, bump(text, find(root, path), 10))
            here = moved[device][element][1] > base[device][element][1]
            # the element's own key is shared: every device without an
            # override moves with it, and that is correct
            shared = [d for d in DEVICES if target(root, element, d, shapes[d]) == path]
            others = all((moved[d][element] == base[d][element]) != (d in shared)
                         for d in DEVICES if d != device)
            good = here and others
            ok += good
            say(f"  {element:<16} drag on {device:<16} patches {'.'.join(map(str, path[2:]))}: "
                f"moved here {here}, other devices as expected {others}")
    say(f"{ok}/{tried} drags moved exactly the devices that read the patched key")
    Path(__file__).with_name("overrides_results.txt").write_text("\n".join(OUT) + "\n",
                                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
