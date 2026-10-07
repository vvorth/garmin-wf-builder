// Resource generation: every declared font baked at the device's size,
// every icon and ring font, the fonts' resource entries, the strings, the
// launcher icon and the native editor's config..
import type { Device } from "../devices/device.ts";
import { bake, dilate, inkHeight, toFnt } from "../fonts/bake.ts";
import * as complications from "../complications.ts";
import { CONFIG_SYMBOL } from "../ir/model.ts";
import { configDataIds, configLabelId, configStyleLabelId } from "../ir/naming.ts";
import { Color } from "../palette.ts";
import { encodePng } from "../png.ts";
import { ellipse, type Image, image as newImage, line } from "../raster/pillow.ts";
import { escape, XMLNS, XSD } from "./xml.ts";
import type { BakedFont } from "../fonts/bmfont.ts";
import type { FontFile } from "../fonts/files.ts";
import { type Face, FontSpec } from "../ir/model.ts";
import { comparePoints } from "../kinds/data.ts";
import * as kinds from "../kinds/index.ts";
import { roundHalfEven } from "../py.ts";
import * as units from "../units.ts";

/** Reads a font file a design names (`FontSpec.source`) or the icon font. */
export type FontReader = (path: string) => FontFile;

/** The icon font, relative to the repository. */
export const ICON_FONT = "ts/assets/icons/SymbolsNerdFont-Regular.ttf";

/** The characters each declared baked font must hold: its `glyphs:` if written, else what the design draws with it. */
export function glyphSet(face: Face): Map<string, string> {
  const needed = new Map<string, Set<string>>();
  for (const [name, spec] of face.fonts) if (spec.isBaked) needed.set(name, new Set());
  for (const [, run] of kinds.faceTextRuns(face)) {
    if (run.icon === null && !run.isVector(face)) {
      let set = needed.get(run.font);
      if (set === undefined) needed.set(run.font, set = new Set());
      for (const c of run.glyphs) set.add(c);
    }
  }
  const out = new Map<string, string>();
  for (const [name, chars] of needed) {
    const declared = face.fonts.get(name)!.glyphs;
    out.set(name, declared !== null ? declared : [...chars].sort(comparePoints).join(""));
  }
  return out;
}

const bakeSizes = new Map<string, number>();

/**
 * The nominal size to bake `codepoint` at so its ink height is as close as
 * possible to `targetPx`: the icon font's aggregated sets pad their glyphs
 * differently, so `size:` means one visual height for every icon.
 */
export function bakeSize(iconFont: FontFile, codepoint: string, targetPx: number): number {
  const key = `${codepoint}\0${targetPx}`;
  const hit = bakeSizes.get(key);
  if (hit !== undefined) return hit;
  let result: number;
  if (targetPx <= 0) {
    result = 1;
  } else {
    const reference = 512;
    const atReference = inkHeight(iconFont, codepoint, reference);
    const ratio = atReference ? atReference / reference : 1.0;
    const guess = Math.max(1, roundHalfEven(targetPx / ratio));
    let bestSize = guess, bestInk = inkHeight(iconFont, codepoint, guess), bestDiff = Math.abs(bestInk - targetPx);
    for (let candidate = Math.max(1, guess - 4); candidate < guess + 9; candidate++) {
      if (candidate === guess) continue;
      const ink = inkHeight(iconFont, codepoint, candidate);
      const diff = Math.abs(ink - targetPx);
      // On a tie, prefer not undershooting.
      if (diff < bestDiff || (diff === bestDiff && ink >= targetPx && targetPx > bestInk)) {
        [bestSize, bestInk, bestDiff] = [candidate, ink, diff];
      }
    }
    result = bestSize;
  }
  bakeSizes.set(key, result);
  return result;
}

/** One synthetic `FontSpec` per icon font key: its nominal size on this device, its glyphs and anti-aliasing. */
export function iconFontSpecs(face: Face, device: Device, iconFont: FontFile): Map<string, FontSpec> {
  const byKey = new Map<string, [units.Length | null, string, string, boolean]>();
  for (const [, run] of kinds.faceTextRuns(face)) {
    if (run.icon !== null) byKey.set(run.font, [run.icon.size, run.icon.glyphs, run.icon.reference, run.icon.antialias]);
  }
  return new Map([...byKey].map(([key, [length, glyphs, reference, antialias]]) => [key, FontSpec.create({
    name: key, source: ICON_FONT, glyphs, antialias, span: null,
    size: new units.Length(bakeSize(iconFont, reference, units.pixelSize(length, device.minorRadius)), "px"),
  })]));
}

/** Rasterise every declared font, every icon font and every ring font, at this device's size. */
/**
 * Baked sheets kept across bakes, by font file bytes and bake options: an
 * editor re-resolves the same face after every edit, and most edits leave
 * every sheet as it was.
 */
export type BakeMemo = WeakMap<Uint8Array, Map<string, BakedFont>>;

function memoBake(memo: BakeMemo | null, source: FontFile, options: Parameters<typeof bake>[1]): BakedFont {
  if (memo === null) return bake(source, options);
  let sheets = memo.get(source.bytes);
  if (sheets === undefined) memo.set(source.bytes, sheets = new Map());
  const key = JSON.stringify([source.path, options.name, options.size, options.glyphs, options.antialias ?? false, options.monospace ?? false, options.align ?? "center"]);
  let baked = sheets.get(key);
  if (baked === undefined) sheets.set(key, baked = bake(source, options));
  return baked;
}

export function bakeFonts(face: Face, device: Device, read: FontReader, memo: BakeMemo | null = null): Map<string, BakedFont> {
  const sets = glyphSet(face);
  const baked = new Map<string, BakedFont>();
  for (const [name, spec] of face.fonts) {
    if (spec.isVector) continue; // drawn from the device's own resident face
    baked.set(name, memoBake(memo, read(spec.source!), {
      name, size: spec.pixelSize(device.minorRadius), glyphs: sets.get(name) || "0123456789",
      antialias: spec.antialias, monospace: spec.monospace, align: spec.align,
    }));
  }
  const specs = [...kinds.faceTextRuns(face)].some(([, run]) => run.icon !== null) ? iconFontSpecs(face, device, read(ICON_FONT)) : new Map();
  for (const [name, spec] of specs) {
    baked.set(name, memoBake(memo, read(spec.source!), { name, size: spec.pixelSize(device.minorRadius), glyphs: spec.glyphs!, antialias: spec.antialias }));
  }
  // Last: each ring font is dilated from its base's own sheet.
  for (const [name, [base, glyphs, width]] of kinds.ringFonts(face)) {
    baked.set(name, dilate(baked.get(base)!, { name, glyphs: [...glyphs].sort(comparePoints).join(""), width }));
  }
  return baked;
}

/** Everything written under one device's resource directory. */
export interface ResourceBundle {
  device_id: string;
  directory: string;
  /** Relative path to text. */
  files: Map<string, string>;
  fonts: Map<string, BakedFont>;
  /** Relative path to an RGBA image. */
  images: Map<string, RgbaImage>;
}

/** An RGBA image: `data` straight-alpha bytes. */
export interface RgbaImage {
  width: number;
  height: number;
  data: Uint8Array;
}

/** A ring font's resource entry: its base font's spec under its own name, holding just its ringed glyphs. */
function ringFontSpecs(face: Face, specs: ReadonlyMap<string, FontSpec>): Map<string, FontSpec> {
  return new Map([...kinds.ringFonts(face)].map(([name, [base, glyphs]]) =>
    [name, FontSpec.create({ ...specs.get(base)!, name, glyphs: [...glyphs].sort(comparePoints).join("") })]));
}

const basename = (path: string): string => path.slice(path.lastIndexOf("/") + 1);

/** One device's resource bundle: its fonts' entries, the launcher icon at its size, and the native editor's config. */
export function buildBundle(face: Face, device: Device, baked: ReadonlyMap<string, BakedFont>, read: FontReader): ResourceBundle {
  const bundle: ResourceBundle = { device_id: device.id, directory: `resources-${device.id}`, files: new Map(), fonts: new Map(), images: new Map() };
  const sets = glyphSet(face);
  const hasIcons = [...kinds.faceTextRuns(face)].some(([, run]) => run.icon !== null);
  const specs = new Map<string, FontSpec>([...face.fonts, ...(hasIcons ? iconFontSpecs(face, device, read(ICON_FONT)) : new Map<string, FontSpec>())]);
  for (const [name, spec] of ringFontSpecs(face, specs)) specs.set(name, spec);
  if (baked.size > 0) {
    const lines = [`<fonts ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">`];
    for (const [name, font] of baked) {
      const spec = specs.get(name)!;
      const rawChars = sets.get(name) ?? spec.glyphs ?? "";
      lines.push(`    <!-- ${name}: ${basename(spec.source!)} at ${font.size}px, ${font.glyphs.size} glyphs -->`);
      if ([...rawChars].some((c) => c.codePointAt(0)! >= 0x10000)) {
        lines.push(`    <!-- filter omitted: ${name} needs a glyph above U+FFFF, which the resource compiler's filter parsing cannot represent -->`);
        lines.push(`    <font id="${spec.resourceId}" filename="${font.fnt_name}" antialias="${spec.antialias ? "true" : "false"}" />`);
      } else {
        const chars = escape(rawChars, { '"': "&quot;" });
        lines.push(`    <font id="${spec.resourceId}" filename="${font.fnt_name}" filter="${chars}" antialias="${spec.antialias ? "true" : "false"}" />`);
      }
    }
    lines.push("</fonts>");
    bundle.files.set("fonts/fonts.xml", lines.join("\n") + "\n");
    bundle.fonts = new Map(baked);
  }
  const icon = (device.compiler["launcherIcon"] as { width: number; height: number } | undefined) ?? { width: 40, height: 40 };
  bundle.images.set("drawables/launcher_icon.png", launcherIcon(face, Math.trunc(Number(icon.width)), Math.trunc(Number(icon.height))));
  bundle.files.set("drawables/drawables.xml",
    `<drawables ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">\n`
    + `    <!-- generated at ${icon.width}x${icon.height}, the size ${device.id} asks for -->\n`
    + '    <bitmap id="LauncherIcon" filename="launcher_icon.png" />\n'
    + "</drawables>\n");
  if (face.hasConfig) {
    let supported: boolean;
    try {
      supported = device.hasSymbol(CONFIG_SYMBOL);
    } catch {
      supported = false;
    }
    if (supported) bundle.files.set("configs/watchface.xml", configResource(face));
  }
  return bundle;
}

/** `resources-<device>/configs/watchface.xml`, for a device with the native editor. */
export function configResource(face: Face): string {
  const lines = [`<resources ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">`, "    <watchface-config>"];
  if (face.config_style !== null) {
    lines.push("        <styles>");
    face.config_style.entries.forEach((entry, index) => {
      let attrs = ` id="${index}"`;
      if (entry.name === face.config_style!.default) attrs += ' default="true"';
      if (face.styleLabel(entry) !== null) attrs += ` label="@Strings.${configStyleLabelId(index)}"`;
      lines.push(`            <style${attrs}/>`);
    });
    lines.push("        </styles>");
  }
  if (face.config_data.size > 0) {
    lines.push("        <data>");
    for (const [name, slotId] of configDataIds(face)) {
      const slot = face.config_data.get(name)!;
      if (slot.choices === "any") {
        lines.push(`            <complication id="${slotId}" allowAny="true"/>`);
        continue;
      }
      lines.push(`            <complication id="${slotId}">`);
      for (const choice of slot.choices) {
        const attrs = choice === slot.default ? ' default="true"' : "";
        lines.push(`                <type${attrs}>Complications.${complications.TYPES.get(choice)!.constant}</type>`);
      }
      lines.push("            </complication>");
    }
    lines.push("        </data>");
  }
  for (const [name, axis] of face.config) {
    const tag = axis.axis.resource_tag;
    if (axis.choices === "any") {
      lines.push(`        <${tag} allowAny="true"/>`);
      continue;
    }
    lines.push(`        <${tag}>`);
    axis.choices.forEach((option, index) => {
      let attrs = "";
      if (option.color.equals(axis.default)) attrs += ' default="true"';
      if (option.label !== null) attrs += ` label="@Strings.${configLabelId(name, index)}"`;
      lines.push(`            <color${attrs}>${option.color.asMonkeyc()}</color>`);
    });
    lines.push(`        </${tag}>`);
  }
  lines.push("    </watchface-config>");
  lines.push("</resources>");
  return lines.join("\n") + "\n";
}

/** `[string id, label]` for every labelled `config:` choice and every style entry with a label. */
export function configLabelStrings(face: Face): [string, string][] {
  const out: [string, string][] = [];
  if (face.config_style !== null) {
    face.config_style.entries.forEach((entry, index) => {
      const label = face.styleLabel(entry);
      if (label !== null) out.push([configStyleLabelId(index), label]);
    });
  }
  for (const [name, axis] of face.config) {
    if (axis.choices === "any") continue;
    axis.choices.forEach((option, index) => {
      if (option.label !== null) out.push([configLabelId(name, index), option.label]);
    });
  }
  return out;
}

export function sharedStrings(face: Face): string {
  const lines = [`<strings ${XMLNS} xsi:noNamespaceSchemaLocation="${XSD}">`, `    <string id="AppName">${escape(face.name)}</string>`];
  for (const [stringId, text] of configLabelStrings(face)) lines.push(`    <string id="${stringId}">${escape(text)}</string>`);
  lines.push("</strings>");
  return lines.join("\n") + "\n";
}

/** A plain mark in the design's own colours, at the device's icon size: drawn as Pillow draws it. */
export function launcherIcon(face: Face, width: number, height: number): RgbaImage {
  const background = face.palette.get("bg") ?? new Color(0, 0, 0);
  const accent = ["accent", "text", "fg"].map((n) => face.palette.get(n)).find((c) => c !== undefined) ?? new Color(0xff, 0xff, 0xff);
  const inset = Math.max(1, Math.floor(width / 10));
  const stroke = Math.max(2, Math.floor(width / 12));
  const cx = width / 2, cy = height / 2;
  const ink: [number, number, number] = [accent.r, accent.g, accent.b];
  const draw = (im: Image, fill: [number, number, number], outline: [number, number, number]): void => {
    ellipse(im, [inset, inset, width - inset - 1, height - inset - 1], { outline, fill, width: stroke });
    line(im, [cx, cy, cx, inset + stroke + 1], outline, Math.max(1, Math.floor(stroke / 2)));
    line(im, [cx, cy, width - inset - stroke - 1, cy], outline, Math.max(1, Math.floor(stroke / 2)));
  };
  const colour = newImage(width, height, [0, 0, 0]);
  draw(colour, [background.r, background.g, background.b], ink);
  // Every shape is opaque, so a pixel is opaque wherever any shape reached it;
  // an outline in the fill's own colour is not drawn at all, as Pillow skips it.
  const coverage = newImage(width, height, [0, 0, 0]);
  draw(coverage, [255, 255, 255], background.equals(accent) ? [255, 255, 255] : [255, 255, 254]);
  const data = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    if (coverage.data[i * 4] === 0) continue;
    data[i * 4] = colour.data[i * 4]!;
    data[i * 4 + 1] = colour.data[i * 4 + 1]!;
    data[i * 4 + 2] = colour.data[i * 4 + 2]!;
    data[i * 4 + 3] = 255;
  }
  return { width, height, data };
}

/** Every file of a bundle, by path relative to the project: text, or PNG bytes. */
export function bundleFiles(bundle: ResourceBundle): Map<string, string | Uint8Array> {
  const out = new Map<string, string | Uint8Array>();
  for (const [relative, text] of bundle.files) out.set(`${bundle.directory}/${relative}`, text);
  for (const [relative, image] of bundle.images) out.set(`${bundle.directory}/${relative}`, encodePng(image.width, image.height, image.data, 4));
  for (const font of bundle.fonts.values()) {
    if (font.sheet === null) continue;
    out.set(`${bundle.directory}/fonts/${font.fnt_name}`, toFnt(font));
    out.set(`${bundle.directory}/fonts/${font.png_name}`, encodePng(font.sheet.width, font.sheet.height, font.sheet.bytes, 1));
  }
  return out;
}
