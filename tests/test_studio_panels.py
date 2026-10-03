"""The editor's panels rendered in Node with preact over a minimal DOM
(`tests/studio_dom.mjs`): each renders from a real face's summary, and its
controls send the edits the server expects. Nothing is drawn or laid out;
how the page looks is still checked by hand."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from wfb import starters
from wfb.studio.bundle import Bundle
from wfb.studio.document import Studio
from wfb.studio.inspect import vocabulary
from wfb.studio.store import Store

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "wfb/studio/static"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture
def summary(tmp_path, db):
    def make(text: str) -> dict:
        studio = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
        try:
            return studio.create(Bundle("T", text), "new").summary()
        finally:
            studio.close()
    return make


def render(summary: dict, body: str) -> list:
    """Render the Face panel over ``summary``, run ``body`` (which has
    `root`, `find`, `click`, `settle` and `edits`), and return what it
    prints, one JSON value a line."""
    script = f"""
      import {{ install }} from {json.dumps((HERE / 'studio_dom.mjs').as_uri())};
      const document = install();
      const {{ html, render }} = await import({json.dumps((STATIC / 'vendor/preact-htm.module.js').as_uri())});
      const {{ FacePanel }} = await import({json.dumps((STATIC / 'panels.js').as_uri())});
      const edits = [];
      const root = document.createElement("div");
      render(html`<${{FacePanel}} doc=${{{json.dumps(summary)}}} vocab=${{{json.dumps({**vocabulary(), "devices": []})}}}
        onEdit=${{(op) => edits.push(op)}} onSelect=${{(id) => edits.push({{select: id}})}}
        onUpload=${{() => {{}}}} onStructure=${{() => {{}}}} />`, root);
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => root.all(pred);
      const settle = () => new Promise((r) => setTimeout(r, 5));
      const click = async (e) => {{ e.click(); await settle(); }};
      const out = (v) => console.log(JSON.stringify(v));
      {body}
    """
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1500:]
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_the_colours_say_who_uses_them_and_a_pick_changes_the_swatch(summary):
    text = summary(starters.instantiate("minimal", "T"))
    printed = render(text, """
      out(root.textContent.includes("used by background"));
      const chips = find((e) => cls(e).includes("chip-button"));
      out(chips.map((c) => c.textContent));
      await click(chips[0]);                                  // bg's own picker
      const grid = find((e) => cls(e).includes("swatch") && e.parentNode && cls(e.parentNode) === "pop-grid");
      out(grid.length);
      out(find((e) => cls(e) === "pop-title").map((t) => t.textContent));
      await click(grid[1]);                                   // shalimar, #FFFFAA
      out(edits);
    """)
    assert printed[0] is True
    assert printed[1] == ["#000000", "#FFFFFF", "#AAAAAA", "+ Colour"]
    assert printed[2] == 64
    assert printed[3] == ["MIP 64", "Custom"]              # a swatch's value takes no role
    assert printed[4] == [{"op": "set_swatch", "name": "bg", "value": "#FFFFAA"}]


def test_add_a_colour_and_an_accent_setting(summary):
    text = summary(starters.instantiate("minimal", "T"))
    printed = render(text, """
      const add = find((e) => cls(e).includes("chip-button") && e.textContent === "+ Colour")[0];
      await click(add);
      const grid = find((e) => cls(e).includes("swatch") && cls(e.parentNode) === "pop-grid");
      await click(grid[15]);                                  // red
      await click(find((e) => e.localName === "button" && e.textContent === "+ Accent colour")[0]);
      out(edits);
    """)
    assert printed[0] == [
        {"op": "add_swatch", "value": "#FF0000"},
        {"op": "set", "path": ["config", "accent_color"],
         "value": {"default": "color.bg", "choices": ["color.bg"]}},
    ]


def test_an_axis_lists_the_palette_as_ticks_and_any_offers_a_list(summary):
    base = starters.instantiate("minimal", "T")
    listed = summary(base + "\nconfig:\n  accent_color:\n    default: color.text\n"
                     "    choices: [color.text, color.dim]\n")
    printed = render(listed, """
      const boxes = find((e) => e.localName === "input" && e.attributes.type === "checkbox");
      const on = (b, k) => b[k] === true || k in b.attributes;
      out(boxes.map((b) => on(b, "checked")));
      out(boxes.map((b) => on(b, "disabled")));
      boxes[0].dispatch("change"); await settle();
      out(edits);
    """)
    assert printed[0] == [False, True, True]                 # bg, text, dim
    assert printed[1] == [False, True, False]                # the default stays listed
    assert printed[2] == [{"op": "set", "path": ["config", "accent_color", "choices"],
                           "value": ["color.text", "color.dim", "color.bg"]}]
    any_ = summary(base + "\nconfig:\n  accent_color:\n    default: color.text\n    choices: any\n")
    printed = render(any_, """
      out(root.textContent.includes("every colour in the palette"));
      await click(find((e) => e.localName === "button" && e.textContent === "Make it a list")[0]);
      out(edits);
    """)
    assert printed[0] is True
    assert printed[1] == [{"op": "set", "path": ["config", "accent_color", "choices"],
                           "value": ["color.text", "color.bg", "color.dim"]}]


def test_a_scheme_cell_picks_through_use_color(summary):
    text = summary(starters.instantiate("minimal", "T") + (
        "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n"
        "\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark } }\n"))
    printed = render(text, """
      const cell = find((e) => cls(e).includes("chip-button") && e.textContent === "text")[0];
      await click(cell);
      out(find((e) => cls(e) === "pop-roles").length);        // no roles in a scheme's value
      await click(find((e) => cls(e).includes("swatch") && cls(e.parentNode) === "pop-swatches")[2]);
      out(edits);
    """)
    assert printed[0] == 0
    assert printed[1] == [{"op": "use_color", "path": ["theme", "schemes", "dark", "colors", "ink"],
                           "value": "color.dim"}]
