// Assemble a complete, compilable Connect IQ project from a resolved design.
// Writing it to disk is the Node host's job.
import { computeGuards, lacksComplicationType } from "../availability.ts";
import * as complications from "../complications.ts";
import type { Device } from "../devices/device.ts";
import type { BakedFont } from "../fonts/bmfont.ts";
import type { Face } from "../ir/model.ts";
import * as kinds from "../kinds/index.ts";
import { resolve, type ResolvedFace } from "../layout.ts";
import { splitlines } from "../py.ts";
import * as jungle from "./jungle.ts";
import * as manifest from "./manifest.ts";
import { emitApp, emitIconGlyphs, emitPalette, iconGlyphEntries } from "./monkeyc/app.ts";
import { dataElements, editorSlots, needsDelegate, type SourceFile } from "./monkeyc/common.ts";
import * as configMenu from "./monkeyc/config_menu.ts";
import * as conditionText from "./monkeyc/condition_text.ts";
import { emitSlotDrawable, emitSlotText } from "./monkeyc/data.ts";
import { emitDelegate } from "./monkeyc/delegate.ts";
import { emitLayout } from "./monkeyc/layout_constants.ts";
import * as slotScale from "./monkeyc/slot_scale.ts";
import { traced } from "./monkeyc/trace.ts";
import { emitView } from "./monkeyc/view.ts";
import { bakeFonts, buildBundle, bundleFiles, type FontReader, type ResourceBundle, sharedStrings } from "./resources.ts";
import * as strhash from "./strhash.ts";
import * as usage from "./usage.ts";

/** A shared source that came out differently from another target's resolved face. */
export interface Divergence {
  path: string;
  first: string;
  other: string;
  first_line: string;
  other_line: string;
}

/** A complication type constant named where a target lacking it could reach it: a build error each. */
export interface UnguardedType {
  path: string;
  line: number;
  constant: string;
  device: string;
}

export class GeneratedProject {
  readonly face: Face;
  readonly devices: Device[];
  sources: SourceFile[] = [];
  bundles: ResourceBundle[] = [];
  manifest_text = "";
  jungle_text = "";
  strings_text = "";
  barrel: string[] = [];
  resolved = new Map<string, ResolvedFace>();
  /** String literals that would still share a monkeyc label: a build error each. */
  string_collisions: strhash.Collision[] = [];
  /** Shared sources that differ between targets: a build error each. */
  divergences: Divergence[] = [];
  /** Complication type constants named outside a `has` check naming them, where some target lacks them. */
  unguarded_types: UnguardedType[] = [];

  constructor(face: Face, devices: Device[]) {
    this.face = face;
    this.devices = devices;
  }

  /** The project-level files and every generated Monkey C source, by path. */
  generatedText(): Map<string, string> {
    const out = new Map<string, string>([
      ["manifest.xml", this.manifest_text],
      ["monkey.jungle", this.jungle_text],
      ["resources/strings/strings.xml", this.strings_text],
    ]);
    for (const source of this.sources) out.set(source.path, source.text);
    return out;
  }

  /** Every file of the project, by path: text, or PNG bytes. */
  files(): Map<string, string | Uint8Array> {
    const out = new Map<string, string | Uint8Array>(this.generatedText());
    for (const name of this.barrel) out.set(`runtime-lib/${name}`, usage.RUNTIME_LIB.get(name)!);
    for (const bundle of this.bundles) for (const [path, content] of bundleFiles(bundle)) out.set(path, content);
    return out;
  }
}

/**
 * Build the project in memory. `resolved` (`resolveAll`'s result) is used
 * as is; a device it does not cover is resolved here from `baked`, or from
 * fonts baked through `read`.
 */
export function generate(face: Face, devices: Device[], read: FontReader,
  { baked = null, resolved = null, profile = null, trace = false }: {
    baked?: ReadonlyMap<string, Map<string, BakedFont>> | null; resolved?: ReadonlyMap<string, ResolvedFace> | null; profile?: number | null;
    trace?: boolean;
  } = {}): GeneratedProject {
  const project = new GeneratedProject(face, devices);
  const perDevice = new Map<string, Device>();
  const guards = computeGuards(face, devices);
  project.sources.push(emitApp(face, guards));
  if (face.palette.size > 0) project.sources.push(emitPalette(face));
  project.manifest_text = manifest.render(face, devices);
  project.jungle_text = jungle.render(face, devices);
  project.strings_text = sharedStrings(face, devices);
  for (const device of devices) {
    let deviceResolved = resolved?.get(device.id);
    if (deviceResolved === undefined) {
      const fonts = baked?.get(device.id) ?? bakeFonts(face, device, read);
      deviceResolved = resolve(face, device, fonts);
    }
    project.resolved.set(device.id, deviceResolved);
    const layout = emitLayout(deviceResolved, guards, profile);
    perDevice.set(layout.path, device);
    project.sources.push(layout);
    project.bundles.push(buildBundle(face, device, deviceResolved.fonts, read));
  }
  const needsIconGlyphs = [...project.resolved.values()].some((r) => kinds.placedTextRuns(r.items, face).some(([, run]) => run.glyph_table !== null));
  if (needsIconGlyphs) project.sources.push(emitIconGlyphs(face));
  project.sources.push(checkShared(project, (r) => emitView(r, guards, profile)));
  if (editorSlots(face).length > 0) project.sources.push(emitSlotDrawable(face, guards));
  if (dataElements(face).length > 0) project.sources.push(emitSlotText(face, guards));
  if (slotScale.slotGauges(face).length > 0 || slotScale.autoScaleGauges(face).length > 0) {
    const [names, apps] = slotScale.slotScaleTypes(face);
    project.sources.push(slotScale.emitSlotScale(face, names, apps, guards));
  }
  if (needsDelegate(face)) project.sources.push(checkShared(project, (r) => emitDelegate(r, guards)));
  if (guards.config_menu) project.sources.push(configMenu.emitDelegates(face));
  const conditionTables = conditionText.conditionTables(project.sources.map((s) => s.text));
  if (conditionTables.size > 0) project.sources.push(conditionText.emitConditionText(face, conditionTables));
  if (trace) project.sources = project.sources.map(traced);
  project.barrel = [...usage.barrelModules(project.sources.map((s) => s.text))].sort();
  avoidStringLabelCollisions(project);
  for (const [path, text] of programTexts(project)) {
    const device = perDevice.get(path);
    project.unguarded_types.push(...unguardedTypes(path, text, device !== undefined ? [device] : devices));
  }
  return project;
}

const TYPE_CONSTANT = /Complications\.(COMPLICATION_TYPE_[A-Z0-9_]+)/g;

/**
 * Every reference in `text` to a complication type constant some device in
 * `devices` has the module but not the constant for, that is not covered by a
 * `has :<constant>` earlier in its own statement or in an enclosing `if`'s
 * condition. The VM resolves the constant when it reaches it and throws
 * Symbol Not Found on that device (docs/lore/platform-constraints.md, 6d);
 * the module check monkeyc accepts does not stop it. Textual, over the
 * printed source: comments and strings are skipped, each `{` remembers the
 * header before it, and only an `if` header's condition counts.
 */
export function unguardedTypes(path: string, text: string, devices: readonly Device[]): UnguardedType[] {
  const byConstant = new Map([...complications.TYPES.values()].map((t) => [t.constant, t]));
  const lacking = (constant: string): Device | undefined => {
    const type = byConstant.get(constant);
    return type === undefined ? undefined : devices.find((d) => lacksComplicationType(d, type));
  };
  if (![...text.matchAll(TYPE_CONSTANT)].some((m) => lacking(m[1]!) !== undefined)) return [];
  const out: UnguardedType[] = [];
  const headers: string[] = [];
  let statement = "";
  let line = 1;
  let i = 0;
  const covered = (constant: string): boolean => {
    const check = new RegExp(`\\bhas\\s*:${constant}\\b`);
    return check.test(statement) || headers.some((h) => /^(else\s+)?if\b/.test(h.trim()) && check.test(h));
  };
  while (i < text.length) {
    const ch = text[i]!;
    if (ch === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      continue;
    }
    if (ch === "/" && text[i + 1] === "*") {
      const end = text.indexOf("*/", i + 2);
      const stop = end < 0 ? text.length : end + 2;
      for (; i < stop; i++) if (text[i] === "\n") line++;
      continue;
    }
    if (ch === '"' || ch === "'") {
      i++;
      while (i < text.length && text[i] !== ch && text[i] !== "\n") i += text[i] === "\\" ? 2 : 1;
      i++;
      continue;
    }
    if (ch === "\n") line++;
    if (ch === "{") {
      headers.push(statement);
      statement = "";
    } else if (ch === "}") {
      headers.pop();
      statement = "";
    } else if (ch === ";") {
      statement = "";
    } else {
      const match = ch === "C" && text.startsWith("Complications.COMPLICATION_TYPE_", i) && !/[A-Za-z0-9_]/.test(text[i - 1] ?? "")
        ? /^Complications\.(COMPLICATION_TYPE_[A-Z0-9_]+)/.exec(text.slice(i, i + 80)) : null;
      if (match !== null) {
        const constant = match[1]!;
        const device = lacking(constant);
        if (device !== undefined && !covered(constant)) out.push({ path, line, constant, device: device.id });
        statement += match[0];
        i += match[0].length;
        continue;
      }
      statement += ch;
    }
    i++;
  }
  return out;
}

/** Emit one shared source from every target, recording a `Divergence` for each that differs from the first. */
function checkShared(project: GeneratedProject, emit: (r: ResolvedFace) => SourceFile): SourceFile {
  const ids = project.devices.map((d) => d.id);
  const source = emit(project.resolved.get(ids[0]!)!);
  for (const other of ids.slice(1)) {
    const text = emit(project.resolved.get(other)!).text;
    if (text === source.text) continue;
    const mine = splitlines(source.text), theirs = splitlines(text);
    let index = 0;
    while (index < Math.min(mine.length, theirs.length) && mine[index] === theirs[index]) index++;
    project.divergences.push({
      path: source.path, first: ids[0]!, other,
      first_line: index < mine.length ? mine[index]! : "(end of file)",
      other_line: index < theirs.length ? theirs[index]! : "(end of file)",
    });
  }
  return source;
}

/** Every Monkey C source monkeyc assembles into one program. */
function programTexts(project: GeneratedProject): Map<string, string> {
  const texts = new Map(project.sources.map((s) => [s.path, s.text]));
  for (const name of project.barrel) texts.set(`runtime-lib/${name}`, usage.RUNTIME_LIB.get(name)!);
  return texts;
}

/** Keep two string literals from sharing a monkeyc label: an `IconGlyphs` glyph is rebuilt at runtime instead. */
function avoidStringLabelCollisions(project: GeneratedProject): void {
  let found = strhash.collisions(programTexts(project));
  if (found.length === 0) return;
  const index = project.sources.findIndex((s) => s.path === "source/IconGlyphs.mc");
  if (index >= 0) {
    const colliding = new Set(found.flatMap((c) => [...c.strings.keys()]));
    const entries = iconGlyphEntries(project.face);
    const viaChar = new Set([...entries].filter(([, glyph]) => colliding.has(glyph)).map(([key]) => key));
    if (viaChar.size > 0) {
      project.sources[index] = emitIconGlyphs(project.face, viaChar);
      found = strhash.collisions(programTexts(project));
    }
  }
  project.string_collisions = found;
}
