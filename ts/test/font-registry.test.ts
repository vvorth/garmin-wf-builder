// The free-font registry (`src/data/font-registry.json`): every reference is
// to an entry that exists, every source is pinned and licensed, and every
// scalable face the SDK device reference publishes resolves to a stand-in.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import registry from "../src/data/font-registry.json" with { type: "json" };
import { DEVICE_REFERENCE } from "../src/devices/node.ts";
import { resolveRegistryKey } from "../src/fonts/files.ts";

interface Source { url: string; member?: string; sha256: string; size: number; license?: string; license_url?: string; license_member?: string }
const SOURCES = registry.sources as Record<string, Source>;
const FONTS = registry.fonts as Record<string, { source: string; match: string; note: string }>;
const NAMES = registry.names as Record<string, string>;
const FACES = registry.faces as Record<string, string>;
const PATTERNS = registry.patterns as { regex: string; key: string; note: string }[];

/** A key's source has what redistributing its file needs: a licence named, and where its text is. */
function licensed(key: string): boolean {
  const source = SOURCES[FONTS[key]?.source ?? ""];
  return source !== undefined && Boolean(source.license) && Boolean(source.license_url);
}

test("every name, pattern and face names a font, and every font a source", () => {
  for (const [name, key] of Object.entries(NAMES)) assert.ok(Object.hasOwn(FONTS, key), `names.${name} -> ${key}: no such font`);
  for (const [face, key] of Object.entries(FACES)) assert.ok(Object.hasOwn(FONTS, key), `faces.${face} -> ${key}: no such font`);
  for (const { regex, key } of PATTERNS) {
    assert.ok(Object.hasOwn(FONTS, key), `pattern ${regex} -> ${key}: no such font`);
    assert.doesNotThrow(() => new RegExp(regex), regex);
  }
  for (const [key, font] of Object.entries(FONTS)) {
    assert.ok(Object.hasOwn(SOURCES, font.source), `fonts.${key}: no source ${font.source}`);
    assert.ok(["exact", "family", "substitute"].includes(font.match), `fonts.${key}: match ${font.match}`);
    assert.ok(font.note.length > 0, `fonts.${key}: no note`);
  }
  const used = new Set(Object.values(FONTS).map((font) => font.source));
  for (const id of Object.keys(SOURCES)) assert.ok(used.has(id), `sources.${id} is used by no font`);
});

test("every source is pinned to bytes that cannot move, and licensed", () => {
  for (const [id, source] of Object.entries(SOURCES)) {
    assert.match(source.sha256, /^[0-9a-f]{64}$/, `${id}: sha256`);
    assert.ok(Number.isInteger(source.size) && source.size > 0, `${id}: size`);
    assert.ok(source.url.startsWith("https://"), `${id}: ${source.url}`);
    // A release asset, or a file at a full commit hash: never a branch.
    assert.ok(/\/releases\/download\//.test(source.url) || /^https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/[0-9a-f]{40}\//.test(source.url), `${id}: ${source.url} is not pinned`);
    assert.equal(source.member !== undefined, source.url.endsWith(".zip"), `${id}: an archive names its member, and only an archive`);
    assert.ok(source.license && source.license_url, `${id}: no licence`);
    if (source.license_member !== undefined) assert.ok(source.url.endsWith(".zip"), `${id}: license_member outside an archive`);
    else assert.match(source.license_url!, /^https:\/\/\S+$/, `${id}: its licence text has no URL`);
  }
});

test("names resolve as the research decided, the older ones unchanged", () => {
  const expected: Record<string, string> = {
    RobotoCondensedBold: "roboto-condensed-bold", "RobotoCondensed-Bold": "roboto-condensed-bold",
    RobotoCondensedRegular: "roboto-condensed-regular", RobotoRegular: "roboto-regular", RobotoItalic: "roboto-italic",
    RobotoMedium: "roboto-medium", "Roboto-Medium-Outdoor": "roboto-medium", RobotoBlack: "roboto-black",
    YantramanavRegular: "yantramanav-regular", BionicMedium: "rajdhani-medium",
    // Bionic is Garmin's tabular-digit build of Rajdhani.
    BionicBold: "rajdhani-bold", Bionic_Bold_Number_Only: "rajdhani-bold", BionicSemiBold: "rajdhani-semibold", BionicSemibold: "rajdhani-semibold",
    FNT_FENIX6_BIONIC_BOLD_NUMBER_18: "bionic-substitute", "006B410500_BIONIC_SEMI_BOLD_NUMBER_28": "rajdhani-semibold",
    "006B410500_BIONIC_COND_SEMI_BOLD_NUMBER_42": "bionic-cond-substitute",
    RobotoCondensedRegularItalic: "roboto-condensed-italic",
    "Kosugi-Regular-2": "kosugi-regular", "NotoSansSC-Medium-Outdoor": "noto-sans-sc-medium", PridiRegularGarmin: "pridi-regular-garmin",
    SakkalMajallaRoman: "amiri-regular", swiss_721_bd: "arimo-bold", ExoSemiBold: "exo-semibold", TomorrowBold: "tomorrow-bold",
  };
  for (const [name, key] of Object.entries(expected)) assert.equal(resolveRegistryKey(name), key, name);
  assert.equal(FONTS["bionic-substitute"]!.source, "rajdhani-bold");
  assert.equal(FONTS["amiri-regular"]!.match, "substitute");
  assert.equal(FONTS["noto-sans-hebrew-regular"]!.match, "exact");
});

test("nothing listed as unmapped resolves", () => {
  for (const entry of registry.unmapped as { name?: string; face?: string }[]) {
    if (entry.name !== undefined) assert.equal(resolveRegistryKey(entry.name), null, entry.name);
    if (entry.face !== undefined) assert.ok(!Object.hasOwn(FACES, entry.face), entry.face);
  }
});

const REFERENCE = existsSync(DEVICE_REFERENCE) ? DEVICE_REFERENCE : null;

test("every scalable face in the device reference, by name and by file, resolves to a licensed stand-in", { skip: REFERENCE === null && "no SDK device reference (tools/setup-env.sh extracts it)" }, (t) => {
  const missing: string[] = [];
  let faces = 0;
  for (const file of readdirSync(REFERENCE!).filter((n) => n.endsWith(".json"))) {
    const device = JSON.parse(readFileSync(join(REFERENCE!, file), "utf8")) as { id: string; fonts?: Record<string, { scalable?: Record<string, { face: string; font: string }> }> };
    for (const group of Object.values(device.fonts ?? {})) {
      for (const [name, entry] of Object.entries(group.scalable ?? {})) {
        faces++;
        // The face name alone is what `fallback: auto` resolves; the file stem is what a device's own font is called.
        for (const [what, key] of [[name, resolveRegistryKey(name)], [`${name}'s file ${entry.font}`, resolveRegistryKey(entry.font, entry.face)]] as const) {
          if (key === null || !licensed(key)) missing.push(`${device.id}: ${what} -> ${key ?? "nothing"}`);
        }
      }
    }
  }
  // The fixture device's reference (CI's only one) lists no scalable face: nothing to check there, not a failure.
  if (faces === 0) {
    t.skip(`${REFERENCE} lists no scalable face`);
    return;
  }
  assert.deepEqual([...new Set(missing)], []);
});
