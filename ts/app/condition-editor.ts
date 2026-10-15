// A value that depends on data, edited as rows: `source · operator · value
// → result`, tried in order, and an `else` row for the rest, written as a
// rule list (`docs/guide/data.md`, "Rules"):
//
//   [{when: "<source> <op> <value>", value: <result>}, …, {else: <result>}]
//
// A boolean key (`visible:`) has no result column: its rows are the
// conditions it is shown under, any one of which shows it. One row is
// written as that condition alone (`visible: system.charging`), several as
// the rule list of `true` rows and `else: false` the format reads the same
// way.
//
// A value opens in the rows when it is a rule list the rows can hold, or a
// `?:` chain whose conditions are one comparison each and whose branches
// are plain values (a reading, a number, a `color.<name>`); written back
// from the rows it becomes the rule list. A value with no condition opens in
// the key's own control, with a button into the rows; anything else (two
// comparisons joined by `and`, a computed colour) opens as its expression,
// the rows' button disabled with the reason. Every change is one write of
// the whole value, made once every row is complete.

import { html } from "htm/preact";
import { useEffect, useState } from "preact/hooks";
import type { JSX, VNode } from "preact";
import { ExprError, parse, type Node, valueText } from "../src/expr.ts";
import type { RuleFamily, SourceInfo, Value, Vocabulary } from "../src/studio/protocol.ts";

type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type KeyEvent = JSX.TargetedKeyboardEvent<HTMLInputElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;

// -- the rows, as data ------------------------------------------------------------

/** A comparison, or `absent`/`present` for `== null`/`!= null`. */
export type Op = "<" | "<=" | ">" | ">=" | "==" | "!=" | "absent" | "present";

/** The operators a row offers, each as the select shows it. */
export const OPS: readonly [Op, string][] = [
  ["<", "<"], ["<=", "≤"], [">", ">"], [">=", "≥"], ["==", "="], ["!=", "≠"], ["absent", "is absent"], ["present", "is present"],
];

/** One condition: a source, an operator and the value it is compared with, as the expression language writes it (`20`, `true`, `"Mon"`). */
export interface Cond { source: string; op: Op; value: string }
/** One row: its condition and, but for a boolean key, the value the key takes while it holds. */
export interface Rule { when: Cond; value: Value }
export interface Rows { rules: Rule[]; otherwise: Value }

/** How a value opens: in the key's own control (no condition), in rows, or as its expression, with why the rows cannot hold it. */
export type Reading =
  | { mode: "plain" }
  | { mode: "rows"; rows: Rows }
  | { mode: "raw"; text: string; why: string };

const COMPARISONS = new Set(["<", "<=", ">", ">=", "==", "!="]);
const COLOR_REF = /^color\.[A-Za-z_][A-Za-z0-9_]*$/;
const HEX = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** A literal as the expression language writes it. */
function literalText(node: Node): string | null {
  if (node.kind !== "literal") return null;
  if (typeof node.value === "string") return JSON.stringify(node.value);
  return valueText(node.value);
}

/** The condition `node` is, when it is one the rows hold: `source op literal`, a bare boolean source, or `not` one. */
export function condOf(node: Node): Cond | null {
  if (node.kind === "ref") return { source: node.path, op: "==", value: "true" };
  if (node.kind === "unary" && node.op === "not" && node.operand.kind === "ref") return { source: node.operand.path, op: "==", value: "false" };
  if (node.kind !== "binary" || !COMPARISONS.has(node.op) || node.left.kind !== "ref") return null;
  const right = node.right;
  if (right.kind === "literal" && right.value === null) {
    if (node.op === "==") return { source: node.left.path, op: "absent", value: "" };
    if (node.op === "!=") return { source: node.left.path, op: "present", value: "" };
    return null;
  }
  const value = literalText(right);
  return value === null ? null : { source: node.left.path, op: node.op as Op, value };
}

/** `text` as a condition the rows hold, or `null`. */
export function parseCond(text: string): Cond | null {
  try {
    return condOf(parse(text));
  } catch (error) {
    if (error instanceof ExprError) return null;
    throw error;
  }
}

/** A condition as the expression language writes it: `== true` as the source alone, `== false` as `not` it. */
export function condText(c: Cond): string {
  if (c.op === "absent") return `${c.source} == null`;
  if (c.op === "present") return `${c.source} != null`;
  if (c.op === "==" && c.value === "true") return c.source;
  if (c.op === "==" && c.value === "false") return `not ${c.source}`;
  return `${c.source} ${c.op} ${c.value}`;
}

/** A branch of a `?:` chain the rows hold: a reading or a palette name, a number, or `true`/`false` for a boolean key. */
function plainOf(node: Node, family: RuleFamily): Value | null {
  if (node.kind === "ref") return family === "color" && !COLOR_REF.test(node.path) ? null : node.path;
  if (node.kind !== "literal" || family === "color") return null;
  if (typeof node.value === "boolean") return family === "boolean" ? node.value : null;
  if (typeof node.value === "number") return node.value;
  if (node.value !== null && typeof node.value === "object" && "value" in node.value) return Number(node.value.value);
  return null;
}

/** A rule list's piece as the chain spells it: a `?:` inside one parenthesised. */
function pieceText(v: unknown): string {
  const t = typeof v === "string" ? v : typeof v === "boolean" || typeof v === "number" ? String(v) : JSON.stringify(v);
  return t.includes("?") ? `(${t})` : t;
}

/** A rule list as the `?:` chain it stands for. */
export function chainText(list: readonly unknown[]): string {
  const rec = (v: unknown): Record<string, unknown> => (v !== null && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {});
  const rules = list.slice(0, -1).map(rec);
  const last = rec(list[list.length - 1]);
  return [...rules.map((r) => `${pieceText(r["when"])} ? ${pieceText(r["value"])} : `), pieceText(last["else"])].join("");
}

/** Whether `v` is the boolean `b`, written as one or as its word. */
const isBool = (v: unknown, b: boolean): boolean => v === b || v === String(b);

/** A rule list's rows, or why the rows cannot hold it. */
function rowsOfList(list: readonly unknown[], family: RuleFamily): Rows | string {
  const items = list.map((v) => (v !== null && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : null));
  const last = items[items.length - 1];
  if (items.length < 2 || !last || !("else" in last) || items.slice(0, -1).some((r) => !r || typeof r["when"] !== "string" || !("value" in r))) {
    return "not a list of when: rules ending in one else:";
  }
  const rules: Rule[] = [];
  for (const r of items.slice(0, -1) as Record<string, unknown>[]) {
    const when = parseCond(String(r["when"]));
    if (when === null) return `the condition "${String(r["when"])}" is more than one comparison`;
    const v = r["value"];
    if (family === "color" && !(typeof v === "string" && COLOR_REF.test(v))) return `a rule's colour "${String(v)}" is not one of the face's colours`;
    if (family === "boolean" && !isBool(v, true)) return "a rule's value is not true";
    if (family === "value" && typeof v !== "string" && typeof v !== "number") return "a rule's value is not an expression";
    rules.push({ when, value: family === "boolean" ? true : v as Value });
  }
  const otherwise = last["else"];
  if (family === "color" && !(typeof otherwise === "string" && COLOR_REF.test(otherwise))) return `the else colour "${String(otherwise)}" is not one of the face's colours`;
  if (family === "boolean" && !isBool(otherwise, false)) return "its else: is not false";
  if (family === "value" && typeof otherwise !== "string" && typeof otherwise !== "number") return "its else: is not an expression";
  return { rules, otherwise: family === "boolean" ? false : otherwise as Value };
}

/** How `value`, the key's value as written, opens. */
export function readCondition(value: Value | undefined, family: RuleFamily): Reading {
  if (value === null || value === undefined || typeof value === "number" || typeof value === "boolean") return { mode: "plain" };
  if (Array.isArray(value)) {
    const rows = rowsOfList(value, family);
    return typeof rows === "string" ? { mode: "raw", text: chainText(value), why: rows } : { mode: "rows", rows };
  }
  if (typeof value !== "string") return { mode: "raw", text: JSON.stringify(value), why: "not an expression" };
  if (family === "color" && (HEX.test(value.trim()) || COLOR_REF.test(value.trim()))) return { mode: "plain" };
  let node: Node;
  try {
    node = parse(value);
  } catch (error) {
    if (error instanceof ExprError) return { mode: "raw", text: value, why: `it does not read: ${error.message}` };
    throw error;
  }
  if (family === "boolean") {
    // one condition, or several joined by `or`: any one of them shows the key
    const conds: Cond[] = [];
    const ors = (n: Node): boolean => {
      if (n.kind === "binary" && n.op === "or") return ors(n.left) && ors(n.right);
      const c = condOf(n);
      if (c !== null) conds.push(c);
      return c !== null;
    };
    if (ors(node)) return { mode: "rows", rows: { rules: conds.map((when) => ({ when, value: true })), otherwise: false } };
    return { mode: "raw", text: value, why: "rows hold one comparison each, any one of which shows it; this is more" };
  }
  if (node.kind !== "conditional") {
    return family === "color" ? { mode: "raw", text: value, why: "a colour computed by an expression" } : { mode: "plain" };
  }
  const rules: Rule[] = [];
  let n: Node = node;
  while (n.kind === "conditional") {
    const when = condOf(n.cond);
    if (when === null) return { mode: "raw", text: value, why: "a condition is more than one comparison" };
    const then = plainOf(n.then, family);
    if (then === null) return { mode: "raw", text: value, why: "a branch is computed, not a plain value" };
    rules.push({ when, value: then });
    n = n.otherwise;
  }
  const otherwise = plainOf(n, family);
  if (otherwise === null) return { mode: "raw", text: value, why: "the last branch is computed, not a plain value" };
  return { mode: "rows", rows: { rules, otherwise } };
}

/** Whether every row says all it must: a source, a value to compare with (but for absent/present) and, but for a boolean key, a result. */
export function complete(rows: Rows, family: RuleFamily): boolean {
  const given = (v: Value | undefined): boolean => v !== null && v !== undefined && v !== "";
  return rows.rules.length > 0 && rows.rules.every((r) => r.when.source !== "" && (r.when.op === "absent" || r.when.op === "present" || r.when.value !== "")
    && (family === "boolean" || given(r.value))) && (family === "boolean" || given(rows.otherwise));
}

/** The value the rows write: a rule list, or for a boolean key with one row, its condition alone. */
export function writeRows(rows: Rows, family: RuleFamily): Value {
  if (family === "boolean") {
    if (rows.rules.length === 1) return condText(rows.rules[0]!.when);
    return [...rows.rules.map((r) => ({ when: condText(r.when), value: true })), { else: false }];
  }
  return [...rows.rules.map((r) => ({ when: condText(r.when), value: r.value })), { else: rows.otherwise }];
}

/** One step of rewriting a rule list in place, its path under the key: a leaf set, a rule inserted or removed. */
export type ListStep =
  | { op: "set"; path: (string | number)[]; value: Value }
  | { op: "insert_item"; path: (string | number)[]; at: number; value: Value }
  | { op: "remove_item"; path: (string | number)[]; at: number };

/** `v`'s rules and its else, when it is a rule list's shape. */
function shaped(v: Value | undefined): [Record<string, Value>[], Value] | null {
  if (!Array.isArray(v) || v.length < 2) return null;
  const items = v.map((x) => (x !== null && typeof x === "object" && !Array.isArray(x) ? x : null));
  const last = items[items.length - 1];
  if (!last || !("else" in last) || items.slice(0, -1).some((r) => !r || !("when" in r))) return null;
  return [items.slice(0, -1) as Record<string, Value>[], last["else"] ?? null];
}

/**
 * The steps that turn the rule list `own` (what the key holds) into `next`
 * in place: each changed `when:`/`value:` set, rules added before the
 * `else:` or removed from the end, the `else:` set; so a list written in
 * block style stays so, and what did not change stays byte for byte.
 * `null` when `own` is not a rule list: the key is then written whole.
 */
export function ruleListSteps(own: Value | undefined, next: Value): ListStep[] | null {
  const before = shaped(own), after = shaped(next);
  if (before === null || after === null) return null;
  const [oldRules, oldElse] = before, [newRules, newElse] = after;
  const same = (a: Value | undefined, b: Value | undefined): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const steps: ListStep[] = [];
  for (let i = 0; i < Math.min(oldRules.length, newRules.length); i++) {
    for (const key of ["when", "value"]) if (!same(oldRules[i]![key], newRules[i]![key])) steps.push({ op: "set", path: [i, key], value: newRules[i]![key] ?? null });
  }
  for (let i = oldRules.length; i < newRules.length; i++) steps.push({ op: "insert_item", path: [], at: i, value: newRules[i]! });
  for (let i = oldRules.length - 1; i >= newRules.length; i--) steps.push({ op: "remove_item", path: [], at: i });
  if (!same(oldElse, newElse)) steps.push({ op: "set", path: [newRules.length, "else"], value: newElse });
  return steps;
}

/** A result typed into a box: a number when it reads as one, else the text. */
export function resultOf(text: string): Value {
  const t = text.trim();
  return t !== "" && Number.isFinite(Number(t)) && /^-?(\d+\.?\d*|\.\d+)$/.test(t) ? Number(t) : t;
}

// -- the editor -------------------------------------------------------------------

export interface ConditionEditorProps {
  family: RuleFamily;
  /** The key's value as the context reads it. */
  value: Value | undefined;
  vocab: Partial<Vocabulary>;
  /** The key's own control, for a value with no condition. */
  plain: VNode;
  /** A result cell: the key's own control over `value`, calling `onPick` with what is picked. */
  result: (value: Value | undefined, onPick: (value: Value) => void) => VNode;
  /** Writes the whole value. */
  onCommit: (value: Value) => void;
}

/** A blank row: no source yet. */
const blankRule = (family: RuleFamily): Rule => ({ when: { source: "", op: "<", value: "" }, value: family === "boolean" ? true : null });

export function ConditionEditor({ family, value, vocab, plain, result, onCommit }: ConditionEditorProps): VNode {
  const reading = readCondition(value, family);
  // what the author asked to see: the rows of a plain value, or the expression of rows
  const [view, setView] = useState<"auto" | "rows" | "raw">("auto");
  const [draft, setDraft] = useState<Rows | null>(null);
  const key = JSON.stringify(value ?? null);
  useEffect(() => { setDraft(null); }, [key]);
  const intoRows = family === "color" ? "follows data…" : "rows";
  if (view === "raw" || reading.mode === "raw") {
    const text = reading.mode === "raw" ? reading.text : typeof value === "string" ? value : Array.isArray(value) ? chainText(value) : value == null ? "" : String(value);
    const why = reading.mode === "raw" ? reading.why : "";
    return html`<span class="condition raw">
      <${ExpressionBox} value=${text} onCommit=${(t: string) => onCommit(family === "value" ? resultOf(t) : t)} />
      <button class="link" disabled=${reading.mode === "raw"} title=${why ? `the rows cannot hold this: ${why}` : "edit it as rows"}
        onClick=${() => setView("rows")}>rows</button>
    </span>`;
  }
  if (reading.mode === "plain" && view !== "rows") {
    return html`<span class="condition plain">${plain}
      <button class="link" title=${family === "color" ? "a colour chosen by rows over data" : "a value chosen by rows over data"}
        onClick=${() => setView("rows")}>${intoRows}</button></span>`;
  }
  const seeded: Rows = reading.mode === "rows" ? reading.rows
    : { rules: [blankRule(family)], otherwise: family === "boolean" ? false : value ?? null };
  const rows = draft ?? seeded;
  const change = (next: Rows): void => {
    setDraft(next);
    if (!complete(next, family)) return;
    const out = writeRows(next, family);
    if (JSON.stringify(out) !== key) onCommit(out);
  };
  const setRule = (i: number, rule: Rule | null): void =>
    change({ ...rows, rules: rule === null ? rows.rules.filter((_, k) => k !== i) : rows.rules.map((r, k) => (k === i ? rule : r)) });
  return html`<div class="condition rows">
    ${rows.rules.map((rule, i) => html`<div class="rule" key=${i}>
      ${family === "boolean" && i > 0 ? html`<span class="dim">or</span>` : null}
      <${CondCells} cond=${rule.when} vocab=${vocab} onChange=${(when: Cond) => setRule(i, { ...rule, when })} />
      ${family !== "boolean" ? html`<span class="dim">→</span>${result(rule.value ?? undefined, (v: Value) => setRule(i, { ...rule, value: v }))}` : null}
      <button class="reset" title="remove this row" aria-label="remove this row" disabled=${rows.rules.length === 1}
        onClick=${() => setRule(i, null)}>×</button>
    </div>`)}
    ${family !== "boolean" ? html`<div class="rule else"><span class="dim">else →</span>${result(rows.otherwise ?? undefined, (v: Value) => change({ ...rows, otherwise: v }))}</div>`
      : html`<div class="note">shown while any row holds</div>`}
    <div class="rule-actions">
      <button class="link" title="a row before else" onClick=${() => setDraft({ ...rows, rules: [...rows.rules, blankRule(family)] })}>+ row</button>
      <button class="link" title="edit it as one expression" onClick=${() => setView("raw")}>as expression</button>
      ${!complete(rows, family) ? html`<span class="note">written once every row is complete</span>` : null}
    </div>
  </div>`;
}

interface CondCellsProps {
  cond: Cond;
  vocab: Partial<Vocabulary>;
  onChange: (cond: Cond) => void;
}

/** A literal as the value box shows it: a string without its quotes. */
const shownValue = (text: string): string => (/^".*"$|^'.*'$/.test(text) ? text.slice(1, -1) : text);

/** What the value box holds as a literal for a source of `info`'s type: a string quoted, anything else as typed. */
function literalFor(text: string, info: SourceInfo | undefined): string {
  if (info?.type === "string") return JSON.stringify(text);
  return text.trim();
}

// source · operator · value: the source picked by namespace (its doc on
// hover), the value in the source's own terms: true/false for a boolean, a
// number (its unit beside it) for a number, text for a string.
function CondCells({ cond, vocab, onChange }: CondCellsProps): VNode {
  const sources = vocab.sources || {};
  const info = vocab.source_info?.[cond.source];
  const listed = Object.values(sources).some((paths) => paths.includes(cond.source));
  const pickSource = (source: string): void => {
    const type = vocab.source_info?.[source]?.type;
    if (type === "boolean") onChange({ source, op: "==", value: "true" });
    else onChange({ ...cond, source, value: vocab.source_info?.[cond.source]?.type === "boolean" ? "" : cond.value });
  };
  const none = cond.op === "absent" || cond.op === "present";
  let valueCell: VNode | null = null;
  if (!none && info?.type === "boolean") {
    valueCell = html`<select value=${cond.value} aria-label="value" onChange=${(e: SelectEvent) => onChange({ ...cond, value: e.currentTarget.value })}>
      <option value="true">true</option><option value="false">false</option></select>`;
  } else if (!none) {
    const numeric = info?.type === "number" || info?.type === "float";
    valueCell = html`<${ValueBox} value=${shownValue(cond.value)} numeric=${numeric} unit=${info?.unit ?? null}
      onCommit=${(t: string) => onChange({ ...cond, value: literalFor(t, info) })} />`;
  }
  return html`<span class="cond">
    <select value=${cond.source} aria-label="source" title=${info?.doc ?? "the reading the row compares"}
      onChange=${(e: SelectEvent) => pickSource(e.currentTarget.value)}>
      ${cond.source === "" ? html`<option value="">source…</option>` : null}
      ${!listed && cond.source !== "" ? html`<option value=${cond.source}>${cond.source}</option>` : null}
      ${Object.entries(sources).map(([ns, paths]) => html`<optgroup label=${ns}>
        ${paths.map((p) => html`<option value=${p} title=${vocab.source_info?.[p]?.doc ?? ""}>${p}</option>`)}</optgroup>`)}
    </select>
    <select value=${cond.op} aria-label="operator" onChange=${(e: SelectEvent) => onChange({ ...cond, op: e.currentTarget.value as Op })}>
      ${OPS.map(([op, label]) => html`<option value=${op}>${label}</option>`)}
    </select>
    ${valueCell}
  </span>`;
}

interface ValueBoxProps {
  value: string;
  numeric: boolean;
  unit: string | null;
  onCommit: (text: string) => void;
}

// The value a row compares with, committed on Enter or when the box loses
// focus; a number's box takes a number only, its unit as the placeholder.
function ValueBox({ value, numeric, unit, onCommit }: ValueBoxProps): VNode {
  const [text, setText] = useState<string>(value);
  useEffect(() => setText(value), [value]);
  const ok = (t: string): boolean => t.trim() !== "" && (!numeric || Number.isFinite(Number(t)));
  return html`<input type="text" class="cond-value" aria-label="value" value=${text} placeholder=${unit ?? "value"} title=${unit ? `in ${unit}` : ""}
    aria-invalid=${text !== "" && !ok(text)} style="width:6em"
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
    onBlur=${(e: InputEvent) => { const t = e.currentTarget.value; if (t !== value && ok(t)) onCommit(t); }}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value); }} />`;
}

interface ExpressionBoxProps {
  value: string;
  onCommit: (text: string) => void;
}

// The value as one expression, committed on Enter or when the box loses focus.
function ExpressionBox({ value, onCommit }: ExpressionBoxProps): VNode {
  const [text, setText] = useState<string>(value);
  useEffect(() => setText(value), [value]);
  return html`<input type="text" class="mono" aria-label="expression" value=${text}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
    onBlur=${(e: InputEvent) => { if (e.currentTarget.value !== value && e.currentTarget.value.trim() !== "") onCommit(e.currentTarget.value); }}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value); }} />`;
}
