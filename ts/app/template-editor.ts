// A `text:` template as chips: a literal chip for each run of text (edited
// in place), a data chip for each placeholder (the source it reads, its
// format spec and the source's unit; a click opens a source picker grouped
// by namespace, the specs its type takes, a free spec box and the
// expression itself), and a `{unit}` chip where the template has one. Chips
// reorder by dragging one onto another, × removes one, "+ text" and
// "+ data" add one at the caret (the chip last focused, splitting a
// literal at its caret) or at the end. Every change writes the whole
// template once, rebuilt from the chips: what a chip did not change is
// written back exactly as it was, spaces and escaped braces included.
//
// A template the parser cannot read opens as its text, with the error
// shown, and so does "edit as text"; nothing typed is lost either way.

import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { JSX, VNode } from "preact";
import { parseTemplate, TemplateError } from "../src/template.ts";
import type { FormatCode, FormatCodes, SourceInfo, Vocabulary } from "../src/studio/protocol.ts";
import { Popover } from "./ui.ts";

type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type KeyEvent = JSX.TargetedKeyboardEvent<HTMLInputElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;
type DragEvent = JSX.TargetedDragEvent<HTMLSpanElement>;

// -- the chips, as data -----------------------------------------------------------

/** A run of literal text. */
export interface TextChip { kind: "text"; text: string }
/**
 * A placeholder: its expression (a source path, or any expression), its
 * spec (`null` for none), and what it was written with round them, so an
 * unchanged chip rebuilds exactly: the spaces before and after the
 * expression, and a colon with no spec after it.
 */
export interface DataChip { kind: "data"; expr: string; spec: string | null; lead: string; trail: string; colon: boolean }
/** `{unit}`, as written between its braces. */
export interface UnitChip { kind: "unit"; inner: string }
export type Chip = TextChip | DataChip | UnitChip;

/** A template read as chips, or why it cannot be. */
export type Chips = { ok: true; chips: Chip[] } | { ok: false; error: string; offset: number };

const WHITESPACE = /\s/u;

/**
 * `text` as chips, through the compiler's own parser (`parseTemplate`):
 * the parser says what each piece is, and the text says how it was
 * written, so `templateOf(chips)` gives `text` back.
 */
export function chipsOf(text: string): Chips {
  let pieces;
  try {
    pieces = parseTemplate(text).pieces;
  } catch (error) {
    if (error instanceof TemplateError) return { ok: false, error: error.message, offset: error.offset };
    throw error;
  }
  const chars = Array.from(text);
  const chips: Chip[] = [];
  let i = 0;
  for (const piece of pieces) {
    if (piece.kind === "literal") {
      // a brace in a literal is written twice
      const written = Array.from(piece.text).reduce((n, c) => n + (c === "{" || c === "}" ? 2 : 1), 0);
      chips.push({ kind: "text", text: piece.text });
      i += written;
    } else if (piece.kind === "unit") {
      const close = chars.indexOf("}", i);
      chips.push({ kind: "unit", inner: chars.slice(i + 1, close).join("") });
      i = close + 1;
    } else {
      // the placeholder's text is its expression stripped: the spaces before and after it are kept apart
      let start = piece.offset;
      let lead = "";
      while (start < chars.length && WHITESPACE.test(chars[start]!)) lead += chars[start++];
      let j = start + Array.from(piece.expr).length;
      const exprEnd = j;
      while (j < chars.length && chars[j] !== ":" && chars[j] !== "}") j++;
      const trail = chars.slice(exprEnd, j).join("");
      if (chars[j] === "}") {
        chips.push({ kind: "data", expr: piece.expr, spec: null, lead, trail, colon: false });
        i = j + 1;
      } else {
        const close = chars.indexOf("}", j + 1);
        chips.push({ kind: "data", expr: piece.expr, spec: piece.spec, lead, trail, colon: true });
        i = close + 1;
      }
    }
  }
  return { ok: true, chips };
}

/** The template `chips` spell: a literal's braces doubled, a placeholder as it was written round its expression. */
export function templateOf(chips: readonly Chip[]): string {
  return chips.map((c) => {
    if (c.kind === "text") return c.text.replace(/[{}]/g, (b) => b + b);
    if (c.kind === "unit") return `{${c.inner}}`;
    const spec = c.colon || c.spec !== null ? `:${c.spec ?? ""}` : "";
    return `{${c.lead}${c.expr}${c.trail}${spec}}`;
  }).join("");
}

/** A new placeholder for `expr`, with `spec` (or none). */
export const dataChip = (expr: string, spec: string | null = null): DataChip => ({ kind: "data", expr, spec, lead: "", trail: "", colon: spec !== null });

/** `chips` with the one at `from` moved to `to` (an index into `chips` as they are). */
export function moved<T>(chips: readonly T[], from: number, to: number): T[] {
  const out = [...chips];
  const [chip] = out.splice(from, 1);
  out.splice(Math.max(0, Math.min(to, out.length)), 0, chip!);
  return out;
}

/** Where a new chip goes: after chip `index` (-1: first), or inside a literal chip at `offset` code points, splitting it. */
export interface Caret { index: number; offset: number | null }

/** `chips` with `chip` inserted at `caret` (the end when `null`). */
export function inserted(chips: readonly Chip[], chip: Chip, caret: Caret | null): Chip[] {
  if (caret === null || caret.index >= chips.length) return [...chips, chip];
  const at = chips[caret.index];
  if (at && at.kind === "text" && caret.offset !== null) {
    const points = Array.from(at.text);
    const before = points.slice(0, caret.offset).join(""), after = points.slice(caret.offset).join("");
    const parts: Chip[] = [...(before ? [{ kind: "text", text: before } as Chip] : []), chip, ...(after ? [{ kind: "text", text: after } as Chip] : [])];
    return [...chips.slice(0, caret.index), ...parts, ...chips.slice(caret.index + 1)];
  }
  return [...chips.slice(0, caret.index + 1), chip, ...chips.slice(caret.index + 1)];
}

/**
 * The specs a placeholder over a source of `info`'s type takes, each group
 * with whether a pick replaces the spec (a number's) or adds a code to it
 * (strftime codes: `%H` then `:` then `%M`). An expression, whose type is
 * not known here, is offered a number's specs and the duration codes.
 */
export function specGroups(info: SourceInfo | undefined, codes: Partial<FormatCodes>): { label: string; codes: FormatCode[]; append: boolean }[] {
  const type = info?.type;
  if (type === "time") return [{ label: "time", codes: codes.time ?? [], append: true }];
  if (type === "date") return [{ label: "date", codes: codes.date ?? [], append: true }];
  if (type === "string" || type === "boolean" || type === "color") return [];
  return [
    { label: "number", codes: codes.number ?? [], append: false },
    { label: "as seconds", codes: codes.duration ?? [], append: true },
  ];
}

// -- the editor -------------------------------------------------------------------

export interface TemplateEditorProps {
  /** The template as written. */
  value: string;
  vocab: Partial<Vocabulary>;
  /** Writes the whole template. */
  onCommit: (text: string) => void;
}

/** The chip editor, or the template's text when it does not parse or the author asked for it. */
export function TemplateEditor({ value, vocab, onCommit }: TemplateEditorProps): VNode {
  const parsed = chipsOf(value);
  const [asText, setAsText] = useState<boolean>(false);
  useEffect(() => { if (!parsed.ok) setAsText(false); }, [value]);
  if (!parsed.ok || asText) {
    return html`<span class="template raw">
      <${RawTemplate} value=${value} onCommit=${onCommit} />
      ${parsed.ok ? html`<button class="link" title="back to the chips" onClick=${() => setAsText(false)}>chips</button>` : null}
      ${!parsed.ok ? html`<div class="note error-text" title=${`at character ${parsed.offset + 1}`}>${parsed.error}: edited as text until it reads</div>` : null}
    </span>`;
  }
  return html`<${ChipEditor} value=${value} chips=${parsed.chips} vocab=${vocab} onCommit=${onCommit} onAsText=${() => setAsText(true)} />`;
}

interface RawTemplateProps {
  value: string;
  onCommit: (text: string) => void;
}

// The template's text in one box, committed on Enter or when the box loses focus.
function RawTemplate({ value, onCommit }: RawTemplateProps): VNode {
  const [text, setText] = useState<string>(value);
  useEffect(() => setText(value), [value]);
  return html`<input type="text" class="mono tpl-raw" aria-label="the template as text" value=${text}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
    onBlur=${(e: InputEvent) => { if (e.currentTarget.value !== value) onCommit(e.currentTarget.value); }}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value); }} />`;
}

interface ChipEditorProps {
  value: string;
  chips: Chip[];
  vocab: Partial<Vocabulary>;
  onCommit: (text: string) => void;
  onAsText: () => void;
}

function ChipEditor({ value, chips: written, vocab, onCommit, onAsText }: ChipEditorProps): VNode {
  // the chips as shown: the written ones, plus a literal added and not typed into yet
  const [chips, setChips] = useState<Chip[]>(written);
  const caret = useRef<Caret | null>(null);
  const dragging = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  useEffect(() => { setChips(written); caret.current = null; }, [value]);
  const write = (next: Chip[]): void => {
    setChips(next);
    const text = templateOf(next);
    if (text !== value) onCommit(text);
  };
  const replace = (i: number, chip: Chip | null): void => write(chip === null ? chips.filter((_, k) => k !== i) : chips.map((c, k) => (k === i ? chip : c)));
  const add = (chip: Chip): void => write(inserted(chips, chip, caret.current));
  const addText = (): void => {
    const at = caret.current === null || caret.current.index >= chips.length ? chips.length : caret.current.index + 1;
    caret.current = { index: at, offset: null };
    setChips([...chips.slice(0, at), { kind: "text", text: "" }, ...chips.slice(at)]);
  };
  const drop = (to: number): void => {
    const from = dragging.current;
    dragging.current = null;
    setOver(null);
    if (from === null || from === to) return;
    write(moved(chips, from, to));
  };
  const sources = vocab.sources || {};
  return html`<span class="template chips">
    ${chips.map((chip, i) => html`<span key=${i} class=${"tpl-chip tpl-" + chip.kind + (over === i ? " over" : "")} draggable="true"
        title="drag onto another chip to reorder"
        onDragStart=${(e: DragEvent) => { dragging.current = i; try { e.dataTransfer?.setData("text/plain", String(i)); } catch { /* a test's event has none */ } }}
        onDragOver=${(e: DragEvent) => { e.preventDefault(); if (over !== i) setOver(i); }}
        onDragLeave=${() => { if (over === i) setOver(null); }}
        onDrop=${(e: DragEvent) => { e.preventDefault(); drop(i); }}
        onDragEnd=${() => { dragging.current = null; setOver(null); }}>
      ${chip.kind === "text" ? html`<${LiteralChip} chip=${chip}
          onCaret=${(offset: number | null) => { caret.current = { index: i, offset }; }}
          onCommit=${(text: string) => replace(i, text === "" ? null : { kind: "text", text })} />`
        : chip.kind === "unit" ? html`<span class="tpl-label" title="the label of the unit units: converts to">unit</span>`
        : html`<${DataChipView} chip=${chip} vocab=${vocab} onFocus=${() => { caret.current = { index: i, offset: null }; }}
            onChange=${(next: DataChip) => replace(i, next)} />`}
      <button class="reset tpl-remove" title="remove this chip" aria-label=${`remove ${chip.kind === "data" ? chip.expr : chip.kind === "unit" ? "unit" : `"${chip.text}"`}`}
        onClick=${() => replace(i, null)}>×</button>
    </span>`)}
    <span class="tpl-add">
      <button title="add literal text at the caret, or at the end" onClick=${addText}>+ text</button>
      <select value="" aria-label="add data" title="add a data placeholder at the caret, or at the end"
        onChange=${(e: SelectEvent) => { const path = e.currentTarget.value; e.currentTarget.value = ""; if (path) add(dataChip(path)); }}>
        <option value="">+ data</option>
        ${Object.entries(sources).map(([ns, paths]) => html`<optgroup label=${ns}>
          ${paths.map((p) => html`<option value=${p} title=${vocab.source_info?.[p]?.doc ?? ""}>${p}</option>`)}</optgroup>`)}
      </select>
      <button class="link" title="edit the template as its text" onClick=${onAsText}>edit as text</button>
    </span>
  </span>`;
}

interface LiteralChipProps {
  chip: TextChip;
  onCaret: (offset: number | null) => void;
  onCommit: (text: string) => void;
}

// A literal chip: its text in a box as wide as the text, committed on Enter
// or when the box loses focus; emptied, the chip goes. Its caret is where
// "+ data" splits it.
function LiteralChip({ chip, onCaret, onCommit }: LiteralChipProps): VNode {
  const [text, setText] = useState<string>(chip.text);
  useEffect(() => setText(chip.text), [chip.text]);
  const mark = (e: InputEvent | KeyEvent): void => {
    const box = e.currentTarget;
    const at = typeof box.selectionStart === "number" ? Array.from(box.value.slice(0, box.selectionStart)).length : null;
    onCaret(at);
  };
  return html`<input type="text" class="tpl-literal" aria-label="literal text" value=${text} size=${Math.max(1, Array.from(text).length)}
    placeholder="text" onFocus=${mark} onClick=${mark} onKeyUp=${mark}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
    onBlur=${(e: InputEvent) => { mark(e); if (e.currentTarget.value !== chip.text || chip.text === "") onCommit(e.currentTarget.value); }}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(chip.text); }} />`;
}

interface DataChipProps {
  chip: DataChip;
  vocab: Partial<Vocabulary>;
  onFocus: () => void;
  onChange: (chip: DataChip) => void;
}

// A placeholder chip: the source (or expression), its spec and the source's
// unit; a click opens the picker.
function DataChipView({ chip, vocab, onFocus, onChange }: DataChipProps): VNode {
  const info = vocab.source_info?.[chip.expr];
  const label = html`<span class="tpl-expr mono">${chip.expr || "…"}</span>${chip.spec ? html`<span class="tpl-spec mono">:${chip.spec}</span>` : null}${info?.unit ? html`<span class="tpl-unit-hint dim">${info.unit}</span>` : null}`;
  return html`<span onFocusIn=${onFocus}><${Popover} buttonClass="tpl-data-button" bodyClass="pop tpl-pop" title=${info ? `${chip.expr}: ${info.doc}` : chip.expr} label=${label}>
    <${DataPicker} chip=${chip} vocab=${vocab} onChange=${onChange} />
  </${Popover}></span>`;
}

interface DataPickerProps {
  chip: DataChip;
  vocab: Partial<Vocabulary>;
  onChange: (chip: DataChip) => void;
}

// What a placeholder reads and how it is shown: a source picker grouped by
// namespace (each source's doc as its title), the expression itself, the
// specs the source's type takes (a number's replace the spec, a code is
// added to it) and the spec as text.
function DataPicker({ chip, vocab, onChange }: DataPickerProps): VNode {
  const info = vocab.source_info?.[chip.expr];
  const sources = vocab.sources || {};
  const known = info !== undefined;
  const setSpec = (spec: string | null): void => onChange({ ...chip, spec: spec === "" ? null : spec, colon: spec !== null && spec !== "" });
  return html`<div class="pop-group">
      <div class="pop-title">Source</div>
      <select value=${known ? chip.expr : ""} aria-label="source" onChange=${(e: SelectEvent) => { const p = e.currentTarget.value; if (p) onChange({ ...chip, expr: p }); }}>
        ${known ? null : html`<option value="">(an expression)</option>`}
        ${Object.entries(sources).map(([ns, paths]) => html`<optgroup label=${ns}>
          ${paths.map((p) => html`<option value=${p} title=${vocab.source_info?.[p]?.doc ?? ""}>${p}</option>`)}</optgroup>`)}
      </select>
      ${info ? html`<div class="note">${info.doc}${info.unit ? ` · ${info.unit}` : ""}${info.nullable ? " · can be absent" : ""}</div>` : null}
      <label class="tpl-field">expression <${Box} value=${chip.expr} label="expression" mono onCommit=${(t: string) => { if (t.trim()) onChange({ ...chip, expr: t.trim() }); }} /></label>
    </div>
    <div class="pop-group">
      <div class="pop-title">Format</div>
      ${specGroups(info, vocab.format_codes ?? {}).map((group) => html`<div class="tpl-specs" title=${group.append ? "adds the code to the spec" : "sets the spec"}>
        <span class="dim">${group.label}</span>
        ${group.codes.map(([spec, what]) => html`<button class=${"spec mono" + (chip.spec === spec ? " on" : "")} title=${what}
          onClick=${() => setSpec(group.append ? (chip.spec ?? "") + spec : spec)}>${spec}</button>`)}
      </div>`)}
      <label class="tpl-field">spec <${Box} value=${chip.spec ?? ""} label="format spec" mono onCommit=${(t: string) => setSpec(t)} /></label>
      ${chip.spec !== null ? html`<button class="reset" title="no spec: the value's own text" onClick=${() => setSpec(null)}>no spec</button>` : null}
    </div>`;
}

interface BoxProps {
  value: string;
  label: string;
  mono?: boolean;
  onCommit: (text: string) => void;
}

// A text box committed on Enter or when it loses focus.
function Box({ value, label, mono = false, onCommit }: BoxProps): VNode {
  const [text, setText] = useState<string>(value);
  useEffect(() => setText(value), [value]);
  return html`<input type="text" class=${mono ? "mono" : ""} aria-label=${label} value=${text}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
    onBlur=${(e: InputEvent) => { if (e.currentTarget.value !== value) onCommit(e.currentTarget.value); }}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value); }} />`;
}
