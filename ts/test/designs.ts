// A design written inline in a test: loaded, resolved and generated in
// memory, as the Python suite's `write_design` helpers did on disk.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { load as loadDesign } from "../src/build.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag, type Diagnostic } from "../src/diagnostics.ts";
import { drawnText } from "../src/draw/index.ts";
import { generate } from "../src/emit/project.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import type { Face } from "../src/ir/model.ts";
import { resolve, type ResolvedFace } from "../src/layout.ts";
import { readFontFile } from "../src/node.ts";
import { db } from "../tools/goldens.ts";

export { db };

/** Where an inline design is said to be: font sources resolve against the repository's root. */
export const PATH = "face.yaml";

const exists = (p: string): boolean => existsSync(join(REPO_ROOT, p));
const read = (p: string) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p));

/** `text` loaded: the face (or null) and its diagnostics. */
export function load(text: string): [Face | null, Bag] {
  const bag = new Bag();
  bag.registerSource(PATH, text);
  return [loadDesign(PATH, bag, text, exists), bag];
}

/** `text` loaded, asserted to load. */
export function face(text: string): Face {
  const [f, bag] = load(text);
  assert.ok(f !== null, bag.render());
  return f;
}

export function errors(text: string): Diagnostic[] {
  return load(text)[1].errors;
}

export function resolved(text: string, deviceId = "fenix8solar47mm"): ResolvedFace {
  const f = face(text);
  const device = db.get(deviceId);
  return resolve(f, device, bakeFonts(f, device, read));
}

/** The generated project's files for `deviceIds` (the design's targets when null). */
export function generated(text: string, deviceIds: string[] | null = null): Map<string, string> {
  const f = face(text);
  const devices = (deviceIds ?? f.targets).map((id) => db.get(id));
  const out = new Map<string, string>();
  for (const [name, content] of generate(f, devices, read).files()) if (typeof content === "string") out.set(name, content);
  return out;
}

/** The generated view's text. */
export function view(text: string, deviceIds: string[] | null = null): string {
  return [...generated(text, deviceIds)].find(([name]) => name.endsWith("View.mc"))![1];
}

/** One of the view's methods: from its declaration to the next closing brace at method depth. */
export function method(viewText: string, name: string): string {
  return viewText.split(`function ${name}`)[1]!.split("\n    }")[0]!;
}

/** The text an element draws on a device, with these readings. */
export function drawn(text: string, element: string, sample: Record<string, unknown>, deviceId = "fenix8solar47mm"): string | null {
  const r = resolved(text, deviceId);
  return drawnText(r, r.items.find((p) => p.id === element)!, new Map(Object.entries(sample)) as never);
}

/** A `text:` template reading `value` through a format spec written the old way: "{:.1f}" -> "{value:.1f}". */
export function template(value: string, fmt: string | null = null): string {
  if (fmt === null) return `{${value}}`;
  return fmt.replace(/\{(:[^}]*)?\}/g, (_, spec: string | undefined) => `{${value}${spec ?? ""}}`);
}

/** The smallest design most tests start from. */
export const MINIMAL = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
`;
