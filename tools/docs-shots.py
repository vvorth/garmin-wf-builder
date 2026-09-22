#!/usr/bin/env python3
"""Regenerate the screenshots in docs/screenshots/ that README.md and
docs/guide/ show.

Renders examples/showcase with ``wfb preview`` for one device and crops the
per-feature details, then renders the topic examples that cover what the
showcase does not.  Run from the repo root:

    ./.venv/bin/python tools/docs-shots.py
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


# Topic examples, rendered whole: name -> (example directory, extra args,
# an optional (crop box in device pixels, scale) -- the render then adds
# ``--scale`` itself, so it need not be repeated in extra args).
EXAMPLES = {
    "align": ("features/align", [], None),
    "patterns": ("features/patterns", [], None),
    "graph": ("features/graph", [], None),
    "shapes": ("features/shapes", [], None),
    "analog-styles": ("features/analog", ["--all-styles"], None),
    "vector-text": ("features/vector-text", [], None),
    "outline": ("features/outline", [], None),
    "styles": ("features/styles", ["--all-styles"], None),
    "slots": ("features/slots", [], None),
    # Cropped to the five system-font-size rows; the two extra vertical_align
    # demo rows below them are calibration detail, not gallery material.
    "system-fonts": ("system-fonts/text", [], ((0, 0, 260, 195), SCALE)),
}

# `wfb new` templates: name -> (-t value or None for the default, face name).
NEW_TEMPLATES = {
    "new-template": (None, "My Face"),
    "new-minimal": ("minimal", "My Face"),
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
        for name, (example, extra, crop) in EXAMPLES.items():
            dest = Path(tmp) / f"example-{name}"
            args = list(extra)
            if crop:
                _, crop_scale = crop
                args = args + ["--scale", str(crop_scale)]
            subprocess.run(
                [sys.executable, str(ROOT / "wfb.py"), "preview",
                 str(ROOT / "examples" / example / "face.yaml"),
                 "-d", DEVICE, "-o", str(dest), *args],
                check=True, capture_output=True,
            )
            (rendered,) = dest.glob("*.png")
            image = Image.open(rendered)
            if crop:
                box, crop_scale = crop
                image = image.crop(tuple(v * crop_scale for v in box))
            image.save(OUT / f"{name}.png", optimize=True)
            print(f"wrote {OUT.relative_to(ROOT)}/{name}.png")

        # A polished single-style analog hero, for the README gallery and
        # the analog-hands chapter.
        analog_custom = ROOT / "examples/analog-custom/face.yaml"
        image = Image.open(render(
            "classic_dark", ["--time", "10:09:42"], Path(tmp) / "analog-custom",
            design=analog_custom))
        image.save(OUT / "analog-custom.png", optimize=True)
        print(f"wrote {OUT.relative_to(ROOT)}/analog-custom.png")

        # `wfb new` templates, for getting-started: generate into a throwaway
        # directory (face.yaml itself is never written into the repo) and
        # preview the result exactly as a first-time author would see it.
        for name, (template, face_name) in NEW_TEMPLATES.items():
            work = Path(tmp) / name
            work.mkdir()
            design = work / "face.yaml"
            new_args = [sys.executable, str(ROOT / "wfb.py"), "new", face_name,
                        "-o", str(design)]
            if template:
                new_args += ["-t", template]
            subprocess.run(new_args, check=True, capture_output=True)
            dest = work / "out"
            subprocess.run(
                [sys.executable, str(ROOT / "wfb.py"), "preview", str(design),
                 "-d", DEVICE, "--scale", str(SCALE), "-o", str(dest)],
                check=True, capture_output=True,
            )
            Image.open(dest / f"{DEVICE}.png").save(OUT / f"{name}.png", optimize=True)
            print(f"wrote {OUT.relative_to(ROOT)}/{name}.png")


if __name__ == "__main__":
    main()
