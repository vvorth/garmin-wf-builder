// Host-side preview: a resolved design rendered to an image..
//
// The preview consumes the same resolved IR the code generator does (ADR
// 0004), so preview and device cannot disagree about position. Shapes are
// drawn as Pillow draws them (`raster/pillow.ts`); text pastes the baked
// sheets' tiles, and a system or vector face is drawn from its outlines by
// the coverage rasteriser (`fonts/raster.ts`), each glyph exactly where the
// layout's advances put it. A rotated or curved run turns its outlines
// before they are rasterised, as the watch does, so no bitmap is rotated.
import * as aodMask from "./aod_mask.ts";
import type { Device, FontMetric } from "./devices/device.ts";
import * as drawProgram from "./draw/index.ts";
import type { Values } from "./draw/evaluator.ts";
import { frameMembers, inLayout } from "./draw/frames.ts";
import { type ExprValue } from "./expr.ts";
import * as expr from "./expr.ts";
import { RingPass } from "./emit/monkeyc/common.ts";
import { ReadPlan } from "./emit/monkeyc/readplan.ts";
import { glyphOutline } from "./fonts/bake.ts";
import type { BakedFont, GlyphBox, Sheet } from "./fonts/bmfont.ts";
import { fontForHeight, type SystemFace } from "./fonts/fallback.ts";
import { bounds, flatten, rasterise } from "./fonts/raster.ts";
import { type Element, type Expression, type Face, type StyleEntry } from "./ir/model.ts";
import { type RingGroup, ringGroups } from "./ir/rings.ts";
import { alignmentShift, type Placed, radialAlignOffset, radialDirectionSign, type ResolvedFace } from "./layout.ts";
import { Color, MIP64_SNAP, MONO_LUMINANCE, MONO_THRESHOLD } from "./palette.ts";
import { degrees, radians, roundHalfEven } from "./py.ts";
import { composite, ellipse, type Image, image as newImage, paste, rectangle, type Tile } from "./raster/pillow.ts";
import { SAMPLE } from "./sample.ts";
import type { IntBox } from "./units.ts";
import { decodePng, encodePng } from "./png.ts";
import { skin as skinOf, visibleMask } from "./visible_area.ts";

export { SAMPLE, SAMPLE_GOALS, SAMPLE_HEART_RATE_ZONES, SAMPLE_WEARER_AGE, SAMPLE_WEARER_SEX } from "./sample.ts";

/** One drawn colour. */
export type RGB = [number, number, number];

export interface PreviewOptions {
  /** How many times larger than the watch's own screen the image is, by whole-pixel replication. */
  scale: number;
  /** Snap every colour to the device's real palette. */
  quantise: boolean;
  /** Grey out what the bezel hides. */
  mask_shape: boolean;
  /** Sample readings overriding `SAMPLE`. */
  sample: ReadonlyMap<string, ExprValue> | null;
  /** A `config: style:` entry to render, or `null` for the default entry. */
  style: string | null;
  /** `[hour, minute, second]` overriding the sample time. */
  time: [number, number, number] | null;
  /** `[year, month, day]` overriding the sample date. */
  date: [number, number, number] | null;
  /** Hide every `awake`-only second hand. */
  asleep: boolean;
  /** Render the AMOLED always-on frame. */
  aod: boolean;
  /** Apply the face's `defaults: {aod: {mask: ...}}` when rendering `aod`. */
  aod_mask: boolean;
  /** The type each `config: slots:` slot is drawn showing, as `[slot, type]` pairs. */
  picks: readonly (readonly [string, string])[];
  /** Set the panel into the device's simulator skin (`frameInSkin`); a device without one renders bare. */
  skin: boolean;
}

export function previewOptions(fields: Partial<PreviewOptions> = {}): PreviewOptions {
  return {
    scale: 2, quantise: true, mask_shape: true, sample: null, style: null, time: null, date: null, asleep: false, aod: false,
    aod_mask: true, picks: [], skin: false, ...fields,
  };
}

/** `PreviewOptions.style` named an entry the design does not declare. */
export class UnknownStyleError extends Error {}

/** The `config: style:` entry `name` asks for, or the default entry; `null` with no style axis. */
export function resolveStyleEntry(face: Face, name: string | null): StyleEntry | null {
  const axis = face.config_style;
  if (name === null) return axis !== null ? axis.defaultEntry : null;
  if (axis === null) {
    throw new UnknownStyleError(`'${face.name}' declares no 'config: style:' at all, so there is no entry named '${name}' to render`);
  }
  const found = axis.entries.find((entry) => entry.name === name);
  if (found !== undefined) return found;
  throw new UnknownStyleError(`'${name}' is not one of this design's config.style entries -- declared: ${axis.entries.map((e) => e.name).join(", ")}`);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** The `date.*` readings for one day, in the shapes the watch gives them. */
export function dateValues(year: number, month: number, day: number): Map<string, ExprValue> {
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    throw new RangeError("day is out of range for month");
  }
  const weekday = (date.getUTCDay() + 6) % 7; // Monday = 0
  return new Map<string, ExprValue>([
    ["date.year", year], ["date.month_number", month], ["date.month", MONTHS[month - 1]!], ["date.day", day],
    ["date.day_of_week", DAYS[weekday]!], ["date.weekday", ((weekday + 1) % 7) + 1],
  ]);
}

/** The readings a frame draws at: `SAMPLE`, the overrides, the palette, the `config:` defaults and the style's scheme. */
export function sampleValues(resolved: ResolvedFace, options: PreviewOptions, entry: StyleEntry | null): Map<string, ExprValue> {
  const values = new Map(SAMPLE);
  if (options.time !== null) {
    const [hour, minute, second] = options.time;
    values.set("time.hour", hour);
    values.set("time.minute", minute);
    values.set("time.second", second);
  }
  if (options.date !== null) for (const [k, v] of dateValues(...options.date)) values.set(k, v);
  if (options.sample !== null) for (const [k, v] of options.sample) values.set(k, v);
  const setDefault = (key: string, value: ExprValue): void => {
    if (!values.has(key)) values.set(key, value);
  };
  for (const [name, color] of resolved.face.palette) setDefault(`color.${name}`, color.value);
  for (const configEntry of resolved.face.config.values()) setDefault(`color.${configEntry.role}`, configEntry.default.value);
  if (entry !== null && entry.colors !== null) {
    for (const [role, color] of resolved.face.color_scheme.get(entry.colors)!.colors) setDefault(`color.${role}`, color.value);
  }
  return values;
}

/**
 * Every system or vector face a run of renders drew with, keyed by its
 * metric: one map handed to every render, read once by `standInWarning`.
 */
export type UsedFaces = Map<string, [FontMetric, SystemFace]>;

/** A `Renderer` over a fresh canvas of the device's native size, filled with `ground`. */
export function newRenderer(resolved: ResolvedFace, options: PreviewOptions, values: Values, ground: RGB,
  usedFaces: UsedFaces | null = null): Renderer {
  const device = resolved.device;
  const renderer = new Renderer(resolved, newImage(device.width, device.height, ground), 1, values, options);
  renderer.usedFaces = usedFaces;
  return renderer;
}

/** What this frame draws, in draw order, under the chosen style's layout. */
export function frameItems(resolved: ResolvedFace, options: PreviewOptions, entry: StyleEntry | null): Placed[] {
  const activeLayout = entry !== null ? entry.layout : null;
  return frameMembers(resolved.shownItems, options.aod ? "aod" : "active").filter((placed) => inLayout(placed, activeLayout));
}

/** Render `resolved` to an image, recording the system faces it draws with into `usedFaces`. */
export function render(resolved: ResolvedFace, options: PreviewOptions = previewOptions(), usedFaces: UsedFaces | null = null): Frame {
  const entry = resolveStyleEntry(resolved.face, options.style);
  const values = sampleValues(resolved, options, entry);
  const renderer = newRenderer(resolved, options, values, [0, 0, 0], usedFaces);
  renderer.renderSequence(frameItems(resolved, options, entry), ringGroups(resolved.face.elements));
  return finishFrame(renderer.image, resolved, options, values);
}

/** The whole-frame steps once the elements are drawn: the AOD mask, the palette, the bezel, the enlargement, then the skin. */
export function finishFrame(image: Image, resolved: ResolvedFace, options: PreviewOptions, values: Values): Frame {
  const device = resolved.device;
  const scale = Math.max(1, options.scale);
  if (options.aod && resolved.face.aod_mask && options.aod_mask) {
    image = aodMask.apply(image, Math.trunc(Number(numberOf(values.get("time.minute") ?? 0))));
  }
  if (options.quantise) image = quantise(image, device.displayColors);
  if (options.mask_shape) image = maskShape(image, device);
  image = enlarge(image, scale);
  if (options.skin) return frameInSkin(image, device, scale) ?? image;
  return image;
}

function numberOf(value: unknown): number {
  const n = expr.asNumber(value);
  return typeof n === "bigint" ? Number(n) : typeof n === "number" ? n : n.value;
}

/** What a text or glyph paints, recorded instead of painted while `Renderer.stamps` is a list. */
export interface Stamp {
  kind: "mask" | "rgba" | "box";
  image: Tile | null;
  x: number;
  y: number;
  color: RGB;
  size: [number, number];
}

/** One rasterised glyph or run: a coverage tile and where its top-left lands. */
interface Coverage {
  tile: Tile;
  x: number;
  y: number;
}

type Segment = [number, number, number, number];

/** Rasterise `segments` (canvas pixels) into a mask tile cropped to its ink; `null` for no ink. */
function coverage(segments: readonly Segment[]): Coverage | null {
  const box = bounds(segments);
  if (box === null) return null;
  const x0 = Math.floor(box[0]), y0 = Math.floor(box[1]);
  const width = Math.ceil(box[2]) - x0 + 2, height = Math.ceil(box[3]) - y0 + 1;
  const pixels = rasterise(segments, x0, y0, width, height);
  let ix0 = width, iy0 = height, ix1 = -1, iy1 = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!pixels[y * width + x]) continue;
      if (x < ix0) ix0 = x;
      if (x > ix1) ix1 = x;
      if (y < iy0) iy0 = y;
      if (y > iy1) iy1 = y;
    }
  }
  if (ix1 < 0) return null;
  const w = ix1 - ix0 + 1, h = iy1 - iy0 + 1;
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      data[o] = data[o + 1] = data[o + 2] = 255;
      data[o + 3] = pixels[(iy0 + y) * width + ix0 + x]!;
    }
  }
  return { tile: { width: w, height: h, kind: "mask", data }, x: x0 + ix0, y: y0 + iy0 };
}

/** A one-byte-a-pixel coverage as a mask tile. */
function maskTile(width: number, height: number, alpha: Uint8Array): Tile {
  const data = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = 255;
    data[i * 4 + 3] = alpha[i]!;
  }
  return { width, height, kind: "mask", data };
}

/** `tile` `s` times larger, by pixel replication. */
function enlargeTile(tile: Tile, s: number): Tile {
  if (s === 1) return tile;
  const width = tile.width * s, height = tile.height * s;
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const from = (Math.floor(y / s) * tile.width + Math.floor(x / s)) * 4, to = (y * width + x) * 4;
      for (let c = 0; c < 4; c++) data[to + c] = tile.data[from + c]!;
    }
  }
  return { width, height, kind: tile.kind, data };
}

/** A face's glyph outline for `ch`, flattened, its pen at the origin on the baseline. */
function glyphSegments(face: SystemFace, ch: string): Segment[] {
  if (face.file === null) return [];
  return flatten(glyphOutline(face.file, ch, face.drawSize));
}

/**
 * Draws one resolved face into a canvas the way the generated code draws it
 * on the watch: each element's draw program, evaluated, in the order the
 * view draws them, outlined groups' rings included.
 */
export class Renderer {
  readonly resolved: ResolvedFace;
  image: Image;
  readonly scale: number;
  values: Values;
  readonly options: PreviewOptions;
  private plan: ReadPlan | null = null;
  /** While a list, text and glyphs land here as `Stamp`s instead of on the canvas. */
  stamps: Stamp[] | null = null;
  /** Where the system faces drawn with are recorded, for `standInWarning`. */
  usedFaces: UsedFaces | null = null;

  constructor(resolved: ResolvedFace, image: Image, scale: number, values: Values, options: PreviewOptions) {
    this.resolved = resolved;
    this.image = image;
    this.scale = scale;
    this.values = values;
    this.options = options;
  }

  private systemFace(metric: FontMetric, scale: number = this.scale): SystemFace | null {
    const face = this.resolved.device.db.measure.systemFace(metric, scale);
    if (this.usedFaces !== null && face !== null && !this.usedFaces.has(metric.key)) this.usedFaces.set(metric.key, [metric, face]);
    return face;
  }

  // -- aod: restyling --

  private dimRgb(rgb: RGB, [num, den]: [number, number]): RGB {
    const dimmed = new Color(...rgb).dim(num, den);
    return [dimmed.r, dimmed.g, dimmed.b];
  }

  /** The drawn RGB for one colour role: while `aod` renders, the `aod:` override or the colour, dimmed by its `dim:`. */
  aodColor(element: Element, key: "color" | "track_color" | "icon_color", baseExpr: Expression | null, values: Values | null = null): RGB {
    const base = this.color(baseExpr, values);
    if (!this.options.aod || element.aod === null) return base;
    const override = element.aod[key];
    const asleep = override !== null ? this.color(override) : base;
    return element.aod.dim !== null ? this.dimRgb(asleep, element.aod.dim) : asleep;
  }

  /** `asleep`'s RGB dimmed by the element's `dim:` while `aod` renders an element the AOD frame draws; `awake`'s otherwise. */
  aodDimmed(element: Element, asleep: Expression | null, awake: Expression | null = asleep, values: Values | null = null): RGB {
    if (!this.options.aod || element.aod === null) return this.color(awake, values);
    const rgb = this.color(asleep, values);
    return element.aod.dim !== null ? this.dimRgb(rgb, element.aod.dim) : rgb;
  }

  // -- dispatch --

  /** Does `placed` draw in this frame? */
  shows(placed: Placed): boolean {
    const visible = this.options.aod && placed.element.aod !== null ? placed.element.aod.visible : placed.element.visible;
    return this.visible(visible);
  }

  /** The reads and guards of the view this preview stands in for, built once. */
  get readPlan(): ReadPlan {
    if (this.plan === null) this.plan = new ReadPlan(this.resolved);
    return this.plan;
  }

  valueGuards(placed: Placed): string[] {
    return this.readPlan.valueGuards(placed);
  }

  renderElement(placed: Placed): void {
    if (this.shows(placed)) drawProgram.paint(this, placed);
  }

  /** An outlined group's ring: every member's ring pass, each at its own width, in the group's colour. */
  renderRing(ring: RingGroup, members: readonly Placed[]): void {
    const outline = ring.group.outline!;
    const color = this.aodDimmed(ring.group, outline.color);
    for (const member of members) {
      if (this.shows(member)) drawProgram.paint(this, member, new RingPass("ringColor", ring.widthOf(member.id)), color);
    }
  }

  /** Draw `items` in order, each outlined group's ring just before its first member here. */
  renderSequence(items: readonly Placed[], rings: readonly RingGroup[]): void {
    for (const placed of items) {
      for (const ring of rings) {
        const members = items.filter((p) => ring.ids.has(p.id));
        if (members.length > 0 && members[0] === placed) this.renderRing(ring, members);
      }
      this.renderElement(placed);
    }
  }

  // -- text --

  /**
   * Draw `text` upright at `anchor`: its line box placed by `align` and
   * `verticalAlign`, then glyph by glyph from the baked sheet or the device
   * face. With neither, `box` is outlined instead.
   */
  drawText(font: BakedFont | null, text: string, anchor: readonly [number, number], align: string, verticalAlign: string,
    metric: FontMetric | null, color: RGB, box: IntBox | null = null): void {
    const s = this.scale;
    if (font !== null && font.sheet !== null) {
      const width = font.measure(text)[0] * s, lineHeight = font.line_height * s;
      const [left, top] = this.lineBox(anchor, width, lineHeight, align, verticalAlign);
      this.blitBakedLine(font, text, left, top, color);
      return;
    }
    const face = metric !== null ? this.systemFace(metric) : null;
    if (face === null) {
      this.markExtent(box);
      return;
    }
    const [left, top] = this.lineBox(anchor, face.width(text), face.lineHeight, align, verticalAlign);
    this.drawSystemLine(face, left, top + face.baseline, text, color);
  }

  private lineBox(anchor: readonly [number, number], width: number, lineHeight: number, align: string, verticalAlign: string): [number, number] {
    const s = this.scale;
    const left = anchor[0] * s - (align === "left" ? 0 : align === "right" ? width : width / 2);
    const top = anchor[1] * s - ({ top: 0, center: lineHeight / 2, bottom: lineHeight } as Record<string, number>)[verticalAlign]!;
    return [left, top];
  }

  /** Paste `text`'s baked glyphs pen-wise from the (scaled) top-left of their line box. */
  private blitBakedLine(font: BakedFont, text: string, left: number, top: number, color: RGB): void {
    let pen = left;
    for (const ch of text) {
      const glyph = font.glyphs.get(ch);
      if (glyph === undefined) continue;
      this.pasteGlyph(font.sheet!, glyph, pen, top, color);
      pen += glyph.xadvance * this.scale;
    }
  }

  /** One glyph tile off a baked sheet, tinted, at `(x, y)`: the top-left of the text's (or icon's) own box, scaled. */
  pasteGlyph(sheet: Sheet, glyph: GlyphBox, x: number, y: number, color: RGB): void {
    if (!(glyph.width && glyph.height)) return;
    const alpha = new Uint8Array(glyph.width * glyph.height);
    for (let row = 0; row < glyph.height; row++) {
      alpha.set(sheet.bytes.subarray((glyph.y + row) * sheet.width + glyph.x, (glyph.y + row) * sheet.width + glyph.x + glyph.width), row * glyph.width);
    }
    const tile = enlargeTile(maskTile(glyph.width, glyph.height, alpha), this.scale);
    this.place(tile, Math.trunc(x + glyph.xoffset * this.scale), Math.trunc(y + glyph.yoffset * this.scale), color);
  }

  /** A tile painted, or recorded while `stamps` is a list. */
  private place(tile: Tile, x: number, y: number, color: RGB): void {
    if (this.stamps !== null) {
      this.stamps.push({ kind: tile.kind, image: tile, x, y, color, size: [0, 0] });
      return;
    }
    paste(this.image, tile, x, y, color);
  }

  /** A system-font line glyph by glyph, each on the pen position the face's advances give. */
  private drawSystemLine(face: SystemFace, left: number, baselineY: number, text: string, color: RGB): void {
    const chars = Array.from(text);
    const advances = face.advances(text);
    let pen = left;
    chars.forEach((ch, i) => {
      if (face.bitmap !== null) {
        this.drawBitmapGlyph(face, ch, pen, baselineY - face.baseline, color);
      } else {
        const found = coverage(glyphSegments(face, ch).map(([ax, ay, bx, by]): Segment => [ax + pen, ay + baselineY, bx + pen, by + baselineY]));
        if (found !== null) this.place(found.tile, found.x, found.y, color);
      }
      pen += advances[i]!;
    });
  }

  /** A bitmap face's `.cft` cell, its top at `top`, tinted through its ink levels. */
  private drawBitmapGlyph(face: SystemFace, ch: string, pen: number, top: number, color: RGB): void {
    const font = face.bitmap!;
    const glyph = font.glyph(ch);
    if (glyph.advance <= 0 || glyph.height <= 0) return;
    const maxLevel = font.maxLevel || 1;
    const alpha = glyph.levels.map((level) => Math.floor(level * 255 / maxLevel));
    const tile = enlargeTile(maskTile(glyph.advance, glyph.height, alpha), this.scale);
    this.place(tile, roundHalfEven(pen), roundHalfEven(top), color);
  }

  // -- vector fonts, curve: --

  /**
   * A `face:` font's draw: upright (as a system font), `angled` (the whole
   * string turned about the anchor) or `radial` (each glyph placed round a
   * circle). `angleGarmin` is Garmin's convention: degrees counter-clockwise
   * from 3 o'clock.
   */
  drawVectorText(text: string, anchor: readonly [number, number], align: string, verticalAlign: string, metric: FontMetric | null,
    color: RGB, style: string | null, angleGarmin: number, radiusPx: number, direction: string | null, box: IntBox | null = null): void {
    if (style === null) {
      this.drawText(null, text, anchor, align, verticalAlign, metric, color, box);
      return;
    }
    const face = metric !== null ? this.systemFace(metric) : null;
    if (face === null) return;
    const s = this.scale;
    if (style === "angled") {
      this.turnedRun(face, text, angleGarmin, align, verticalAlign, [anchor[0] * s, anchor[1] * s], color);
    } else {
      this.radialRun(anchor, radiusPx, angleGarmin, direction, face, text, align, verticalAlign, color);
    }
  }

  /**
   * `curve: {style: radial}`: each glyph turned and placed round the circle
   * of `radiusPx` centred on the anchor, at the arc position of the middle
   * of its own advance. `clockwise` faces outward and walks with decreasing
   * Garmin angle; `counter_clockwise` faces inward and walks the other way.
   */
  private radialRun(anchor: readonly [number, number], radiusPx: number, angleGarmin: number, direction: string | null,
    face: SystemFace, text: string, align: string, verticalAlign: string, color: RGB): void {
    const s = this.scale;
    const radius = radiusPx * s;
    if (radius <= 0) return;
    const cx = anchor[0] * s, cy = anchor[1] * s;
    const advances = face.advances(text);
    const total = advances.reduce((a, b) => a + b, 0);
    const alignOffset = radialAlignOffset(align, total);
    const counterClockwise = direction === "counter_clockwise";
    const sign = radialDirectionSign(direction);
    const facing = counterClockwise ? 90.0 : -90.0;
    let glyphVerticalAlign = verticalAlign, glyphRadius = radius;
    if (verticalAlign === "bottom") {
      glyphVerticalAlign = "top";
      glyphRadius = radius + (counterClockwise ? -face.baseline : face.baseline);
    }
    const base = radians(angleGarmin);
    let pen = 0.0;
    Array.from(text).forEach((ch, i) => {
      const advance = advances[i]!;
      const theta = base + sign * ((pen + advance / 2.0 - alignOffset) / radius);
      const px = cx + glyphRadius * Math.cos(theta), py = cy - glyphRadius * Math.sin(theta);
      this.turnedRun(face, ch, degrees(theta) + facing, "center", glyphVerticalAlign, [px, py], color);
      pen += advance;
    });
  }

  /**
   * `run` turned by `angleGarmin` about the point `align`/`verticalAlign`
   * place it at, that point landing on `anchorXy` (scaled pixels): each
   * glyph's outline is laid out upright about the line box's centre, turned,
   * and rasterised in place.
   */
  private turnedRun(face: SystemFace, run: string, angleGarmin: number, align: string, verticalAlign: string,
    anchorXy: readonly [number, number], color: RGB): void {
    if (!run || face.bitmap !== null) return; // a `face:` font is an outline face
    const width = face.width(run), lineHeight = face.lineHeight;
    if (width <= 0 || lineHeight <= 0) return;
    const theta = radians(angleGarmin);
    const cos = Math.cos(theta), sin = Math.sin(theta);
    const [dx, dy] = alignmentShift(width, lineHeight, align, verticalAlign);
    const centerX = anchorXy[0] + dx * cos + dy * sin, centerY = anchorXy[1] - dx * sin + dy * cos;
    const turn = (x: number, y: number): [number, number] => [centerX + x * cos + y * sin, centerY - x * sin + y * cos];
    const segments: Segment[] = [];
    const advances = face.advances(run);
    let pen = -width / 2;
    const baseline = -lineHeight / 2 + face.baseline;
    Array.from(run).forEach((ch, i) => {
      for (const [ax, ay, bx, by] of glyphSegments(face, ch)) {
        segments.push([...turn(ax + pen, ay + baseline), ...turn(bx + pen, by + baseline)]);
      }
      pen += advances[i]!;
    });
    const found = coverage(segments);
    if (found !== null) this.place(found.tile, found.x, found.y, color);
  }

  // -- shared --

  /** Outline `box` in dark grey where text cannot be drawn at its real size; an empty box draws nothing. */
  private markExtent(box: IntBox | null): void {
    if (box === null || box.width <= 0 || box.height <= 0) return;
    const [x0, y0, x1, y1] = this.rect(box).map(Math.trunc) as [number, number, number, number];
    if (this.stamps !== null) {
      this.stamps.push({ kind: "box", image: null, x: x0, y: y0, color: [64, 64, 64], size: [x1 - x0, y1 - y0] });
      return;
    }
    rectangle(this.image, [x0, y0, x1, y1], { outline: [64, 64, 64], width: 1 });
  }

  /** `box` scaled to preview pixels, as `[x0, y0, x1, y1]`. */
  rect(box: IntBox): number[] {
    const s = this.scale;
    return [box.x * s, box.y * s, box.right * s - 1, box.bottom * s - 1];
  }

  /** `visible:` on the sample readings: absent means hidden. */
  visible(expression: Expression | null, values: Values | null = null): boolean {
    if (expression === null) return true;
    if (expression.constant !== null) return expression.constant === true;
    if (expression.ast === null) return true;
    return expr.evaluate(expression.ast, values ?? this.values) === true;
  }

  /** A colour expression's RGB at the sample readings; white when absent. */
  color(expression: Expression | null, values: Values | null = null): RGB {
    if (expression === null) return [255, 255, 255];
    let value: ExprValue = expression.constant;
    if (value === null && expression.ast !== null) value = expr.evaluate(expression.ast, values ?? this.values);
    if (value === null) return [255, 255, 255];
    const color = Color.parse(Math.trunc(numberOf(value)));
    return [color.r, color.g, color.b];
  }
}

/** Snap every pixel to what the panel shows, by the palette's own rule for its size. */
export function quantise(image: Image, displayColors: number | null): Image {
  if (displayColors !== 64 && displayColors !== 2) return image;
  const out = { width: image.width, height: image.height, data: new Uint8ClampedArray(image.data) };
  for (let i = 0; i < out.data.length; i += 4) {
    if (displayColors === 64) {
      out.data[i] = MIP64_SNAP[out.data[i]!]!;
      out.data[i + 1] = MIP64_SNAP[out.data[i + 1]!]!;
      out.data[i + 2] = MIP64_SNAP[out.data[i + 2]!]!;
    } else {
      const sum = MONO_LUMINANCE[0]![out.data[i]!]! + MONO_LUMINANCE[1]![out.data[i + 1]!]! + MONO_LUMINANCE[2]![out.data[i + 2]!]!;
      out.data[i] = out.data[i + 1] = out.data[i + 2] = sum > MONO_THRESHOLD ? 255 : 0;
    }
  }
  return out;
}

/** `image` `scale` times larger, each pixel a `scale` x `scale` block. */
export function enlarge(image: Image, scale: number): Image {
  if (scale <= 1) return image;
  const width = image.width * scale, height = image.height * scale;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    const from = Math.floor(y / scale) * image.width;
    for (let x = 0; x < width; x++) {
      const a = (from + Math.floor(x / scale)) * 4, b = (y * width + x) * 4;
      data[b] = image.data[a]!;
      data[b + 1] = image.data[a + 1]!;
      data[b + 2] = image.data[a + 2]!;
      data[b + 3] = 255;
    }
  }
  return { width, height, data };
}

/** Grey out what the bezel hides: the inscribed circle on a round screen, else the skin's visible area. */
export function maskShape(image: Image, device: Device): Image {
  let visible: (i: number) => boolean;
  if (device.shape === "round") {
    const mask = newImage(image.width, image.height, [0, 0, 0]);
    ellipse(mask, [0, 0, image.width - 1, image.height - 1], { fill: [255, 255, 255] });
    visible = (i) => mask.data[i * 4] === 255;
  } else {
    const skin = visibleMask(device);
    if (skin === null) return image;
    visible = (i) => {
      const x = i % image.width, y = Math.floor(i / image.width);
      const sx = Math.floor(x * skin.width / image.width), sy = Math.floor(y * skin.height / image.height);
      return skin.visible[sy * skin.width + sx] === 1;
    };
  }
  const out = newImage(image.width, image.height, [24, 24, 24]);
  for (let i = 0; i < image.width * image.height; i++) {
    if (!visible(i)) continue;
    out.data[i * 4] = image.data[i * 4]!;
    out.data[i * 4 + 1] = image.data[i * 4 + 1]!;
    out.data[i * 4 + 2] = image.data[i * 4 + 2]!;
  }
  return out;
}

// -- whole-run extras: every style side by side, the AOD heat map, the skin --

/** Where a substituted face was drawn from: its file's name, or Pillow's default. */
function drawnWith(face: SystemFace): string {
  return face.path ? face.path.slice(face.path.lastIndexOf("/") + 1) : "Pillow default";
}

/**
 * One warning naming every face `usedFaces` recorded at match level
 * `substitute` or `none`, one row per substituted typeface, or `null`.
 */
export function standInWarning(usedFaces: UsedFaces): string | null {
  const rows = new Map<string, [string, string, string]>();
  for (const [metric, face] of usedFaces.values()) {
    if (face.match !== "substitute" && face.match !== "none") continue;
    const row: [string, string, string] = [metric.face || metric.symbol, drawnWith(face), face.match];
    rows.set(JSON.stringify(row), row);
  }
  const affected = [...rows.values()].sort((a, b) => cmp(a[0], b[0]) || cmp(a[1], b[1]) || cmp(a[2], b[2]));
  if (affected.length === 0) return null;
  const nameWidth = Math.max(...affected.map((r) => r[0].length));
  const drawnWidth = Math.max(...affected.map((r) => r[1].length));
  const count = affected.length;
  return [
    `warning: ${count} font${count !== 1 ? "s" : ""} ${count !== 1 ? "were" : "was"} drawn with a stand-in, not Garmin's own face --`,
    "         glyph shapes will not match the simulator:",
    ...affected.map(([name, drawn, match]) => `           ${name.padEnd(nameWidth)}  -> ${drawn.padEnd(drawnWidth)}  (${match})`),
    "         install the SDK Manager's Fonts directory at vendor/fonts/,",
    "         or set WFB_FONTS / pass --fonts DIR -- see `wfb doctor`.",
  ].join("\n");
}

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** One line when a 2-colour device's image was snapped to black and white, or `null`. */
export function monoGuessWarning(devices: Iterable<Device>, quantised: boolean): string | null {
  const mono = [...devices].filter((d) => d.displayColors === 2).map((d) => d.id).sort();
  if (!quantised || mono.length === 0) return null;
  return `warning: ${mono.join(", ")} show(s) 2 colours; the preview snaps every other colour to black or white by luminance, `
    + "but how the watch maps them is unverified (docs/limitations.md)";
}

/** `text` drawn with `face`, its advance centred on `cx` and its line box's middle on `cy`. */
function drawCaption(image: Image, face: SystemFace, cx: number, cy: number, text: string, color: RGB): void {
  let pen = cx - face.width(text) / 2;
  const baseline = cy - face.lineHeight / 2 + face.baseline;
  const advances = face.advances(text);
  Array.from(text).forEach((ch, i) => {
    const found = coverage(glyphSegments(face, ch).map(([ax, ay, bx, by]): Segment => [ax + pen, ay + baseline, bx + pen, by + baseline]));
    if (found !== null) paste(image, found.tile, found.x, found.y, color);
    pen += advances[i]!;
  });
}

/** A frame that may carry transparency: a skinned render keeps the skin's own background. */
export interface Frame extends Image {
  rgba?: boolean;
}

/**
 * Every `config: style:` entry rendered side by side in one image, each
 * panel under a caption naming the entry.
 */
export function renderAllStyles(resolved: ResolvedFace, options: PreviewOptions = previewOptions(),
  usedFaces: UsedFaces | null = null): Frame {
  const face = resolved.face;
  const axis = face.config_style;
  if (axis === null) {
    throw new UnknownStyleError(`'${face.name}' declares no 'config: style:' at all, so there is nothing for --all-styles to lay out`);
  }
  const captionHeight = Math.max(16, 10 * Math.max(1, options.scale));
  const panels = axis.entries.map((entry): [Frame, string] => {
    return [render(resolved, { ...options, style: entry.name }, usedFaces), face.styleLabel(entry) || entry.name];
  });
  const gap = Math.max(1, options.scale);
  const width = panels.reduce((n, [p]) => n + p.width, 0) + gap * (panels.length - 1);
  const height = Math.max(...panels.map(([p]) => p.height)) + captionHeight;
  const composed = newImage(width, height, [16, 16, 16]);
  const captionFace = fontForHeight(captionHeight - 4);
  let x = 0;
  for (const [panel, label] of panels) {
    if (panel.rgba) composite(composed, panel, x, captionHeight);
    else pasteImage(composed, panel, x, captionHeight);
    if (captionFace !== null) drawCaption(composed, captionFace, x + panel.width / 2, captionHeight / 2, label, [220, 220, 220]);
    x += panel.width + gap;
  }
  return composed;
}

function pasteImage(into: Image, from: Image, x0: number, y0: number): void {
  for (let y = 0; y < from.height; y++) {
    const ty = y0 + y;
    if (ty < 0 || ty >= into.height) continue;
    for (let x = 0; x < from.width; x++) {
      const tx = x0 + x;
      if (tx < 0 || tx >= into.width) continue;
      const a = (y * from.width + x) * 4, b = (ty * into.width + tx) * 4;
      into.data[b] = from.data[a]!;
      into.data[b + 1] = from.data[a + 1]!;
      into.data[b + 2] = from.data[a + 2]!;
      into.data[b + 3] = 255;
    }
  }
}

/** Minutes in a day: what `--minute` accepts and how many frames the heat map sums. */
export const MINUTES_PER_DAY = 24 * 60;

/**
 * The AOD frame summed over every minute of the day: a pixel lit (any
 * colour but black) every minute is white. Returns the image and the peak
 * count as a share of the minutes rendered.
 */
export function renderAodHeatmap(resolved: ResolvedFace, options: PreviewOptions = previewOptions(),
  usedFaces: UsedFaces | null = null, minutes: readonly number[] | null = null): [Frame, number] {
  const base = { ...options, aod: true, mask_shape: false, skin: false };
  const device = resolved.device;
  const scale = Math.max(1, options.scale);
  const list = minutes ?? Array.from({ length: MINUTES_PER_DAY }, (_, i) => i);
  const counts = new Uint32Array(device.width * device.height);
  for (const minute of list) {
    const frame = render(resolved, { ...base, scale: 1, time: [Math.floor(minute / 60), minute % 60, 0] }, usedFaces);
    for (let i = 0; i < counts.length; i++) {
      if (frame.data[i * 4] || frame.data[i * 4 + 1] || frame.data[i * 4 + 2]) counts[i]!++;
    }
  }
  const total = Math.max(list.length, 1);
  let heat: Frame = newImage(device.width, device.height, [0, 0, 0]);
  let peak = 0;
  for (let i = 0; i < counts.length; i++) {
    const v = Math.min(255, Math.trunc(counts[i]! * (255.0 / total)));
    heat.data[i * 4] = heat.data[i * 4 + 1] = heat.data[i * 4 + 2] = v;
    peak = Math.max(peak, counts[i]!);
  }
  if (options.mask_shape) heat = maskShape(heat, device);
  heat = enlarge(heat, scale);
  if (options.skin) heat = frameInSkin(heat, device, scale) ?? heat;
  return [heat, peak / total];
}

const skins = new Map<string, Image | null>();

/** The device's skin PNG as RGBA, `scale` times larger by Lanczos, and where the panel sits in it. */
export function skinFor(device: Device, scale: number): [Image, [number, number]] | null {
  const found = skinOf(device);
  if (found === null) return null;
  const [name, [x, y, width, height]] = found;
  const key = `${device.id}\0${scale}`;
  if (!skins.has(key)) {
    const bytes = device.db.files.file(device.id, name);
    const decoded = bytes === undefined ? null : decodePng(bytes);
    let image: Image | null = null;
    if (decoded !== null && x >= 0 && y >= 0 && x + width <= decoded.width && y + height <= decoded.height) {
      image = { width: decoded.width, height: decoded.height, data: new Uint8ClampedArray(decoded.pixels) };
      if (scale !== 1) image = lanczos(image, image.width * scale, image.height * scale);
    }
    skins.set(key, image);
  }
  const image = skins.get(key)!;
  return image === null ? null : [image, [x * scale, y * scale]];
}

/** Whether `frameInSkin` can frame this device. */
export function hasSkin(device: Device): boolean {
  return skinFor(device, 1) !== null;
}

/** `image` set into the device's simulator skin at its panel location, or `null` without one. RGBA. */
export function frameInSkin(image: Image, device: Device, scale: number): Frame | null {
  const found = skinFor(device, scale);
  if (found === null) return null;
  const [skin, [ox, oy]] = found;
  const framed: Frame = { width: skin.width, height: skin.height, data: new Uint8ClampedArray(skin.width * skin.height * 4), rgba: true };
  pasteImage(framed, image, ox, oy);
  // Pillow's `alpha_composite`: the skin over the frame.
  for (let i = 0; i < framed.data.length; i += 4) {
    const sa = skin.data[i + 3]! / 255, da = framed.data[i + 3]! / 255;
    const oa = sa + da * (1 - sa);
    if (oa === 0) {
      framed.data[i] = framed.data[i + 1] = framed.data[i + 2] = framed.data[i + 3] = 0;
      continue;
    }
    for (let c = 0; c < 3; c++) {
      framed.data[i + c] = Math.round((skin.data[i + c]! * sa + framed.data[i + c]! * da * (1 - sa)) / oa);
    }
    framed.data[i + 3] = Math.round(oa * 255);
  }
  return framed;
}

/** One line when `--skin` found no skin for some device, or `null`. */
export function skinMissingWarning(devices: Iterable<Device>, skin: boolean): string | null {
  const bare = [...devices].filter((d) => !hasSkin(d)).map((d) => d.id).sort();
  if (!skin || bare.length === 0) return null;
  return `warning: ${bare.join(", ")} ha(s) no simulator skin in the device files; rendered the bare screen instead`;
}

function sinc(x: number): number {
  if (x === 0) return 1;
  const px = Math.PI * x;
  return Math.sin(px) / px;
}

/**
 * Pillow's Lanczos resize (support 3), on premultiplied alpha as Pillow
 * resizes RGBA: separable, horizontal then vertical, in floating point
 * where Pillow rounds through fixed point, so an edge pixel may differ by one.
 */
function lanczos(image: Image, width: number, height: number): Image {
  const coefficients = (inSize: number, outSize: number): [number, number[]][] => {
    const scale = inSize / outSize;
    const filterscale = Math.max(scale, 1);
    const support = 3 * filterscale;
    const out: [number, number[]][] = [];
    for (let x = 0; x < outSize; x++) {
      const center = (x + 0.5) * scale;
      const xmin = Math.max(Math.trunc(center - support + 0.5), 0);
      const xmax = Math.min(Math.trunc(center + support + 0.5), inSize);
      const weights: number[] = [];
      for (let i = xmin; i < xmax; i++) {
        const t = (i - center + 0.5) / filterscale;
        weights.push(Math.abs(t) < 3 ? sinc(t) * sinc(t / 3) : 0);
      }
      const sum = weights.reduce((a, b) => a + b, 0);
      out.push([xmin, weights.map((w) => (sum ? w / sum : 0))]);
    }
    return out;
  };
  const premultiplied = new Float64Array(image.width * image.height * 4);
  for (let i = 0; i < premultiplied.length; i += 4) {
    const a = image.data[i + 3]! / 255;
    premultiplied[i] = image.data[i]! * a;
    premultiplied[i + 1] = image.data[i + 1]! * a;
    premultiplied[i + 2] = image.data[i + 2]! * a;
    premultiplied[i + 3] = image.data[i + 3]!;
  }
  const clamp = (v: number): number => Math.min(255, Math.max(0, v));
  const across = coefficients(image.width, width);
  const middle = new Float64Array(width * image.height * 4);
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < width; x++) {
      const [start, weights] = across[x]!;
      for (let c = 0; c < 4; c++) {
        let v = 0;
        weights.forEach((w, k) => { v += w * premultiplied[(y * image.width + start + k) * 4 + c]!; });
        middle[(y * width + x) * 4 + c] = clamp(Math.round(v));
      }
    }
  }
  const down = coefficients(image.height, height);
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    const [start, weights] = down[y]!;
    for (let x = 0; x < width; x++) {
      const px = new Array<number>(4);
      for (let c = 0; c < 4; c++) {
        let v = 0;
        weights.forEach((w, k) => { v += w * middle[((start + k) * width + x) * 4 + c]!; });
        px[c] = clamp(Math.round(v));
      }
      const a = px[3]!;
      const at = (y * width + x) * 4;
      data[at + 3] = a;
      for (let c = 0; c < 3; c++) data[at + c] = a === 0 ? 0 : clamp(Math.round(px[c]! * 255 / a));
    }
  }
  return { width, height, data };
}

/** The frame as PNG bytes: RGB, or RGBA for a skinned frame. */
export function pngBytes(frame: Frame): Uint8Array {
  if (frame.rgba) return encodePng(frame.width, frame.height, new Uint8Array(frame.data.buffer, frame.data.byteOffset, frame.data.byteLength), 4);
  const rgb = new Uint8Array(frame.width * frame.height * 3);
  for (let i = 0, j = 0; i < frame.data.length; i += 4, j += 3) {
    rgb[j] = frame.data[i]!;
    rgb[j + 1] = frame.data[i + 1]!;
    rgb[j + 2] = frame.data[i + 2]!;
  }
  return encodePng(frame.width, frame.height, rgb, 3);
}
