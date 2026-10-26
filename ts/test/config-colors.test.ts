// A `config:` colour setting: what the wearer is offered, and by what name,
// on the native editor's resource and in the generated settings menu.
import assert from "node:assert/strict";
import { test } from "node:test";
import { menuAxes } from "../src/emit/monkeyc/config_menu.ts";
import { configLabelStrings, configResource } from "../src/emit/resources.ts";
import { MIP64_NAMED, MIP_RECOMMENDED } from "../src/palette.ts";
import { face, MINIMAL } from "./designs.ts";

const design = (config: string, palette = ""): string =>
  MINIMAL.replace('    fg: "#FFFFFF"\n', `    fg: "#FFFFFF"\n${palette}`) + `config:\n${config}`;

const LABEL = new Map(MIP64_NAMED.map(([name, , label]) => [name, label]));
const HEX = new Map(MIP64_NAMED.map(([name, hex]) => [name, hex]));

/** The accent setting's offer as the menu lists it: `label hex` each. */
const offered = (text: string): string[] => {
  const axis = menuAxes(face(text)).find((a) => a.name === "accent_color")!;
  return axis.labels!.map((label, i) => `${label} ${axis.colors[i]}`);
};

test("choices: any offers the recommended 37 by name, in order, and no allowAny", () => {
  const text = design("  accent_color: { default: color.fg, choices: any }\n");
  const want = MIP_RECOMMENDED.map((name) => `${LABEL.get(name)} ${HEX.get(name)}`);
  assert.equal(want.length, 37);
  assert.deepEqual(offered(text), want);
  const xml = configResource(face(text));
  assert.doesNotMatch(xml, /allowAny/);
  // the default (white) is marked once, where the list has it
  assert.equal(xml.match(/default="true"/g)?.length, 1);
  assert.match(xml, /<color default="true" label="@Strings\.ConfigAccentColor33">0xFFFFFF<\/color>/);
  assert.deepEqual(configLabelStrings(face(text)).map(([, label]) => label), MIP_RECOMMENDED.map((n) => LABEL.get(n)));
});

test("choices: any puts a default it does not offer first, by its swatch's name", () => {
  // #FF8000 is not one of the 64; #5555AA is, but not one of the 37
  const first = `${LABEL.get(MIP_RECOMMENDED[0]!)} ${HEX.get(MIP_RECOMMENDED[0]!)}`;
  const amber = offered(design("  accent_color: { default: color.amber, choices: any }\n", '    amber: "#FF8000"\n'));
  assert.deepEqual([amber.length, ...amber.slice(0, 2)], [38, "Amber #FF8000", first]);
  assert.deepEqual(offered(design('  accent_color: { default: "#5555AA", choices: any }\n')).slice(0, 2), ["Rich Blue #5555AA", first]);
  assert.equal(offered(design('  accent_color: { default: "#FF8000", choices: any }\n'))[0], "#FF8000 #FF8000");
});

test("a listed colour is named: its label, its swatch's name, else its MIP name; never its hex when it is one of the 64", () => {
  const palette = '    deep_orange: "#FF5500"\n    sea: { value: "#00AAFF", label: "Sea" }\n    azure_radiance: "#00AAFF"\n    cFF8000: "#FF8000"\n    navy_blue_2: "#0055FF"\n';
  const text = design([
    "  accent_color:",
    "    default: color.deep_orange",
    "    choices:",
    "      - color.deep_orange",            // the author's own name
    "      - color.sea",                    // a label wins
    "      - color.azure_radiance",         // named after its colour: the MIP name
    "      - color.navy_blue_2",            // the same, with the editor's suffix
    "      - color.cFF8000",                // named after a colour not among the 64: nothing to say but its hex
    '      - { color: "#FFFF00" }',         // inline, one of the 64
    '      - { color: "#FFFF00", label: "Lemon" }',
    "",
  ].join("\n"), palette);
  assert.deepEqual(offered(text), ["Deep orange #FF5500", "Sea #00AAFF", "Azure Radiance #00AAFF", "Navy Blue #0055FF",
    "#FF8000 #FF8000", "Yellow #FFFF00", "Lemon #FFFF00"]);
  // the native editor gets the same names as strings; the colour with none has no label
  const xml = configResource(face(text));
  assert.equal(xml.match(/label=/g)?.length, 6);
  assert.match(xml, /<color>0xFF8000<\/color>/);
});
