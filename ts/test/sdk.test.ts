// The SDK on disk: finding one, which files the compiler needs, and the
// writable copy made when the install is read-only (a mounted SDK Manager
// folder in the container).
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { compilerNeeds, compilerRoot, findSdk, monkeycCommand, prunedSdkKeeps, sdksIn, sdkVersion } from "../src/sdk.ts";

const scratch = (): string => mkdtempSync(join(tmpdir(), "wfb-sdk-"));

/** A pretend SDK root: the compiler's files, a GUI program beside them, and the version named or not. */
function fakeSdk(root: string, version: string | null, jarBytes = 100): string {
  mkdirSync(join(root, "bin"), { recursive: true });
  writeFileSync(join(root, "bin", "monkeybrains.jar"), Buffer.alloc(jarBytes, 1));
  writeFileSync(join(root, "bin", "api.db"), "db");
  writeFileSync(join(root, "bin", "monkeyc"), "#!/bin/bash\n");
  writeFileSync(join(root, "bin", "simulator"), "gui");
  writeFileSync(join(root, "bin", "simulator.exe"), "gui");
  mkdirSync(join(root, "doc", "docs", "Device_Reference"), { recursive: true });
  writeFileSync(join(root, "doc", "docs", "Device_Reference", "fr955.html"), "<html></html>");
  if (version !== null) writeFileSync(join(root, "bin", "version.txt"), `${version}\n`);
  return root;
}

describe("the SDK on disk", { concurrency: true }, () => {
  test("a folder of SDKs lists newest first; one SDK is itself; a version comes from version.txt, else the folder's name", () => {
    const sdks = join(scratch(), "Sdks");
    fakeSdk(join(sdks, "connectiq-sdk-mac-9.2.0-2026-07-01-abc"), "9.2.0");
    fakeSdk(join(sdks, "connectiq-sdk-mac-9.3.0-2026-10-20-def"), null);
    fakeSdk(join(sdks, "connectiq-sdk-mac-9.10.0-2027-01-01-ghi"), "9.10.0");
    mkdirSync(join(sdks, "not-an-sdk"));
    assert.deepEqual(sdksIn(sdks).map((s) => s.version), ["9.10.0", "9.3.0", "9.2.0"]);
    assert.equal(sdkVersion(join(sdks, "connectiq-sdk-mac-9.3.0-2026-10-20-def")), "9.3.0");
    const one = sdksIn(join(sdks, "connectiq-sdk-mac-9.2.0-2026-07-01-abc"));
    assert.equal(one.length, 1);
    assert.equal(one[0]!.version, "9.2.0");
    assert.deepEqual(sdksIn(join(sdks, "missing")), []);
    assert.deepEqual(sdksIn(join(sdks, "not-an-sdk")), []);
  });

  test("findSdk takes the override first, and in an Sdks folder the SDK Manager's current one over the newest", () => {
    const home = scratch();
    const sdks = join(home, "Sdks");
    fakeSdk(join(sdks, "connectiq-sdk-mac-9.2.0-a"), "9.2.0");
    const newest = fakeSdk(join(sdks, "connectiq-sdk-mac-9.3.0-b"), "9.3.0");
    assert.equal(findSdk(sdks)?.root, newest);
    writeFileSync(join(home, "current-sdk.cfg"), `/somewhere/else/connectiq-sdk-mac-9.2.0-a\n`);
    assert.equal(findSdk(sdks)?.version, "9.2.0");
    writeFileSync(join(home, "current-sdk.cfg"), "connectiq-sdk-mac-9.9.9-gone");
    assert.equal(findSdk(sdks)?.version, "9.3.0", "a current SDK that is not installed falls back to the newest");
    assert.equal(findSdk(join(home, "nowhere"))?.root, findSdk()?.root, "an empty override falls through to the defaults");
  });

  test("the compiler needs bin/ without the GUI programs and native files; a pruned SDK also keeps the device pages and licences", () => {
    for (const keep of ["bin/monkeybrains.jar", "bin/api.db", "bin/api.debug.xml", "bin/resources.xsd", "bin/version.txt", "bin/monkeyc", "bin/monkeydo"]) {
      assert.ok(compilerNeeds(keep), keep);
    }
    for (const drop of ["bin/simulator", "bin/simulator.exe", "bin/shell", "bin/era.jar", "bin/LanguageServer.jar", "bin/monkeyc.bat", "bin/vcruntime140.dll",
      "bin/cyclist-monkey.png", "bin/ConnectIQ.app/Contents/Info.plist", "bin/", "doc/docs/Device_Reference/fr955.html", "samples/x", "share/y", "README.html"]) {
      assert.ok(!compilerNeeds(drop), drop);
    }
    assert.ok(prunedSdkKeeps("doc/docs/Device_Reference/fr955.html"));
    assert.ok(prunedSdkKeeps("resources/readme/licenses/CIQ-LICENSE-AGREEMENT.html"));
    assert.ok(!prunedSdkKeeps("doc/docs/Core_Topics/x.html"));
    assert.ok(!prunedSdkKeeps("resources/readme/other.txt"));
  });

  test("a writable SDK compiles in place; a read-only one from a copy of the compiler's files, made once and remade for another release", () => {
    const dir = scratch();
    const sdk = { root: fakeSdk(join(dir, "install"), "9.3.0"), version: "9.3.0" };
    const into = join(dir, "cache", "sdk");
    const inPlace = compilerRoot(sdk, into, () => true);
    assert.deepEqual(inPlace, { ...sdk, copied: false });
    assert.ok(!existsSync(into));

    const copy = compilerRoot(sdk, into, () => false);
    assert.equal(copy.copied, true);
    assert.equal(copy.root, join(into, "9.3.0"));
    assert.deepEqual(readdirSync(join(copy.root, "bin")).sort(), ["api.db", "monkeybrains.jar", "monkeyc", "version.txt"]);
    assert.ok(!existsSync(join(copy.root, "doc")), "the copy is for compiling: no doc pages");
    const made = statSync(join(copy.root, "bin", "monkeybrains.jar")).mtimeMs;
    assert.equal(compilerRoot(sdk, into, () => false).root, copy.root);
    assert.equal(statSync(join(copy.root, "bin", "monkeybrains.jar")).mtimeMs, made, "a matching copy is reused");

    // The install moves to another release at the same path: the copy of that release is made beside the old one.
    writeFileSync(join(sdk.root, "bin", "version.txt"), "9.4.0\n");
    const next = compilerRoot({ ...sdk, version: "9.4.0" }, into, () => false);
    assert.equal(next.root, join(into, "9.4.0"));
    // The same release with a different compiler (a reinstall): the copy is remade.
    writeFileSync(join(sdk.root, "bin", "monkeybrains.jar"), Buffer.alloc(200, 2));
    writeFileSync(join(sdk.root, "bin", "version.txt"), "9.3.0\n");
    const remade = compilerRoot(sdk, into, () => false);
    assert.equal(readFileSync(join(remade.root, "bin", "monkeybrains.jar")).length, 200);
  });

  test("monkeyc is the JVM on the compiler's jar, as the SDK's own launcher runs it", () => {
    const command = monkeycCommand("/sdk/x");
    assert.equal(command.at(-1), "com.garmin.monkeybrains.Monkeybrains");
    assert.ok(command.includes("/sdk/x/bin/monkeybrains.jar"));
    assert.ok(command[0]!.endsWith("java"));
  });
});

describe("the SDK download", { concurrency: true }, () => {
  test("the newest Linux release is picked, or the one asked for, and none when Garmin lists none", async () => {
    const { pickLinuxSdk, unpackSdk } = await import("../src/init.ts");
    const list = [
      { version: "9.2.0", linux: "connectiq-sdk-lin-9.2.0-a.zip", mac: "m.dmg" },
      { version: "9.10.0", linux: "connectiq-sdk-lin-9.10.0-c.zip" },
      { version: "9.3.0", linux: "connectiq-sdk-lin-9.3.0-b.zip" },
      { version: "9.11.0", mac: "connectiq-sdk-mac-9.11.0-d.dmg" },
    ];
    assert.equal(pickLinuxSdk(list)?.version, "9.10.0", "numeric order, and a release with no Linux archive is skipped");
    assert.equal(pickLinuxSdk(list, "9.2.0")?.linux, "connectiq-sdk-lin-9.2.0-a.zip");
    assert.equal(pickLinuxSdk(list, "9.11.0"), null);
    assert.equal(pickLinuxSdk([]), null);

    // An archive unpacks as the SDK Manager lays one out, bin/ programs executable, nothing left half-made.
    const { zipSync, strToU8 } = await import("fflate");
    const dir = scratch();
    const archive = zipSync({
      "bin/monkeybrains.jar": strToU8("jar"), "bin/version.txt": strToU8("9.3.0\n"), "bin/monkeyc": strToU8("#!/bin/bash\n"),
      "bin/api.db": strToU8("db"), "doc/docs/Device_Reference/fr955.html": strToU8("<html></html>"),
    });
    const sdk = unpackSdk(archive, dir, "connectiq-sdk-lin-9.3.0-x");
    assert.equal(sdk.root, join(dir, "connectiq-sdk-lin-9.3.0-x"));
    assert.equal(sdk.version, "9.3.0");
    assert.ok(statSync(join(sdk.root, "bin", "monkeyc")).mode & 0o111, "monkeyc is executable");
    assert.ok(!(statSync(join(sdk.root, "bin", "api.db")).mode & 0o111), "a data file is not");
    assert.ok(existsSync(join(sdk.root, "doc", "docs", "Device_Reference", "fr955.html")));
    assert.ok(!existsSync(join(dir, "connectiq-sdk-lin-9.3.0-x.tmp")));
    assert.throws(() => unpackSdk(zipSync({ "readme.txt": strToU8("x") }), dir, "not-an-sdk"), /monkeybrains\.jar/);
    assert.ok(!existsSync(join(dir, "not-an-sdk")) && !existsSync(join(dir, "not-an-sdk.tmp")));
  });
});

describe("the SDK update check", { concurrency: true }, () => {
  test("a newer Linux release is reported; the list is fetched once a day and never when it cannot be", async () => {
    const { checkForNewerSdk, newerThan, updateNotice } = await import("../src/init.ts");
    const list = [{ version: "9.3.0", linux: "a.zip" }, { version: "9.10.0", linux: "b.zip" }, { version: "9.11.0", mac: "c.dmg" }];
    assert.equal(newerThan("9.3.0", list)?.version, "9.10.0");
    assert.equal(newerThan("9.10.0", list), null, "the newest Linux release is what counts, not a Mac-only one");
    assert.equal(newerThan("9.9.0", list)?.version, "9.10.0", "numeric, not lexical");

    const saved = process.env["WFB_NO_UPDATE_CHECK"];
    delete process.env["WFB_NO_UPDATE_CHECK"];
    try {
      const cacheFile = join(scratch(), "cache", "sdks.json");
      let fetches = 0;
      const fetchList = async (): Promise<typeof list> => { fetches++; return list; };
      const day = 24 * 60 * 60 * 1000;
      assert.equal((await checkForNewerSdk("9.3.0", { cacheFile, fetchList, now: 0 }))?.version, "9.10.0");
      assert.ok(existsSync(cacheFile));
      assert.equal((await checkForNewerSdk("9.3.0", { cacheFile, fetchList, now: Date.now() }))?.version, "9.10.0");
      assert.equal(fetches, 1, "the day-old copy answers");
      assert.equal((await checkForNewerSdk("9.3.0", { cacheFile, fetchList, now: Date.now() + 2 * day }))?.version, "9.10.0");
      assert.equal(fetches, 2, "a stale copy is fetched again");
      const failing = async (): Promise<typeof list> => { throw new Error("offline"); };
      assert.equal(await checkForNewerSdk("9.3.0", { cacheFile: join(scratch(), "none.json"), fetchList: failing }), null, "offline: no notice, no error");
      process.env["WFB_NO_UPDATE_CHECK"] = "1";
      assert.equal(await checkForNewerSdk("9.3.0", { cacheFile, fetchList }), null);
      assert.ok(updateNotice("9.3.0", list[1]!, true).includes("WFB_ACCEPT_LICENSE=1"));
      assert.ok(updateNotice("9.3.0", list[1]!, false).includes("--download-sdk"));
    } finally {
      if (saved === undefined) delete process.env["WFB_NO_UPDATE_CHECK"]; else process.env["WFB_NO_UPDATE_CHECK"] = saved;
    }
  });

  test("in the container the download lands in the mounted folder when writable, else in the cache's sdks/", async () => {
    const { sdkDownloadFolder } = await import("../src/init.ts");
    const { downloadedSdks } = await import("../src/sdk.ts");
    const dir = scratch();
    const saved = process.env["CIQ_SDK"];
    try {
      process.env["CIQ_SDK"] = join(dir, "sdk");
      mkdirSync(join(dir, "sdk"));
      assert.equal(sdkDownloadFolder(true), join(dir, "sdk"));
      // A read-only mount (root in a test can write anywhere, so the answer is injected).
      assert.equal(sdkDownloadFolder(true, () => false), downloadedSdks());
      assert.equal(sdkDownloadFolder(false, () => false), join(homedir(), ".Garmin", "ConnectIQ", "Sdks"), "a Linux host: the SDK Manager's folder");
    } finally {
      if (saved === undefined) delete process.env["CIQ_SDK"]; else process.env["CIQ_SDK"] = saved;
    }
  });
});
