// Diagnostics carrying YAML source spans, and their rendering for a
// terminal.
//
// ADR 0002 requires every error to point at the author's YAML, with file,
// line and column, not at an internal representation. ADR 0008 requires
// each diagnostic to carry a severity and, where the check rests on
// estimation, to say so.
import { compareStrings, lines as splitLines } from "./py.ts";
import { SEVERITY_STYLE, style } from "./term.ts";
import { wrap } from "./textwrap.ts";

/** Visible width of the "      note: " label, which continuation lines hang under. */
const NOTE_PREFIX = "      note: ";
const NOTE_INDENT = " ".repeat(NOTE_PREFIX.length);

/** `Bag.render` order: notes, warnings, then errors, so the most important sit next to the summary. */
const RENDER_ORDER: Record<Severity, number> = { note: 0, warning: 1, error: 2 };

export interface RenderOptions {
  color?: boolean;
  /** Wrap prose notes to this width; `null` leaves every note one line. */
  width?: number | null;
  /** Replaces the notes with one collapsed line reading this. */
  notesAs?: string | null;
  /** The header line alone. */
  brief?: boolean;
}

export type Severity = "error" | "warning" | "note";

/** A location in a source file. `line` and `col` are 1-based. */
export class Span {
  readonly path: string;
  readonly line: number;
  readonly col: number;

  constructor(path: string, line: number, col: number) {
    this.path = path;
    this.line = line;
    this.col = col;
  }

  toString(): string {
    return `${this.path}:${this.line}:${this.col}`;
  }
}

export interface DiagnosticOptions {
  /** Free-form follow-up lines: suggestions, the legal alternatives, etc. */
  notes?: string[];
  /** Set when the finding rests on estimation rather than measurement (ADR 0008). */
  confidence?: string | null;
}

export class Diagnostic {
  severity: Severity;
  code: string;
  message: string;
  span: Span | null;
  notes: string[];
  confidence: string | null;

  constructor(severity: Severity, code: string, message: string, span: Span | null = null,
    { notes = [], confidence = null }: DiagnosticOptions = {}) {
    this.severity = severity;
    this.code = code;
    this.message = message;
    this.span = span;
    this.notes = notes;
    this.confidence = confidence;
  }

  /** Render one diagnostic; plain text with the defaults. */
  render(sources: ReadonlyMap<string, string[]> | null = null,
    { color = false, width = null, notesAs = null, brief = false }: RenderOptions = {}): string {
    const sevStyles = SEVERITY_STYLE[this.severity]!;
    const head = this.span ? `${style(this.span.path, ["bold"], color)}:${this.span.line}:${this.span.col}: ` : "";
    const out = [`${head}${style(this.severity, sevStyles, color)}${style(`[${this.code}]`, ["dim"], color)}: ${style(this.message, ["bold"], color)}`];
    if (brief) return out[0]!;
    if (this.span && sources) {
      const lines = sources.get(this.span.path);
      if (lines && this.span.line > 0 && this.span.line <= lines.length) {
        const gutter = `${String(this.span.line).padStart(5)} | `;
        out.push(`${style(gutter, ["dim"], color)}${lines[this.span.line - 1]!}`);
        out.push(" ".repeat(gutter.length) + " ".repeat(this.span.col - 1) + style("^", sevStyles, color));
      }
    }
    if (notesAs !== null) {
      out.push(`      ${style("note:", ["bold", "cyan"], color)} ${notesAs}`);
    } else {
      for (const note of this.notes) out.push(...renderNote(note, color, width));
      if (this.confidence) out.push(`      ${style("confidence:", ["dim"], color)} ${this.confidence}`);
    }
    return out.join("\n");
  }
}

/** One `note:` entry: a note with its own newlines printed as is, prose wrapped under its label. */
function renderNote(note: string, color: boolean, width: number | null): string[] {
  const label = style("note:", ["bold", "cyan"], color);
  let lines: string[];
  if (note.includes("\n") || !width) {
    lines = splitLines(note);
    if (lines.length === 0) lines = [""];
  } else {
    lines = wrap(note, Math.max(1, width - NOTE_PREFIX.length));
    if (lines.length === 0) lines = [""];
  }
  return [`      ${label} ${lines[0]!}`, ...lines.slice(1).map((line) => NOTE_INDENT + line)];
}

/** `id` as a word of its own: `fr955` in "on fr955." but not in "fr955s". */
function naming(id: string): RegExp {
  return new RegExp(`(?<![\\w-])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`, "g");
}

/**
 * `items` with each set of diagnostics that differ only in which one of
 * `devices` they name merged into the first of them, which says where else
 * it holds: "… which fr955 lacks -- and the same on fenix8solar47mm". A
 * check run per device says the same thing once per target, and the
 * repeats bury what differs. Order is kept; nothing else is merged.
 */
export function mergedAcrossDevices(items: readonly Diagnostic[], devices: readonly string[]): Diagnostic[] {
  if (devices.length < 2) return [...items];
  const patterns = devices.map((id) => [id, naming(id)] as const);
  const out: Diagnostic[] = [];
  const groups = new Map<string, { at: number; also: string[] }>();
  for (const d of items) {
    const named = patterns.filter(([, re]) => d.message.search(re) >= 0);
    if (named.length !== 1) {
      out.push(d);
      continue;
    }
    const [id, re] = named[0]!;
    const mask = (text: string): string => text.replace(re, "\0");
    const key = JSON.stringify([d.severity, d.code, d.span?.toString() ?? null, mask(d.message), d.notes.map(mask), d.confidence]);
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, { at: out.length, also: [] });
      out.push(d);
    } else if (!group.also.includes(id) && out[group.at]!.message.search(re) < 0) {
      group.also.push(id);
    }
  }
  for (const { at, also } of groups.values()) {
    if (also.length === 0) continue;
    const d = out[at]!;
    out[at] = new Diagnostic(d.severity, d.code, `${d.message} -- and the same on ${also.join(", ")}`, d.span,
      { notes: d.notes, confidence: d.confidence });
  }
  return out;
}

/** Collects diagnostics across a build and decides whether it may proceed. */
export class Bag {
  items: Diagnostic[] = [];
  /** The devices the design was checked for (`selectDevices`), whose repeats `render` and `summary` merge. */
  devices: readonly string[] = [];
  /** Each registered file's lines, for rendering a diagnostic's source excerpt. */
  sources = new Map<string, string[]>();

  registerSource(path: string, text: string): void {
    this.sources.set(path, splitLines(text));
  }

  add(diag: Diagnostic): Diagnostic {
    this.items.push(diag);
    return diag;
  }

  error(code: string, message: string, span: Span | null = null, options: DiagnosticOptions = {}): Diagnostic {
    return this.add(new Diagnostic("error", code, message, span, options));
  }

  warning(code: string, message: string, span: Span | null = null, options: DiagnosticOptions = {}): Diagnostic {
    return this.add(new Diagnostic("warning", code, message, span, options));
  }

  note(code: string, message: string, span: Span | null = null, options: DiagnosticOptions = {}): Diagnostic {
    return this.add(new Diagnostic("note", code, message, span, options));
  }

  /** A bag of the diagnostics `keep` accepts, rendering against the same source lines. */
  only(keep: (d: Diagnostic) => boolean): Bag {
    const view = new Bag();
    view.sources = this.sources;
    view.devices = this.devices;
    view.items = this.items.filter(keep);
    return view;
  }

  get errors(): Diagnostic[] {
    return this.items.filter((d) => d.severity === "error");
  }

  ok(): boolean {
    return this.errors.length === 0;
  }

  /** The diagnostics as shown: repeats across `devices` merged (`mergedAcrossDevices`). */
  shown(): Diagnostic[] {
    return mergedAcrossDevices(this.items, this.devices);
  }

  /**
   * Every diagnostic as `shown` (each one, with `merge` off), notes first and errors last. Without `verbose`, notes
   * are their header lines alone, as one block. A diagnostic repeating an
   * earlier one's `(code, notes, confidence)` collapses its notes to one
   * "same notes as" line.
   */
  render({ color = false, width = null, verbose = true, merge = true }:
    { color?: boolean; width?: number | null; verbose?: boolean; merge?: boolean } = {}): string {
    const ordered = (merge ? this.shown() : this.items).map((d, i) => [d, i] as const)
      .sort((a, b) => RENDER_ORDER[a[0].severity] - RENDER_ORDER[b[0].severity] || a[1] - b[1]).map(([d]) => d);
    const seen = new Set<string>();
    const pieces: string[] = [];
    const brief = verbose ? [] : ordered.filter((d) => d.severity === "note");
    if (brief.length > 0) {
      const lines = brief.map((d) => d.render(null, { color, brief: true }));
      if (brief.some((d) => d.notes.length > 0 || d.confidence || d.span)) {
        lines.push(style("      (-v shows the notes in full)", ["dim"], color));
      }
      pieces.push(lines.join("\n"));
    }
    for (const d of ordered) {
      if (brief.length > 0 && d.severity === "note") continue;
      const key = JSON.stringify([d.code, d.notes, d.confidence]);
      let notesAs: string | null = null;
      if ((d.notes.length > 0 || d.confidence) && seen.has(key)) notesAs = `same notes as the earlier [${d.code}] above`;
      else seen.add(key);
      pieces.push(d.render(this.sources, { color, width, notesAs }));
    }
    return pieces.join("\n\n");
  }

  /** "N errors, N warnings, N notes" of those `shown`, or "no diagnostics". */
  summary({ color = false }: { color?: boolean } = {}): string {
    const parts: string[] = [];
    const shown = this.shown();
    for (const severity of ["error", "warning", "note"] as const) {
      const n = shown.filter((d) => d.severity === severity).length;
      if (n) parts.push(style(`${n} ${severity}${n !== 1 ? "s" : ""}`, SEVERITY_STYLE[severity]!, color));
    }
    return parts.length > 0 ? parts.join(", ") : "no diagnostics";
  }
}

/** The shared "did you mean" note for a misspelled name: one note naming `near`, or none. */
export function didYouMean(near: string[]): string[] {
  return near.length > 0 ? [`did you mean: ${near.join(", ")}?`] : [];
}

/**
 * A fixed, name-keyed table an author picks from (data sources, graph
 * series, complication types), with the one fuzzy lookup its "unknown
 * name" diagnostics share.
 */
export class Catalogue<T> extends Map<string, T> {
  /** The nearest names, best first. */
  suggest(name: string, limit = 3): string[] {
    return getCloseMatches(name, this.keys(), limit, 0.5);
  }

  didYouMeanNotes(name: string, limit = 3): string[] {
    return didYouMean(this.suggest(name, limit));
  }
}

/** Characters matched by Ratcliff/Obershelp: the longest common run (earliest on a tie), then the same either side of it. */
function matched(a: readonly string[], b: readonly string[]): number {
  let best = 0, bi = 0, bj = 0;
  let row = new Array<number>(b.length + 1).fill(0);
  for (let i = 0; i < a.length; i++) {
    const next = new Array<number>(b.length + 1).fill(0);
    for (let j = 0; j < b.length; j++) {
      if (a[i] !== b[j]) continue;
      next[j + 1] = row[j]! + 1;
      if (next[j + 1]! > best) [best, bi, bj] = [next[j + 1]!, i + 1 - next[j + 1]!, j + 1 - next[j + 1]!];
    }
    row = next;
  }
  if (best === 0) return 0;
  return best + matched(a.slice(0, bi), b.slice(0, bj)) + matched(a.slice(bi + best), b.slice(bj + best));
}

/** difflib's `SequenceMatcher(None, x, y).ratio()` over code points. */
function similarity(x: string, y: string): number {
  const a = Array.from(x), b = Array.from(y);
  return a.length + b.length ? 2 * matched(a, b) / (a.length + b.length) : 1;
}

/** The "did you mean" candidates: up to `n` of `possibilities` at least `cutoff` similar to `word`, best first. */
export function getCloseMatches(word: string, possibilities: Iterable<string>, n = 3, cutoff = 0.6): string[] {
  const scored: [number, string][] = [];
  for (const x of possibilities) {
    const score = similarity(x, word);
    if (score >= cutoff) scored.push([score, x]);
  }
  scored.sort((p, q) => q[0] - p[0] || compareStrings(q[1], p[1]));
  return scored.slice(0, n).map(([, x]) => x);
}
