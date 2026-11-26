import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { bitmapTile, readBitmap } from "../src/bitmaps.ts";
import { load } from "../src/build.ts";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { resolve } from "../src/layout.ts";
import { installAssets } from "../src/node.ts";
import { decodePng, encodePng, pngSize } from "../src/png.ts";
import { previewOptions, render } from "../src/preview.ts";
import { readUpload } from "../src/studio/bundle.ts";
import { frameKey, Studio } from "../src/studio/document.ts";
import { MemoryBackend, Store } from "../src/studio/store.ts";

installAssets();
const root = join(REPO_ROOT, "ts/test/fixtures/devices");
const db = new DeviceDatabase(NodeDeviceFiles.discover(root, join(root, "reference")), new NodeFontFiles());
const device = db.get("wfbtest");
const noFont = (): never => { throw new Error("a bitmap-only face must not read a font"); };
const pixels = new Uint8Array([255, 0, 0, 255, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255, 255, 128]);
const png = Buffer.from(encodePng(2, 2, pixels, 4)).toString("base64");
const text = `format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Bitmap}
build: {targets: [wfbtest]}
static:
  backdrop: {type: image, png: "${png}", at: {anchor: center}, aod: {visible: false}}
`;

function loaded(source = text) {
  const bag = new Bag();
  bag.registerSource("bitmap.yaml", source);
  return { face: load("bitmap.yaml", bag, source, () => false), bag };
}

test("PNG bitmaps preserve alpha, reject invalid input, and zoom without losing transparency", () => {
  const image = readBitmap(png);
  assert.deepEqual(image.pixels, pixels);
  for (const invalid of ["not a PNG", "AAAA", "A".repeat(8 * 1024 * 1024 + 1)]) assert.throws(() => readBitmap(invalid));
  assert.ok(loaded(text.replace(png, "AAAA")).bag.errors.length);
  const zoom = bitmapTile(image, 2);
  assert.deepEqual([zoom.width, zoom.height], [4, 4]);
  assert.equal(zoom.data[(0 * 4 + 2) * 4 + 3], 0);
  assert.equal(zoom.data[(3 * 4 + 3) * 4 + 3], 128);
});

test("a background PNG is a native resource and has the same pixels in the editor, without Garmin files", async () => {
  const built = loaded();
  assert.ok(built.face, built.bag.render());
  const f = built.face;
  const project = generate(f, [device], noFont);
  const files = project.files();
  const view = project.sources.find((s) => s.path.endsWith("View.mc"))!.text;
  assert.match(view, /dc.drawBitmap\(Layout\..*, WatchUi.loadResource\(Rez.Drawables.BitmapStaticBackdrop\) as Graphics.BitmapType\)/);
  const image = files.get("resources-wfbtest/drawables/BitmapStaticBackdrop.png");
  assert.ok(image instanceof Uint8Array);
  assert.deepEqual(pngSize(image), [2, 2]);
  assert.match(String(files.get("resources-wfbtest/drawables/drawables.xml")), /bitmap id="BitmapStaticBackdrop"/);
  const placed = resolve(f, device, new Map());
  const frame = render(placed, previewOptions({ scale: 1, quantise: false, mask_shape: false }));
  const at = (x: number, y: number) => [...frame.data.slice((y * frame.width + x) * 4, (y * frame.width + x) * 4 + 3)];
  assert.deepEqual(at(129, 129), [255, 0, 0]);
  assert.deepEqual(at(130, 129), [0, 0, 0]);
  assert.deepEqual(at(129, 130), [0, 0, 255]);
  const sleeping = render(placed, previewOptions({ scale: 1, aod: true }));
  assert.equal(sleeping.data[(129 * sleeping.width + 129) * 4], 0);
  const studio = new Studio(await Store.open(new MemoryBackend()), db, noFont);
  const doc = studio.create(readUpload("bitmap.yaml", new TextEncoder().encode(text)), "open");
  const editor = doc.frame(frameKey({ device: "wfbtest", scale: 1 }));
  assert.ok(editor.frame);
  assert.ok(editor.layers.some((layer) => layer.ops?.some((op) => op.op === "bitmap")));
  const shown = decodePng(Buffer.from(editor.frame.split(",")[1]!, "base64"))!;
  assert.deepEqual([...shown.pixels.slice((129 * shown.width + 129) * 4, (129 * shown.width + 129) * 4 + 3)], [255, 0, 0]);
  const doubled = doc.frame(frameKey({ device: "wfbtest", scale: 2 }));
  assert.deepEqual(pngSize(Buffer.from(doubled.frame.split(",")[1]!, "base64")), [520, 520]);
});
