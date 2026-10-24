"""Write face.yaml: the 64 as an 8x8 grid of swatches, to judge on a real MIP watch.

The grid is MIP64_NAMED's order (white top left, black bottom right), the
order of appearance.png. A swatch `choose.py` drops carries a black dot in
its middle, so the photo of the watch shows both the colour and the verdict.
"""
from model import NAMED
from choose import select

CELL, GAP = 19, 3
kept, _ = select()
lines = [
    "# The 64 MIP colours on a watch: research 37's probe face (gen-face.py writes it).",
    "# A black dot marks a colour the recommended set leaves out.",
    "format: 2",
    "face:",
    "  id: 7d3e9a41-2b6c-4f80-9e15-c4a2d8b06f37",
    "  name: MIP 64",
    "  version: 1.0.0",
    "build:",
    "  targets: [fenix8solar47mm, fenix8solar51mm, fr955]",
    "resources:",
    "  palette:",
]
lines += [f'    {name}: "#{h}"' for name, h in NAMED]
lines += [
    "elements:",
    "  background:",
    "    type: rectangle",
    "    at: { anchor: center }",
    "    size: { width: 100%, height: 100% }",
    "    color: color.black",
    "  grid:",
    "    type: group",
    "    lint: { allow: [contrast], reason: \"every colour is shown on black on purpose, the dark ones too\" }",
    "    children:",
]
step = CELL + GAP
for i, (name, h) in enumerate(NAMED):
    dx = (i % 8 - 3.5) * step
    dy = (i // 8 - 3.5) * step
    lines += [
        f"      s_{name}:",
        "        type: rectangle",
        f"        at: {{ anchor: center, dx: {dx:g}px, dy: {dy:g}px }}",
        f"        size: {{ width: {CELL}px, height: {CELL}px }}",
        f"        color: color.{name}",
    ]
    if h not in kept:
        lines += [
            f"      x_{name}:",
            "        type: rectangle",
            f"        at: {{ anchor: center, dx: {dx:g}px, dy: {dy:g}px }}",
            "        size: { width: 6px, height: 6px }",
            "        color: color.black",
        ]
open("face.yaml", "w").write("\n".join(lines) + "\n")
