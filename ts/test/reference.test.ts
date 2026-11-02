// The SDK device reference: parsed from the SDK's own device pages, written
// whole, and extracted by wfb itself when missing or from another release.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { ensureDeviceReference } from "../src/devices/node.ts";
import { extractDeviceReference, parseDevicePage, referenceIsFrom, referenceVersion } from "../src/devices/reference.ts";

const scratch = (): string => mkdtempSync(join(tmpdir(), "wfb-ref-"));

/** A device page in the shape the SDK's are: an attribute table, the app types, and a fonts table per language list. */
const page = (name: string, colors: number): string => `<html><body><h1 class="title">${name}</h1>
<table><tr><th>Attribute</th><th>Value</th></tr>
<tr><td>Screen Shape</td><td>round</td></tr><tr><td>Screen Size</td><td>260 x 260</td></tr>
<tr><td>Display Colors</td><td>${colors}</td></tr><tr><td>Touch</td><td>true</td></tr><tr><td>Buttons</td><td>Start, Back</td></tr></table>
<p><strong>App Types</strong></p>
<table><tr><th>App Type</th><th>Memory Limit</th><th>Notes</th></tr><tr><td>Watch Face</td><td>131,072</td><td>&nbsp;</td></tr></table>
<p><strong>Fonts</strong></p>
<p><em>Languages</em></p><p>eng, deu</p>
<p><strong>Fonts</strong></p>
<table><tr><th>Font Symbol</th><th>Face</th><th>Size</th><th>Font</th></tr>
<tr><td>FONT_SMALL</td><td>Roboto Condensed</td><td>26</td><td>RobotoCondensed-Regular</td></tr>
<tr><td>FONT_SYSTEM_LARGE</td><td>Roboto</td><td>Scalable</td><td>Roboto-Regular</td></tr></table>
</body></html>`;

/** A pretend SDK with two device pages and a release. */
function fakeSdk(root: string, version: string, devices: string[]): string {
  mkdirSync(join(root, "bin"), { recursive: true });
  writeFileSync(join(root, "bin", "monkeybrains.jar"), "jar");
  writeFileSync(join(root, "bin", "version.txt"), `${version}\n`);
  const pages = join(root, "doc", "docs", "Device_Reference");
  mkdirSync(pages, { recursive: true });
  for (const id of devices) writeFileSync(join(pages, `${id}.html`), page(`${id} name`, 64));
  writeFileSync(join(pages, "Overview.html"), "<html>not a device</html>");
  return root;
}

describe("the device reference", { concurrency: true }, () => {
  test("a page parses to the attributes, the watch-face limit and the English font table under default", () => {
    const dev = parseDevicePage(page("fr955 name", 64), "fr955.html") as Record<string, unknown>;
    assert.equal(dev["id"], "fr955");
    assert.equal(dev["name"], "fr955 name");
    assert.equal(dev["source"], "doc/docs/Device_Reference/fr955.html");
    assert.deepEqual(dev["normalized"], {
      screen_shape: "round", screen_width: 260, screen_height: 260, display_colors: 64, touch: true, buttons: ["Start", "Back"], watchface_memory_bytes: 131072,
    });
    const fonts = dev["fonts"] as Record<string, { fixed: Record<string, unknown>; scalable: Record<string, unknown> }>;
    assert.deepEqual(fonts["default"]!.fixed["FONT_SMALL"], { face: "Roboto Condensed", font: "RobotoCondensed-Regular", size_px: 26 });
    assert.deepEqual(fonts["default"]!.scalable["FONT_SYSTEM_LARGE"], { face: "Roboto", font: "Roboto-Regular" });
    assert.ok("eng,deu" in fonts);
  });

  test("extraction writes one file per device, skips the overview, and records its source and release", () => {
    const dir = scratch();
    const sdk = fakeSdk(join(dir, "sdk"), "9.3.0", ["fr955", "fenix847mm"]);
    const out = join(dir, "reference");
    assert.equal(extractDeviceReference(sdk, out), 2);
    assert.deepEqual(Object.keys(JSON.parse(readFileSync(join(out, "devices", "fenix847mm.json"), "utf8"))).sort(), ["app_types", "attributes", "fonts", "id", "name", "normalized", "source"]);
    assert.ok(!existsSync(join(out, "devices", "Overview.json")));
    assert.equal(JSON.parse(readFileSync(join(out, "devices-index.json"), "utf8")).length, 2);
    assert.equal(referenceVersion(out), "9.3.0");
    assert.ok(referenceIsFrom(out, sdk));
    assert.ok(!referenceIsFrom(out, sdk, "9.2.0"));
    assert.ok(!existsSync(join(dir, "reference.tmp")));
  });

  test("ensureDeviceReference extracts when missing or from another release, leaves a current one, and never touches WFB_DEVICE_REFERENCE", () => {
    const dir = scratch();
    const sdk = { root: fakeSdk(join(dir, "sdk"), "9.3.0", ["fr955"]), version: "9.3.0" };
    const devices = join(dir, "ref", "devices");
    const saved = process.env["WFB_DEVICE_REFERENCE"];
    delete process.env["WFB_DEVICE_REFERENCE"];
    try {
      assert.equal(ensureDeviceReference(sdk, devices), devices);
      assert.ok(existsSync(join(devices, "fr955.json")));
      const first = readFileSync(join(dir, "ref", "source.txt"), "utf8");
      writeFileSync(join(dir, "ref", "sdk-version.txt"), "9.2.0\n");
      assert.equal(ensureDeviceReference(sdk, devices), devices);
      assert.equal(referenceVersion(join(dir, "ref")), "9.3.0", "a stale reference is extracted again");
      assert.equal(readFileSync(join(dir, "ref", "source.txt"), "utf8"), first);
      // No SDK, or one pruned of its pages: whatever is there is used as it stands.
      assert.equal(ensureDeviceReference(null, join(dir, "nothing", "devices")), join(dir, "nothing", "devices"));
      const bare = { root: join(dir, "bare"), version: "9.3.0" };
      mkdirSync(join(bare.root, "bin"), { recursive: true });
      assert.equal(ensureDeviceReference(bare, join(dir, "nothing", "devices")), join(dir, "nothing", "devices"));
      assert.ok(!existsSync(join(dir, "nothing")));
    } finally {
      if (saved !== undefined) process.env["WFB_DEVICE_REFERENCE"] = saved;
    }
    // Named outright, the reference is read as given, missing or not.
    process.env["WFB_DEVICE_REFERENCE"] = join(dir, "named");
    try {
      assert.equal(ensureDeviceReference(sdk, join(dir, "named")), join(dir, "named"));
      assert.ok(!existsSync(join(dir, "named")));
    } finally {
      if (saved === undefined) delete process.env["WFB_DEVICE_REFERENCE"]; else process.env["WFB_DEVICE_REFERENCE"] = saved;
    }
  });
});
