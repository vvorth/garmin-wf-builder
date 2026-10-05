// One installed device, read through `DeviceFiles`: its screen, display,
// limits, symbol table and system-font metrics. Port of wfb/devices.py's
// `Device`, `FontMetric` and `DeviceDatabase`.
import { FontMeasure } from "../fonts/fallback.ts";
import { garminAnyFile, type FontFiles } from "../fonts/files.ts";
import { headHhea } from "../fonts/sfnt.ts";
import { roundHalfEven } from "../py.ts";
import type { DeviceFiles } from "./files.ts";
import { readJson } from "./files.ts";

export class DeviceError extends Error {}

/** A system font's pixel metrics on one device, for the default language; see `Device.systemFonts`. */
export class FontMetric {
  readonly symbol: string;
  readonly face: string;
  readonly font: string;
  /** The published line height: authoritative for layout. */
  readonly size_px: number;
  readonly em_px: number | null;
  readonly ascent_px: number | null;
  readonly height_px: number | null;

  constructor(symbol: string, face: string, font: string, sizePx: number,
    emPx: number | null = null, ascentPx: number | null = null, heightPx: number | null = null) {
    this.symbol = symbol;
    this.face = face;
    this.font = font;
    this.size_px = sizePx;
    this.em_px = emPx;
    this.ascent_px = ascentPx;
    this.height_px = heightPx;
  }

  /** A key for caching per metric, as Python hashes the frozen dataclass. */
  get key(): string {
    return JSON.stringify([this.symbol, this.face, this.font, this.size_px, this.em_px, this.ascent_px, this.height_px]);
  }
}

type Json = Record<string, unknown>;
const obj = (value: unknown): Json => (value !== null && typeof value === "object" && !Array.isArray(value) ? value as Json : {});
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/** `"5.2.0"` as `[5, 2, 0]`, compared element by element. */
export function versionKey(v: string): number[] {
  return v.split(".").map((p) => (/^\d+$/.test(p) ? Number(p) : 0));
}

export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a), kb = versionKey(b);
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const x = ka[i], y = kb[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    if (x !== y) return x - y;
  }
  return 0;
}

const ATTR = /([\w:.-]+)="([^"]*)"/g;

/** `(em_px, ascent_px, height_px)` from one `simulator.json` `type: "ttf"` entry. */
function ttfEnrichment(entry: Json, ppi: number | null): [number | null, number | null, number | null] {
  const em = ppi && "size" in entry ? (entry["size"] as number) * ppi / 72 : null;
  const ascent = "ascent" in entry ? Math.trunc(Number(entry["ascent"])) : null;
  const height = entry["height"];
  return [em, ascent, height !== undefined && height !== null ? Math.trunc(Number(height)) : null];
}

/** Every device's files and reference, and the font files their metrics may read. */
export class DeviceDatabase {
  readonly files: DeviceFiles;
  readonly fonts: FontFiles;
  /** Measures system fonts through `fonts`: every device of this database shares its faces. */
  readonly measure: FontMeasure;
  private readonly cache = new Map<string, Device>();
  private vocabulary: Set<string> | null = null;

  constructor(files: DeviceFiles, fonts: FontFiles) {
    this.files = files;
    this.fonts = fonts;
    this.measure = new FontMeasure(fonts);
  }

  ids(): string[] {
    return this.files.ids();
  }

  get(id: string): Device {
    let device = this.cache.get(id);
    if (device !== undefined) return device;
    const compiler = readJson(this.files, id, "compiler.json");
    if (compiler === undefined) throw new DeviceError(`unknown device '${id}'.  Installed: ${this.ids().join(", ")}`);
    device = new Device(id, this, obj(compiler), obj(readJson(this.files, id, "simulator.json")));
    this.cache.set(id, device);
    return device;
  }

  /** Every `FONT_*` symbol any scraped device's `fonts.default.fixed` table names. */
  documentedFontSymbols(): Set<string> {
    if (this.vocabulary === null) {
      this.vocabulary = new Set();
      for (const id of this.files.referenceIds()) {
        for (const symbol of Object.keys(obj(obj(obj(obj(this.files.reference(id))["fonts"])["default"])["fixed"]))) {
          this.vocabulary.add(symbol);
        }
      }
    }
    return this.vocabulary;
  }
}

export class Device {
  readonly id: string;
  readonly db: DeviceDatabase;
  readonly compiler: Json;
  readonly simulator: Json;
  private memo = new Map<string, unknown>();

  static readonly VECTOR_FONT_SYMBOL = "Graphics.getVectorFont";
  static readonly DRAW_ANGLED_TEXT_SYMBOL = "Dc.drawAngledText";
  static readonly DRAW_RADIAL_TEXT_SYMBOL = "Dc.drawRadialText";
  static readonly BURN_IN_FIELD = "requiresBurnInProtection";
  static readonly DISPLAY_MODE_SYMBOL = "System.getDisplayMode";
  static readonly SUBSCREEN_SYMBOL = "WatchUi.getSubscreen";

  constructor(id: string, db: DeviceDatabase, compiler: Json, simulator: Json) {
    this.id = id;
    this.db = db;
    this.compiler = compiler;
    this.simulator = simulator;
  }

  private once<T>(key: string, make: () => T): T {
    if (!this.memo.has(key)) this.memo.set(key, make());
    return this.memo.get(key) as T;
  }

  // -- geometry ---------------------------------------------------------------

  get width(): number { return Math.trunc(Number(obj(this.compiler["resolution"])["width"])); }
  get height(): number { return Math.trunc(Number(obj(this.compiler["resolution"])["height"])); }

  /** `round` | `rectangle` | `semi-round` | `semi-octagon`. */
  get shape(): string {
    return (obj(this.simulator["display"])["shape"] as string | undefined) ?? "unknown";
  }

  /** Half the smaller screen dimension: what `%r` resolves against. */
  get minorRadius(): number {
    return Math.min(this.width, this.height) / 2.0;
  }

  get deviceFamily(): string {
    return this.compiler["deviceFamily"] as string;
  }

  /** The simulator skin's file name, when the device files ship it. */
  get skinName(): string | null {
    const name = this.simulator["image"];
    return typeof name === "string" && this.db.files.file(this.id, name) !== undefined ? name : null;
  }

  /** `[x, y, width, height]` of the panel inside the skin image. */
  get displayLocation(): [number, number, number, number] | null {
    const loc = obj(this.simulator["display"])["location"];
    if (loc === null || typeof loc !== "object" || Array.isArray(loc)) return null;
    const l = loc as Json;
    const values = [l["x"], l["y"], l["width"], l["height"]].map((v) => (typeof v === "number" ? Math.trunc(v) : Number.NaN));
    return values.some(Number.isNaN) ? null : values as [number, number, number, number];
  }

  /** `[x, y, width, height]` of the subscreen window in screen pixels; `null` without both the box and the symbol. */
  get subscreen(): [number, number, number, number] | null {
    try {
      if (!this.hasSymbol(Device.SUBSCREEN_SYMBOL)) return null;
    } catch (error) {
      if (error instanceof DeviceError) return null;
      throw error;
    }
    const sub = this.simulator["subscreen"];
    const panel = this.displayLocation;
    if (sub === null || typeof sub !== "object" || Array.isArray(sub) || panel === null) return null;
    const loc = (sub as Json)["location"];
    if (loc === null || typeof loc !== "object" || Array.isArray(loc)) return null;
    const l = loc as Json;
    const nums = [l["x"], l["y"], l["width"], l["height"]].map((v) => (typeof v === "number" ? Math.trunc(v) : Number.NaN));
    if (nums.some(Number.isNaN)) return null;
    const [lx, ly, width, height] = nums as [number, number, number, number];
    const x = lx - panel[0], y = ly - panel[1];
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > this.width || y + height > this.height) return null;
    return [x, y, width, height];
  }

  // -- display ----------------------------------------------------------------

  get displayType(): string {
    return (this.compiler["displayType"] as string | undefined) ?? "unknown";
  }

  get isAmoled(): boolean {
    return ["amoled", "oled"].includes(this.displayType.toLowerCase());
  }

  get supportsPartialUpdate(): boolean {
    return !this.isAmoled;
  }

  private get scraped(): Json {
    return this.once("scraped", () => obj(this.db.files.reference(this.id)));
  }

  /** Size of the displayable palette, from the device reference; `null` when it does not say. */
  get displayColors(): number | null {
    const value = obj(this.scraped["normalized"])["display_colors"];
    return value ? Math.trunc(Number(value)) : null;
  }

  get alphaBlending(): boolean {
    return Boolean(this.compiler["alphaBlendingSupport"]);
  }

  get graphicsPoolBytes(): number | null {
    return (this.simulator["graphicsResourcePoolSize"] as number | undefined) ?? null;
  }

  get bitsPerPixel(): number | null {
    const value = this.compiler["bitsPerPixel"];
    return value ? Math.trunc(Number(value)) : null;
  }

  bufferBytes(width: number | null = null, height: number | null = null): number | null {
    const depth = this.bitsPerPixel;
    if (!depth) return null;
    return Math.floor(((width ?? this.width) * (height ?? this.height) * depth + 7) / 8);
  }

  // -- limits -----------------------------------------------------------------

  private get watchfaceAppType(): Json | null {
    return arr(this.compiler["appTypes"]).map(obj).find((e) => e["type"] === "watchFace") ?? null;
  }

  get watchfaceMemoryLimit(): number {
    const entry = this.watchfaceAppType;
    if (entry === null) throw new DeviceError(`${this.id} declares no watchFace app type`);
    return Math.trunc(Number(entry["memoryLimit"]));
  }

  get supportsWatchface(): boolean {
    return this.watchfaceAppType !== null;
  }

  /** The highest Connect IQ version across the device's part numbers. */
  get apiLevel(): string {
    const versions = arr(this.compiler["partNumbers"]).map((pn) => obj(pn)["connectIQVersion"]).filter((v): v is string => Boolean(v));
    if (versions.length === 0) return "0.0.0";
    return versions.reduce((best, v) => (compareVersions(v, best) > 0 ? v : best));
  }

  get languages(): string[] {
    const seen: string[] = [];
    for (const pn of arr(this.compiler["partNumbers"])) {
      for (const lang of arr(obj(pn)["languages"])) {
        const code = lang !== null && typeof lang === "object" ? (lang as Json)["code"] : lang;
        if (typeof code === "string" && code && !seen.includes(code)) seen.push(code);
      }
    }
    return seen;
  }

  // -- symbols ----------------------------------------------------------------

  private get apiDebugXml(): string {
    return this.once("xml", () => {
      const bytes = this.db.files.file(this.id, `${this.id}.api.debug.xml`);
      if (bytes === undefined) throw new DeviceError(`${this.id}: missing ${this.id}.api.debug.xml`);
      return new TextDecoder("utf-8").decode(bytes);
    });
  }

  /** The attributes of every `<tag ...>` in the symbol table, one record per tag. */
  private tags(tag: string): Record<string, string>[] {
    const out: Record<string, string>[] = [];
    for (const m of this.apiDebugXml.matchAll(new RegExp(`<${tag}\\b[^>]*>`, "g"))) {
      const attrs: Record<string, string> = {};
      for (const a of m[0].matchAll(ATTR)) attrs[a[1]!] = a[2]!;
      out.push(attrs);
    }
    return out;
  }

  private get symbols(): [Set<string>, Map<string, string>] {
    return this.once("symbols", () => {
      const functions = new Set(this.tags("functionEntry").filter((a) => "parent" in a && "name" in a)
        .map((a) => `${a["parent"]}\0${a["name"]}`));
      const scopes = new Map<string, string>();
      for (const a of this.tags("apiScopeEntry")) if ("classId" in a && "label" in a) scopes.set(a["classId"]!, a["label"]!);
      return [functions, scopes];
    });
  }

  /** Is `Parent.name` present on this device? The parent is matched on its fully-qualified label. */
  hasSymbol(qualified: string): boolean {
    const [functions, scopes] = this.symbols;
    const dot = qualified.lastIndexOf(".");
    const parent = dot < 0 ? "" : qualified.slice(0, dot), name = qualified.slice(dot + 1);
    if (!parent) throw new Error(`expected Parent.name, got '${qualified}'`);
    const shortParent = parent.slice(parent.lastIndexOf(".") + 1);
    if (!functions.has(`${shortParent}\0${name}`)) return false;
    const want = parent.replaceAll(".", "_");
    const label = scopes.get(shortParent);
    if (label && parent.includes(".") && !label.endsWith(want)) return false;
    return true;
  }

  hasModule(name: string): boolean {
    return this.once("modules", () => new Set(this.tags("dataEntry").filter((a) => a["type"] === "module" && "symbolId" in a)
      .map((a) => a["symbolId"]!))).has(name);
  }

  hasField(name: string): boolean {
    return this.once("fields", () => new Set(this.tags("entry").filter((a) => a["field"] === "true" && "symbol" in a)
      .map((a) => a["symbol"]!))).has(name);
  }

  // -- fonts ------------------------------------------------------------------

  /** `xtiny` to `FONT_XTINY`, `numberHot` to `FONT_NUMBER_HOT`. */
  static symbolForSimulatorName(name: string): string {
    return "FONT_" + name.replace(/(?<!^)(?=[A-Z])/g, "_").toUpperCase();
  }

  /** Every font entry of `simulator.json`'s `ww` set, in file order. */
  private get wwFontEntries(): Json[] {
    return this.once("ww", () => arr(this.simulator["fonts"]).map(obj).filter((block) => block["fontSet"] === "ww")
      .flatMap((block) => arr(block["fonts"]).map(obj)));
  }

  private get simulatorWwFonts(): Map<string, Json> {
    return this.once("wwBySymbol", () => {
      const out = new Map<string, Json>();
      for (const entry of this.wwFontEntries) {
        const name = entry["name"];
        if (typeof name === "string" && name) {
          const symbol = Device.symbolForSimulatorName(name);
          if (!out.has(symbol)) out.set(symbol, entry);
        }
      }
      return out;
    });
  }

  /** The device-resident face names this device publishes to `Graphics.getVectorFont`, in file order. */
  get scalableFaces(): string[] {
    return this.once("faces", () => [...new Set(this.wwFontEntries.filter((e) => e["type"] === "system_ttf" && e["name"])
      .map((e) => e["name"] as string))]);
  }

  /** A scalable face's name to its file stem. */
  get scalableFaceFiles(): Map<string, string> {
    return this.once("faceFiles", () => {
      const out = new Map<string, string>();
      for (const e of this.wwFontEntries) {
        if (e["type"] === "system_ttf" && e["name"] && e["filename"] && !out.has(e["name"] as string)) {
          out.set(e["name"] as string, e["filename"] as string);
        }
      }
      return out;
    });
  }

  /**
   * `FONT_*` pixel metrics: the scraped reference enriched from the
   * device's own `ww` entry; a `ww` `ttf` entry stating its height; and,
   * for a device with no scrape, a documented symbol whose file is a real
   * local outline font, its line height from that file's own tables.
   */
  get systemFonts(): Map<string, FontMetric> {
    return this.once("systemFonts", () => {
      const fixed = obj(obj(obj(this.scraped["fonts"])["default"])["fixed"]);
      const ppiRaw = this.simulator["ppi"];
      const ppi = typeof ppiRaw === "number" ? ppiRaw : null;
      const sim = this.simulatorWwFonts;
      const metrics = new Map<string, FontMetric>();
      for (const [symbol, raw] of Object.entries(fixed)) {
        const entry = obj(raw);
        if (!("size_px" in entry)) continue;
        let font = (entry["font"] as string | undefined) ?? "";
        let enrichment: [number | null, number | null, number | null] = [null, null, null];
        const simEntry = sim.get(symbol);
        if (simEntry !== undefined) {
          font = (simEntry["filename"] as string | undefined) ?? font;
          if (simEntry["type"] === "ttf") enrichment = ttfEnrichment(simEntry, ppi);
        }
        metrics.set(symbol, new FontMetric(symbol, (entry["face"] as string | undefined) ?? "", font,
          Math.trunc(Number(entry["size_px"])), ...enrichment));
      }
      for (const [symbol, simEntry] of sim) {
        if (metrics.has(symbol) || simEntry["type"] !== "ttf") continue;
        const [em, ascent, height] = ttfEnrichment(simEntry, ppi);
        if (height === null) continue;
        metrics.set(symbol, new FontMetric(symbol, "", (simEntry["filename"] as string | undefined) ?? "", height, em, ascent, height));
      }
      if (ppi) {
        const vocabulary = this.db.documentedFontSymbols();
        for (const [symbol, simEntry] of sim) {
          if (metrics.has(symbol) || simEntry["type"] !== "ttf") continue;
          if (!vocabulary.has(symbol) || !("size" in simEntry)) continue;
          const filename = simEntry["filename"];
          if (typeof filename !== "string" || !filename) continue;
          const file = garminAnyFile(this.db.fonts, filename);
          if (file === undefined || !/\.(ttf|otf)$/i.test(file.path)) continue;
          const sfnt = headHhea(file.bytes);
          if (sfnt === null) continue;
          const [upm, ascent, descent] = sfnt;
          const em = ttfEnrichment(simEntry, ppi)[0]!;
          const sizePx = roundHalfEven(em * (ascent - descent) / upm);
          metrics.set(symbol, new FontMetric(symbol, "", filename, sizePx, em, null, sizePx));
        }
      }
      return metrics;
    });
  }
}
