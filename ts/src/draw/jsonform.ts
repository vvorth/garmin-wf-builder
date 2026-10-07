// Backend 3: a draw program as JSON for one frame, and the reference
// rasteriser of that JSON.
//
// `toJson` partly evaluates an element's program for the frame being
// painted: every reading, colour, string and always-on choice is folded to
// its value, and every `Layout` constant stays named beside its value
// (`{const: "CLOCK_X", value: 130, add: -1}`), so an editor can redraw the
// layer with a dragged constant changed. Text and icons are laid out here:
// every `text` and `glyph` op carries its `run`, the tiles the renderer would
// paste, each at a whole-pixel offset from the op's anchor. The tiles live
// once each in a `Tiles` store.
import { zlibSync } from "fflate";
import type { FontMetric } from "../devices/device.ts";
import { WholeFloat } from "../edit/yaml.ts";
import type { Placed } from "../layout.ts";
import type { Renderer, RGB } from "../preview.ts";
import { deepEqual } from "../py.ts";
import { drawArc, fillPolygon } from "../raster/garmin.ts";
import { type Image, type JsonNum, type JsonOp, paste, primitive, rectangle, type RunItem, type Tile } from "../raster/pillow.ts";
import { IntBox } from "../units.ts";
import * as barrel from "./barrel.ts";
import { val } from "./barrel.ts";
import { Evaluator, justifyAlign, partOps, pasteGlyph, seriesOps, Stop } from "./evaluator.ts";
import { context, program } from "./index.ts";
import type { Font, Num, Op } from "./program.ts";

/** Every op `toJson` emits, all of which the reference rasteriser draws. */
export const BROWSER_OPS: ReadonlySet<string> = new Set([
  "color", "pen", "fillPolygon", "arc", "text", "glyph",
  "fillRectangle", "drawRectangle", "fillRoundedRectangle", "drawRoundedRectangle",
  "fillCircle", "drawCircle", "fillEllipse", "drawEllipse", "drawLine",
]);

/** The tiles a frame's runs paste, each stored once. */
export class Tiles {
  readonly images = new Map<string, Tile>();
  private readonly ids = new Map<string, string>();

  add(tile: Tile): string {
    let bytes = "";
    for (let i = 0; i < tile.data.length; i += 4096) bytes += String.fromCharCode(...tile.data.subarray(i, i + 4096));
    const key = `${tile.kind}\0${tile.width}\0${tile.height}\0${bytes}`;
    let found = this.ids.get(key);
    if (found === undefined) {
      found = `t${this.ids.size}`;
      this.ids.set(key, found);
      this.images.set(found, tile);
    }
    return found;
  }

  /**
   * Every tile as RGBA bytes, one after another, zlib-compressed, and their
   * index `{id: [offset, width, height, kind]}`. A mask is its coverage in
   * alpha over white. Raw bytes, not a PNG: a browser canvas premultiplies
   * alpha, which would lose a translucent RGBA tile's colour.
   */
  pack(): [Uint8Array, Record<string, [number, number, number, "mask" | "rgba"]>] {
    const index: Record<string, [number, number, number, "mask" | "rgba"]> = {};
    let size = 0;
    for (const tile of this.images.values()) size += tile.width * tile.height * 4;
    const out = new Uint8Array(size);
    let at = 0;
    for (const [id, tile] of this.images) {
      index[id] = [at, tile.width, tile.height, tile.kind];
      const n = tile.width * tile.height * 4;
      if (tile.kind === "mask") {
        for (let i = 0; i < n; i += 4) {
          out[at + i] = out[at + i + 1] = out[at + i + 2] = 255;
          out[at + i + 3] = tile.data[i + 3]!;
        }
      } else {
        out.set(tile.data.subarray(0, n), at);
      }
      at += n;
    }
    return [zlibSync(out, { level: 6 }), index];
  }
}

/** What a JSON font id stands for: a baked sheet or a device face, and whether it is a `face:` font. */
export interface FontRef {
  baked: string | null;
  metric: FontMetric | null;
  vector: boolean;
}

/** `placed`'s program for the frame `renderer` paints, as JSON ops and the fonts they name. */
export function toJson(renderer: Renderer, placed: Placed, tiles: Tiles = new Tiles()): [JsonOp[], Map<string, FontRef>] {
  const ops = program(context(renderer, placed), placed, renderer.readPlan);
  const writer = new JsonWriter(renderer, tiles);
  try {
    writer.walk(ops);
  } catch (error) {
    if (!(error instanceof Stop)) throw error;
  }
  return [writer.out, writer.fonts];
}

function value(n: JsonNum): number {
  return typeof n === "object" ? n.value + n.add : n;
}

/** The canvas pixel a `text` or `glyph` op's run is placed from. */
export function anchorOf(op: JsonOp, scale: number): [number, number] {
  return [Math.floor(value(op["x"] as JsonNum) * scale), Math.floor(value(op["y"] as JsonNum) * scale)];
}

class JsonWriter {
  readonly aod: boolean;
  readonly renderer: Renderer;
  readonly ev: Evaluator;
  readonly tiles: Tiles;
  readonly out: JsonOp[] = [];
  readonly fonts = new Map<string, FontRef>();

  constructor(renderer: Renderer, tiles: Tiles) {
    this.aod = renderer.options.aod;
    this.renderer = renderer;
    this.ev = new Evaluator(renderer);
    this.tiles = tiles;
  }

  /** What `draw` would paint for `op`, as tiles placed relative to the op's anchor. */
  run(op: JsonOp, draw: () => void): RunItem[] {
    const r = this.renderer;
    r.stamps = [];
    let stamps;
    try {
      draw();
      stamps = r.stamps;
    } finally {
      r.stamps = null;
    }
    const [ax, ay] = anchorOf(op, r.scale);
    return stamps.map((st): RunItem => (st.kind === "box"
      ? { box: [st.x - ax, st.y - ay, st.size[0], st.size[1]], rgb: [...st.color] }
      : { tile: this.tiles.add(st.image!), x: st.x - ax, y: st.y - ay }));
  }

  /** A `Layout` constant, or one moved by a whole amount, stays named; anything else is folded to its value. */
  num(n: Num): JsonNum {
    if (n.t === "Const") return { const: n.name, value: val(n.value), add: 0 };
    if (n.t === "Lit") return val(n.value);
    if (n.t === "AodPick") return this.num(this.aod && n.asleep !== null ? n.asleep : n.awake);
    if (n.t === "Shifted" || n.t === "Grown") {
      const add = n.t === "Shifted" ? n.by : n.by * n.times;
      const base = this.num(n.base);
      return typeof base === "object" ? { ...base, add: base.add + add } : base + add;
    }
    if (n.t === "Bin" && (n.op === "+" || n.op === "-") && n.a.t === "Const") {
      const add = this.ev.num(n.b);
      if (typeof add === "number" || add instanceof WholeFloat) {
        const amount = val(add);
        return { const: n.a.name, value: val(n.a.value), add: n.op === "+" ? amount : -amount };
      }
    }
    return val(this.ev.num(n)!);
  }

  font(font: Font): string {
    const face = this.aod && font.asleep !== null ? font.asleep : font;
    const ref: FontRef = { baked: face.baked, metric: face.metric, vector: face.vector };
    for (const [key, known] of this.fonts) {
      if (known.baked === ref.baked && known.vector === ref.vector && deepEqual(known.metric, ref.metric)) return key;
    }
    const key = `f${this.fonts.size}`;
    this.fonts.set(key, ref);
    return key;
  }

  walk(ops: readonly Op[]): void {
    for (const op of ops) this.op(op);
  }

  op(op: Op): void {
    const ev = this.ev;
    switch (op.t) {
      case "SetColor":
        ev.color = ev.paint(op.color);
        this.out.push({ op: "color", rgb: [...ev.color] });
        break;
      case "SetPen":
        ev.step(op);
        this.out.push({ op: "pen", width: op.width !== null ? this.num(op.width) : 1 });
        break;
      case "Primitive":
        this.out.push({ op: op.name, args: op.args.flat().map((n) => this.num(n)) });
        break;
      case "FillPolygon":
        this.out.push({ op: "fillPolygon", const: op.const, points: op.points.map(([x, y]) => [x, y]) });
        break;
      case "ArcProgress": {
        const call = barrel.drawProgress(ev.n(op.start), ev.n(op.sweep), ev.n(op.fraction));
        this.out.push({
          op: "arc", cx: this.num(op.cx), cy: this.num(op.cy), radius: this.num(op.radius), pen: this.num(op.pen),
          start: this.num(op.start), sweep: this.num(op.sweep), fraction: ev.n(op.fraction), call,
        });
        ev.pen = 1;
        this.out.push({ op: "pen", width: 1 }); // the barrel resets it
        break;
      }
      case "ArcSpan": {
        const call = barrel.drawSpan(ev.n(op.start), ev.n(op.sweep));
        this.out.push({
          op: "arc", cx: this.num(op.cx), cy: this.num(op.cy), radius: this.num(op.radius), pen: this.num(op.pen),
          start: this.num(op.start), sweep: this.num(op.sweep), call,
        });
        ev.pen = 1;
        this.out.push({ op: "pen", width: 1 });
        break;
      }
      case "Part": this.walk(partOps(op, ev)); break;
      case "SeriesRebuild": ev.step(op); break;
      case "SeriesDraw": this.walk(seriesOps(op, ev)); break;
      case "Let": case "Assign": case "LetSlotPick": case "LetAutoScale": case "VisibleGuard": case "NullGuard": case "AntiAlias":
      case "Return": case "SlotPull": case "SlotIcon": case "SlotText": case "Continue": case "LetText":
        ev.step(op);
        break;
      case "If": this.walk(ev.cond(op.cond) ? op.then : op.otherwise); break;
      case "For": ev.loop(op, (body) => this.walk(body)); break;
      case "Text": {
        const text = ev.string(op.text);
        if (text === null) return;
        const out: JsonOp = {
          op: "text", x: this.num(op.x), y: this.num(op.y), text, font: this.font(op.font), justify: [...op.justify],
          align: op.align, valign: op.valign, style: op.style, angle: op.angle !== null ? ev.n(op.angle) : null,
          radius: op.radius !== null ? val(op.radius.value) : null, direction: op.direction,
          box: op.box !== null ? [op.box.x, op.box.y, op.box.width, op.box.height] : null,
        };
        const color = ev.color;
        out["run"] = this.run(out, () => drawText(out, this.fonts, this.renderer, color));
        this.out.push(out);
        break;
      }
      case "Glyph": {
        const glyph = ev.string(op.glyph);
        if (glyph === null) return;
        const out: JsonOp = {
          op: "glyph", x: this.num(op.x), y: this.num(op.y), text: glyph, font: this.font(op.font), justify: [...op.justify],
          valign: op.valign, box: [op.box.x, op.box.y, op.box.width, op.box.height], origin: [...op.origin],
        };
        const color = ev.color;
        out["run"] = this.run(out, () => drawGlyph(out, this.fonts, this.renderer, color));
        this.out.push(out);
        break;
      }
      case "IfNotNull": if (op.present) this.walk(op.body); break;
      case "IfAod": this.walk(this.aod ? op.then : op.otherwise); break;
      case "IfAwake": if (!this.aod) this.walk(op.body); break;
      case "LoadFont": case "Comment": case "Blank": break;
    }
  }
}

/** A `glyph` op as the evaluator draws it: the run's source. */
function drawGlyph(op: JsonOp, fonts: Map<string, FontRef>, renderer: Renderer, color: RGB): void {
  const ref = fonts.get(op["font"] as string)!;
  const box = op["box"] as number[], origin = op["origin"] as number[];
  if (ref.baked !== null) {
    pasteGlyph(renderer, ref.baked, op["text"] as string, box[0]! + value(op["x"] as JsonNum) - origin[0]!,
      box[1]! + value(op["y"] as JsonNum) - origin[1]!, color);
  }
}

/** A `text` op as the evaluator draws it: the run's source. */
function drawText(op: JsonOp, fonts: Map<string, FontRef>, renderer: Renderer, color: RGB): void {
  const ref = fonts.get(op["font"] as string)!;
  const anchor: [number, number] = [Math.trunc(value(op["x"] as JsonNum)), Math.trunc(value(op["y"] as JsonNum))];
  const align = (op["align"] as string | null) ?? justifyAlign(op["justify"] as string[]);
  const raw = op["box"] as [number, number, number, number] | null;
  const box = raw !== null ? new IntBox(...raw) : null;
  if (ref.vector) {
    renderer.drawVectorText(op["text"] as string, anchor, align, op["valign"] as string, ref.metric, color, op["style"] as string | null,
      (op["angle"] as number | null) ?? 0.0, op["radius"] !== null ? Math.trunc(op["radius"] as number) : 0, op["direction"] as string | null, box);
  } else {
    const font = ref.baked !== null ? renderer.resolved.fonts.get(ref.baked) ?? null : null;
    renderer.drawText(font, op["text"] as string, anchor, align, op["valign"] as string, ref.metric, color, box);
  }
}

/** A run's tiles pasted: a mask tinted `color`, an RGBA image through its own alpha, a box as a 1 px outline. */
export function pasteRun(run: readonly RunItem[], anchor: [number, number], tiles: Tiles, image: Image, color: RGB): void {
  const [ax, ay] = anchor;
  for (const item of run) {
    if ("box" in item) {
      const [x, y, w, h] = item.box;
      rectangle(image, [ax + x, ay + y, ax + x + w, ay + y + h], { outline: item.rgb, width: 1 });
      continue;
    }
    paste(image, tiles.images.get(item.tile)!, ax + item.x, ay + item.y, color);
  }
}

/** Paint JSON ops onto `image` at `scale`: `Dc`'s calls as Pillow draws them, and text by pasting its runs' tiles. */
export function rasterise(ops: readonly JsonOp[], tiles: Tiles, image: Image, scale: number): void {
  const s = scale;
  let color: RGB = [255, 255, 255];
  let pen = 1;
  for (const op of ops) {
    const name = op.op;
    if (name === "color") {
      color = op["rgb"] as RGB;
    } else if (name === "pen") {
      pen = Math.trunc(value(op["width"] as JsonNum));
    } else if (name === "fillPolygon") {
      const points = op["points"] as [number, number][];
      if (points.length >= 3) fillPolygon(image, points, color, s);
    } else if (name === "arc") {
      const radius = value(op["radius"] as JsonNum);
      const call = op["call"] as barrel.ArcCall | null;
      if (call === null || radius <= 0) continue;
      drawArc(image, value(op["cx"] as JsonNum), value(op["cy"] as JsonNum), radius, value(op["pen"] as JsonNum), call, color, s);
    } else if (name === "glyph" || name === "text") {
      pasteRun(op["run"] as RunItem[], anchorOf(op, s), tiles, image, color);
    } else {
      primitive(image, name, (op["args"] as JsonNum[]).map(value), color, pen, s);
    }
  }
}
