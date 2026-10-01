"""Do separately rendered transparent layers, stacked in draw order,
reproduce the single-frame preview?

Backs docs/research/27-draw-program.md §5.4. Each element is rendered alone
through today's `Renderer.render_element` onto a black and onto a white
ground; the pair gives its colour and coverage per pixel (difference
matting: alpha = 1 - (white - black) / 255, exact for any linear blend).
The layers are then composited over black in draw order and compared with
`preview.render` of the whole face, unquantised and unmasked; and again
with quantise and the bezel mask applied to the composite.

An outlined group's ring is its own layer, drawn as `render_sequence` does:
the stamp of every member, just before the first member.

    ./.venv/bin/python docs/research/probes/draw-program/layers.py
"""

from __future__ import annotations

import glob
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from probe import renderer_for, resolve  # noqa: E402
from wfb import preview  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.ir.rings import ring_groups  # noqa: E402

OUT: list[str] = []
SCALE = 2


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def on_ground(renderer, size, ground, paint) -> Image.Image:
    image = Image.new("RGB", size, ground)
    renderer.image, renderer.draw = image, ImageDraw.Draw(image)
    paint()
    return renderer.image


def layer(renderer, size, paint) -> Image.Image:
    """One RGBA layer from a black and a white render."""
    black = on_ground(renderer, size, (0, 0, 0), paint)
    white = on_ground(renderer, size, (255, 255, 255), paint)
    # alpha = 255 - (white - black), per channel; take the max coverage
    inv = ImageChops.subtract(white, black).convert("L")       # 255 * (1 - alpha)
    alpha = inv.point(lambda v: 255 - v)
    # colour premultiplied = black; un-premultiply where alpha > 0
    a = alpha.tobytes()
    b = black.tobytes()
    rgba = bytearray(len(a) * 4)
    for i, av in enumerate(a):
        if av:
            r, g, bb = b[3 * i], b[3 * i + 1], b[3 * i + 2]
            rgba[4 * i:4 * i + 4] = bytes((min(255, round(r * 255 / av)),
                                           min(255, round(g * 255 / av)),
                                           min(255, round(bb * 255 / av)), av))
    return Image.frombytes("RGBA", black.size, bytes(rgba))


def drawn_items(resolved, active):
    out = []
    for placed in resolved.shown_items:
        if placed.kind == "group" or "active" not in placed.element.modes:
            continue
        if placed.element.layout is not None and placed.element.layout != active:
            continue
        out.append(placed)
    return out


def layers_for(resolved):
    renderer, entry = renderer_for(resolved)
    renderer.scale = SCALE
    renderer.options = replace(renderer.options, scale=SCALE)
    size = (resolved.device.width * SCALE, resolved.device.height * SCALE)
    items = drawn_items(resolved, entry.layout if entry is not None else None)
    rings = ring_groups(resolved.face.elements)
    out: list[tuple[str, Image.Image]] = []
    for placed in items:
        for ring in rings:
            members = [p for p in items if p.id in ring.ids]
            if members and members[0] is placed:
                outline = ring.group.outline

                def paint_ring(members=members, ring=ring, outline=outline):
                    renderer.stamp_ring(
                        renderer.silhouette(lambda: renderer.render_sequence(members, rings, ring)),
                        renderer.aod_dimmed(ring.group, outline.color), outline.width)
                out.append((f"ring:{ring.group.id}", layer(renderer, size, paint_ring)))
        out.append((placed.id, layer(renderer, size, lambda p=placed: renderer.render_element(p))))
    return out, size


def differing(a: Image.Image, b: Image.Image) -> int:
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    return sum(1 for v in d.tobytes() if v)


def main() -> None:
    db = DeviceDatabase.discover()
    faces = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
                   if "examples/dashboard/" not in f)
    say(f"## stacked transparent layers vs preview.render, fenix8solar47mm, {SCALE}x")
    say(f"{'face':<52} {'layers':>6} {'raw diff px':>11} {'final diff px':>13}")
    same_raw = same_final = n = 0
    for path in faces:
        resolved = resolve(db, path)
        if resolved is None:
            continue
        layers, size = layers_for(resolved)
        stacked = Image.new("RGBA", size, (0, 0, 0, 255))
        for _, img in layers:
            stacked = Image.alpha_composite(stacked, img)
        stacked = stacked.convert("RGB")
        raw = preview.render(resolved, preview.PreviewOptions(scale=SCALE, quantise=False,
                                                              mask_shape=False))
        final = preview.render(resolved, preview.PreviewOptions(scale=SCALE))
        composed = preview._mask_shape(preview._quantise(stacked, resolved.device.display_colors),
                                       resolved.device, SCALE)
        d_raw, d_final = differing(raw, stacked), differing(final, composed)
        n += 1
        same_raw += d_raw == 0
        same_final += d_final == 0
        say(f"{path:<52} {len(layers):>6} {d_raw:>11} {d_final:>13}")
    say(f"identical: {same_raw}/{n} unquantised, {same_final}/{n} after quantise + bezel mask")
    Path(__file__).with_name("layers_results.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
