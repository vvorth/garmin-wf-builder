#!/usr/bin/env python3
"""Regenerate the screenshots in docs/screenshots/ that README.md shows.

Renders examples/showcase with ``wfb preview`` for one device and crops the
per-feature details, then renders the topic examples that cover what the
showcase does not.  Run from the repo root:

    ./.venv/bin/python tools/readme-shots.py
"""
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from ruamel.yaml import YAML

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

# On-device editor variants: each sets `config:` defaults, by key, in a
# throwaway copy of the design, so face.yaml itself is never touched.  A
# value must be one of that axis's `choices:` (or the axis `choices: any`),
# so a variant that no longer fits the design fails with the reason.
VARIANTS = [
    {},
    {"accent_color": "palette.lime_green",
     "data_color": "palette.magenta",
     "data.left_register": "complication.heart_rate"},
    {"accent_color": "palette.magenta",
     "data_color": "palette.cyan",
     "data.right_register": "complication.calories"},
]


# The README's top image: every style, with the design's own defaults unless
# set here (e.g. {"data_color": "palette.amber"} when the accent and data
# defaults coincide and would render as one colour).
STYLES_DEFAULTS = {}


def variant_copy(tmp, name, defaults):
    """A throwaway copy of the showcase with ``defaults`` applied; its path."""
    copy = Path(tmp) / name
    shutil.copytree(DESIGN.parent, copy)
    (copy / DESIGN.name).write_text(with_defaults(DESIGN.read_text(), defaults))
    return copy / DESIGN.name


def with_defaults(text, defaults):
    """``text`` (a design) with each ``config:`` axis's default replaced."""
    yaml = YAML()
    yaml.preserve_quotes = True
    doc = yaml.load(text)
    for path, value in defaults.items():
        axis = doc["config"]
        for key in path.split("."):
            axis = axis[key]
        choices = axis["choices"]
        names = [c["type"] if isinstance(c, dict) else c for c in choices]
        if choices != "any" and value not in names:
            sys.exit(f"variant: {value} is not a choice of config.{path}: {names}")
        if value == axis["default"]:
            sys.exit(f"variant: {value} is already config.{path}'s default")
        axis["default"] = value
    out = io.StringIO()
    yaml.dump(doc, out)
    return out.getvalue()


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
        styles_design = variant_copy(tmp, "styles", STYLES_DEFAULTS)
        subprocess.run(
            [sys.executable, str(ROOT / "wfb.py"), "preview", str(styles_design),
             "-d", DEVICE, "--all-styles", "-o", tmp],
            check=True, capture_output=True,
        )
        Image.open(Path(tmp) / f"{DEVICE}--all-styles.png").save(
            OUT / "showcase-styles.png", optimize=True)
        print(f"wrote {OUT.relative_to(ROOT)}/showcase-styles.png")
        panels = []
        for i, defaults in enumerate(VARIANTS):
            design = variant_copy(tmp, f"variant{i}", defaults)
            panels.append(Image.open(render(
                "digital_dark", ["--scale", "2"], design.parent / "out", design)))
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
