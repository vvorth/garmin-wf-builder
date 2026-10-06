// A line diff, for showing what a change elsewhere did to the face's text
// (the YAML tab's conflict). Pure functions, no DOM, so Node can check
// them (tests/test_studio_frontend.py).

// Past this many cells, a middle part is shown as removed then added
// rather than compared line by line: a face's text never gets near it.
const MAX_CELLS = 4_000_000;

// `a` to `b` as `[{op: "same" | "del" | "add", text}]`, one per line, in
// order: a longest common subsequence of lines.
export function lineDiff(a, b) {
  const x = a.split("\n"), y = b.split("\n");
  let start = 0;
  while (start < x.length && start < y.length && x[start] === y[start]) start++;
  let endX = x.length, endY = y.length;
  while (endX > start && endY > start && x[endX - 1] === y[endY - 1]) { endX--; endY--; }
  const same = (lines) => lines.map((text) => ({ op: "same", text }));
  return [...same(x.slice(0, start)), ...middle(x.slice(start, endX), y.slice(start, endY)),
          ...same(x.slice(endX))];
}

function middle(x, y) {
  const n = x.length, m = y.length;
  if (n * m > MAX_CELLS) {
    return [...x.map((text) => ({ op: "del", text })), ...y.map((text) => ({ op: "add", text }))];
  }
  // lengths[i][j]: the common subsequence of x[i:] and y[j:]
  const lengths = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lengths[i][j] = x[i] === y[j] ? lengths[i + 1][j + 1] + 1
        : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push({ op: "same", text: x[i] }); i++; j++; }
    else if (lengths[i + 1][j] >= lengths[i][j + 1]) out.push({ op: "del", text: x[i++] });
    else out.push({ op: "add", text: y[j++] });
  }
  while (i < n) out.push({ op: "del", text: x[i++] });
  while (j < m) out.push({ op: "add", text: y[j++] });
  return out;
}

// How many lines `ops` adds and removes: `{added, removed}`.
export function diffCounts(ops) {
  let added = 0, removed = 0;
  for (const o of ops) { if (o.op === "add") added++; else if (o.op === "del") removed++; }
  return { added, removed };
}

// The changed lines of `ops` with `context` unchanged lines around each,
// and `{op: "gap"}` where unchanged lines are left out.
export function hunks(ops, context = 2) {
  const near = ops.map(() => false);
  ops.forEach((o, i) => {
    if (o.op === "same") return;
    for (let k = Math.max(0, i - context); k <= Math.min(ops.length - 1, i + context); k++) near[k] = true;
  });
  const out = [];
  ops.forEach((o, i) => {
    if (near[i]) out.push(o);
    else if (out.length && out[out.length - 1].op !== "gap") out.push({ op: "gap" });
  });
  if (out.length && out[out.length - 1].op === "gap") out.pop();
  return out;
}

// "added 2 lines and removed 1", for the conflict banner.
export function changeSummary({ added, removed }) {
  const lines = (n) => `${n} line${n === 1 ? "" : "s"}`;
  if (added && removed) return `added ${lines(added)} and removed ${lines(removed)}`;
  if (added) return `added ${lines(added)}`;
  if (removed) return `removed ${lines(removed)}`;
  return "left the text as it was";
}
