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
        onUpload=${{() => {{}}}} onStructure=${{() => {{}}}}
        onReveal=${{(line, end) => edits.push({{reveal: [line, end]}})}} />`, root);
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => root.all(pred);
      const within = (e, c) => {{ for (let p = e.parentNode; p; p = p.parentNode) if (cls(p) === c) return true; return false; }};
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
      const boxes = find((e) => e.localName === "input" && e.attributes.type === "checkbox" && within(e, "axis"));
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


def test_colours_are_made_switchable_from_the_schemes_section(summary):
    text = summary(starters.instantiate("minimal", "T"))
    printed = render(text, """
      globalThis.prompt = () => "night";
      const boxes = find((e) => e.localName === "input" && e.attributes.type === "checkbox");
      boxes[0].dispatch("change"); await settle();           // bg
      boxes[1].dispatch("change"); await settle();           // text
      await click(find((e) => e.localName === "button" && e.textContent === "Make switchable…")[0]);
      out(edits);
    """)
    assert printed[0] == [{"op": "make_switchable", "names": ["bg", "text"], "scheme": "night"}]


def test_the_schemes_table_adds_renames_and_removes(summary):
    text = summary(starters.instantiate("minimal", "T") + (
        "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n"
        "    light:\n      colors: { ink: color.bg }\n"
        "\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark }, l: { scheme: light } }\n"))
    printed = render(text, """
      const answers = ["dusk", "hot", "day", "pen"];
      globalThis.prompt = () => answers.shift();
      let asked = "";
      globalThis.confirm = (m) => { asked = m; return true; };
      const button = (label) => find((e) => e.localName === "button" && e.textContent === label)[0];
      await click(button("+ Scheme"));
      await click(button("+ Role"));
      await click(find((e) => cls(e) === "name" && e.textContent === "light")[0]);
      await click(find((e) => cls(e) === "name" && e.textContent === "ink")[0]);
      await click(button("Remove schemes…"));
      out(edits);
      out(asked);
    """)
    assert printed[0] == [
        {"op": "add_scheme", "name": "dusk"},
        {"op": "add_role", "name": "hot", "value": "#FFFFFF"},
        {"op": "rename_scheme", "name": "light", "to": "day"},
        {"op": "rename_role", "name": "ink", "to": "pen"},
        {"op": "remove_theme", "keep": "dark"},
    ]
    assert printed[1] == ("Every role becomes a palette colour with dark's value.\n"
                          "2 styles naming only a scheme will go.")


def test_a_styles_label_is_set_and_cleared(summary):
    text = summary(starters.instantiate("minimal", "T") + (
        "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n"
        "    light:\n      colors: { ink: color.bg }\n"
        "\nconfig:\n  style:\n    default: d\n"
        "    choices: { d: { scheme: dark, label: Night }, l: { scheme: light } }\n"))
    printed = render(text, """
      const inputs = find((e) => e.localName === "input" && e.attributes.placeholder === "label");
      out(inputs.map((i) => i.attributes.value));
      const type = (input, value) => { input.value = value; input.dispatch("blur", { target: input }); };
      type(inputs[1], " Day "); await settle();
      type(inputs[0], ""); await settle();
      type(inputs[1], ""); await settle();                    // no label to remove: nothing sent
      out(edits);
    """)
    assert printed[0] == ["Night", ""]
    assert printed[1] == [
        {"op": "set", "path": ["config", "style", "choices", "l", "label"], "value": "Day"},
        {"op": "remove", "path": ["config", "style", "choices", "d", "label"]},
    ]


def test_hand_sets_are_listed_added_and_shown_in_the_yaml(summary):
    text = summary(starters.instantiate("analog", "T"))
    printed = render(text, """
      globalThis.prompt = (q, d) => d;
      const thumb = find((e) => e.localName === "img" && cls(e) === "hand-thumb")[0];
      out(thumb.attributes.src.split("?")[1].split("&").slice(0, 2));
      out(root.textContent.includes("placed by"));
      await click(find((e) => e.localName === "a" && e.textContent === "Edit in YAML")[0]);
      const select = find((e) => e.localName === "select" && e.textContent.startsWith("from a preset"))[0];
      select.value = "baton"; select.dispatch("change", { target: select }); await settle();
      await click(find((e) => e.localName === "button" && e.textContent === "+ Hand set")[0]);
      await click(find((e) => e.localName === "button" && e.textContent === "Duplicate")[0]);
      out(edits);
    """)
    assert printed[0] == ["name=classic", "device=fenix8solar47mm"]
    assert printed[1] is True
    reveal, *rest = printed[2]
    assert reveal["reveal"][0] < reveal["reveal"][1]
    assert rest == [{"op": "add_hand_set", "name": "baton", "preset": "baton"},
                    {"op": "duplicate_hand_set", "name": "classic"}]


def test_a_slot_card_ticks_stars_and_opens_to_every_type(summary):
    text = summary((Path(__file__).resolve().parent.parent
                    / "examples/features/slot-gauge/face.yaml").read_text())
    printed = render(text, """
      const card = find((e) => cls(e) === "slot-card")[0];
      const row = (label) => card.all((e) => ["slot-type", "slot-type off"].includes(cls(e))
                                       && e.textContent.includes(label))[0];
      const box = (label) => row(label).all((e) => e.localName === "input")[0];
      out(["Steps", "Floors climbed", "Heart rate"].map((l) => "checked" in box(l).attributes || box(l).checked === true));
      box("Floors climbed").dispatch("change"); await settle();
      await click(row("Calories").all((e) => cls(e).startsWith("star"))[0]);
      const anyBox = card.all((e) => e.localName === "input" && e.parentNode.localName === "label")[0];
      anyBox.dispatch("change"); await settle();
      out(edits);
    """)
    assert printed[0] == [True, True, False]
    top = ["config", "slots", "top"]
    assert printed[1] == [
        {"op": "set", "path": top + ["choices"],
         "value": ["steps", "intensity_minutes", "battery", "body_battery", "stress"]},
        {"op": "set", "path": top + ["choices"],
         "value": ["steps", "floors_climbed", "intensity_minutes", "battery", "body_battery",
                   "stress", "calories"]},
        {"op": "set", "path": top + ["default"], "value": "calories"},
        {"op": "set", "path": top + ["choices"], "value": "any"},
    ]


def test_a_new_slot_asks_what_it_shows_first(summary):
    text = summary(starters.instantiate("minimal", "T"))
    printed = render(text, """
      globalThis.prompt = (q, d) => d;
      const select = find((e) => e.localName === "select" && e.textContent.startsWith("a new slot"))[0];
      select.value = "heart_rate"; select.dispatch("change"); await settle();
      await click(find((e) => e.localName === "button" && e.textContent === "+ Slot")[0]);
      out(edits);
    """)
    assert printed[0] == [{"op": "add_slot", "name": "heart", "default": "heart_rate"}]
