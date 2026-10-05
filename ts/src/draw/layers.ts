// A preview frame as layers: each drawn element alone on a transparent
// ground, plus one layer per outlined group's ring, in draw order. Port of
// wfb/draw/layers.py.
//
// The editor stacks them, and moves or hides one without redrawing the
// rest. The whole-frame steps (the black ground, the AOD mask, the palette,
// the bezel) run once on the stack (`compose`), never per layer. Stacking
// reproduces `preview.render` up to rounding on anti-aliased edges: a
// layer's colour and coverage are recovered from a black and a white render
// of it (difference matting).
import type { Span } from "../diagnostics.ts";
import { ringGroups } from "../ir/rings.ts";
import type { Placed, ResolvedFace } from "../layout.ts";
import {
  finishFrame, frameItems, newRenderer, previewOptions, type PreviewOptions, type Renderer, resolveStyleEntry, type RGB, sampleValues,
} from "../preview.ts";
import { image as newImage, type Image, type JsonOp } from "../raster/pillow.ts";
import { BROWSER_OPS, type FontRef, Tiles, toJson } from "./jsonform.ts";

/** An RGBA image, straight alpha. */
export interface RgbaImage {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

/** One layer of a frame: an element's, or `ring:<group id>` for an outlined group's ring. */
export interface Layer {
  id: string;
  kind: string;
  span: Span | null;
  /** RGBA at the device's native size, or `null` for a layer left to its JSON. */
  image: RgbaImage | null;
  /** The lowered element's program as JSON for this frame; `null` for a group ring. */
  ops: JsonOp[] | null;
  fonts: Map<string, FontRef>;
  tiles: Tiles | null;
}

/** One layer's RGBA from the same drawing on a black and on a white ground. */
export function matte(black: Image, white: Image): RgbaImage {
  const out = new Uint8ClampedArray(black.data.length);
  for (let i = 0; i < black.data.length; i += 4) {
    const d = (c: number): number => Math.max(0, white.data[i + c]! - black.data[i + c]!);
    const alpha = 255 - ((d(0) * 19595 + d(1) * 38470 + d(2) * 7471 + 0x8000) >> 16);
    if (alpha === 0) continue;
    for (let c = 0; c < 3; c++) out[i + c] = Math.trunc(Math.min(black.data[i + c]! * 255.0 / Math.max(alpha, 1.0) + 0.5, 255.0));
    out[i + 3] = alpha;
  }
  return { width: black.width, height: black.height, data: out };
}

/**
 * The frame `preview.render` draws, as layers in draw order: before each
 * outlined group's first member drawn here, that group's ring, then the
 * element. With `paintAll` false, a layer whose JSON a browser draws itself
 * is not painted; with `images` false, no layer is.
 */
export function layers(resolved: ResolvedFace, options: PreviewOptions = previewOptions(),
  { paintAll = true, images = true }: { paintAll?: boolean; images?: boolean } = {}): Layer[] {
  const entry = resolveStyleEntry(resolved.face, options.style);
  const values = sampleValues(resolved, options, entry);
  const items = frameItems(resolved, options, entry);
  const rings = ringGroups(resolved.face.elements);
  const tiles = new Tiles();
  const paint = (draw: (r: Renderer) => void): RgbaImage => {
    const grounds = ([[0, 0, 0], [255, 255, 255]] as RGB[]).map((ground) => {
      const renderer = newRenderer(resolved, options, values, ground);
      draw(renderer);
      return renderer.image;
    });
    return matte(grounds[0]!, grounds[1]!);
  };
  const out: Layer[] = [];
  for (const placed of items) {
    for (const ring of rings) {
      const members = items.filter((p) => ring.ids.has(p.id));
      if (members.length === 0 || members[0] !== placed) continue;
      out.push({
        id: `ring:${ring.group.id}`, kind: "ring", span: ring.group.span,
        image: images ? paint((r) => r.renderRing(ring, members)) : null, ops: null, fonts: new Map(), tiles: null,
      });
    }
    const renderer = newRenderer(resolved, options, values, [0, 0, 0]);
    let ops: JsonOp[] = [], fonts = new Map<string, FontRef>();
    if (renderer.shows(placed)) [ops, fonts] = toJson(renderer, placed, tiles);
    const drawnByBrowser = ops.every((op) => BROWSER_OPS.has(op.op));
    const image = images && (paintAll || !drawnByBrowser) ? paint((r) => r.renderElement(placed as Placed)) : null;
    out.push({ id: placed.id, kind: placed.kind, span: placed.element.span, image, ops, fonts, tiles });
  }
  return out;
}

/** `stack` over the black ground, then the whole-frame steps: the frame `preview.render` draws, up to rounding. */
export function compose(stack: readonly Layer[], resolved: ResolvedFace, options: PreviewOptions = previewOptions()): Image {
  const entry = resolveStyleEntry(resolved.face, options.style);
  const values = sampleValues(resolved, options, entry);
  const device = resolved.device;
  const frame = newImage(device.width, device.height, [0, 0, 0]);
  for (const layer of stack) {
    if (layer.image === null) throw new Error("compose needs every layer painted");
    alphaComposite(frame, layer.image);
  }
  return finishFrame(frame, resolved, options, values);
}

/** Pillow's `Image.alpha_composite` of `over` onto the opaque `frame`, in place. */
function alphaComposite(frame: Image, over: RgbaImage): void {
  for (let i = 0; i < frame.data.length; i += 4) {
    const a = over.data[i + 3]!;
    if (a === 0) continue;
    for (let c = 0; c < 3; c++) {
      // AlphaComposite.c with an opaque destination: coef1 = a << 7, coef2 = (255 - a) << 7.
      const t = (over.data[i + c]! * a + frame.data[i + c]! * (255 - a)) * 128 + (0x80 << 7);
      frame.data[i + c] = (((t >> 8) + t) >> 8) >> 7;
    }
  }
}
