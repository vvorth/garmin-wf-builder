// The host twin of `runtime-lib/WfbAodMask.mc`: the moving 2x2 pixel mask
// over the AOD frame. Port of wfb/aod_mask.py.
//
// In minute `m`, `m mod 4` picks `(dx, dy)` from `PHASES`; device pixel
// `(x, y)` keeps its colour iff `x mod 2 == dx` and `y mod 2 == dy`, and
// every other pixel becomes black.
import type { Image } from "./raster/pillow.ts";

/** `[dx, dy]` by `minute % 4`, mirrored from `runtime-lib/WfbAodMask.mc`. */
export const PHASES: readonly (readonly [number, number])[] = [[0, 0], [1, 0], [1, 1], [0, 1]];

/** `[dx, dy]` for clock minute `minute`. */
export function offset(minute: number): readonly [number, number] {
  return PHASES[((minute % 4) + 4) % 4]!;
}

/** A new image with the mask applied for `minute`; at `scale`, image pixel `(X, Y)` is device pixel `(X // s, Y // s)`. */
export function apply(image: Image, minute: number, scale = 1): Image {
  const [dx, dy] = offset(minute);
  const s = Math.max(1, scale);
  const out = { width: image.width, height: image.height, data: new Uint8ClampedArray(image.data) };
  for (let y = 0; y < image.height; y++) {
    for (let x = 0; x < image.width; x++) {
      if (Math.floor(x / s) % 2 === dx && Math.floor(y / s) % 2 === dy) continue;
      const i = (y * image.width + x) * 4;
      out.data[i] = 0;
      out.data[i + 1] = 0;
      out.data[i + 2] = 0;
    }
  }
  return out;
}
