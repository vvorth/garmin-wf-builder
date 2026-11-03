// The environment in the page (`app/sdk.ts`): the SDK dialog on a load that
// finds no SDK, with the agreement to accept before the download, and the
// Doctor dialog over the server's report, from the top bar.
import assert from "node:assert/strict";
import { test } from "node:test";
import { faceFixture, page } from "./page-harness.ts";

/** A `fetch` answering the server's environment endpoints from `answers` and recording what was asked. */
const serverStub = (answers: Record<string, unknown>): string => `
      const fetched = [];
      globalThis.fetch = async (url, init = {}) => {
        const path = String(url).split("?")[0];
        fetched.push([init.method || "GET", path, init.body ? JSON.parse(init.body) : null]);
        const body = ${JSON.stringify(answers)}[path];
        if (body === undefined) return { ok: false, status: 404, json: async () => ({ error: "not found" }) };
        return { ok: true, status: 200, json: async () => body };
      };
    `;

const status = (sdk: { version: string; install: string; copied: boolean } | null, canDownload = true, deviceCount = 3): unknown => ({
  sdk, newer: null, download: null, canDownload, downloadFolder: "/home/me/.Garmin/ConnectIQ/Sdks", inContainer: false, reloadNeeded: false,
  devices: { root: "/vendor/Devices", count: deviceCount },
  manager: {
    downloads: { mac: "https://x/connectiq-sdk-manager.dmg", linux: "https://x/connectiq-sdk-manager-linux.zip", windows: "https://x/connectiq-sdk-manager-windows.zip" },
    folders: { mac: "~/Library/Application Support/Garmin/ConnectIQ", linux: "~/.Garmin/ConnectIQ", windows: "%APPDATA%\\Garmin\\ConnectIQ" },
    names: { mac: "macOS", linux: "Linux", windows: "Windows" }, page: "https://developer.garmin.com/connect-iq/sdk/",
  },
});

const agreement = { url: "https://developer.garmin.com/connect-iq/sdk/", updated: "Updated August 6, 2024", text: "I. DEVELOPMENT\n\n- a. License. A limited licence." };

test("with no SDK, the dialog opens on load; the download waits for the agreement to be accepted, then is asked for", async () => {
  const printed = await page(faceFixture(), "#/", `
      const shown = () => app.textContent.includes("The Connect IQ SDK is needed");
      out([shown(), app.textContent.includes("A limited licence.")]);
      out(button("Download and install").attributes.disabled !== undefined);
      const box = find((e) => e.localName === "input" && e.attributes.type === "checkbox")[0];
      box.checked = true; box.dispatch("change", { target: box, currentTarget: box }); await settle();
      out(button("Download and install").attributes.disabled !== undefined);
      await click(button("Download and install"));
      await settle();
      out(fetched.filter(([m]) => m === "POST"));
    `, serverStub({ "api/sdk": status(null), "api/sdk/agreement": agreement, "api/doctor": {} }));
  assert.deepEqual(printed, [[true, true], true, false, [["POST", "api/sdk/download", { accept: true }]]]);
});

test("with an SDK the dialog stays closed, and on a host that cannot download the SDK Manager's links are offered instead", async () => {
  const quiet = await page(faceFixture(), "#/", `
      out(app.textContent.includes("The Connect IQ SDK is needed"));
    `, serverStub({ "api/sdk": status({ version: "9.3.0", install: "/sdk", copied: false }) }));
  assert.deepEqual(quiet, [false]);
  const mac = await page(faceFixture(), "#/", `
      out([app.textContent.includes("the SDK Manager installs the SDK"), app.textContent.includes("connectiq-sdk-manager.dmg"), button("Download and install") === undefined]);
    `, serverStub({ "api/sdk": status(null, false) }));
  assert.deepEqual(mac, [[true, true, true]]);
});

test("with no watches, the dialog says so and points at the SDK Manager; with an SDK as well there is no download to offer", async () => {
  const printed = await page(faceFixture(), "#/", `
      const text = () => app.textContent;
      out([text().includes("The watches' definitions are needed"), text().includes("No device definitions"), text().includes("connectiq-sdk-manager-linux.zip"),
           button("Download and install") === undefined, fetched.some(([, p]) => p === "api/sdk/agreement")]);
    `, serverStub({ "api/sdk": status({ version: "9.3.0", install: "/sdk", copied: false }, true, 0), "api/sdk/agreement": agreement }));
  assert.deepEqual(printed, [[true, true, true, true, false]]);
  const both = await page(faceFixture(), "#/", `
      out([app.textContent.includes("The Connect IQ SDK and the watches' definitions are needed"), button("Download and install") !== undefined]);
    `, serverStub({ "api/sdk": status(null, true, 0), "api/sdk/agreement": agreement }));
  assert.deepEqual(both, [[true, true]]);
});

test("Doctor shows the report with the devices and fonts behind their counts, and names a newer SDK", async () => {
  const face = faceFixture();
  face.summary.targets = ["fr955"];
  const report = {
    wfb: "0.1.0", node: { version: "24.22.1", path: "/usr/bin/node", problem: null }, schema: { path: "/s.json", ok: true },
    reference: { dir: "/cache/device-reference", ok: true, sdkVersion: "9.3.0", hints: [] }, iconFont: { path: "/icons.ttf", ok: true },
    garminFonts: { root: "/fonts", files: ["Roboto-Regular.ttf", "sub/Bionic.cft"], hints: [] },
    devices: { root: "/devices", ids: ["fr955", "fenix847mm"], error: null, hints: [] },
    systemFonts: { lacking: [], summary: "3 installed", hints: [] },
    sdk: { version: "9.3.0", install: "/sdk", compiler: "/cache/wfb/sdk/9.3.0", copied: true }, sdkHints: [],
    newerSdk: { version: "9.4.0", how: "download it with the SDK Manager" }, referenceStale: null,
    key: { path: "/keys/developer_key.der", state: "will-generate", hints: [] }, verdict: "ready", problems: [], inContainer: true,
  };
  const printed = await page(face, `#/face/${face.summary.id}`, `
      await click(button("Doctor"));
      const text = () => app.textContent;
      out([text().includes("ready"), text().includes("2 files at"), text().includes("sub/Bionic.cft"), text().includes("2 installed at"), text().includes("fenix847mm"),
           text().includes("runs from a copy at /cache/wfb/sdk/9.3.0"), text().includes("SDK 9.4.0 is available"), button("Install SDK 9.4.0") !== undefined]);
      await click(button("SDK Manager downloads"));
      out(text().includes("connectiq-sdk-manager-windows.zip"));
    `, serverStub({ "api/sdk": { ...(status({ version: "9.3.0", install: "/sdk", copied: true }) as object), newer: { version: "9.4.0" } }, "api/doctor": report }));
  assert.deepEqual(printed, [[true, true, true, true, true, true, true, true], true]);
});
