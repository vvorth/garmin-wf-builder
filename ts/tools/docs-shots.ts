// Regenerates the screenshots in docs/screenshots/ that README.md and
// docs/guide/ show: examples/showcase through `wfb preview` for one device,
// cropped to its per-feature details, then the topic examples that cover
// what the showcase does not.
//
//   node ts/tools/docs-shots.ts
import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { isMap, isSeq, parseDocument } from "yaml";
import { REPO_ROOT } from "../src/devices/node.ts";
import { decodePng, encodePng, type RgbaImage } from "../src/png.ts";

const DESIGN = join(REPO_ROOT, "examples", "showcase", "face.yaml");
const OUT = join(REPO_ROOT, "docs", "screenshots");
const DEVICE = "fenix8solar47mm";
const SCALE = 3; // 260 px device -> 780 px image
type Box = [number, number, number, number];

/** name -> [style, extra preview args, crop box in device pixels or null]. */
const SHOTS: Record<string, [string, string[], Box | null]> = {
  "showcase-asleep": ["analog_dark", ["--asleep"], null],
  "showcase-header": ["digital_dark", [], [40, 12, 220, 62]],
  "showcase-registers": ["digital_dark", [], [30, 64, 230, 116]],
  "showcase-clock": ["digital_dark", [], [30, 116, 230, 174]],
  "showcase-clusters": ["digital_dark", [], [40, 182, 225, 218]],
  "showcase-status": ["digital_dark", [], [60, 216, 200, 260]],
  "showcase-dial": ["analog_light", ["--time", "03:41:17"], null],
};

/** Topic examples, whole: name -> [example directory, extra args, optional [crop box, scale]]. */
const EXAMPLES: Record<string, [string, string[], [Box, number] | null]> = {
  align: ["features/align", [], null],
  // The same design on a 320x360 rectangle, beside the round shot in docs/guide/placement.md.
  "align-venusq2": ["features/align", [], null],
  instinct: ["features/instinct", [], null],
  patterns: ["features/patterns", [], null],
  graph: ["features/graph", [], null],
  shapes: ["features/shapes", [], null],
  "analog-styles": ["features/analog", ["--all-styles"], null],
  "vector-text": ["features/vector-text", [], null],
  outline: ["features/outline", [], null],
  outlines: ["features/rings", ["--time", "10:08:37"], null],
  styles: ["features/styles", ["--all-styles"], null],
  slots: ["features/slots", [], null],
  "slot-gauge": ["features/slot-gauge", [], null],
  // Cropped to the five system-font-size rows; the vertical_align rows below are calibration detail.
  "system-fonts": ["system-fonts/text", [], [[0, 0, 260, 195], SCALE]],
  // The AMOLED sleep frame, not the awake design.
  aod: ["features/aod", ["--aod"], null],
};

/** The topic examples not drawn on DEVICE: the AMOLED one, align on a rectangle, and the semi-octagon. */
const EXAMPLE_DEVICE: Record<string, string> = { aod: "fenix847mm", "align-venusq2": "venusq2", instinct: "instinct2" };

/** `wfb new` starters: name -> [-t value or null for the default, face name]. */
const NEW_TEMPLATES: Record<string, [string | null, string]> = {
  "new-template": [null, "My Face"],
  "new-minimal": ["minimal", "My Face"],
};

/**
 * On-device editor variants: each sets `config:` defaults, by key, in a
 * throwaway copy of the design. A value must be one of that axis's
 * `choices:` (or the axis's `choices: any`), so a variant that no longer
 * fits the design fails with the reason.
 */
const VARIANTS: Record<string, string>[] = [
  {},
  { accent_color: "color.lime_green", data_color: "color.magenta", "slots.left_register": "heart_rate" },
  { accent_color: "color.magenta", data_color: "color.cyan", "slots.right_register": "calories" },
];

/** The README's top image: every style, with the design's own defaults unless set here. */
const STYLES_DEFAULTS: Record<string, string> = {};

const wfb = (...args: string[]): void => {
  execFileSync(process.execPath, [join(REPO_ROOT, "ts", "src", "cli.ts"), ...args], { cwd: REPO_ROOT, stdio: "pipe" });
};
const load = (path: string): RgbaImage => decodePng(new Uint8Array(readFileSync(path)))!;

function crop(image: RgbaImage, [l, t, r, b]: Box): RgbaImage {
  const width = r - l, height = b - t, pixels = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) pixels.set(image.pixels.subarray(((t + y) * image.width + l) * 4, ((t + y) * image.width + r) * 4), y * width * 4);
  return { width, height, pixels };
}

function save(image: RgbaImage, name: string): void {
  const rgb = new Uint8Array(image.width * image.height * 3);
  for (let i = 0; i < image.width * image.height; i++) rgb.set(image.pixels.subarray(i * 4, i * 4 + 3), i * 3);
  writeFileSync(join(OUT, `${name}.png`), encodePng(image.width, image.height, rgb, 3));
  console.log(`wrote ${relative(REPO_ROOT, OUT)}/${name}.png`);
}

/** `text` (a design) with each `config:` axis's default replaced. */
function withDefaults(text: string, defaults: Record<string, string>): string {
  const doc = parseDocument(text);
  for (const [path, value] of Object.entries(defaults)) {
    const keys = ["config", ...path.split(".")];
    const axis = doc.getIn(keys, true);
    if (!isMap(axis)) throw new Error(`variant: config.${path} is not an axis`);
    const choices = axis.get("choices", true);
    const names = isSeq(choices) ? choices.toJSON().map((c: unknown) => (typeof c === "object" && c !== null ? (c as { type: string }).type : c)) : choices;
    if (axis.get("choices") !== "any" && !(Array.isArray(names) && names.includes(value))) throw new Error(`variant: ${value} is not a choice of config.${path}: ${JSON.stringify(names)}`);
    if (axis.get("default") === value) throw new Error(`variant: ${value} is already config.${path}'s default`);
    doc.setIn([...keys, "default"], value);
  }
  return doc.toString();
}

/** A throwaway copy of the showcase with `defaults` applied; its design's path. */
function variantCopy(tmp: string, name: string, defaults: Record<string, string>): string {
  const copy = join(tmp, name);
  cpSync(dirname(DESIGN), copy, { recursive: true });
  writeFileSync(join(copy, "face.yaml"), withDefaults(readFileSync(DESIGN, "utf8"), defaults));
  return join(copy, "face.yaml");
}

/** One style rendered into `dest`: its PNG. */
function render(style: string, extra: string[], dest: string, design = DESIGN): RgbaImage {
  wfb("preview", design, "-d", DEVICE, "--scale", String(SCALE), "--style", style, "-o", dest, ...extra);
  return load(join(dest, `${DEVICE}--${style}.png`));
}

mkdirSync(OUT, { recursive: true });
const tmp = mkdtempSync(join(tmpdir(), "wfb-shots-"));
try {
  for (const [name, [style, extra, box]] of Object.entries(SHOTS)) {
    const image = render(style, extra, join(tmp, name));
    save(box ? crop(image, box.map((v) => v * SCALE) as Box) : image, name);
  }
  wfb("preview", variantCopy(tmp, "styles", STYLES_DEFAULTS), "-d", DEVICE, "--all-styles", "-o", tmp);
  save(load(join(tmp, `${DEVICE}--all-styles.png`)), "showcase-styles");

  const panels = VARIANTS.map((defaults, i) => {
    const design = variantCopy(tmp, `variant${i}`, defaults);
    return render("digital_dark", ["--scale", "2"], join(dirname(design), "out"), design);
  });
  const width = panels.reduce((n, p) => n + p.width, 0), height = panels[0]!.height;
  const strip = new Uint8Array(width * height * 4);
  let x = 0;
  for (const panel of panels) {
    for (let y = 0; y < height; y++) strip.set(panel.pixels.subarray(y * panel.width * 4, (y + 1) * panel.width * 4), (y * width + x) * 4);
    x += panel.width;
  }
  save({ width, height, pixels: strip }, "showcase-config");

  for (const [name, [example, extra, cropped]] of Object.entries(EXAMPLES)) {
    const dest = join(tmp, `example-${name}`);
    wfb("preview", join(REPO_ROOT, "examples", example, "face.yaml"), "-d", EXAMPLE_DEVICE[name] ?? DEVICE, "-o", dest,
      ...extra, ...(cropped ? ["--scale", String(cropped[1])] : []));
    const image = load(join(dest, readdirSync(dest).find((n) => n.endsWith(".png"))!));
    save(cropped ? crop(image, cropped[0].map((v) => v * cropped[1]) as Box) : image, name);
  }

  // A polished single-style analog hero, for the README gallery and the analog-hands chapter.
  save(render("classic_dark", ["--time", "10:09:42"], join(tmp, "analog-custom"), join(REPO_ROOT, "examples", "analog-custom", "face.yaml")), "analog-custom");

  // `wfb new` starters, previewed exactly as a first-time author would see them.
  for (const [name, [template, faceName]] of Object.entries(NEW_TEMPLATES)) {
    const work = join(tmp, name), design = join(work, "face.yaml");
    mkdirSync(work);
    wfb("new", faceName, "-o", design, ...(template ? ["-t", template] : []));
    wfb("preview", design, "-d", DEVICE, "--scale", String(SCALE), "-o", join(work, "out"));
    save(load(join(work, "out", `${DEVICE}.png`)), name);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
