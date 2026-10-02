"""`wfb.draw.layers`, `wfb.draw.jsonform` and `wfb.draw.frames`: a frame as
layers, the JSON contract a browser canvas implements, and the one answer to
"which elements does this frame draw".

- **Stacking.**  Every example face's layers, stacked and finished, equal
  `wfb.preview.render` before the palette snap to within one level per
  channel, which only anti-aliased edges reach (research 27 §5.4).
- **The JSON contract.**  For every lowered element of every example, in the
  awake frame and, where it has one, the always-on frame: the reference
  rasteriser reading only the element's JSON paints exactly what the
  evaluator paints.
- **Frames.**  `frame_members` and `in_layout` on their own.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from tests.helpers import resolved_example
from wfb import preview
from wfb.draw.frames import frame_members, in_layout
from wfb.draw.jsonform import rasterise, to_json
from wfb.draw.layers import compose, layers
from wfb.ir.rings import ring_groups

DEVICE = "fenix8solar47mm"
FACES = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
               if "examples/dashboard/" not in f)
RAW = preview.PreviewOptions(quantise=False, mask_shape=False)


def _max_channel_difference(a: Image.Image, b: Image.Image) -> int:
    return max(high for _, high in ImageChops.difference(a, b).getextrema())


def _frames(resolved) -> list[preview.PreviewOptions]:
    """The awake frame, and the always-on one for a face that has one."""
    out = [RAW]
    if any(p.element.aod is not None for p in resolved.items):
        out.append(preview.PreviewOptions(quantise=False, mask_shape=False, aod=True,
                                          aod_mask=False))
    return out


@pytest.mark.parametrize("path", FACES)
def test_the_layers_stack_to_the_rendered_frame(db, path):
    resolved = resolved_example(Path(path), db, DEVICE)
    for options in _frames(resolved):
        stacked = compose(layers(resolved, options), resolved, options)
        assert _max_channel_difference(preview.render(resolved, options), stacked) <= 1, (
            path, options.aod)


def test_only_anti_aliased_edges_round(db):
    """The control: `analog-custom`'s anti-aliased numerals are the one place
    stacking rounds, and a face with none stacks exactly."""
    custom = resolved_example(Path("examples/analog-custom/face.yaml"), db, DEVICE)
    shapes = resolved_example(Path("examples/features/shapes/face.yaml"), db, DEVICE)
    assert _max_channel_difference(preview.render(custom, RAW),
                                   compose(layers(custom, RAW), custom, RAW)) == 1
    assert ImageChops.difference(preview.render(shapes, RAW),
                                 compose(layers(shapes, RAW), shapes, RAW)).getbbox() is None


@pytest.mark.parametrize("path", FACES)
def test_the_json_alone_paints_what_the_evaluator_paints(db, path):
    resolved = resolved_example(Path(path), db, DEVICE)
    checked = 0
    for options in _frames(resolved):
        entry = preview._resolve_style_entry(resolved.face, options.style)
        values = preview.sample_values(resolved, options, entry)
        for placed in preview.frame_items(resolved, options, entry):
            evaluated = preview.new_renderer(resolved, options, values, (0, 0, 0))
            if not evaluated.shows(placed):
                continue
            evaluated.render_element(placed)
            ops, fonts = to_json(evaluated, placed)
            read = preview.new_renderer(resolved, options, values, (0, 0, 0))
            rasterise(ops, fonts, read)
            assert ImageChops.difference(evaluated.image, read.image).getbbox() is None, (
                path, placed.id, options.aod)
            checked += 1
    assert checked, path


def test_the_json_names_the_layout_constants_an_editor_moves(db):
    """A rectangle's position and size reach the JSON as its `Layout`
    constants, with their values, and a stamp's shift as an offset on one
    -- what lets a browser redraw the layer with a dragged constant."""
    resolved = resolved_example(Path("examples/features/shapes/face.yaml"), db, DEVICE)
    rect = next(p for p in resolved.shown_items
                if p.kind == "shape" and p.element.shape == "rectangle" and p.element.filled)
    renderer = preview.new_renderer(resolved, RAW, preview.sample_values(resolved, RAW, None),
                                    (0, 0, 0))
    ops, _ = to_json(renderer, rect)
    fill = next(op for op in ops if op["op"] == "fillRectangle")
    names = [arg["const"] for arg in fill["args"]]
    prefix = rect.id.upper()
    assert names == [f"{prefix}_X", f"{prefix}_Y", f"{prefix}_WIDTH", f"{prefix}_HEIGHT"]
    assert [arg["value"] for arg in fill["args"]] == [
        rect.inner_box.x, rect.inner_box.y, rect.inner_box.width, rect.inner_box.height]

    profile = resolved_example(Path("examples/features/profile/face.yaml"), db, DEVICE)
    rule = next(p for p in profile.items if p.id == "rule_ring1")
    renderer = preview.new_renderer(profile, RAW, preview.sample_values(profile, RAW, None),
                                    (0, 0, 0))
    lines = [op for op in to_json(renderer, rule)[0] if op["op"] == "drawLine"]
    assert {line["args"][0]["add"] for line in lines} == {-1, 0, 1}


def test_a_group_ring_is_its_own_layer_just_before_its_first_member(db):
    for path, style in (("examples/features/rings/face.yaml", None),
                        ("examples/features/profile/face.yaml", "ring1")):
        resolved = resolved_example(Path(path), db, DEVICE)
        members = {f"ring:{ring.group.id}": ring.ids for ring in ring_groups(resolved.face.elements)}
        stack = layers(resolved, preview.PreviewOptions(quantise=False, mask_shape=False,
                                                        style=style))
        rings = [i for i, layer in enumerate(stack) if layer.kind == "ring"]
        assert rings, path
        for index in rings:
            ring = stack[index]
            assert ring.ops is None and ring.image.getbbox() is not None
            after = next(layer for layer in stack[index + 1:] if layer.kind != "ring")
            assert after.id in members[ring.id], (path, ring.id, after.id)
            earlier = {layer.id for layer in stack[:index]}
            assert not earlier & members[ring.id], (path, ring.id)


def test_a_layer_is_transparent_where_its_element_draws_nothing(db):
    resolved = resolved_example(Path("examples/features/shapes/face.yaml"), db, DEVICE)
    small = next(layer for layer in layers(resolved, RAW) if layer.id != "background")
    alpha = small.image.split()[3]
    assert alpha.getextrema() == (0, 255)
    assert sum(1 for v in alpha.tobytes() if v == 0) > alpha.width * alpha.height // 2


# -- frames -------------------------------------------------------------------------


def test_frame_members_reads_modes_awake_and_aod_alone_asleep(db):
    resolved = resolved_example(Path("examples/features/aod/face.yaml"), db, "fenix847mm")
    active = frame_members(resolved.items, "active")
    aod = frame_members(resolved.items, "aod")
    assert all(p.kind != "group" for p in active + aod)
    assert all("active" in p.element.modes for p in active)
    assert [p.id for p in aod] == [p.id for p in resolved.items
                                   if p.kind != "group" and p.element.aod is not None]
    assert set(p.id for p in aod) < set(p.id for p in active)


def test_in_layout_keeps_shared_content_and_one_layout(db):
    resolved = resolved_example(Path("examples/features/styles/face.yaml"), db, DEVICE)
    scoped = [p for p in resolved.items if p.element.layout is not None]
    shared = [p for p in resolved.items if p.element.layout is None]
    assert scoped and shared
    layout = scoped[0].element.layout
    assert all(in_layout(p, layout) for p in shared)
    assert all(in_layout(p, layout) == (p.element.layout == layout) for p in scoped)
    assert not any(in_layout(p, None) for p in scoped)
