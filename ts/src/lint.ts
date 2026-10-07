// Build-time checks, with explicit confidence (ADR 0008)..
//
// The linter is this framework's main claim to being better than
// hand-writing, so its credibility matters more than its coverage. Every
// check states what it rests on, and the two that cannot be exact (memory
// and the partial-update power budget) say so in their own message. Only
// `checkMemory` needs a real build.
import * as availability from "./availability.ts";
import * as catalog from "./catalog.ts";
import * as complications from "./complications.ts";
import * as series from "./series.ts";
import type { IntBox } from "./units.ts";
import { compareVersions, Device, DeviceError } from "./devices/device.ts";
import { Bag, Diagnostic, getCloseMatches, type Severity, type Span } from "./diagnostics.ts";
import { authoredDrawOrder, CONFIG_SYMBOL, type Curve, type Element, type Face, type FontSpec, Graph, neverTogether, PatternElement, slotOf, walkElements } from "./ir/model.ts";
import * as kinds from "./kinds/index.ts";
import * as expr from "./expr.ts";
import type { Expression } from "./ir/model.ts";
import {
  BEZEL_MARGIN, HIDDEN_BY_FONT, insideScreen, insideVisibleAreaFor, isFullBleed, type Placed, PlacedGauge, PlacedPattern, PlacedText, ResolvedFace,
  visibleReach,
} from "./layout.ts";
import { type Color, Color as ColorClass, hasPaletteRule, LUMINANCE_WEIGHTS, srgbChannelToLinear } from "./palette.ts";
import { deepEqual, formatFixed, quoted, roundHalfEven, truthy } from "./py.ts";
import * as aodMask from "./aod_mask.ts";
import { PyFloat } from "./edit/yaml.ts";
import type { ExprValue } from "./expr.ts";
import { type PreviewOptions, previewOptions, render } from "./preview.ts";
import { ellipse, type Image, image as newImage } from "./raster/pillow.ts";
import { visibleMask } from "./visible_area.ts";
import { ringGroups } from "./ir/rings.ts";

/** Checks an author may silence with `lint: {allow: [...], reason: "..."}`. */
export const SUPPRESSIBLE: ReadonlySet<string> = new Set([
  "palette-dither", "palette-mono", "safe-area", "text-overflow", "contrast",
  "partial-update-budget", "hold-unsupported", "hold-overlap", "api-gated",
  "dead-element", "graphics-pool", "antialias-dither", "static-overlap",
  "config-unsupported", "duplicate-style", "unreachable-layout",
  "sub-pixel-length", "font-unavailable", "off-screen", "text-outline-interior",
  "aod-unreachable", "aod-empty", "aod-burn-in", "override-unreachable",
]);

/** Every diagnostic code emitted anywhere in this compiler. */
export const ALL_CODES: ReadonlySet<string> = new Set([
  "antialias-dither",
  "aod", "aod-unreachable", "aod-empty", "aod-burn-in",
  "api-gated", "api-gated-unguardable",
  "color", "color-scheme", "complication-slot",
  "config", "config-unsupported",
  "contrast", "dead-element",
  "element-mapping",
  "devices", "duplicate-id", "duplicate-style", "element", "expression",
  "font", "font-unavailable", "format", "format-version", "graph", "graphics-pool", "hands",
  "icon", "io",
  "layouts", "lint-allow", "memory",
  "metrics", "missing-glyph", "monkeyc", "off-screen", "palette",
  "hold-overlap", "hold-unsupported",
  "hold-auto-ambiguous", "hold-auto-unresolved",
  "palette-dither", "palette-mono", "partial-update", "partial-update-budget", "pattern",
  "progress-segments",
  "pattern-step", "permission",
  "on-hold", "overrides", "override-unreachable", "raw-color", "reserved", "safe-area", "schema", "sdk",
  "shared-source",
  "shared-view", "source-renamed",
  "sub-pixel-length", "target",
  "static", "static-overlap", "string-label", "subscreen",
  "text-antialias", "text-curve", "outline", "text-outline-interior",
  "unreachable-layout",
  "text-overflow", "toolchain", "type", "units", "when-absent", "yaml",
]);

/** Python's `sorted()` of strings: by code point. */
export function sorted<T>(items: Iterable<T>, key: (item: T) => string = (item) => String(item)): T[] {
  return [...items].sort((a, b) => {
    const x = [...key(a)].map((c) => c.codePointAt(0)!), y = [...key(b)].map((c) => c.codePointAt(0)!);
    for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i]! - y[i]!;
    return x.length - y.length;
  });
}

/** A diagnostic, as `Diagnostic(severity, code, message, span, notes=..., confidence=...)`. */
function diag(severity: Severity, code: string, message: string, span: Span | null = null,
  { notes = [], confidence = null }: { notes?: string[]; confidence?: string | null } = {}): Diagnostic {
  return new Diagnostic(severity, code, message, span, { notes, confidence });
}

export function checkOverrideSelectors(face: Face, installed: Iterable<string>, devices: readonly Device[], bag: Bag): void {
  const known = new Set(installed);
  const shapes = new Set(devices.map((d) => d.shape));
  const ids = new Set(devices.map((d) => d.id));
  for (const element of walkElements(face.elements)) {
    for (const [selector, span] of element.override_selectors) {
      let reachable: boolean;
      if (selector.startsWith("shape:")) {
        reachable = shapes.has(selector.slice("shape:".length));
      } else if (!known.has(selector)) {
        bag.error("overrides", `${element.id}: 'overrides:' names ${quoted(selector)}, which is not an installed device`, span, {
          notes: ["'wfb devices' lists the installed devices; a shape is written 'shape:round', 'shape:rectangle', "
            + "'shape:semi-octagon' or 'shape:semi-round'"],
        });
        continue;
      } else {
        reachable = ids.has(selector);
      }
      if (reachable) continue;
      emitForUsers(bag, [element], diag("warning", "override-unreachable",
        `${element.id}: no device in this build matches the override ${quoted(selector)}, so it changes nothing`, span, {
          notes: ["building for: " + sorted(ids).join(", ")],
          confidence: "exact -- the devices this build resolves",
        }));
    }
  }
}

/** Every check that depends on the design alone: run once per build, before any target is resolved. */
export function runDesign(face: Face, bag: Bag): void {
  for (const check of DESIGN_CHECKS) check(face, bag);
}

/** Everything computable from resolved geometry on one device; an item the device does not draw is not checked. */
export function run(resolved: ResolvedFace, bag: Bag): void {
  resolved = resolved.drawnOnly();
  for (const check of DEVICE_CHECKS) check(resolved, bag);
  for (const warning of resolved.warnings) {
    bag.note("metrics", warning.message, warning.span, { confidence: "not checked -- no metrics available" });
  }
}

/** `code` is suppressible and some owner's `lint: {allow:}` accepted it. */
export function suppressed(code: string, allows: Iterable<ReadonlySet<string>>): boolean {
  if (!SUPPRESSIBLE.has(code)) return false;
  for (const allow of allows) if (allow.has(code)) return true;
  return false;
}

/** A diagnostic about one placed element, unless it accepted its code. */
function emit(bag: Bag, placed: Placed, d: Diagnostic): void {
  emitForUsers(bag, [placed.element], d);
}

/** A diagnostic about a shared declaration, unless any element using it accepted its code. */
function emitForUsers(bag: Bag, users: Iterable<Element>, d: Diagnostic): void {
  if (!suppressed(d.code, [...users].map((u) => u.allLintAllow))) bag.add(d);
}

// -- permissions --

export function checkPermissions(face: Face, bag: Bag): void {
  for (const element of face.walk()) {
    for (const expression of element.expressions()) {
      for (const path of expression.sources) {
        const source = catalog.get(path);
        if (source === undefined) continue;
        for (const permission of source.permissions) {
          if (catalog.WATCHFACE_PERMISSIONS.has(permission)) continue;
          bag.error("permission", `${element.id}: ${quoted(path)} needs the ${quoted(permission)} permission, which a watch face may not declare`,
            expression.span ?? element.span, {
              notes: [
                "the SDK's permission table leaves the Watch Face column blank for this one (Core_Topics/Manifest_and_Permissions)",
                "legal for a watch face: " + sorted(catalog.WATCHFACE_PERMISSIONS).join(", "),
              ],
              confidence: "exact -- the SDK's own permission table",
            });
        }
      }
    }
  }
}

export function checkDuplicateStyle(face: Face, bag: Bag): void {
  const axis = face.config_style;
  if (axis === null) return;
  const seen = new Map<string, (typeof axis.entries)[number]>();
  for (const entry of axis.entries) {
    const key = JSON.stringify([entry.layout, entry.colors]);
    if (!seen.has(key)) seen.set(key, entry);
    const first = seen.get(key)!;
    if (first === entry) continue;
    if (suppressed("duplicate-style", [entry.lint_allow])) continue;
    bag.warning("duplicate-style", `config.style.choices.${entry.name}: the same combination as '${first.name}' -- indistinguishable on the wrist`,
      entry.span, {
        notes: [
          `both resolve to colors: ${quoted(entry.colors)}` + (entry.layout !== null ? `, layout: ${quoted(entry.layout)}` : ""),
          "set 'lint: {allow: [duplicate-style], reason: ...}' on "
          + `'${entry.name}' to accept it -- e.g. two labels while iterating on the same look`,
        ],
      });
  }
}

export function checkUnreachableLayout(face: Face, bag: Bag): void {
  if (face.layouts.length === 0) return;
  const referenced = new Set<string>();
  if (face.config_style !== null) for (const e of face.config_style.entries) if (e.layout !== null) referenced.add(e.layout);
  for (const name of face.layouts) {
    if (referenced.has(name)) continue;
    const decl = face.layout_decls.get(name)!;
    if (suppressed("unreachable-layout", [decl.lint_allow])) continue;
    bag.warning("unreachable-layout", `layouts.${name}: no 'config: style:' entry names it as its 'layout:' -- it can never be drawn`,
      decl.span, {
        notes: [
          "its elements, fonts and code still ship in the .prg -- content is not free even though a style entry is",
          "name it from a 'config: style:' entry's 'layout:', or delete the layout",
          `set 'lint: {allow: [unreachable-layout], reason: ...}' on 'layouts.${name}' to accept it`,
        ],
      });
  }
}

export function checkSharedViewTargets(resolved: ReadonlyMap<string, ResolvedFace>, bag: Bag): void {
  const devices = [...resolved.values()].map((rf) => rf.device);
  const mip = sorted(devices.filter((d) => !d.isAmoled).map((d) => d.id));
  if (mip.length === 0 || mip.length === devices.length) return;
  bag.note("shared-view",
    `the AMOLED always-on frame ('aod:') is compiled into every target, and never runs on the MIP one${mip.length > 1 ? "s" : ""}: ${mip.join(", ")}`,
    null, {
      notes: [
        "the generated view is one file shared by every target; only Layout.mc is per device",
        "each MIP target's measured memory includes it; build the MIP targets on their own (-d) to leave it out",
      ],
      confidence: "exact -- device displayType",
    });
}

export function checkSubscreenAvailability(face: Face, resolved: ReadonlyMap<string, ResolvedFace>, bag: Bag): void {
  const lacking = sorted([...resolved].filter(([, rf]) => rf.device.subscreen === null).map(([id]) => id));
  if (lacking.length === 0) return;
  for (const element of face.elements) {
    if (!element.inSubscreen) continue;
    const span = element.span;
    if (element.unsupported === "hide") {
      bag.note("subscreen", `${element.id}: not drawn on ${lacking.join(", ")} -- no subscreen window there ('unsupported: hide')`, span, {
        confidence: "exact -- the device files' subscreen box and WatchUi.getSubscreen",
      });
      continue;
    }
    bag.error("subscreen", `${element.id}: 'at: {anchor: subscreen}', but ${lacking.join(", ")}${lacking.length === 1 ? " has" : " have"} no subscreen window`,
      span, {
        notes: [
          "the subscreen is the Instinct family's round window; a device has one when its simulator.json declares "
          + "'subscreen.location' and its symbol table has WatchUi.getSubscreen",
          `set 'unsupported: hide' on '${element.id}' to leave it out there, or drop the device from 'targets:'`,
        ],
        confidence: "exact -- the device files' subscreen box and WatchUi.getSubscreen",
      });
  }
}

export function checkVectorFontAvailability(face: Face, resolved: ReadonlyMap<string, ResolvedFace>, bag: Bag): void {
  const placedByDevice = new Map([...resolved].map(([id, rf]) => [id,
    new Map(rf.items.filter((p) => (rf.hidden.get(p.id) ?? HIDDEN_BY_FONT) === HIDDEN_BY_FONT).map((p) => [p.id, p]))]));
  for (const [element, run] of kinds.faceTextRuns(face)) {
    const spec = face.fonts.get(run.font);
    if (run.aod_only || spec === undefined || !spec.isVector) continue;
    const what = run.label;
    const failing = sorted([...placedByDevice].filter(([, byId]) => byId.has(element.id)
      && !kinds.placedFont(byId.get(element.id)!, run).available).map(([id]) => id));
    if (failing.length === 0) continue;
    const effective = run.unsupported || spec.unsupported || "error";
    const requested = (spec.face ?? []).join(", ");
    if (effective === "error") {
      bag.error("font-unavailable", `${what}: 'font: font.${run.font}' has no usable face on ${failing.join(", ")}`, run.span, {
        notes: [
          `requested face(s), in author order: ${requested}`,
          ...failing.map((id) => vectorFontFailureReason(resolved.get(id)!.device, spec, run.curve)),
          `set 'unsupported: hide' on 'font.${run.font}' or on '${what}' to let it disappear on a target that cannot `
          + "draw it, drop the device from 'targets:', or add a face it actually publishes",
        ],
        confidence: "exact -- resolved per-device gates 1-3",
      });
      continue;
    }
    if (suppressed("font-unavailable", [element.allLintAllow])) continue;
    bag.warning("font-unavailable", `${what}: will not draw on ${failing.join(", ")} -- 'font: font.${run.font}' has no usable face there`,
      run.span, {
        notes: [
          `requested face(s), in author order: ${requested}`,
          `set 'lint: {allow: [font-unavailable], reason: ...}' on '${what}' to accept it`,
        ],
        confidence: "exact -- resolved per-device gates 1-3",
      });
  }
}

function vectorFontFailureReason(device: Device, spec: FontSpec, curve: Curve | null): string {
  if (!device.hasSymbol(Device.VECTOR_FONT_SYMBOL)) {
    return `${device.id}: has no ${quoted(Device.VECTOR_FONT_SYMBOL)} at all (gate 1) -- no device-resident face, of any name, can ever be drawn here`;
  }
  if (curve !== null) {
    const symbol = curve.style === "angled" ? Device.DRAW_ANGLED_TEXT_SYMBOL : Device.DRAW_RADIAL_TEXT_SYMBOL;
    if (!device.hasSymbol(symbol)) {
      return `${device.id}: has ${quoted(Device.VECTOR_FONT_SYMBOL)} but not ${quoted(symbol)} (gate 1) -- 'curve: {style: ${curve.style}}' `
        + "cannot draw here even though a plain, upright 'face:' text could";
    }
  }
  const published = device.scalableFaces.length > 0 ? device.scalableFaces.join(", ") : "none";
  return `${device.id}: publishes ${published} (gates 2/3) -- none of the requested face(s) is in that list`;
}

function checkOneLintAllow(bag: Bag, what: string, span: Span | null, code: string): void {
  if (SUPPRESSIBLE.has(code)) return;
  if (ALL_CODES.has(code)) {
    bag.error("lint-allow", `${what}: ${quoted(code)} is a real diagnostic code, but it is deliberately not suppressible`, span, {
      notes: [
        "the hard-platform-limit checks stay unsuppressible on purpose: silencing one would produce a face that does not work",
        "suppressible codes: " + sorted(SUPPRESSIBLE).join(", "),
      ],
      confidence: "exact -- SUPPRESSIBLE is this file's own registry",
    });
    return;
  }
  const near = getCloseMatches(code, ALL_CODES, 1, 0.6);
  const notes = ["suppressible codes: " + sorted(SUPPRESSIBLE).join(", ")];
  if (near.length > 0) notes.unshift(`did you mean ${quoted(near[0])}?`);
  bag.error("lint-allow", `${what}: ${quoted(code)} is not a diagnostic code this compiler emits`, span, {
    notes, confidence: "exact -- SUPPRESSIBLE is this file's own registry",
  });
}

export function checkLintAllow(face: Face, bag: Bag): void {
  for (const element of face.walk()) for (const code of sorted(element.lint_allow)) checkOneLintAllow(bag, element.id, element.span, code);
  if (face.config_style !== null) {
    for (const entry of face.config_style.entries) {
      for (const code of sorted(entry.lint_allow)) checkOneLintAllow(bag, `config.style.choices.${entry.name}`, entry.span, code);
    }
  }
  for (const name of face.layouts) {
    const decl = face.layout_decls.get(name)!;
    for (const code of sorted(decl.lint_allow)) checkOneLintAllow(bag, `layouts.${name}`, decl.span, code);
  }
}

// -- palette legality --

/** Elements with a colour whose author text is exactly `token`. */
function usersOf(face: Face, token: string): Element[] {
  return face.walk().filter((element) => element.colorRoles().some((r) => r.expression.text === token));
}

function emitDither(bag: Bag, users: Element[], device: Device, subject: string, nearestNote: string, token: string): void {
  const colors = device.displayColors;
  const code = colors === 2 ? "palette-mono" : "palette-dither";
  const suppressNote = users.length > 0
    ? `set 'lint: {allow: [${code}], reason: ...}' on an element that draws '${token}' (${users.map((u) => u.id).join(", ")}) to keep it`
    : `no element draws exactly '${token}' (as 'color:', 'track_color:', 'icon: {color:}', 'outline:' or an 'aod:' override), `
      + `so there is nowhere to put 'lint: {allow: [${code}]}' for it`;
  const message = `${subject} not one of ${device.id}'s ${colors} colours`;
  if (colors === 2) {
    emitForUsers(bag, users, diag("warning", "palette-mono", `${message}; only black and white are safe`, null, {
      notes: [
        nearestNote,
        "the panel shows black and one 'on' colour, and its compiler.json palette is exactly #000000 and #FFFFFF; how the "
        + "firmware maps any other colour is unverified, so the nearest shown is a guess (by contrast ratio)",
        suppressNote,
      ],
      confidence: "exact that the colour is outside the palette; its mapping unverified",
    }));
  } else {
    emitForUsers(bag, users, diag("warning", "palette-dither", `${message} and will be dithered`, null, {
      notes: [
        nearestNote,
        "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is dithered by the firmware and looks grainy",
        suppressNote,
      ],
      confidence: "exact -- device display_colors",
    }));
  }
}

export function checkPalette(resolved: ResolvedFace, bag: Bag): void {
  const colors = resolved.device.displayColors;
  if (!hasPaletteRule(colors)) {
    const size = colors === null ? "unknown" : `${colors} colours, which has no known rule`;
    bag.note("palette-dither", `${resolved.device.id}: palette size is ${size}, so colour legality is not checked`, null, { confidence: "not checked" });
    return;
  }
  for (const [name, color] of resolved.face.palette) {
    if (color.isPaletteLegal(colors)) continue;
    const token = `color.${name}`;
    emitDither(bag, usersOf(resolved.face, token), resolved.device, `${token} = ${color} is`,
      `nearest legal colour: ${color.nearestLegal(colors)}`, token);
  }
}

export function checkAntialiasPalette(resolved: ResolvedFace, bag: Bag): void {
  const colors = resolved.device.displayColors;
  if (colors !== 64) return;
  const users = resolved.items.filter((p) => kinds.forPlaced(p).antialiased && p.element.resolved_antialias);
  if (users.length === 0) return;
  emit(bag, users[0]!, diag("warning", "antialias-dither",
    `${resolved.device.id}: anti-aliased primitive drawing is enabled, and this device's panel shows only ${colors} colours `
    + "-- every soft edge it draws will be dithered", users[0]!.element.span, {
      notes: [
        "each channel must be 0x00, 0x55, 0xAA or 0xFF; anti-aliasing blends toward values in between by construction, "
        + "so this is not avoidable while antialias: stays true here",
        `${users.length} element(s) draw anti-aliased on ${resolved.device.id}: ` + sorted(users.map((p) => p.id)).join(", "),
        `set 'lint: {allow: [antialias-dither], reason: ...}' on '${users[0]!.id}' to accept it`,
      ],
      confidence: "exact -- device display_colors",
    }));
}

function checkDeclaredColors(resolved: ResolvedFace, bag: Bag, token: string, declared: [string, Color][], shown: string | null = null): void {
  const colors = resolved.device.displayColors;
  const bad = declared.filter(([, c]) => !c.isPaletteLegal(colors));
  if (bad.length === 0) return;
  const nearest = bad.map(([label, c]) => `${label}${c} -> ${c.nearestLegal(colors)}`).join(", ");
  emitDither(bag, usersOf(resolved.face, token), resolved.device, `${shown || token}: ${bad.length} declared colour(s) are`,
    `off-palette -> nearest legal: ${nearest}`, token);
}

export function checkConfigPalette(resolved: ResolvedFace, bag: Bag): void {
  if (!hasPaletteRule(resolved.device.displayColors)) return;
  for (const [name, entry] of resolved.face.config) {
    const declared: Color[] = [entry.default];
    if (entry.choices !== "any") declared.push(...entry.choices.map((c) => c.color));
    checkDeclaredColors(resolved, bag, `color.${entry.role}`, declared.map((c): [string, Color] => ["", c]), `config.${name}`);
  }
}

export function checkColorSchemePalette(resolved: ResolvedFace, bag: Bag): void {
  if (!hasPaletteRule(resolved.device.displayColors)) return;
  const axis = resolved.face.config_style;
  if (axis === null) return;
  const defaultEntry = axis.defaultEntry;
  if (defaultEntry.colors === null) return;
  const schemes = resolved.face.color_scheme;
  const roles = sorted(schemes.get(defaultEntry.colors)!.colors.keys());
  const schemeNames = [...new Set(axis.entries.filter((e) => e.colors !== null).map((e) => e.colors!))];
  for (const role of roles) {
    checkDeclaredColors(resolved, bag, `color.${role}`,
      schemeNames.map((name): [string, Color] => [`theme.schemes.${name}.colors.${role}=`, schemes.get(name)!.colors.get(role)!]));
  }
}

/** `probe()` against the device's symbol table, or a "not checked" note and `null` when it is unavailable. */
function probeSymbols<T>(bag: Bag, device: Device, code: string, what: string, probe: () => T): T | null {
  try {
    return probe();
  } catch (error) {
    if (!(error instanceof DeviceError)) throw error;
    bag.note(code, `${device.id}: no symbol table, so ${what} is not checked`, null, {
      confidence: "not checked -- the device's api.debug.xml is unavailable",
    });
    return null;
  }
}

function axisName(token: string): string {
  return token.startsWith("config.data.") ? `slot ${quoted(token.slice("config.data.".length))}` : token;
}

export function checkConfigSupport(resolved: ResolvedFace, bag: Bag): void {
  const face = resolved.face;
  if (!face.hasConfig) return;
  const device = resolved.device;
  const available = probeSymbols(bag, device, "config-unsupported", "on-device config support", () => device.hasSymbol(CONFIG_SYMBOL));
  if (available !== false) return;
  if (probeSymbols(bag, device, "config-unsupported", "the settings menu", () => device.hasSymbol(availability.SETTINGS_MENU_SYMBOL)) !== false) return;

  const colourTokens = sorted(face.config.keys()).map((name) => `color.${face.config.get(name)!.role}`);
  let nonDefaultEntries: string[] = [];
  let defaultStyle = "";
  if (face.config_style !== null) {
    const defaultEntry = face.config_style.defaultEntry;
    if (defaultEntry.colors !== null) {
      colourTokens.push(...sorted(face.color_scheme.get(defaultEntry.colors)!.colors.keys()).map((role) => `color.${role}`));
    }
    defaultStyle = face.config_style.default;
    nonDefaultEntries = face.config_style.entries.filter((e) => e.name !== defaultStyle).map((e) => e.name);
  }
  const slotTokens = sorted(face.config_data.keys()).map((name) => `config.data.${name}`);
  const namesList = [...colourTokens, ...slotTokens];
  if (namesList.length === 0 && nonDefaultEntries.length === 0) return;
  const names = namesList.map(axisName).join(", ");
  const hasComplications = slotTokens.length === 0 || device.hasModule("Complications");
  const keptNamesList = hasComplications ? namesList : colourTokens;
  const absentSlotTokens = hasComplications ? [] : slotTokens;
  const users = colourTokens.flatMap((token) => usersOf(face, token));
  users.push(...face.walk().filter((element) => { const s = slotOf(element); return s !== null && face.config_data.has(s); }));
  const notes: string[] = [];
  if (keptNamesList.length > 0) {
    notes.push(slotTokens.length > 0 && hasComplications
      ? "the face still works: every element bound to a 'config:' colour, or drawing a 'config: slots:' slot, simply keeps "
        + "its declared default forever on this device"
      : "the face still works: every element bound to a 'config:' colour simply keeps its declared default forever on this device");
  }
  if (absentSlotTokens.length > 0) {
    notes.push("a slot's own declared default is itself read through Toybox.Complications, which this device also lacks -- so "
      + absentSlotTokens.map((t) => t.slice("config.data.".length)).join(", ")
      + " show their absent state here instead of any declared default (see the 'api-gated' warning for the same fact)");
  }
  notes.push("the native editor is fēnix 8 and newer only, and the settings menu that offers config: elsewhere needs "
    + "AppBase.getSettingsView, which this device lacks too");
  if (nonDefaultEntries.length > 0) {
    notes.push(`with no editor to switch styles, every 'config: style:' entry but the default (${quoted(defaultStyle)}) is unreachable here: `
      + nonDefaultEntries.join(", "));
  }
  let suppressNote: string;
  if (users.length > 0) {
    suppressNote = `set 'lint: {allow: [config-unsupported], reason: ...}' on the element whose 'color:'/'track_color:' or 'slot:' is one of ${names} to accept it`;
  } else if (names) {
    suppressNote = `no element's 'color:'/'track_color:'/'slot:' is exactly one of ${names}, so there is nowhere to put `
      + "'lint: {allow: [config-unsupported]}' for it";
  } else {
    suppressNote = "nothing here binds a 'color:'/'track_color:'/'slot:' at all -- this is purely about the unreachable style entries named above";
  }
  const editor = `${device.id}: has no on-device watch face editor and no settings menu`;
  const kept = keptNamesList.map(axisName).join(", ");
  const absent = absentSlotTokens.map(axisName).join(", ");
  let message: string;
  if (keptNamesList.length > 0 && absentSlotTokens.length > 0) {
    message = `${editor}, so ${kept} keep their declared defaults here; it also lacks Toybox.Complications, so ${absent} show as absent here instead`;
  } else if (keptNamesList.length > 0) {
    message = `${editor}, so ${kept} keep their declared defaults here`;
  } else if (absentSlotTokens.length > 0) {
    message = `${editor}, and also lacks Toybox.Complications, so ${absent} show as absent here rather than their declared defaults`;
  } else {
    message = `${editor}, so every 'config: style:' entry but the default is stuck there`;
  }
  emitForUsers(bag, users, diag("warning", "config-unsupported", message, null, {
    notes: [...notes, suppressNote], confidence: "exact -- the device's own api.debug.xml",
  }));
}

// -- geometry --

export function checkProgressSegments(resolved: ResolvedFace, bag: Bag): void {
  for (const placed of resolved.items) {
    if (!(placed instanceof PlacedGauge)) continue;
    const element = placed.element;
    if (element.style !== "segments" || placed.cell * placed.step > 0) continue;
    const unit = element.geometry === "arc" ? "degrees of arc" : "px";
    bag.error("progress-segments",
      `${element.id}: on ${resolved.device.id}, ${element.count} segments with this 'gap:' leave ${formatFixed(placed.cell, 1)} ${unit} per cell -- nothing would be drawn`,
      element.span, { notes: ["shrink 'gap:', lower 'count:', or lengthen the track"] });
  }
}

export function checkGeometry(resolved: ResolvedFace, bag: Bag): void {
  const device = resolved.device;
  let uncheckedShape = false;
  for (const placed of resolved.items) {
    if (placed.kind === "group") continue;
    const box = placed.box;
    if (!insideScreen(box, device)) {
      emit(bag, placed, diag("warning", "off-screen",
        `${placed.id}: ${box.width}x${box.height} at (${box.x}, ${box.y}) falls outside the ${device.width}x${device.height} framebuffer`,
        placed.element.span, {
          notes: ["the device clips silently (Dc, like setClip: pixels outside the region are simply not drawn), so this is a "
            + "cropped design, not a broken one -- acknowledge it with 'lint: {allow: [off-screen], reason: ...}' if it is deliberate"],
          confidence: "exact -- resolved geometry",
        }));
      continue;
    }
    if (isFullBleed(box, device)) continue;
    const visible = insideVisibleAreaFor(placed, device);
    if (visible === null) {
      uncheckedShape = true;
    } else if (!visible) {
      const notes: string[] = [];
      let confidence: string;
      if (device.shape === "round") {
        notes.push("the framebuffer is rectangular but the panel is not; the outer edge is cropped by the bezel");
        const reach = visibleReach(placed, device, device.width / 2, device.height / 2);
        const limit = device.minorRadius * (1.0 - BEZEL_MARGIN);
        if (reach !== null) {
          notes.push(`this element's own ink reaches ${formatFixed(reach, 1)}px from ${device.id}'s screen centre; `
            + `the visible disc's own limit is ${formatFixed(limit, 1)}px`);
        }
        confidence = "exact -- resolved geometry against the visible disc";
      } else {
        notes.push(`the visible area is ${device.id}'s simulator skin, which covers this element's ink (one pixel of tolerance allowed)`);
        confidence = "exact -- resolved geometry against the simulator skin's mask";
      }
      emit(bag, placed, diag("warning", "safe-area", `${placed.id} reaches outside the visible area of ${device.id}'s ${device.shape} screen`,
        placed.element.span, { notes, confidence }));
    }
  }
  if (uncheckedShape) {
    bag.note("safe-area", `${device.id}: no visible-area geometry is defined for a ${quoted(device.shape)} screen, so element placement is not checked`,
      null, { confidence: "not checked -- see ADR 0004" });
  }
}

export function checkSubPixelLength(resolved: ResolvedFace, bag: Bag): void {
  for (const sp of resolved.sub_pixel) {
    const isPart = sp.owner !== sp.element.id;
    const levels = isPart ? `the face, a containing group, '${sp.element.id}' itself, or just this part`
      : `the face, a containing group, or '${sp.element.id}' itself`;
    const notes = [
      `turn on 'min_1px: true' at whichever level actually needs it -- ${levels} -- to floor it at 1px on every device`,
      `or accept it deliberately with 'lint: {allow: [sub-pixel-length], reason: ...}' on '${sp.element.id}'`,
    ];
    if (isPart) {
      notes.push("a hand or pattern part has no 'lint:' key of its own, so that acknowledgement suppresses every "
        + `sub-pixel-length finding on any part of '${sp.element.id}', not just this one`);
    }
    emitForUsers(bag, [sp.element], diag("warning", "sub-pixel-length",
      `${sp.owner}: ${sp.key} = ${sp.length} resolves to ${formatFixed(sp.value, 2)}px on ${resolved.device.id} -- a nonzero relative `
      + "length this thin rounds away to nothing and vanishes here, though it may draw fine on a target with a bigger screen",
      sp.span, { notes, confidence: "exact -- resolved device geometry" }));
  }
}

export function checkTextFit(resolved: ResolvedFace, bag: Bag): void {
  const device = resolved.device;
  for (const placed of resolved.items) {
    if (!(placed instanceof PlacedText)) continue;
    if (placed.font.px === 0) continue;
    if (placed.curve.style !== null) continue;
    const confidence = placed.width_is_estimated
      ? "approximate -- the device's own typeface is not available, so the extent is measured from a stand-in scaled to the published pixel height"
      : "exact -- measured from the baked font's own glyph advances";
    const fits = insideVisibleAreaFor(placed, device);
    if (placed.box.width > device.width || fits === false) {
      emit(bag, placed, diag("warning", "text-overflow",
        `${placed.id}: the widest rendering ${quoted(placed.widest)} is ${placed.measured_width}px and does not fit its position on ${device.id}`,
        placed.element.span, {
          notes: [`screen is ${device.width}px wide; the text box spans x=${placed.box.x}..${placed.box.right}`], confidence,
        }));
    }
  }
}

function missingGlyphError(bag: Bag, what: string, fontReference: string, missing: Set<string>, span: Span | null, notes: string[]): void {
  const characters = sorted(missing).map((c) => quoted(c)).join(", ");
  bag.error("missing-glyph", `${what}: font ${quoted(fontReference)} has no glyph for ${characters}`, span, {
    notes: [...notes, "widen the font's 'glyphs:' set, or remove it to let the compiler derive the set from the design"],
    confidence: "exact -- the baked font's own character map",
  });
}

export function checkGlyphs(resolved: ResolvedFace, bag: Bag): void {
  for (const [, run] of kinds.placedTextRuns(resolved.items, resolved.face)) {
    const font = run.samples.length > 0 ? resolved.fonts.get(run.font) : undefined;
    if (font === undefined) continue;
    const missing = new Set<string>();
    for (const sample of run.samples) for (const ch of font.missing(sample)) missing.add(ch);
    if (missing.size > 0) missingGlyphError(bag, run.label, run.font, missing, run.span, run.sample_note ? [run.sample_note] : []);
  }
}

// -- contrast --

/** The colour an expression folds to at build time, or `null`. */
function constantColor(expression: Expression | null | undefined): Color | null {
  if (expression === null || expression === undefined || expression.constant === null) return null;
  const n = expr.asNumber(expression.constant);
  return ColorClass.parse(Math.trunc(typeof n === "bigint" ? Number(n) : typeof n === "number" ? n : n.value));
}

export function checkContrast(resolved: ResolvedFace, bag: Bag): void {
  resolved.items.forEach((placed, index) => {
    if (backdropColor(resolved, placed) !== null) return;
    for (const backdrop of backdrops(resolved, index)) {
      for (const [label, color, ring, allowBackdropMatch] of kinds.forPlaced(placed).contrastSubjects(placed)) {
        if (ring !== null) checkOutlineContrast(bag, placed, ring, color, backdrop, label);
        else checkPlainColorContrast(bag, placed, color, backdrop, label, allowBackdropMatch);
      }
    }
  });
}

function contrastWarning(bag: Bag, placed: Placed, message: string, note: string): void {
  emit(bag, placed, diag("warning", "contrast", message, placed.element.span, {
    notes: [note], confidence: "exact arithmetic; the 3.0 threshold is a judgement call",
  }));
}

function checkPlainColorContrast(bag: Bag, placed: Placed, colorExpression: Expression | null, backdrop: Color, label: string,
  allowBackdropMatch = false): void {
  const color = constantColor(colorExpression);
  if (color === null) return;
  if (allowBackdropMatch && color.value === backdrop.value) return;
  const ratio = color.contrastRatio(backdrop);
  if (ratio < 3.0) {
    contrastWarning(bag, placed, `${label}: ${color} on ${backdrop} has a contrast ratio of ${formatFixed(ratio, 1)}`,
      "below 3.0 this is hard to read on a transflective display in low light");
  }
}

function checkOutlineContrast(bag: Bag, placed: Placed, ringExpression: Expression, interiorExpression: Expression | null,
  backdrop: Color, label: string): void {
  const ring = constantColor(ringExpression);
  if (ring === null) return;
  const interior = constantColor(interiorExpression);
  const ratio = ring.contrastRatio(backdrop);
  const interiorReads = interior !== null && interior.contrastRatio(backdrop) >= 3.0;
  if (ratio < 3.0 && !interiorReads) {
    contrastWarning(bag, placed, `${label}: outline ring ${ring} on ${backdrop} has a contrast ratio of ${formatFixed(ratio, 1)}`,
      "with a hollow interior the ring is the only ink drawn -- below 3.0 the whole character can disappear into the page");
  }
  if (interior === null) return;
  const innerRatio = ring.contrastRatio(interior);
  if (innerRatio < 3.0) {
    contrastWarning(bag, placed,
      `${label}: outline ring ${ring} on its own interior ${interior} has a contrast ratio of ${formatFixed(innerRatio, 1)}`,
      "the ring's inner edge is invisible against its own fill -- the glyph reads as one soft-edged blob in the fill colour instead of a crisp outline");
  }
}

/** Shapes whose ink fills their bounding box closely enough to be the thing behind everything else. */
const BACKDROP_SHAPES = ["rectangle", "circle", "ellipse"];

function isSolidBackdropShape(placed: Placed): boolean {
  const element = placed.element as unknown as { shape?: string; filled?: boolean };
  return placed.kind === "shape" && BACKDROP_SHAPES.includes(element.shape ?? "") && (element.filled ?? true);
}

function backdropColor(resolved: ResolvedFace, placed: Placed): Color | null {
  if (!isSolidBackdropShape(placed) || placed.box.area < resolved.screen.area * 0.9) return null;
  return constantColor((placed.element as unknown as { color?: Expression | null }).color);
}

/** Every distinct colour behind `resolved.items[index]`, one per (mode, layout) it can be drawn in. */
function backdrops(resolved: ResolvedFace, index: number): Color[] {
  const element = resolved.items[index]!.element;
  let layouts: (string | null)[] = [element.layout];
  if (element.layout === null) {
    const declared = sorted(new Set(resolved.face.walk().filter((e) => e.layout !== null).map((e) => e.layout!)));
    layouts = declared.length > 0 ? declared : [null];
  }
  const fallback = resolved.face.palette.get("bg") ?? null;
  const found: Color[] = [];
  for (const mode of element.modes) {
    for (const layout of layouts) {
      let color = fallback;
      for (const earlier of resolved.items.slice(0, index)) {
        if (!earlier.element.modes.includes(mode)) continue;
        if (earlier.element.layout !== null && earlier.element.layout !== layout) continue;
        const backdrop = backdropColor(resolved, earlier);
        if (backdrop !== null) color = backdrop;
      }
      if (color !== null && found.every((c) => c.value !== color!.value)) found.push(color);
    }
  }
  return found;
}

// -- partial-update budget (heuristic) --

/** `[path, call]` for the first weather or complication path this element binds: a real API call every time. */
function expensiveLowPowerReader(element: Element): [string, string] | null {
  for (const expression of element.expressions()) {
    for (const path of expression.sources) {
      const source = catalog.get(path);
      if (source === undefined) continue;
      if (source.reader === "weather_current" || source.reader === "weather_daily") return [path, "Weather.getCurrentConditions()/getDailyForecast()"];
      const reader = catalog.READERS.get(source.reader);
      if (reader !== undefined && reader.complication_type !== null) return [path, "Complications.getComplication()"];
    }
  }
  return null;
}

const BUDGET_PERMANENT = "exceeding the power budget calls onPowerBudgetExceeded and disables partial updates PERMANENTLY for the rest of "
  + "the app's lifecycle -- not just for the frame that overran";

export function checkPartialUpdateBudget(resolved: ResolvedFace, bag: Bag): void {
  const clip = resolved.clipFor("low_power");
  if (clip === null) return;
  const device = resolved.device;
  if (!device.supportsPartialUpdate) {
    bag.error("partial-update", `${device.id} is an ${device.displayType.toUpperCase()} device and does not support onPartialUpdate, but this design has low-power elements`,
      null, {
        notes: ["MIP and AMOLED are structurally different low-power paths, not a styling difference; on an AMOLED target the sleep "
          + "frame is 'aod:', not 'sleep_update: true'"],
        confidence: "exact -- device displayType",
      });
    return;
  }
  const lowPower = resolved.drawnInMode("low_power");
  const fraction = clip.area / (device.width * device.height);
  if (fraction > 0.25) {
    emitForUsers(bag, lowPower.map((p) => p.element), diag("warning", "partial-update-budget",
      `low-power updates clip ${formatFixed(fraction * 100, 0)}% of the screen (${clip.width}x${clip.height}px) and draw ${lowPower.length} element(s) each second`,
      null, {
        notes: [
          "setClip is charged by region area, so a wide clip is expensive even when little inside it changes",
          "exceeding the budget calls onPowerBudgetExceeded and disables partial updates PERMANENTLY for the rest of the app's "
          + "lifecycle -- not just for the frame that overran",
          "since the per-source refresh-cadence check was removed, this warning is now the ONLY thing standing between an author "
          + "and reading Weather.getCurrentConditions() or a Complications lookup inside onPartialUpdate -- a 'weather.*' or "
          + "'complication.*' binding, or a 'graph' element (its own series is recomputed on-device every minute, not read fresh, "
          + "but the drawing itself still runs every partial update), on a 'sleep_update: true' element is the expensive case to look at first",
          "position the low-power elements physically close together to tighten the clip -- wrapping them in a 'group' does not: "
          + "a group paints nothing and, with no explicit 'size:', resolves to its entire parent box, so grouping can make the clip "
          + "bigger, never smaller",
          "set 'lint: {allow: [partial-update-budget], reason: ...}' on any one of the elements drawn in low-power mode to keep it",
        ],
        confidence: "HEURISTIC -- Garmin does not publish the numeric budget; this flags relative cost, not a measured overrun",
      }));
    return;
  }
  const inGroupRing = new Set(ringGroups(resolved.face.elements).flatMap((ring) => [...ring.ids]));
  for (const placed of lowPower) {
    checkLowPowerRing(bag, placed, inGroupRing.has(placed.id), resolved.face);
    if (placed.kind === "graph") {
      emit(bag, placed, diag("warning", "partial-update-budget",
        `${placed.id}: a 'graph' element draws in low-power mode -- its drawing runs every onPartialUpdate, once a second, even `
        + "though the series itself only rebuilds on-device once a minute", placed.element.span, {
          notes: [BUDGET_PERMANENT, "drop this element's 'sleep_update: true', or accept the cost with 'lint: {allow: [partial-update-budget], reason: ...}'"],
          confidence: "HEURISTIC -- Garmin does not publish the numeric budget; this flags a known-expensive draw, not a measured overrun",
        }));
      continue;
    }
    const expensive = expensiveLowPowerReader(placed.element);
    if (expensive === null) continue;
    const [path, call] = expensive;
    emit(bag, placed, diag("warning", "partial-update-budget",
      `${placed.id}: binds ${quoted(path)} in low-power mode, which reads ${call} on every onPartialUpdate, once a second`, placed.element.span, {
        notes: [
          "since the per-source refresh-tier cache was removed, this is a real API call every time, not a cached field read",
          BUDGET_PERMANENT,
          "bind a cheaper source here, drop this element's 'sleep_update: true', or accept the cost with "
          + "'lint: {allow: [partial-update-budget], reason: ...}'",
        ],
        confidence: "HEURISTIC -- Garmin does not publish the numeric budget; this flags a known-expensive read, not a measured overrun",
      }));
  }
}

/** A stamped `outline:` ring drawn in `onPartialUpdate`: the element's own, or its share of a group's. */
function checkLowPowerRing(bag: Bag, placed: Placed, groupRing: boolean, face: Face): void {
  if (placed.element.outline === null && !groupRing) return;
  const draws = kinds.forPlaced(placed).ringDraws(placed.element, face);
  if (draws <= 1) return;
  const whose = groupRing ? "its share of a group's 'outline:' ring" : "its 'outline:' ring";
  emit(bag, placed, diag("warning", "partial-update-budget",
    `${placed.id}: ${whose} is stamped -- ${draws} more draws of it on every onPartialUpdate, once a second`, placed.element.span, {
      notes: [
        "measured on a fenix 8, a stamped ring costs about 4x the element's own draw time (docs/guide/outlines.md, \"Cost and the always-on frame\")",
        "exceeding the power budget calls onPowerBudgetExceeded and disables partial updates PERMANENTLY for the rest of the app's lifecycle",
        "drop the ring or this element's 'sleep_update: true', ring a filled circle or rectangle instead (one grown copy), or accept "
        + "the cost with 'lint: {allow: [partial-update-budget], reason: ...}'",
      ],
      confidence: "HEURISTIC -- Garmin does not publish the numeric budget; the multiplier is measured, the overrun is not",
    }));
}

/** A constant-folded `visible:` that is always false. */
function alwaysFalse(expression: Expression | null): expression is Expression {
  return expression !== null && expression.constant !== null && !truthy(expression.constant);
}

export function checkDeadElement(resolved: ResolvedFace, bag: Bag): void {
  const items = resolved.items;
  let index = 0;
  while (index < items.length) {
    const placed = items[index]!;
    index++;
    const expression = placed.element.visible;
    if (!alwaysFalse(expression)) continue;
    emit(bag, placed, diag("warning", "dead-element", `${placed.id}: 'visible: ${expression.text}' is always false, so this element is never drawn`,
      expression.span ?? placed.element.span, {
        notes: [...(placed.kind === "group" ? ["a group's 'visible:' is conjoined into every element beneath it, so the whole subtree is dead too"] : []),
          "delete it, or fix the condition"],
        confidence: "exact -- constant-folded at build time",
      }));
    while (index < items.length && items[index]!.depth > placed.depth) index++;
  }
  for (const placed of resolved.items) {
    if (!(placed.element instanceof PatternElement)) continue;
    if (alwaysFalse(placed.element.visible)) continue;
    placed.element.parts.forEach((part, partIndex) => {
      const expression = part.visible;
      if (!alwaysFalse(expression)) return;
      emit(bag, placed, diag("warning", "dead-element",
        `${placed.id}.parts[${partIndex}]: 'visible: ${expression.text}' is always false, so this part is never drawn`,
        expression.span ?? placed.element.span, {
          notes: ["delete the part, or fix the condition"], confidence: "exact -- constant-folded at build time",
        }));
    });
  }
}

export function checkAodUnreachable(resolved: ResolvedFace, bag: Bag): void {
  for (const placed of resolved.items) {
    const element = placed.element;
    if (!element.aod_ancestor_hidden || element.aod_own === null) continue;
    emit(bag, placed, diag("warning", "aod-unreachable",
      `${placed.id}: has its own 'aod:', but an ancestor group already writes 'aod: hide', which hides the whole subtree and cannot be undone below it`,
      element.span, {
        notes: [
          "an explicit 'aod: hide' on a group is sticky -- nothing beneath it can turn AOD back on",
          "delete this element's own 'aod:', or drop the ancestor's 'aod: hide'",
        ],
        confidence: "exact -- resolved at build time",
      }));
  }
}

export function checkAodEmpty(resolved: ResolvedFace, bag: Bag): void {
  if (!resolved.device.isAmoled) return;
  if (resolved.items.some((p) => p.kind !== "group" && p.element.aod !== null)) return;
  const face = resolved.face;
  if (suppressed("aod-empty", [face.aod_lint_allow])) return;
  bag.warning("aod-empty", `${resolved.device.id} is AMOLED, but nothing in this design draws in always-on display`, null, {
    notes: [
      "Garmin treats an absent always-on view as a defect on an AMOLED target, not an optional extra (docs/guide/always-on-display.md)",
      "add 'aod: show' (or an override) to at least the time, or set the face-wide 'aod: {default: show}'",
      "suppress with the face's own 'aod: {lint: {allow: [aod-empty], reason: ...}}' if this is deliberate",
    ],
    confidence: "exact -- resolved 'aod:' set, this device",
  });
}

// -- burn-in --

/** Garmin's 10% rule, checked on both bases (lit pixels and luminance) at once. */
export const AOD_BURN_IN_THRESHOLD = 0.10;

/** Two worst-case sample clocks: a 24-hour clock's two tens-of-hours digits against the same other digits. */
export const AOD_BURN_IN_SAMPLE_TIMES: readonly [number, number, number][] = [[10, 8, 0], [20, 8, 0]];

/** Full battery, so a gauge or graph on it is measured at its own worst case too. */
export const AOD_BURN_IN_SAMPLE: ReadonlyMap<string, ExprValue> = new Map<string, ExprValue>([["system.battery", new PyFloat(100)]]);

const AOD_BURN_IN_TOP_N = 3;

let burnInLuts: Uint8Array[] | null = null;

/** Per channel, an sRGB 0-255 value to its share of its weight of full-white luminance, 0-255. */
function aodBurnInLuts(): Uint8Array[] {
  if (burnInLuts === null) {
    burnInLuts = LUMINANCE_WEIGHTS.map((w) => Uint8Array.from({ length: 256 }, (_, v) => Math.min(255, roundHalfEven(w * srgbChannelToLinear(v) * 255))));
  }
  return burnInLuts;
}

/** Which pixels count: the inscribed disc on a round screen, the skin's visible area, or the whole framebuffer. */
function aodBurnInMask(device: Device): Uint8Array {
  const mask = new Uint8Array(device.width * device.height);
  if (device.shape === "round") {
    const im = newImage(device.width, device.height, [0, 0, 0]);
    ellipse(im, [0, 0, device.width - 1, device.height - 1], { fill: [255, 255, 255] });
    for (let i = 0; i < mask.length; i++) mask[i] = im.data[i * 4]! === 255 ? 1 : 0;
    return mask;
  }
  const skin = visibleMask(device);
  if (skin !== null) return Uint8Array.from(skin.visible);
  return mask.fill(1);
}

/** `[litFraction, luminanceFraction, litPixels, maskPixels]` over the mask's pixels. */
function aodBurnInMeasure(image: Image, mask: Uint8Array): [number, number, number, number] {
  const [lr, lg, lb] = aodBurnInLuts() as [Uint8Array, Uint8Array, Uint8Array];
  let lit = 0, luminance = 0, denom = 0;
  for (let i = 0; i < mask.length; i++) {
    if (!mask[i]) continue;
    denom++;
    const r = image.data[i * 4]!, g = image.data[i * 4 + 1]!, b = image.data[i * 4 + 2]!;
    if (r || g || b) lit++;
    luminance += Math.min(255, Math.min(255, lr[r]! + lg[g]!) + lb[b]!);
  }
  if (denom === 0) return [0.0, 0.0, lit, 0];
  return [lit / denom, luminance / denom / 255.0, lit, denom];
}

function aodBurnInOptions(sampleTime: [number, number, number]): PreviewOptions {
  return previewOptions({ scale: 1, quantise: true, mask_shape: false, aod: true, time: sampleTime, sample: AOD_BURN_IN_SAMPLE, aod_mask: false });
}

const pad2 = (n: number): string => String(n).padStart(2, "0");

export function checkAodBurnIn(resolved: ResolvedFace, bag: Bag): void {
  const device = resolved.device;
  if (!device.isAmoled) return;
  const shown = resolved.items.filter((p) => p.kind !== "group" && p.element.aod !== null);
  if (shown.length === 0) return;
  const mask = aodBurnInMask(device);
  const phases: (number | null)[] = resolved.face.aod_mask ? [0, 1, 2, 3] : [null];
  let best: [number, number, number, [number, number, number], number | null] | null = null;
  for (const sampleTime of AOD_BURN_IN_SAMPLE_TIMES) {
    const image = render(resolved, aodBurnInOptions(sampleTime));
    for (const phase of phases) {
      const scored = phase !== null ? aodMask.apply(image, phase) : image;
      const [litF, lumF, litPixels] = aodBurnInMeasure(scored, mask);
      if (best === null || Math.max(litF, lumF) > Math.max(best[0], best[1])) best = [litF, lumF, litPixels, sampleTime, phase];
    }
  }
  const [litFraction, luminanceFraction, litTotal, worstTime, worstPhase] = best!;
  const totalLitPixels = Math.max(litTotal, 1);
  const soloOptions = aodBurnInOptions(worstTime);
  const contributions: [Placed, number][] = shown.map((placed) => {
    let solo = render(ResolvedFace.create({ ...resolved, items: [placed] }), soloOptions);
    if (worstPhase !== null) solo = aodMask.apply(solo, worstPhase);
    return [placed, aodBurnInMeasure(solo, mask)[2]];
  });
  contributions.sort((a, b) => b[1] - a[1]); // stable, as Python's sort
  const topLine = contributions.slice(0, AOD_BURN_IN_TOP_N)
    .map(([placed, count]) => `${placed.id} (${formatFixed(100 * count / totalLitPixels, 1)}%)`).join(", ");
  const anchor = contributions[0]![0];
  const [hh, mm] = worstTime;
  let masked = "";
  if (worstPhase !== null) {
    const [dx, dy] = aodMask.offset(worstPhase);
    masked = `with the pixel mask (phase ${worstPhase}, dx=${dx} dy=${dy}), `;
  }
  const message = `${device.id}: ${masked}the AOD frame lights ${formatFixed(litFraction * 100, 1)}% of pixels and `
    + `${formatFixed(luminanceFraction * 100, 1)}% of luminance at ${pad2(hh)}:${pad2(mm)} (Garmin's 10% rule) -- top contributor: ${topLine}`;
  const notes = [
    `worst of ${AOD_BURN_IN_SAMPLE_TIMES.length} sampled clock times `
    + AOD_BURN_IN_SAMPLE_TIMES.map(([h, m]) => `${pad2(h)}:${pad2(m)}`).join(", ")
    + (worstPhase !== null ? " x 4 mask phases" : "")
    + ", full battery, the preview's other sample readings unchanged -- not every possible time/data value",
    "lit: any pixel rendering other than pure black (Garmin's own definition); luminance: mean relative luminance "
    + "(Color.relative_luminance, Rec. 709 primaries over sRGB-decoded channels) as a fraction of full white -- Garmin's own "
    + "integral is unpublished (docs/guide/always-on-display.md, \"Lints\")",
    "checked against both AMOLED generations' 10% rules at once (original Venu: lit-pixel share; Venu 2+: luminance share), "
    + "since the device files do not say which generation a target is",
    worstPhase !== null
      ? "the moving pixel mask (aod: {mask: ...}, on by default) guarantees no pixel is lit two consecutive minutes, so the "
        + "3-minute static-pixel rule holds by construction -- this still cannot see any minute or data value but the sampled "
        + "ones (`wfb preview --heatmap` approximates that) -- docs/limitations.md"
      : "cannot see the 3-minute static-pixel rule or any minute but the sampled ones (`wfb preview --heatmap` approximates both) "
        + "-- docs/limitations.md",
    `share is each element's own lit-pixel count against the full frame's ${totalLitPixels.toLocaleString("en-US")} lit pixels `
    + `at ${pad2(hh)}:${pad2(mm)} -- overlapping elements' shares can sum past 100%`,
  ];
  const over = Math.max(litFraction, luminanceFraction) > AOD_BURN_IN_THRESHOLD;
  if (over) {
    notes.push("over Garmin's 10% rule risks the system switching always-on off for this app entirely",
      "lighten the top contributor(s) -- hide, thin, or dim them further in 'aod:' -- or accept it with "
      + "lint: {allow: [aod-burn-in], reason: \"...\"} on the element named above");
  }
  emit(bag, anchor, diag(over ? "error" : "note", "aod-burn-in", message, anchor.element.span, {
    notes,
    confidence: "estimate -- rasterised from a chosen worst-case sample frame, not the simulator's own Screen Heat Map "
      + "(root CLAUDE.md §3, unreachable here), which is authoritative; the luminance formula is this compiler's own choice, "
      + "since Garmin's is unpublished",
  }));
}

// -- hold targets --

/** The one way a live watch face can be told about a touch; `onTap` fires only in the config editor. */
const HOLD_SYMBOL = "Toybox.WatchUi.WatchFaceDelegate.onPress";

export function checkHoldTargets(resolved: ResolvedFace, bag: Bag): void {
  const held = resolved.items.filter((p) => p.element.on_hold !== null);
  if (held.length === 0) return;
  const device = resolved.device;
  const available = probeSymbols(bag, device, "hold-unsupported", "touch support", () => device.hasSymbol(HOLD_SYMBOL));
  if (available === null) return;
  if (!available) {
    for (const placed of held) {
      emit(bag, placed, diag("warning", "hold-unsupported",
        `${placed.id}: ${device.id} has no WatchFaceDelegate.onPress, so this hold target can never fire there`, placed.element.span, {
          notes: [
            "the face still works; it is simply not interactive on this device, and the element draws as usual",
            "onPress is the only gesture a live watch face receives; there is no tap to fall back to",
          ],
          confidence: "exact -- the device's own api.debug.xml",
        }));
    }
    return;
  }
  held.forEach((second, index) => {
    for (const first of held.slice(0, index)) {
      if (neverTogether(first.element, second.element)) continue;
      if (!intersects(first.box, second.box)) continue;
      emit(bag, second, diag("warning", "hold-overlap",
        `${second.id}'s hold region overlaps ${first.id}'s on ${device.id}, so a touch in the shared area always opens ${quoted(first.element.on_hold)}`,
        second.element.span, {
          notes: [
            "regions are tested in draw order and the first match wins, so the second target is unreachable where they overlap",
            "a hold region is the element's own drawn box; move them apart, or drop one of the two 'on_hold:' declarations",
          ],
          confidence: "exact -- resolved geometry",
        }));
    }
  });
}

// -- api gating --

export function checkApiGated(resolved: ResolvedFace, bag: Bag): void {
  const device = resolved.device;
  const probed = probeSymbols(bag, device, "api-gated", "API-level gating",
    (): [boolean, boolean] => [device.hasModule("Complications"), device.hasSymbol(HOLD_SYMBOL)]);
  if (probed === null) return;
  const [hasComplications, hasOnpress] = probed;
  const exact = `exact -- ${device.id}'s own api.debug.xml`;
  const candidates: [Placed, string, Span | null, string][] = [];
  for (const placed of resolved.items) {
    const element = placed.element;
    for (const expression of element.expressions()) {
      for (const path of expression.sources) {
        const gap = availability.sourceUnavailable(path, device);
        const span = expression.span ?? element.span;
        if (gap !== null) emitSourceGap(bag, placed, path, span, gap, device);
        if (hasComplications && path.startsWith("complication.") && complications.get(path.slice("complication.".length)) !== undefined) {
          candidates.push([placed, path.slice("complication.".length), span, "read"]);
        }
      }
    }
    if (element.on_hold !== null && complications.get(element.on_hold) !== undefined) {
      if (hasComplications) {
        candidates.push([placed, element.on_hold, element.span, "hold"]);
      } else if (hasOnpress) {
        emit(bag, placed, diag("warning", "api-gated",
          `${placed.id}: on_hold: ${quoted(element.on_hold)} needs Toybox.Complications, which ${device.id} lacks, so it never fires there`,
          element.span, {
            notes: [
              "the generated delegate guards this call with 'Toybox has :Complications' (computeGuards) -- the "
              + "hold compiles in but is a silent no-op here, not a crash",
              "the face still works; the element itself still draws as usual",
            ],
            confidence: exact,
          }));
      }
    }
    if (element instanceof Graph && element.series_def !== null) {
      const module = series.ACQUISITION[element.series_def.acquisition].module;
      const bare = module.replace(/^Toybox\./, "");
      const gap = availability.moduleUnavailable(bare, device);
      if (gap !== null) {
        emit(bag, placed, diag("warning", "api-gated",
          `${placed.id}: series ${quoted(element.series)} needs module ${module}, which ${device.id} lacks, so the graph draws empty there`,
          element.span, {
            notes: [
              `confirmed against ${device.id}'s own api.debug.xml -- not one of its <dataEntry type="module"> rows`,
              `the generated view guards the acquisition with 'Toybox has :${bare}' (computeGuards) -- the build `
              + "still succeeds; only this graph degrades on this device",
            ],
            confidence: exact,
          }));
      }
    }
    const slotName = slotOf(element);
    if (slotName !== null) {
      const slot = resolved.face.config_data.get(slotName);
      if (slot === undefined) continue;
      if (hasComplications) {
        const choices = slot.choices === "any" ? [slot.default] : slot.choices;
        for (const name of choices) if (complications.get(name) !== undefined) candidates.push([placed, name, element.span, "slot"]);
      } else {
        emit(bag, placed, diag("warning", "api-gated",
          `${placed.id}: slot ${quoted(slotName)} needs Toybox.Complications, which ${device.id} lacks, so it shows its absent state here -- never the declared default`,
          element.span, {
            notes: [
              "the generated code guards every reference to Complications for this slot (computeGuards) -- this "
              + "is silent, not a crash",
              "the slot's own 'default:' is itself read through WfbComplications.valueOf, so it is just as unreachable here as any "
              + "other choice -- there is no fallback to a compiled-in value on a device with no Complications module at all",
            ],
            confidence: exact,
          }));
      }
    }
  }
  checkComplicationSince(bag, resolved, candidates);
}

function emitSourceGap(bag: Bag, placed: Placed, path: string, span: Span | null, gap: availability.Unavailable, device: Device): void {
  if (gap.kind === "function") {
    emit(bag, placed, diag("error", "api-gated-unguardable",
      `${placed.id}: ${quoted(path)} needs ${gap.symbol}, which ${device.id} lacks -- the generator cannot gate this call yet`, span, {
        notes: [
          "computeGuards only ever emits a runtime guard for a missing module ('Toybox has :Module') or field "
          + "('x has :field') -- there is no guard for an individual missing function, so this call would run unguarded and crash on this device",
          `drop this target, drop the binding, or add a guard for ${quoted(gap.symbol)} to the generated code before shipping this`,
        ],
        confidence: "exact -- the device's own api.debug.xml",
      }));
    return;
  }
  const need = gap.kind === "module" ? `module Toybox.${gap.symbol}` : `field ${quoted(gap.symbol)}`;
  let confidence = `exact -- ${device.id}'s own api.debug.xml`;
  if (gap.kind === "field") confidence += " (a bare field name's absence from its symbol table is exact)";
  emit(bag, placed, diag("warning", "api-gated",
    `${placed.id}: ${quoted(path)} needs ${need}, which ${device.id} lacks, so it reads as absent there ('absent:' applies)`, span, {
      notes: [
        `confirmed against ${device.id}'s own api.debug.xml -- `
        + (gap.kind === "module" ? "not one of its <dataEntry type=\"module\"> rows" : `${quoted(gap.symbol)} is not one of its <symbolTable> field entries`),
        "the generated view guards this at runtime (computeGuards) -- the build still succeeds; only this binding degrades on this device",
      ],
      confidence,
    }));
}

const READS_AS_ABSENT_NOTE = "Complications.getComplication returns null for a type the device does not support -- the same "
  + "'absence is normal' contract every other nullable source already has, so this reads as absent rather than crashing";

const SINCE_NOTES: Record<string, string[]> = {
  hold: [
    "Complications.subscribeToUpdates returning false or throwing ComplicationNotFoundException is already caught uniformly by "
    + "WfbComplications.mc's subscribe() -- the hold simply becomes a no-op on this device, not a crash",
    "pick a launch target with a lower 'since' for this device, or accept that the hold does nothing here",
  ],
  slot: [
    READS_AS_ABSENT_NOTE,
    "the wearer simply cannot pick this type on this device (or, if it is the slot's 'default:', the slot never shows it here); "
    + "drop it from 'choices:', or accept that it is unreachable on this target",
  ],
  read: [
    READS_AS_ABSENT_NOTE,
    "drop this binding for this target, bind a lower-'since' source instead, or accept that it never updates here",
  ],
};

function sinceSubject(placed: Placed, name: string, kind: string): string {
  if (kind === "hold") return `holding to launch ${quoted(name)}`;
  if (kind === "slot") return `slot ${quoted(slotOf(placed.element))}'s 'complication.${name}'`;
  return `'complication.${name}'`;
}

function checkComplicationSince(bag: Bag, resolved: ResolvedFace, candidates: [Placed, string, Span | null, string][]): void {
  if (candidates.length === 0) return;
  const device = resolved.device;
  const level = device.apiLevel;
  if (level === "0.0.0") {
    bag.note("api-gated", `${device.id}: no ConnectIQ version found in compiler.json, so complication-type availability is not checked`,
      null, { confidence: "not checked -- the device's compiler.json has no usable partNumbers/connectIQVersion" });
    return;
  }
  for (const [placed, name, span, kind] of candidates) {
    const ctype = complications.TYPES.get(name)!;
    if (compareVersions(ctype.since, level) <= 0) continue;
    emit(bag, placed, diag("warning", "api-gated",
      `${placed.id}: ${sinceSubject(placed, name, kind)} needs ConnectIQ ${ctype.since}, but ${device.id} tops out at ${level}`, span, {
        notes: [...SINCE_NOTES[kind]!],
        confidence: `exact -- ${quoted(name)}'s since (${ctype.since}, Toybox/Complications.html) vs ${device.id}'s api_level (${level}, compiler.json)`,
      }));
  }
}

function intersects(a: IntBox, b: IntBox): boolean {
  return a.x < b.right && b.x < a.right && a.y < b.bottom && b.y < a.bottom;
}

// -- overlap: the static hoist and outline interiors --

function fullyContains(outer: IntBox, inner: IntBox): boolean {
  return outer.x <= inner.x && outer.y <= inner.y && outer.right >= inner.right && outer.bottom >= inner.bottom;
}

/** Two elements that can be on screen together, with intersecting boxes. */
function mayOverlap(a: Placed, b: Placed): boolean {
  return a.element.modes.some((m) => b.element.modes.includes(m)) && !neverTogether(a.element, b.element) && intersects(a.box, b.box);
}

const BOXES_NOT_INK = "exact -- resolved geometry, but boxes rather than ink: the elements may not overlap where they actually draw";

export function checkStaticOverlap(resolved: ResolvedFace, bag: Bag): void {
  const drawn = resolved.items.filter((p) => p.kind !== "group");
  const order = new Map(resolved.items.map((p, i): [Placed, number] => [p, i]).filter(([p]) => p.kind !== "group").map(([p, i]) => [p.id, i]));
  const authored = authoredDrawOrder(resolved.face.elements);
  const placedById = new Map(drawn.map((p) => [p.id, p]));
  const covered = new Map<string, string[]>();
  authored.forEach((earlier, index) => {
    for (const later of authored.slice(index + 1)) {
      if ((order.get(earlier.id) ?? 0) <= (order.get(later.id) ?? 0)) continue;
      const top = placedById.get(earlier.id), bottom = placedById.get(later.id);
      if (top === undefined || bottom === undefined || !mayOverlap(top, bottom)) continue;
      if (!covered.has(top.id)) covered.set(top.id, []);
      covered.get(top.id)!.push(bottom.id);
    }
  });
  for (const [elementId, under] of covered) {
    const placed = placedById.get(elementId)!;
    const names = under.map((name) => quoted(name)).join(", ");
    emit(bag, placed, diag("warning", "static-overlap",
      `${quoted(elementId)} may draw over ${names} on ${resolved.device.id}: hoisting the static content to the front of draw order swapped them round`,
      placed.element.span, {
        notes: [
          "the static buffer is opaque and full-screen, so every static element is blitted before anything else is drawn -- "
          + "there is no order in which something can be under it",
          "write them in the order they should paint, static content first, to say so explicitly -- or accept it with "
          + "lint: {allow: [static-overlap], reason: \"...\"}",
        ],
        confidence: BOXES_NOT_INK,
      }));
  }
}

/** Both fold to the same build-time constant. */
function sameProvableColor(a: Expression | null, b: Expression | null): boolean {
  if (a === null || b === null || a.constant === null || b.constant === null) return false;
  return deepEqual(a.constant, b.constant);
}

/** Every interior colour this element draws under a ring: a text's own, or one per outlined text part of a pattern. */
function outlinedInteriors(element: Element): (Expression | null)[] {
  const roles = element.colorRoles().filter((r) => !r.aod);
  const textLabels = element.kind === "text" ? new Set([element.id])
    : new Set(roles.filter((r) => r.label !== element.id && r.is_glyph).map((r) => r.label));
  const interiors: (Expression | null)[] = [];
  for (const label of new Set(roles.filter((r) => r.role === "ring" && textLabels.has(r.label)).map((r) => r.label))) {
    const inks = roles.filter((r) => r.role === "ink" && r.label === label).map((r) => r.expression);
    interiors.push(...(inks.length > 0 ? inks : [null]));
  }
  return interiors;
}

export function checkTextOutlineInterior(resolved: ResolvedFace, bag: Bag): void {
  const drawn = resolved.items.filter((p) => p.kind !== "group");
  drawn.forEach((later, index) => {
    const interiors = outlinedInteriors(later.element);
    if (interiors.length === 0) return;
    const under: string[] = [];
    for (const earlier of drawn.slice(0, index)) {
      if (!mayOverlap(later, earlier)) continue;
      const earlierColor = ((earlier.element as unknown as { color?: Expression | null }).color) ?? null;
      if (isSolidBackdropShape(earlier) && fullyContains(earlier.box, later.box)
        && interiors.every((interior) => sameProvableColor(interior, earlierColor))) continue;
      under.push(earlier.id);
    }
    if (under.length === 0) return;
    const names = under.map((name) => quoted(name)).join(", ");
    emit(bag, later, diag("warning", "text-outline-interior",
      `${quoted(later.id)}'s outline interior may paint over ${names} on ${resolved.device.id}: the interior pass paints over what's `
      + "beneath it, it does not reveal it -- check the interior colour matches what's actually there, or move one of them",
      later.element.span, {
        notes: [
          "'outline:' has no transparency of any kind -- Graphics.BlendMode has no destination-out formula reachable from drawText (docs/guide/text.md)",
          "write lint: {allow: [text-outline-interior], reason: \"...\"} once the interior colour is confirmed correct for what's actually underneath",
        ],
        confidence: BOXES_NOT_INK,
      }));
  });
}

// -- the graphics pool --

/** Fraction of the graphics pool the static buffers may take before this warns: a judgement. */
export const GRAPHICS_POOL_BUDGET = 0.5;

const thousands = (n: number): string => n.toLocaleString("en-US");

export function checkGraphicsPool(resolved: ResolvedFace, bag: Bag): void {
  const roots = resolved.items.filter((p) => p.element.static);
  if (roots.length === 0) return;
  const device = resolved.device;
  const perBuffer = device.bufferBytes();
  const pool = device.graphicsPoolBytes;
  if (perBuffer === null || !pool) return;
  const total = perBuffer;
  const share = total / pool;
  const detail = `the static content buffers ${thousands(total)} B of the ${thousands(pool)} B graphics pool (${formatFixed(share * 100, 1)}%) on ${device.id}`;
  const notes = [
    `${device.width}x${device.height} pixels at the display's own ${device.bitsPerPixel} bits/pixel; the buffer is full-screen because Dc has no translate`,
    `the graphics pool is separate from the ${thousands(device.watchfaceMemoryLimit)} B watch-face limit, so this is not charged against the face's own memory`,
    "it is shared with every font and bitmap loaded at runtime, and a buffer held with .get() is locked and cannot be purged to make room for them",
  ];
  const over = share > GRAPHICS_POOL_BUDGET;
  if (over) notes.push("move content out of `static:`, or accept it with lint: {allow: [graphics-pool], reason: \"...\"} on any element inside the block");
  const members = resolved.items.filter((p) => p.element.static_root !== null).map((p) => p.element);
  emitForUsers(bag, members, diag(over ? "warning" : "note", "graphics-pool", detail, roots[0]!.element.span, {
    notes,
    confidence: "estimate -- bytes per pixel for a BufferedBitmap is not published; this uses the display's bitsPerPixel and ignores any per-surface overhead",
  }));
}

// -- pattern-step --

export function checkPatternStep(resolved: ResolvedFace, bag: Bag): void {
  for (const placed of resolved.items) {
    if (!(placed instanceof PlacedPattern) || placed.element.pattern === "radial") continue;
    const element = placed.element;
    let landing: string;
    if (element.pattern === "grid") {
      const columns = element.columns!;
      const rows = Math.ceil(element.count / columns);
      const collapsed = ([["column", columns, placed.dx], ["row", rows, placed.dy]] as const).filter(([, n, d]) => n > 1 && d === 0).map(([what]) => what);
      if (collapsed.length === 0) continue;
      landing = collapsed.map((what) => `every ${what}`).join(" and ") + " lands on the first";
    } else if (placed.dx !== 0 || placed.dy !== 0) {
      continue;
    } else {
      landing = "every copy lands on copy 0";
    }
    const step = element.step;
    const given = step === null ? [] : ([["dx", step.dx], ["dy", step.dy]] as const).filter(([, l]) => l !== null && l !== undefined);
    const authored = `{${given.map(([key, l]) => `${key}: ${l}`).join(", ")}}`;
    emit(bag, placed, diag("error", "pattern-step",
      `${placed.id}: 'step: ${authored}' rounds to {${placed.dx}, ${placed.dy}}px on ${resolved.device.id} -- ${landing}`, placed.element.span, {
        notes: ["a step this small only reaches a whole pixel on a larger screen, or a larger fraction of the parent box -- use a larger "
          + "'step:', or 'px' instead of '%'/'%r' if the gap should not scale with the screen"],
        confidence: "exact -- resolved geometry",
      }));
  }
}

// -- memory (measured, post-build) --

const STATS_RE = /Data:\s*\n\s*Foreground:\s*(?<data>\d+) bytes[\s\S]*?Code:\s*\n\s*Foreground:\s*(?<code>\d+) bytes/;
const PRG_RE = /Total PRG Size:\s*(?<prg>\d+) bytes/;

/** One device's `monkeyc --build-stats` figures, in bytes. */
export interface MemoryStats { data: number; code: number; total: number; limit: number; prg: number | null }

/** `monkeyc --build-stats` against the device's watch-face limit: measured, not estimated. */
export function checkMemory(device: Device, buildOutput: string, bag: Bag): MemoryStats | null {
  const stats = STATS_RE.exec(buildOutput);
  if (stats === null) return null;
  const data = Number(stats.groups!["data"]), code = Number(stats.groups!["code"]);
  const total = data + code;
  const limit = device.watchfaceMemoryLimit;
  const prg = PRG_RE.exec(buildOutput);
  const result: MemoryStats = { data, code, total, limit, prg: prg !== null ? Number(prg.groups!["prg"]) : null };
  const share = total / limit;
  const message = `${device.id}: ${thousands(total)} B of the ${thousands(limit)} B watch-face limit (${formatFixed(share * 100, 1)}%) -- `
    + `${thousands(data)} B data, ${thousands(code)} B code`;
  const note = "measured by `monkeyc --build-stats`, not estimated.  This is the static foreground figure; resources loaded at "
    + "runtime (fonts, bitmaps) add to it, and that part is not measured here.";
  if (share >= 1.0) bag.error("memory", message, null, { notes: [note], confidence: "measured" });
  else if (share >= 0.85) bag.warning("memory", message, null, { notes: [note], confidence: "measured" });
  else bag.note("memory", message, null, { notes: [note], confidence: "measured" });
  return result;
}

/** Checks that read the design alone, in the order `runDesign` runs them. */
const DESIGN_CHECKS: readonly ((face: Face, bag: Bag) => void)[] = [
  checkPermissions, checkLintAllow, checkDuplicateStyle, checkUnreachableLayout,
];

/** Per-device checks, in the order `run` runs them: the order their diagnostics reach the author. */
const DEVICE_CHECKS: readonly ((resolved: ResolvedFace, bag: Bag) => void)[] = [
  checkPalette, checkAntialiasPalette, checkConfigPalette,
  checkColorSchemePalette, checkConfigSupport, checkGeometry, checkProgressSegments,
  checkSubPixelLength, checkTextFit, checkGlyphs, checkContrast,
  checkPartialUpdateBudget, checkHoldTargets, checkDeadElement,
  checkAodUnreachable, checkAodEmpty, checkAodBurnIn, checkApiGated,
  checkGraphicsPool, checkStaticOverlap, checkTextOutlineInterior,
  checkPatternStep,
];
