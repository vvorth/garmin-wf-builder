// What a build bakes: every declared font at the device's size, every icon
// font the design needs, and every ring font. The baking half of
// wfb/emit/resources.py; the resource bundle comes with codegen.
import type { Device } from "../devices/device.ts";
import { bake, dilate, inkHeight } from "../fonts/bake.ts";
import type { BakedFont } from "../fonts/bmfont.ts";
import type { FontFile } from "../fonts/files.ts";
import * as icons from "../icons.ts";
import { type Face, FontSpec } from "../ir/model.ts";
import { comparePoints } from "../kinds/data.ts";
import * as kinds from "../kinds/index.ts";
import { roundHalfEven } from "../py.ts";
import * as units from "../units.ts";

/** Reads a font file a design names (`FontSpec.source`) or the icon font. */
export type FontReader = (path: string) => FontFile;

/** The icon font, relative to the repository. */
export const ICON_FONT = "wfb/assets/icons/SymbolsNerdFont-Regular.ttf";

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
export function bakeFonts(face: Face, device: Device, read: FontReader): Map<string, BakedFont> {
  const sets = glyphSet(face);
  const baked = new Map<string, BakedFont>();
  for (const [name, spec] of face.fonts) {
    if (spec.isVector) continue; // drawn from the device's own resident face
    baked.set(name, bake(read(spec.source!), {
      name, size: spec.pixelSize(device.minorRadius), glyphs: sets.get(name) || "0123456789",
      antialias: spec.antialias, monospace: spec.monospace, align: spec.align,
    }));
  }
  const specs = [...kinds.faceTextRuns(face)].some(([, run]) => run.icon !== null) ? iconFontSpecs(face, device, read(ICON_FONT)) : new Map();
  for (const [name, spec] of specs) {
    baked.set(name, bake(read(spec.source!), { name, size: spec.pixelSize(device.minorRadius), glyphs: spec.glyphs!, antialias: spec.antialias }));
  }
  // Last: each ring font is dilated from its base's own sheet.
  for (const [name, [base, glyphs, width]] of kinds.ringFonts(face)) {
    baked.set(name, dilate(baked.get(base)!, { name, glyphs: [...glyphs].sort(comparePoints).join(""), width }));
  }
  return baked;
}
