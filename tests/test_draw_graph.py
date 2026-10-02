"""`type: graph` as a draw program (`wfb.kinds.graph.GraphKind.lower`): the
preview's stand-in series drawn through `WfbSeries`'s own whole-pixel
arithmetic, in the `Layout` box the watch draws in."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from tests.helpers import find, resolved_example
from wfb import preview
from wfb.draw import barrel
from wfb.draw.jsonform import to_json
from wfb.kinds.graph import _synthetic_series

GRAPHS = Path("examples/features/graph/face.yaml")
DEVICE = "fenix8solar47mm"


def _json(resolved, placed) -> list[dict]:
    options = preview.PreviewOptions()
    sample = preview.sample_values(resolved, options, None)
    image = Image.new("RGB", (resolved.device.width * 2, resolved.device.height * 2))
    renderer = preview.Renderer(resolved, ImageDraw.Draw(image), image, 2, sample, options)
    ops, _ = to_json(renderer, placed)
    return ops


def _args(op) -> list[float]:
    return [float(n["value"] + n["add"]) if isinstance(n, dict) else float(n) for n in op["args"]]


def test_a_line_runs_through_whole_pixels_and_breaks_at_a_gap(db):
    """`cx = x + (i * w / (n - 1))` on two `Number`s, `cy` truncated: every
    end is a whole pixel, and the stand-in's gap leaves two segments out."""
    resolved = resolved_example(GRAPHS, db, DEVICE)
    graph = find(resolved, "hr_graph")
    n = graph.element.sample_count
    lines = [_args(op) for op in _json(resolved, graph) if op["op"] == "drawLine"]
    assert len(lines) == (n - 1) - 2  # the gap removes the segments either side of it
    assert all(v == int(v) for line in lines for v in line)
    box = graph.box
    xs = [box.x + (i * box.width) // (n - 1) for i in range(n)]
    assert {line[0] for line in lines} <= set(xs)


def test_a_graph_spans_its_layout_box(db):
    """The last sample lands on `X + WIDTH`, the box the watch is given --
    not the unrounded size, a pixel narrower here."""
    resolved = resolved_example(GRAPHS, db, DEVICE)
    graph = find(resolved, "hr_graph")
    assert graph.size[0] != graph.box.width  # the contrast this test needs
    lines = [_args(op) for op in _json(resolved, graph) if op["op"] == "drawLine"]
    assert max(line[2] for line in lines) == graph.box.x + graph.box.width


def test_bars_sit_in_whole_pixel_slots_at_least_one_pixel_tall(db):
    resolved = resolved_example(GRAPHS, db, DEVICE)
    graph = find(resolved, "steps_graph")
    bars = [_args(op) for op in _json(resolved, graph) if op["op"] == "fillRectangle"]
    box = graph.box
    n = graph.element.sample_count
    values = _synthetic_series(n)
    assert len(bars) == sum(v is not None for v in values)
    pitch = box.width // n
    lefts = [box.x + i * pitch + int((pitch - graph.bar_width) / 2)
             for i, v in enumerate(values) if v is not None]
    assert [bar[0] for bar in bars] == lefts
    assert all(bar[3] >= 1 for bar in bars)


def test_the_series_twins_truncate_toward_zero():
    """A bar narrower than its slot centres by truncation, and a negative
    remainder truncates toward zero, as Monkey C's `Number / Number` does."""
    (x, _, _, _), = barrel.series_bars(0, 0, 3, 10, 6, [1.0], 0.0, 1.0)
    assert x == int((3 - 6) / 2) == -1
