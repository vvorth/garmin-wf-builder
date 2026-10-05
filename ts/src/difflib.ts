// Python's difflib, the parts the compiler uses: `SequenceMatcher` over
// two strings and `get_close_matches`, which every "did you mean" note
// comes from. A transcription, so the same names are suggested in the
// same order.

interface Match { a: number; b: number; size: number }

function ratioOf(matches: number, length: number): number {
  return length ? 2.0 * matches / length : 1.0;
}

/** difflib.SequenceMatcher with no junk function, over code points. */
export class SequenceMatcher {
  private a: string[] = [];
  private b: string[] = [];
  private b2j = new Map<string, number[]>();
  private fullbcount: Map<string, number> | null = null;
  private matchingBlocks: Match[] | null = null;

  setSeq1(a: string): void {
    this.a = Array.from(a);
    this.matchingBlocks = null;
  }

  setSeq2(b: string): void {
    this.b = Array.from(b);
    this.matchingBlocks = null;
    this.fullbcount = null;
    this.b2j = new Map();
    this.b.forEach((elt, i) => {
      const list = this.b2j.get(elt);
      if (list) list.push(i); else this.b2j.set(elt, [i]);
    });
    // autojunk: popular elements of a long sequence are dropped (len >= 200)
    if (this.b.length >= 200) {
      const ntest = Math.floor(this.b.length / 100) + 1;
      for (const [elt, idxs] of [...this.b2j]) if (idxs.length > ntest) this.b2j.delete(elt);
    }
  }

  findLongestMatch(alo: number, ahi: number, blo: number, bhi: number): Match {
    const { a, b, b2j } = this;
    let besti = alo, bestj = blo, bestsize = 0;
    let j2len = new Map<number, number>();
    for (let i = alo; i < ahi; i++) {
      const next = new Map<number, number>();
      for (const j of b2j.get(a[i]!) ?? []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) ?? 0) + 1;
        next.set(j, k);
        if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
      }
      j2len = next;
    }
    while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) { besti--; bestj--; bestsize++; }
    while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] === b[bestj + bestsize]) bestsize++;
    return { a: besti, b: bestj, size: bestsize };
  }

  getMatchingBlocks(): Match[] {
    if (this.matchingBlocks !== null) return this.matchingBlocks;
    const la = this.a.length, lb = this.b.length;
    const queue: [number, number, number, number][] = [[0, la, 0, lb]];
    const blocks: Match[] = [];
    while (queue.length > 0) {
      const [alo, ahi, blo, bhi] = queue.pop()!;
      const x = this.findLongestMatch(alo, ahi, blo, bhi);
      const { a: i, b: j, size: k } = x;
      if (k) {
        blocks.push(x);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    blocks.sort((p, q) => p.a - q.a || p.b - q.b || p.size - q.size);
    let i1 = 0, j1 = 0, k1 = 0;
    const out: Match[] = [];
    for (const { a: i2, b: j2, size: k2 } of blocks) {
      if (i1 + k1 === i2 && j1 + k1 === j2) k1 += k2;
      else {
        if (k1) out.push({ a: i1, b: j1, size: k1 });
        i1 = i2; j1 = j2; k1 = k2;
      }
    }
    if (k1) out.push({ a: i1, b: j1, size: k1 });
    out.push({ a: la, b: lb, size: 0 });
    this.matchingBlocks = out;
    return out;
  }

  ratio(): number {
    return ratioOf(this.getMatchingBlocks().reduce((n, m) => n + m.size, 0), this.a.length + this.b.length);
  }

  quickRatio(): number {
    if (this.fullbcount === null) {
      this.fullbcount = new Map();
      for (const elt of this.b) this.fullbcount.set(elt, (this.fullbcount.get(elt) ?? 0) + 1);
    }
    const avail = new Map<string, number>();
    let matches = 0;
    for (const elt of this.a) {
      const numb = avail.has(elt) ? avail.get(elt)! : this.fullbcount.get(elt) ?? 0;
      avail.set(elt, numb - 1);
      if (numb > 0) matches++;
    }
    return ratioOf(matches, this.a.length + this.b.length);
  }

  realQuickRatio(): number {
    const la = this.a.length, lb = this.b.length;
    return ratioOf(Math.min(la, lb), la + lb);
  }
}

/** Python's `str` comparison: by code point. */
export function compareStrings(x: string, y: string): number {
  const a = Array.from(x), b = Array.from(y);
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const d = a[i]!.codePointAt(0)! - b[i]!.codePointAt(0)!;
    if (d !== 0) return d;
  }
  return a.length - b.length;
}

/** difflib.get_close_matches: the best "good enough" matches, best first (ties: the larger string first, as `heapq.nlargest` orders them). */
export function getCloseMatches(word: string, possibilities: Iterable<string>, n = 3, cutoff = 0.6): string[] {
  const result: [number, string][] = [];
  const s = new SequenceMatcher();
  s.setSeq2(word);
  for (const x of possibilities) {
    s.setSeq1(x);
    if (s.realQuickRatio() >= cutoff && s.quickRatio() >= cutoff && s.ratio() >= cutoff) result.push([s.ratio(), x]);
  }
  result.sort((p, q) => q[0] - p[0] || compareStrings(q[1], p[1]));
  return result.slice(0, n).map(([, x]) => x);
}
