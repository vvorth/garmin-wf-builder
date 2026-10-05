// Draws the ring-on-device face's ops (dump_ring_ops.py) without Pillow and
// compares each element's window with the simulator capture, beside
// Pillow's preview of the same ops.
//
// Models:
//   skia-aa         Skia's anti-aliased fill (@napi-rs/canvas: Chrome's
//                   canvas rasteriser), composited as is
//   skia-threshold  Skia's coverage as a mask, ink where coverage >= 50%
//   js-coverage     no canvas: an inside test sampled 16 x 16 per pixel,
//                   ink where at least half the samples are inside
// `off` is where Garmin's (x, y) sits: 0 = a pixel's corner, 0.5 = its
// centre. `r+` grows a circle's radius.
//   node shapes.mjs OUTDIR        (OUTDIR from dump_ring_ops.py)
import { createCanvas } from "@napi-rs/canvas";
import { readFileSync } from "node:fs";

const dir = process.argv[2];
const face = JSON.parse(readFileSync(`${dir}/ring_ops.json`, "utf8"));
const W = face.width, H = face.height;
// An argument is a named Layout constant ({value, add}) or a plain number.
const v = (a) => (typeof a === "number" ? a : a.value + a.add);
const raw = (name) => new Uint8Array(readFileSync(`${dir}/${name}`));

function drawSkia(mode, off, rpad) {
  const out = new Uint8ClampedArray(W * H * 4);
  for (let i = 3; i < out.length; i += 4) out[i] = 255;
  const mx = createCanvas(W, H).getContext("2d");
  for (const layer of face.layers) {
    let rgb = [255, 255, 255];
    for (const op of layer.ops) {
      if (op.op === "color") { rgb = op.rgb; continue; }
      const a = op.args.map(v);
      mx.clearRect(0, 0, W, H);
      mx.fillStyle = "#fff";
      mx.beginPath();
      if (op.op === "fillCircle") mx.arc(a[0] + off, a[1] + off, a[2] + rpad, 0, 2 * Math.PI);
      else if (op.op === "fillRectangle") mx.rect(a[0], a[1], a[2], a[3]);
      else if (op.op === "fillRoundedRectangle") mx.roundRect(a[0], a[1], a[2], a[3], a[4]);
      else throw new Error(op.op);
      mx.fill();
      const cov = mx.getImageData(0, 0, W, H).data;
      for (let i = 0; i < W * H; i++) {
        const k = cov[i * 4 + 3] / 255;
        if (k === 0) continue;
        const t = mode === "aa" ? k : k >= 0.5 ? 1 : 0;
        for (let ch = 0; ch < 3; ch++) out[i * 4 + ch] = Math.round(out[i * 4 + ch] * (1 - t) + rgb[ch] * t);
      }
    }
  }
  return out;
}
function insideFn(op, a) {
  if (op === "fillCircle") {
    const cx = a[0] + 0.5, cy = a[1] + 0.5, r2 = a[2] * a[2];
    return (x, y) => (x - cx) ** 2 + (y - cy) ** 2 <= r2;
  }
  if (op === "fillRectangle") return (x, y) => x >= a[0] && x < a[0] + a[2] && y >= a[1] && y < a[1] + a[3];
  if (op === "fillRoundedRectangle") {
    const [x0, y0, w, h] = a, r = Math.min(a[4], w / 2, h / 2);
    return (x, y) => {
      if (x < x0 || x >= x0 + w || y < y0 || y >= y0 + h) return false;
      const dx = Math.max(x0 + r - x, 0, x - (x0 + w - r)), dy = Math.max(y0 + r - y, 0, y - (y0 + h - r));
      return dx * dx + dy * dy <= r * r;
    };
  }
  throw new Error(op);
}
function drawJs(N) {
  const out = new Uint8ClampedArray(W * H * 4);
  for (let i = 3; i < out.length; i += 4) out[i] = 255;
  for (const layer of face.layers) {
    let rgb = [255, 255, 255];
    for (const op of layer.ops) {
      if (op.op === "color") { rgb = op.rgb; continue; }
      const inside = insideFn(op.op, op.args.map(v));
      for (let py = 0; py < H; py++) for (let px = 0; px < W; px++) {
        let n = 0;
        for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) if (inside(px + (i + 0.5) / N, py + (j + 0.5) / N)) n++;
        if (n * 2 >= N * N) { const k = (py * W + px) * 4; out[k] = rgb[0]; out[k + 1] = rgb[1]; out[k + 2] = rgb[2]; }
      }
    }
  }
  return out;
}
// compare.py's window round an element's centre.
function cellDiff(a, b, [cx, cy]) {
  let n = 0;
  for (let y = cy - 18; y < cy + 18; y++) for (let x = cx - 19; x < cx + 19; x++) {
    const i = (y * W + x) * 4;
    if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) n++;
  }
  return n;
}
const cap = raw("capture.rgba");
const variants = { pillow: raw("pillow.rgba") };
for (const off of [0, 0.5]) for (const rpad of [0, 0.5]) {
  variants[`skia-threshold off=${off} r+${rpad}`] = drawSkia("threshold", off, rpad);
  variants[`skia-aa off=${off} r+${rpad}`] = drawSkia("aa", off, rpad);
}
variants["js-coverage 16x16 off=0.5 r+0"] = drawJs(16);
const kinds = ["circle", "rectangle", "rounded", "bar", "part"];
const kindOf = (id) => kinds.find((k) => id.startsWith(k));
// Each grown element, and each stamp's first copy.
const ids = Object.keys(face.centres).filter((id) => (kindOf(id) && !id.includes("_s")) || /_s0$/.test(id));
console.log(`cells: ${ids.length}; pixels differing from the simulator capture`);
console.log("model".padEnd(32), kinds.map((k) => k.padStart(10)).join(""), "     total");
for (const [name, img] of Object.entries(variants)) {
  const per = Object.fromEntries(kinds.map((k) => [k, 0]));
  for (const id of ids) per[kindOf(id)] += cellDiff(img, cap, face.centres[id]);
  const total = Object.values(per).reduce((a, b) => a + b);
  console.log(name.padEnd(32), kinds.map((k) => String(per[k]).padStart(10)).join(""), String(total).padStart(10));
}
