// Pillow's drawing primitives, in JavaScript, pixel for pixel: the shapes
// the editor's draw program uses (`wfb.draw.jsonform.rasterise`), so a
// layer can be drawn in the browser exactly as the preview draws it.
//
// Follows Pillow 12.3.0: `src/PIL/ImageDraw.py` (rectangle, ellipse, arc,
// line, polygon, rounded_rectangle) and `src/libImaging/Draw.c` (the
// scanline polygon, Bresenham lines, the integer ellipse and its clipped
// arcs and pies), with the argument conversion of `src/_imaging.c`.
// Pillow is under the MIT-CMU licence: `vendor/LICENSES-pillow`.
//
// An image is `{width, height, data}`, `data` RGBA bytes (alpha always
// 255), drawn on as Pillow draws on an "RGB" image: every pixel written
// outright, no blending. Colours are `[r, g, b]`.
//
// The C code's arithmetic is kept: `(int)` truncates toward zero, `float`
// values round to 32 bits after every operation (`F`), and its two
// roundings (`ROUND_UP`/`ROUND_DOWN`, `lround`) round half away from zero.
// Python's `round()` (in `rounded_rectangle`) rounds half to even. Pure
// functions, no DOM, so Node checks them against Pillow itself
// (tests/test_studio_raster.py).

const F = Math.fround;

export function image(width, height, ground = [0, 0, 0]) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data[i] = ground[0]; data[i + 1] = ground[1]; data[i + 2] = ground[2]; data[i + 3] = 255;
  }
  return { width, height, data };
}

// -- C arithmetic ------------------------------------------------------------------

const trunc = Math.trunc;                       // (int) of a double

function halfAway(v) {                          // lround, roundf
  const a = Math.abs(v), t = Math.floor(a);
  const r = a - t >= 0.5 ? t + 1 : t;
  return v < 0 ? -r : r;
}

// ROUND_UP/ROUND_DOWN of a C float: the positive branch adds 0.5F in float,
// the negative one goes through fabs(), a double.
function roundUpF(f) {
  return f >= 0 ? Math.floor(F(f + 0.5)) : -Math.floor(Math.abs(f) + 0.5);
}
function roundDownF(f) {
  return f >= 0 ? Math.ceil(F(f - 0.5)) : -Math.ceil(Math.abs(f) - 0.5);
}
// ... and of a double, where both branches are doubles.
function roundUpD(f) {
  return f >= 0 ? Math.floor(f + 0.5) : -Math.floor(Math.abs(f) + 0.5);
}
function roundDownD(f) {
  return f >= 0 ? Math.ceil(f - 0.5) : -Math.ceil(Math.abs(f) - 0.5);
}

function fmod(a, b) { return a % b; }           // C fmod: the sign of a

function roundHalfEven(v) {                     // Python's round()
  const t = Math.floor(v), d = v - t;
  if (d > 0.5) return t + 1;
  if (d < 0.5) return t;
  return t % 2 === 0 ? t : t + 1;
}

// -- Draw.c: points, lines, scanlines ------------------------------------------------

function point(im, x, y, ink) {
  if (x >= 0 && x < im.width && y >= 0 && y < im.height) {
    const i = (y * im.width + x) * 4;
    im.data[i] = ink[0]; im.data[i + 1] = ink[1]; im.data[i + 2] = ink[2];
  }
}

function hline(im, x0, y0, x1, ink) {
  if (y0 >= 0 && y0 < im.height) {
    if (x0 < 0) x0 = 0;
    else if (x0 >= im.width) return;
    if (x1 < 0) return;
    else if (x1 >= im.width) x1 = im.width - 1;
    let i = (y0 * im.width + x0) * 4;
    for (; x0 <= x1; x0++, i += 4) {
      im.data[i] = ink[0]; im.data[i + 1] = ink[1]; im.data[i + 2] = ink[2];
    }
  }
}

function bresenham(im, x0, y0, x1, y1, ink) {
  let dx = x1 - x0, dy = y1 - y0, xs = 1, ys = 1;
  if (dx < 0) { dx = -dx; xs = -1; }
  if (dy < 0) { dy = -dy; ys = -1; }
  if (dx === 0) {
    for (let i = 0; i < dy; i++) { point(im, x0, y0, ink); y0 += ys; }
  } else if (dy === 0) {
    for (let i = 0; i < dx; i++) { point(im, x0, y0, ink); x0 += xs; }
  } else if (dx > dy) {
    const n = dx;
    dy += dy;
    let e = dy - dx;
    dx += dx;
    for (let i = 0; i < n; i++) {
      point(im, x0, y0, ink);
      if (e >= 0) { y0 += ys; e -= dx; }
      e += dy;
      x0 += xs;
    }
  } else {
    const n = dy;
    dx += dx;
    let e = dx - dy;
    dy += dy;
    for (let i = 0; i < n; i++) {
      point(im, x0, y0, ink);
      if (e >= 0) { x0 += xs; e -= dy; }
      e += dx;
      y0 += ys;
    }
  }
}

function edge(x0, y0, x1, y1) {
  const e = { x0, y0, xmin: Math.min(x0, x1), xmax: Math.max(x0, x1),
              ymin: Math.min(y0, y1), ymax: Math.max(y0, y1), dx: 0, d: 0 };
  if (y0 !== y1) {
    e.dx = F((x1 - x0) / (y1 - y0));
    e.d = y0 === e.ymin ? 1 : -1;
  }
  return e;
}

// `x` of edge `e` on scanline `y`, in C float arithmetic.
function edgeX(e, y) {
  return F(F((y - e.y0) * e.dx) + e.x0);
}

function polygonGeneric(im, edges, ink) {
  const n = edges.length;
  if (n <= 0) return;
  const table = [];
  let ymin = im.height - 1, ymax = 0;
  for (const e of edges) {
    if (ymin > e.ymin) ymin = e.ymin;
    if (ymax < e.ymax) ymax = e.ymax;
    if (e.ymin === e.ymax) {
      hline(im, e.xmin, e.ymin, e.xmax, ink);
      continue;
    }
    table.push(e);
  }
  if (ymin < 0) ymin = 0;
  if (ymax > im.height) ymax = im.height;
  const xx = [];
  for (; ymin <= ymax; ymin++) {
    xx.length = 0;
    for (let i = 0; i < table.length; i++) {
      const current = table[i];
      if (ymin >= current.ymin && ymin <= current.ymax) {
        xx.push(edgeX(current, ymin));
        if (ymin === current.ymax && ymin < ymax) {
          xx.push(xx[xx.length - 1]);
        } else if ((ymin === current.ymin || ymin === current.ymax) && current.dx !== 0) {
          for (let k = 0; k < i; k++) {
            const other = table[k];
            if ((ymin !== other.ymin && ymin !== other.ymax) || other.dx === 0) continue;
            if (halfAway(xx[xx.length - 1]) === halfAway(edgeX(other, ymin))) {
              const offset = ymin === current.ymax ? -1 : 1;
              const adjacent = edgeX(current, ymin + offset);
              if (ymin + offset >= other.ymin && ymin + offset <= other.ymax) {
                const adjacentOther = edgeX(other, ymin + offset);
                const last = xx[xx.length - 1];
                if (last > F(adjacent + 1) && last > F(adjacentOther + 1)) {
                  xx[xx.length - 1] = F(halfAway(Math.max(adjacent, adjacentOther)) + 1);
                } else if (last < F(adjacent - 1) && last < F(adjacentOther - 1)) {
                  xx[xx.length - 1] = F(halfAway(Math.min(adjacent, adjacentOther)) - 1);
                }
                break;
              }
            }
          }
        }
      }
    }
    xx.sort((a, b) => a - b);
    for (let i = 1; i < xx.length; i += 2) {
      hline(im, roundUpF(xx[i - 1]), ymin, roundDownF(xx[i]), ink);
    }
  }
}

function wideLine(im, x0, y0, x1, y1, ink, width) {
  const dx = x1 - x0, dy = y1 - y0;
  if (dx === 0 && dy === 0) { point(im, x0, y0, ink); return; }
  // hypot of two ints: the sum of squares is exact, the root correctly rounded
  const big = Math.sqrt(dx * dx + dy * dy);
  const small = (width - 1) / 2.0;
  const ratioMax = roundUpD(small) / big, ratioMin = roundDownD(small) / big;
  const dxmin = roundDownD(ratioMin * dy), dxmax = roundDownD(ratioMax * dy);
  const dymin = roundDownD(ratioMin * dx), dymax = roundDownD(ratioMax * dx);
  const v = [[x0 - dxmin, y0 + dymax], [x1 - dxmin, y1 + dymax],
             [x1 + dxmax, y1 - dymin], [x0 + dxmax, y0 - dymin]];
  polygonGeneric(im, [edge(...v[0], ...v[1]), edge(...v[1], ...v[2]),
                      edge(...v[2], ...v[3]), edge(...v[3], ...v[0])], ink);
}

// -- Draw.c: the integer ellipse ------------------------------------------------------
// Its points live on a grid of step 2 so angle clipping can work on it; the
// 64-bit products stay exact in a double while the axes are under 2^13.

function quarter(a, b) {
  if (a < 0 || b < 0) return { finished: true };
  return { a, b, cx: a, cy: b % 2, ex: a % 2, ey: b, a2: a * a, b2: b * b,
           a2b2: a * a * b * b, finished: false };
}

function quarterDelta(s, x, y) {
  return Math.abs(s.a2 * y * y + s.b2 * x * x - s.a2b2);
}

function quarterNext(s) {
  if (s.finished) return null;
  const out = [s.cx, s.cy];
  if (s.cx === s.ex && s.cy === s.ey) {
    s.finished = true;
  } else {
    let nx = s.cx, ny = s.cy + 2;
    let ndelta = quarterDelta(s, nx, ny);
    if (nx > 1) {
      let d = quarterDelta(s, s.cx - 2, s.cy + 2);
      if (ndelta > d) { nx = s.cx - 2; ny = s.cy + 2; ndelta = d; }
      d = quarterDelta(s, s.cx - 2, s.cy);
      if (ndelta > d) { nx = s.cx - 2; ny = s.cy; }
    }
    s.cx = nx; s.cy = ny;
  }
  return out;
}

function ellipseState(a, b, w) {
  const s = { buf: [], leftmost: a % 2, outer: quarter(a, b), finished: false };
  const first = w < 1 ? null : quarterNext(s.outer);
  if (first === null) {
    s.finished = true;
  } else {
    [s.pr, s.py] = first;
    s.inner = quarter(a - 2 * (w - 1), b - 2 * (w - 1));
    s.pl = s.leftmost;
  }
  return s;
}

// The next horizontal segment `[x0, y, x1]`, on the step-2 grid, or null.
function ellipseNext(s) {
  if (s.buf.length === 0) {
    if (s.finished) return null;
    const y = s.py;
    let l = s.pl;
    const r = s.pr;
    let next;
    while ((next = quarterNext(s.outer)) !== null && next[1] <= y) { /* skip */ }
    if (next === null) s.finished = true;
    else { s.pr = next[0]; s.py = next[1]; }
    while ((next = quarterNext(s.inner)) !== null && next[1] <= y) l = next[0];
    s.pl = next === null ? s.leftmost : next[0];
    if ((l > 0 || l < r) && y > 0) s.buf.push([l === 0 ? 2 : l, y, r]);
    if (y > 0) s.buf.push([-r, y, -l]);
    if (l > 0 || l < r) s.buf.push([l === 0 ? 2 : l, -y, r]);
    s.buf.push([-r, -y, -l]);
  }
  return s.buf.pop();
}

// -- Draw.c: clipping an ellipse into arcs and pies -----------------------------------

const AND = 0, OR = 1, CLIP = 2;

function clipNode(a, b, c) { return { type: CLIP, a, b, c }; }

// The clipped pieces of one horizontal segment, as sorted
// `[{x, type}]` events (1 opens, -1 closes).
function doClip(root, x0, y, x1) {
  if (root === null) return [{ x: x0, type: 1 }, { x: x1, type: -1 }];
  if (root.type === CLIP) {
    const eps = 1e-9, A = root.a, B = root.b, C = root.c;
    if (Math.abs(A) < eps) {
      if (B * y + C < -eps) { x0 = 1; x1 = 0; }
    } else {
      const ix = -(B * y + C) / A;
      if (A * x0 + B * y + C < eps) x0 = halfAway(Math.max(x0, ix));
      if (A * x1 + B * y + C < eps) x1 = halfAway(Math.min(x1, ix));
    }
    return x0 <= x1 ? [{ x: x0, type: 1 }, { x: x1, type: -1 }] : [];
  }
  const l1 = doClip(root.l, x0, y, x1), l2 = doClip(root.r, x0, y, x1);
  const out = [];
  let i = 0, j = 0, k1 = 0, k2 = 0;
  while (i < l1.length || j < l2.length) {
    let t;
    if (j >= l2.length || (i < l1.length &&
        (l1[i].x < l2[j].x || (l1[i].x === l2[j].x && l1[i].type > l2[j].type)))) {
      t = l1[i++]; k1 += t.type;
    } else {
      t = l2[j++]; k2 += t.type;
    }
    const tail = out.length ? out[out.length - 1] : null;
    if ((root.type === OR &&
         ((t.type === 1 && (tail === null || tail.type === -1)) ||
          (t.type === -1 && k1 === 0 && k2 === 0))) ||
        (root.type === AND &&
         ((t.type === 1 && (tail === null || tail.type === -1) && k1 > 0 && k2 > 0) ||
          (t.type === -1 && tail !== null && tail.type === 1 && (k1 === 0 || k2 === 0))))) {
      out.push({ x: t.x, type: t.type });
    }
  }
  return out;
}

function transpose(root) {
  if (root === null) return;
  if (root.type === CLIP) { const t = root.a; root.a = root.b; root.b = t; }
  else { transpose(root.l); transpose(root.r); }
}

// Angles as C floats: 0 <= al < 360, al <= ar <= al + 360.
function normalizeAngles(al, ar) {
  if (F(ar - al) >= 360) return [0, 360];
  const l = F(fmod(al < 0 ? 360 - fmod(-al, 360) : al, 360));
  const r = F(l + fmod(ar < l ? 360 - fmod(F(l - ar), 360) : F(ar - l), 360));
  return [l, r];
}

function arcTree(a, b, al, ar) {
  if (a < b) {
    const root = arcTree(b, a, F(90 - ar), F(90 - al));
    transpose(root);
    return root;
  }
  [al, ar] = normalizeAngles(al, ar);
  if (ar === F(al + 360)) return null;
  const rad = Math.PI / 180.0;
  const lc = clipNode(-a * Math.sin(al * rad), b * Math.cos(al * rad),
                      (a * a - b * b) * Math.sin(al * Math.PI / 90.0) / 2.0);
  const rc = clipNode(a * Math.sin(ar * rad), -b * Math.cos(ar * rad),
                      (b * b - a * a) * Math.sin(ar * Math.PI / 90.0) / 2.0);
  const span = F(ar - al);
  if (fmod(al, 180) === 0 || fmod(ar, 180) === 0) {
    return { type: span < 180 ? AND : OR, l: lc, r: rc };
  }
  const half = (v) => trunc(F(v / 180));
  if ((half(al) + half(ar)) % 2 === 1) {
    return {
      type: OR,
      l: { type: AND, l: clipNode(0, half(al) % 2 === 0 ? 1 : -1, 0), r: lc },
      r: { type: AND, l: clipNode(0, half(ar) % 2 === 0 ? 1 : -1, 0), r: rc },
    };
  }
  const type = span < 180 ? AND : OR;
  return { type, l: { type, l: lc, r: rc }, r: clipNode(0, ar < 180 || ar > 540 ? 1 : -1, 0) };
}

function pieTree(a, b, al, ar) {
  const rad = Math.PI / 180.0;
  const xl = a * Math.cos(al * rad), xr = a * Math.cos(ar * rad);
  const yl = b * Math.sin(al * rad), yr = b * Math.sin(ar * rad);
  let root = { type: F(ar - al) < 180 ? AND : OR, l: clipNode(-yl, xl, 0), r: clipNode(yr, -xr, 0) };
  if (F(ar - al) < 90) {
    root = { type: AND, l: root, r: clipNode((xl + xr) / 2.0, (yl + yr) / 2.0, 0) };
  }
  return root;
}

function drawSegments(im, x0, y0, a, b, state, root, ink) {
  let seg;
  while ((seg = ellipseNext(state)) !== null) {
    const pieces = root === undefined ? [{ x: seg[0] }, { x: seg[2] }] : doClip(root, seg[0], seg[1], seg[2]);
    for (let i = 0; i + 1 < pieces.length; i += 2) {
      hline(im, x0 + trunc((pieces[i].x + a) / 2), y0 + trunc((seg[1] + b) / 2),
            x0 + trunc((pieces[i + 1].x + a) / 2), ink);
    }
  }
}

function ellipseNew(im, x0, y0, x1, y1, ink, fill, width) {
  const a = x1 - x0, b = y1 - y0;
  if (a < 0 || b < 0) return;
  drawSegments(im, x0, y0, a, b, ellipseState(a, b, fill ? a + b : width), undefined, ink);
}

function arcNew(im, x0, y0, x1, y1, start, end, ink, width) {
  const a = x1 - x0, b = y1 - y0;
  if (a < 0 || b < 0) return;
  drawSegments(im, x0, y0, a, b, ellipseState(a, b, width), arcTree(a, b, start, end), ink);
}

function drawArc(im, x0, y0, x1, y1, start, end, ink, width) {
  [start, end] = normalizeAngles(start, end);
  if (F(start + 360) === end) { ellipseNew(im, x0, y0, x1, y1, ink, false, width); return; }
  if (start === end) return;
  arcNew(im, x0, y0, x1, y1, start, end, ink, width);
}

// A filled pie: all `rounded_rectangle` needs of `ImagingDrawPieslice`.
function drawPiesliceFilled(im, x0, y0, x1, y1, start, end, ink) {
  [start, end] = normalizeAngles(start, end);
  if (F(start + 360) === end) { ellipseNew(im, x0, y0, x1, y1, ink, true, 0); return; }
  if (start === end) return;
  const a = x1 - x0, b = y1 - y0;
  if (a < 0 || b < 0) return;
  drawSegments(im, x0, y0, a, b, ellipseState(a, b, x1 + y1 - x0 - y0), pieTree(a, b, start, end), ink);
}

// -- _imaging.c: the bindings ----------------------------------------------------------

function box(xy) {
  const [x0, y0, x1, y1] = xy;
  if (x1 < x0) throw new RangeError("x1 must be greater than or equal to x0");
  if (y1 < y0) throw new RangeError("y1 must be greater than or equal to y0");
  return [trunc(x0), trunc(y0), trunc(x1), trunc(y1)];
}

function drawRectangle(im, xy, ink, fill, width) {
  let [x0, y0, x1, y1] = box(xy);
  if (fill) {
    if (y0 < 0) y0 = 0;
    else if (y0 >= im.height) return;
    if (y1 < 0) return;
    else if (y1 > im.height) y1 = im.height;
    for (let y = y0; y <= y1; y++) hline(im, x0, y, x1, ink);
  } else {
    if (width === 0) width = 1;
    for (let i = 0; i < width; i++) {
      hline(im, x0, y0 + i, x1, ink);
      hline(im, x0, y1 - i, x1, ink);
      bresenham(im, x1 - i, y0 + width, x1 - i, y1 - width + 1, ink);
      bresenham(im, x0 + i, y0 + width, x0 + i, y1 - width + 1, ink);
    }
  }
}

function drawEllipse(im, xy, ink, fill, width) {
  const [x0, y0, x1, y1] = box(xy);
  ellipseNew(im, x0, y0, x1, y1, ink, fill, width);
}

// -- ImageDraw.py ----------------------------------------------------------------------

export function rectangle(im, xy, { fill = null, outline = null, width = 1 } = {}) {
  if (fill) drawRectangle(im, xy, fill, true, 1);
  if (outline && !sameInk(outline, fill) && width !== 0) drawRectangle(im, xy, outline, false, width);
}

export function ellipse(im, xy, { fill = null, outline = null, width = 1 } = {}) {
  if (fill) drawEllipse(im, xy, fill, true, 1);
  if (outline && !sameInk(outline, fill) && width !== 0) drawEllipse(im, xy, outline, false, width);
}

export function arc(im, xy, start, end, color, width = 1) {
  if (width === 0) return;
  const [x0, y0, x1, y1] = box(xy);
  drawArc(im, x0, y0, x1, y1, F(start), F(end), color, width);
}

// One segment from (x0, y0) to (x1, y1), as `ImageDraw.line` draws it.
export function line(im, xy, color, width = 1) {
  if (width === 0) return;
  const [x0, y0, x1, y1] = xy.map(trunc);
  if (width === 1) {
    bresenham(im, x0, y0, x1, y1, color);
    point(im, x1, y1, color);
  } else {
    wideLine(im, x0, y0, x1, y1, color, width);
  }
}

// A filled polygon: `points` as `[[x, y], ...]`.
export function polygon(im, points, fill) {
  if (points.length < 2) throw new TypeError("coordinate list must contain at least 2 coordinates");
  const xy = points.map(([x, y]) => [trunc(x), trunc(y)]);
  const count = xy.length;
  const edges = [];
  let i;
  for (i = 0; i < count - 1; i++) {
    const [x0, y0] = xy[i], [x1, y1] = xy[i + 1];
    if (y0 === y1 && i !== 0 && y0 === xy[i - 1][1]) {
      const last = edges[edges.length - 1];
      if (x1 > x0 && x0 > xy[i - 1][0]) { last.xmax = x1; continue; }
      if (x1 < x0 && x0 < xy[i - 1][0]) { last.xmin = x1; continue; }
    }
    edges.push(edge(x0, y0, x1, y1));
  }
  if (xy[i][0] !== xy[0][0] || xy[i][1] !== xy[0][1]) {
    edges.push(edge(xy[i][0], xy[i][1], xy[0][0], xy[0][1]));
  }
  polygonGeneric(im, edges, fill);
}

export function roundedRectangle(im, xy, radius, { fill = null, outline = null, width = 1 } = {}) {
  let [x0, y0, x1, y1] = xy;
  if (x1 < x0) throw new RangeError("x1 must be greater than or equal to x0");
  if (y1 < y0) throw new RangeError("y1 must be greater than or equal to y0");
  let d = Math.min(x1 - x0, y1 - y0, radius * 2);
  x0 = roundHalfEven(x0); y0 = roundHalfEven(y0);
  x1 = roundHalfEven(x1); y1 = roundHalfEven(y1);
  const fullX = d >= x1 - x0 - 1;
  if (fullX) d = x1 - x0;
  const fullY = d >= y1 - y0 - 1;
  if (fullY) d = y1 - y0;
  if (fullX && fullY) { ellipse(im, xy, { fill, outline, width }); return; }
  if (d === 0) { rectangle(im, xy, { fill, outline, width }); return; }
  const r = Math.floor(d / 2);
  let parts;
  if (fullX) {
    parts = [[[x0, y0, x0 + d, y0 + d], 180, 360], [[x0, y1 - d, x0 + d, y1], 0, 180]];
  } else if (fullY) {
    parts = [[[x0, y0, x0 + d, y0 + d], 90, 270], [[x1 - d, y0, x1, y0 + d], 270, 90]];
  } else {
    parts = [[[x0, y0, x0 + d, y0 + d], 180, 270], [[x1 - d, y0, x1, y0 + d], 270, 360],
             [[x1 - d, y1 - d, x1, y1], 0, 90], [[x0, y1 - d, x0 + d, y1], 90, 180]];
  }
  if (fill) {
    for (const [xy4, s, e] of parts) {
      const [a0, b0, a1, b1] = box(xy4);
      drawPiesliceFilled(im, a0, b0, a1, b1, F(s), F(e), fill);
    }
    if (fullX) drawRectangle(im, [x0, y0 + r + 1, x1, y1 - r - 1], fill, true, 1);
    else if (x1 - r - 1 >= x0 + r + 1) drawRectangle(im, [x0 + r + 1, y0, x1 - r - 1, y1], fill, true, 1);
    if (!fullX && !fullY) {
      drawRectangle(im, [x0, y0 + r + 1, x0 + r, y1 - r - 1], fill, true, 1);
      drawRectangle(im, [x1 - r, y0 + r + 1, x1, y1 - r - 1], fill, true, 1);
    }
  }
  if (outline && !sameInk(outline, fill) && width !== 0) {
    for (const [xy4, s, e] of parts) {
      const [a0, b0, a1, b1] = box(xy4);
      drawArc(im, a0, b0, a1, b1, F(s), F(e), outline, width);
    }
    if (!fullX) {
      drawRectangle(im, [x0 + r + 1, y0, x1 - r - 1, y0 + width - 1], outline, true, 1);
      drawRectangle(im, [x0 + r + 1, y1 - width + 1, x1 - r - 1, y1], outline, true, 1);
    }
    if (!fullY) {
      drawRectangle(im, [x0, y0 + r + 1, x0 + width - 1, y1 - r - 1], outline, true, 1);
      drawRectangle(im, [x1 - width + 1, y0 + r + 1, x1, y1 - r - 1], outline, true, 1);
    }
  }
}

function sameInk(a, b) {
  return !!a && !!b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}
