// Diagnostics carrying YAML source spans. Port of wfb/diagnostics.py's
// data; rendering for a terminal comes with the CLI.
//
// ADR 0002 requires every error to point at the author's YAML, with file,
// line and column, not at an internal representation. ADR 0008 requires
// each diagnostic to carry a severity and, where the check rests on
// estimation, to say so.
import { getCloseMatches } from "./difflib.ts";

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
}

/** Collects diagnostics across a build and decides whether it may proceed. */
export class Bag {
  items: Diagnostic[] = [];
  /** Each registered file's lines, for rendering a diagnostic's source excerpt. */
  sources = new Map<string, string[]>();

  registerSource(path: string, text: string): void {
    this.sources.set(path, text.split(/\r\n|\r|\n/));
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
    view.items = this.items.filter(keep);
    return view;
  }

  get errors(): Diagnostic[] {
    return this.items.filter((d) => d.severity === "error");
  }

  ok(): boolean {
    return this.errors.length === 0;
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
