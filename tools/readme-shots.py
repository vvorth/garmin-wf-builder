#!/usr/bin/env python3
"""Regenerate the screenshots in docs/screenshots/ that README.md shows.

Renders examples/showcase with ``wfb preview`` for one device and crops the
per-feature details, then renders the topic examples that cover what the
showcase does not.  Run from the repo root:

    ./.venv/bin/python tools/readme-shots.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "examples/showcase/face.yaml"
OUT = ROOT / "docs/screenshots"
DEVICE = "fenix8solar47mm"
SCALE = 3  # 260 px device -> 780 px image

# name -> (style, extra preview args, crop box in device pixels or None)
SHOTS = {
    "showcase-asleep": ("analog_dark", ["--asleep"], None),
    "showcase-header": ("digital_dark", [], (40, 12, 220, 62)),
    "showcase-registers": ("digital_dark", [], (30, 64, 230, 116)),
    "showcase-clock": ("digital_dark", [], (30, 116, 230, 174)),
    "showcase-clusters": ("digital_dark", [], (40, 182, 225, 218)),
    "showcase-status": ("digital_dark", [], (60, 216, 200, 260)),
    "showcase-dial": ("analog_light", ["--time", "03:41:17"], None),
}


# Topic examples, rendered whole: name -> (example directory, extra args).
EXAMPLES = {
    "align": ("align", []),
    "patterns": ("patterns", []),
    "graph": ("graph", []),
    "shapes": ("shapes", []),
    "analog-styles": ("analog", ["--all-styles"]),
}

# On-device editor variants: each is a set of textual swaps applied to a
# throwaway copy of the design, so face.yaml itself is never touched.
VARIANTS = [
    {},
    {"default: palette.orange": "default: palette.lime_green",
     "default: palette.cyan": "default: palette.magenta",
     "default: complication.steps": "default: complication.heart_rate"},
    {"default: palette.orange": "default: palette.magenta",
     "default: palette.cyan": "default: palette.amber",
     "default: complication.body_battery": "default: complication.calories"},
]


def render(style, extra, dest, design=DESIGN):
    """Render one style into ``dest`` and return the PNG path."""
    subprocess.run(
        [sys.executable, str(ROOT / "wfb.py"), "preview", str(design),
         "-d", DEVICE, "--scale", str(SCALE), "--style", style,
         "-o", str(dest), *extra],
        check=True, capture_output=True,
    )
    return dest / f"{DEVICE}--{style}.png"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (style, extra, box) in SHOTS.items():
            image = Image.open(render(style, extra, Path(tmp) / name))
            if box:
                image = image.crop(tuple(v * SCALE for v in box))
            image.save(OUT / f"{name}.png", optimize=True)
            print(f"wrote {OUT.relative_to(ROOT)}/{name}.png")
        subprocess.run(
            [sys.executable, str(ROOT / "wfb.py"), "preview", str(DESIGN),
             "-d", DEVICE, "--all-styles", "-o", tmp],
            check=True, capture_output=True,
        )
        Image.open(Path(tmp) / f"{DEVICE}--all-styles.png").save(
            OUT / "showcase-styles.png", optimize=True)
        print(f"wrote {OUT.relative_to(ROOT)}/showcase-styles.png")
        panels = []
        for i, swaps in enumerate(VARIANTS):
            copy = Path(tmp) / f"variant{i}"
            shutil.copytree(DESIGN.parent, copy,
                            ignore=shutil.ignore_patterns("screenshots"))
            text = DESIGN.read_text()
            for old, new in swaps.items():
                assert old in text, old
                text = text.replace(old, new, 1)
            (copy / DESIGN.name).write_text(text)
            panels.append(Image.open(render(
                "digital_dark", ["--scale", "2"], copy / "out", copy / DESIGN.name)))
        strip = Image.new("RGB", (sum(p.width for p in panels), panels[0].height))
        for i, panel in enumerate(panels):
            strip.paste(panel, (i * panel.width, 0))
        strip.save(OUT / "showcase-config.png", optimize=True)
        print(f"wrote {OUT.relative_to(ROOT)}/showcase-config.png")
        for name, (example, extra) in EXAMPLES.items():
            dest = Path(tmp) / f"example-{name}"
            subprocess.run(
                [sys.executable, str(ROOT / "wfb.py"), "preview",
                 str(ROOT / "examples" / example / "face.yaml"),
                 "-d", DEVICE, "-o", str(dest), *extra],
                check=True, capture_output=True,
            )
            (rendered,) = dest.glob("*.png")
            Image.open(rendered).save(OUT / f"{name}.png", optimize=True)
            print(f"wrote {OUT.relative_to(ROOT)}/{name}.png")


if __name__ == "__main__":
    main()
