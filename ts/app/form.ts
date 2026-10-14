// The generic form over the inspector's field tree (`protocol.ts`'s
// `Field`), and the small controls it is built from, which the Face panel
// shares. One recursive component renders a field by its kind: a scalar as
// the control its `widget` names, an object as a fieldset of its children,
// a list as its items with reorder, remove and add, a choice as a segmented
// control over its branches with the chosen branch's field beneath. Every
// change is one edit sent to the worker (`onEdit`), which patches the text,
// checks it and answers with the face; a refused edit leaves the face as it
// was and says why.
//
// The editing context decides where an edit lands. The tree answers for one
// frame (`Inspect.context`): in the always-on frame the keys the element's
// kind restyles there (`aod_keys`, plus `visible` and `dim`) are edited in
// the element's `aod:` block (the `aod` scope) and every other key is shown
// read-only; awake, a geometry key goes to the element's own key or, as
// **Edit for** says (`target`), to its override for the viewed watch, its
// shape or its display class. Each control shows the value the context
// reads (`effective`), with a badge naming where it comes from when that is
// not the key itself, and its title says where an edit is written.

import { html } from "htm/preact";
import { useState, useEffect, useRef } from "preact/hooks";
import type { JSX, VNode } from "preact";
import YAML from "yaml";
import {
  ANGLE_UNITS, at, colorName, convertQuantity, formatQuantity, lengthUnitsFor, parseHex, parseQuantity, safeOn, swatchFor, toHex,
} from "./values.ts";
import { AddName, Popover } from "./ui.ts";
import type {
  EditOp, EditScope, Effective, Field, Globals, IconSpelling, Inspect, Path, Scope, Summary, Value, Vocabulary,
} from "../src/studio/protocol.ts";

// -- the callbacks and the context the panels share ---------------------------------------

/** One edit sent to the worker: the face it produced, or null when it was refused. The Inspector awaits a rename's to select the renamed element. */
export type OnEdit = (op: EditOp) => Promise<Summary | null> | void;
/** Show lines `line` to `end` of the text in the YAML tab. */
export type OnReveal = (line: number, end: number) => void;
export type OnSelect = (id: string) => void;
export type FaceSectionKey = "targets" | "colours" | "colour_settings" | "schemes" | "styles" | "hand_sets" | "slots" | "fonts";
export type OnFaceSection = (key: FaceSectionKey) => void;

/** What the pickers read: the face as a whole and the format's words. The vocabulary is partial until the worker has answered. */
export interface FaceCtx {
  globals: Globals;
  vocab: Partial<Vocabulary>;
}

/** The form's widgets' context: the viewed device's system fonts, the selected element's type, and where a link may jump. */
export interface WidgetCtx extends FaceCtx {
  systemFonts: string[];
  elementType: string;
  onReveal: OnReveal;
  onFaceSection?: OnFaceSection | undefined;
}

// An event on the input, select or link the handler is on: `currentTarget` is that element.
type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type TextAreaEvent = JSX.TargetedEvent<HTMLTextAreaElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;
type KeyEvent = JSX.TargetedKeyboardEvent<HTMLInputElement>;
type LinkClick = JSX.TargetedMouseEvent<HTMLAnchorElement>;

const ALIGN: string[][] = [["top_left", "top", "top_right"], ["left", "center", "right"],
                           ["bottom_left", "bottom", "bottom_right"]];

/** A value as a text box shows it: an absent one as nothing. */
const shown = (value: Value | undefined): string => (value == null ? "" : String(value));

/** A value as read-only text: a string as it is, anything else as its JSON. */
const asText = (value: Value | undefined): string => (value == null ? "—" : typeof value === "string" ? value : JSON.stringify(value));

const dotted = (path: Path): string => path.map(String).join(".");

// -- the small controls ----------------------------------------------------------------------

interface CommitProps {
  value?: string | null | undefined;
  onCommit: (text: string) => void;
  placeholder?: string | undefined;
  mono?: boolean;
  list?: string;
  width?: string;
  focus?: boolean;
}

// A text input that commits on Enter or when it loses focus, and resets
// when the value it shows changes underneath it. `focus` true takes the
// focus, so the author can type at once.
export function Commit({ value, onCommit, placeholder, mono, list, width, focus = false }: CommitProps): VNode {
  const [text, setText] = useState<string>(value ?? "");
  const input = useRef<HTMLInputElement | null>(null);
  useEffect(() => setText(value ?? ""), [value]);
  useEffect(() => { if (focus && input.current && input.current.focus) input.current.focus(); }, [focus]);
  // The input's own value, not the state: a blur can arrive before the
  // re-render that typing schedules.
  const commit = (e: InputEvent) => { if (e.currentTarget.value !== (value ?? "")) onCommit(e.currentTarget.value); };
  return html`<input type="text" class=${mono ? "mono" : ""} value=${text} placeholder=${placeholder || ""}
    list=${list} style=${width ? `width:${width}` : ""} ref=${input}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)} onBlur=${commit}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value ?? ""); }} />`;
}

interface QuantityProps {
  value: Value | undefined;
  units: string[];
  bareUnit: string;
  onCommit: (value: string | number) => void;
  placeholder?: string | undefined;
  like?: Value | undefined;
}

// A number and its unit. An absent value starts in the unit of ``like`` (the
// value an override would replace), so an override is written in the
// author's own unit. Choosing another unit converts the number where the
// two units are commensurable without the watch (`convertQuantity`) and
// writes it; otherwise nothing is written: the number box empties, shows
// the old number as its placeholder and takes the focus, and the value is
// written once a number is typed in the new unit. A value in a unit the
// key no longer offers keeps its unit listed.
export function Quantity({ value, units, bareUnit, onCommit, placeholder, like }: QuantityProps): VNode {
  const q = parseQuantity(value, bareUnit);
  const l = parseQuantity(like, bareUnit);
  const initial = q ? q.unit : l && units.includes(l.unit) ? l.unit : units[0] ?? bareUnit;
  const [unit, setUnit] = useState<string>(initial);
  const [pending, setPending] = useState<boolean>(false);   // a unit chosen, its number not typed yet
  useEffect(() => { setUnit(initial); setPending(false); }, [value, like]);
  const send = (numberText: string, u: string) => {
    if (numberText === "") return;
    const out = formatQuantity(Number(numberText), u, bareUnit, q ? q.bare : false);
    if (out !== null) onCommit(out);
  };
  const choose = (to: string) => {
    setUnit(to);
    if (!q) return;
    const converted = convertQuantity(q.number, q.unit, to);
    setPending(converted === null);
    if (converted !== null && to !== q.unit) send(String(converted), to);
  };
  if (value != null && !q) {
    return html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`;
  }
  const offered = q && !units.includes(q.unit) ? [...units, q.unit] : units;
  return html`<span class="qty">
    <${Commit} value=${q && !pending ? String(q.number) : ""} width="5em" focus=${pending}
      placeholder=${pending && q ? String(q.number) : placeholder ?? (l ? String(l.number) : "")}
      onCommit=${(t: string) => send(t, unit)} />
    <select value=${unit} onChange=${(e: SelectEvent) => choose(e.currentTarget.value)}>
      ${offered.map((u) => html`<option value=${u}>${u}</option>`)}
    </select>
  </span>`;
}

interface AlignPickerProps {
  value: Value | undefined;
  onCommit: (value: string) => void;
}

function AlignPicker({ value, onCommit }: AlignPickerProps): VNode {
  return html`<span class="align">
    ${ALIGN.map((row) => html`<span class="align-row">${row.map((a) => html`
      <button class=${value === a ? "on" : ""} title=${a} aria-label=${a.replace("_", " ")} aria-pressed=${value === a}
        onClick=${() => onCommit(a)}></button>`)}</span>`)}
  </span>`;
}

export interface ColorPopProps {
  /** The colour as written; none for a picker that only adds. */
  value?: Value | undefined;
  ctx: FaceCtx;
  /** Offer the face's roles beside its swatches. */
  roles?: boolean;
  /** Offer the face's own colours at all. */
  faceGroup?: boolean;
  title?: string | undefined;
  /** Text in place of the chip and the colour's name. */
  label?: string;
  /** `color.<name>` for a swatch or role, a hex for one of the 64 or a custom colour. */
  onPick: (value: string) => void;
}

// The colour picker: a chip that opens three groups, the face's own colours
// (its swatches, then its roles where a role is allowed), the 64 named MIP
// colours, and a custom colour. A swatch or role is picked as
// `color.<name>`; one of the 64 or a custom colour as its hex, which the
// worker turns into the swatch holding it (`src/edit/colors.ts`).
export function ColorPop({ value, ctx, roles = true, faceGroup = true, title, label, onPick }: ColorPopProps): VNode {
  const [custom, setCustom] = useState<string>("");
  const palette = ctx.globals.palette || [];
  const mip = ctx.vocab.mip || [];
  const displays = ctx.globals.displays || [];
  const ref = colorName(value);
  const swatch = ref ? palette.find((p) => p.name === ref) : undefined;
  const held = parseHex(value) ?? (swatch ? parseHex(swatch.value) : null);
  const customRgb = parseHex(custom) || held || [255, 255, 255];
  const target = swatchFor(customRgb, palette, mip);
  const safe = safeOn(customRgb, displays);
  const warn = held !== null && !safeOn(held, displays).ok;
  const chip = html`${label ? null : html`<span class="chip" style=${held ? `background:${toHex(held)}` : ""}></span>`}
      <span class=${ref || label ? "" : "dim"}>${label || ref || (held ? toHex(held) : "—")}</span>`;
  return html`<span class="color">
    <${Popover} buttonClass="chip-button" bodyClass="pop" title=${title || "pick a colour"} label=${chip}
      onOpen=${() => setCustom("")}>${(close: () => void) => {
      const pick = (v: string) => { close(); setCustom(""); onPick(v); };
      return html`
      ${faceGroup ? html`<div class="pop-group">
        <div class="pop-title">This face</div>
        <div class="pop-swatches">${palette.map((p) => { const v = parseHex(p.value); return html`
          <button class=${"swatch" + (ref === p.name ? " on" : "")} title=${`${p.name} ${p.value}`} aria-label=${p.name} aria-pressed=${ref === p.name}
            style=${v ? `background:${toHex(v)}` : ""} onClick=${() => pick(`color.${p.name}`)}></button>`; })}</div>
        ${roles && (ctx.globals.roles || []).length ? html`<div class="pop-roles">${ctx.globals.roles.map((r) => html`
          <button class=${ref === r ? "on" : ""} title="a role: follows the wearer's style or pick" onClick=${() => pick(`color.${r}`)}>${r}</button>`)}</div>` : null}
      </div>` : null}
      <div class="pop-group">
        <div class="pop-title">MIP 64</div>
        <div class="pop-grid">${mip.map((m) => {
          const holder = palette.find((p) => { const v = parseHex(p.value); return v && toHex(v) === m.value; });
          return html`<button class=${"swatch" + (holder ? " held" : "")} style=${`background:${m.value}`} aria-label=${m.label}
            title=${`${m.label} ${m.value}${holder ? ` (this face: ${holder.name})` : ""}`} onClick=${() => pick(m.value)}></button>`; })}</div>
      </div>
      <div class="pop-group">
        <div class="pop-title">Custom</div>
        <div class="pop-custom">
          <input type="color" value=${toHex(customRgb)} onInput=${(e: InputEvent) => setCustom(e.currentTarget.value.toUpperCase())} />
          <input type="text" class="mono hex" aria-label="hex colour" value=${custom || toHex(customRgb)}
            onInput=${(e: InputEvent) => setCustom(e.currentTarget.value)}
            onKeyDown=${(e: KeyEvent) => { const typed = parseHex(custom); if (e.key === "Enter" && typed) pick(toHex(typed)); }} />
          <button class="primary" disabled=${!parseHex(custom)} onClick=${() => pick(toHex(customRgb))}>Use</button>
        </div>
        ${parseHex(custom) ? html`<div class="note">${target.adds ? `adds ${target.name}` : `uses ${target.name}`}
          ${!safe.ok ? html` · <span class="warn">⚠ dithers</span> <a href="#" onClick=${(e: LinkClick) => { e.preventDefault(); setCustom(toHex(safe.nearest)); }}>nearest ${toHex(safe.nearest)}</a>` : null}</div>` : null}
      </div>`;
    }}</${Popover}>
    ${warn ? html`<span class="warn" title=${`dithers on this face's ${displays.join("/")}-colour screens`}>⚠</span>` : null}
  </span>`;
}

interface TemplateProps {
  value: string;
  /** Data sources by namespace, for the "+ data" insert. */
  sources: Record<string, string[]>;
  onCommit: (text: string) => void;
}

function Template({ value, sources, onCommit }: TemplateProps): VNode {
  const input = useRef<HTMLInputElement | null>(null);
  const insert = (path: string) => {
    if (!path) return;
    const el = input.current;
    const text = el ? el.value : (value || "");
    const at = el && el.selectionStart != null ? el.selectionStart : text.length;
    onCommit(text.slice(0, at) + `{${path}}` + text.slice(at));
  };
  const [text, setText] = useState<string>(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  return html`<span class="template">
    <input type="text" class="mono" ref=${input} value=${text} onInput=${(e: InputEvent) => setText(e.currentTarget.value)}
      onBlur=${(e: InputEvent) => { if (e.currentTarget.value !== (value ?? "")) onCommit(e.currentTarget.value); }}
      onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
    <select value="" onChange=${(e: SelectEvent) => { insert(e.currentTarget.value); e.currentTarget.value = ""; }} title="Insert a data placeholder">
      <option value="">+ data</option>
      ${Object.entries(sources).map(([ns, paths]) => html`<optgroup label=${ns}>
        ${paths.map((p) => html`<option value=${p}>${p}</option>`)}</optgroup>`)}
    </select>
  </span>`;
}

export interface GlyphProps {
  /** A catalogue icon's name; anything else draws nothing. */
  name?: Value | null | undefined;
  vocab: Partial<Vocabulary>;
}

// A catalogue icon drawn with the icon font (`/api/icon-font`), or its
// name when the catalogue has no such icon.
export function Glyph({ name, vocab }: GlyphProps): VNode {
  const cp = typeof name === "string" && name ? (vocab.icon_glyphs || {})[name] : undefined;
  return cp ? html`<span class="glyph" title=${name}>${String.fromCodePoint(cp)}</span>`
            : html`<span class="glyph dim">${name === "none" ? "∅" : ""}</span>`;
}

export interface IconPopProps {
  /** The icon as written (a name, or `{codepoint}`), or none. */
  value?: IconSpelling | null | undefined;
  vocab: Partial<Vocabulary>;
  /** Offer `none`, where the key takes it. */
  allowNone?: boolean;
  /** The icon drawn when none is written. */
  placeholder?: string | null | undefined;
  /** A name, `none`, a codepoint as `{codepoint: "U+XXXX"}`, or null to remove. */
  onPick: (value: IconSpelling | null) => void;
}

/** What an icon spelling shows as: the name, or the codepoint. */
const iconText = (value: IconSpelling | null | undefined): string | null =>
  value === null || value === undefined ? null : typeof value === "string" ? value : value.codepoint;

// An icon picker: every catalogue icon as a glyph, `none` where the key
// takes it, and a codepoint (`U+XXXX`) typed in.
export function IconPop({ value: spelled, vocab, allowNone = false, placeholder, onPick }: IconPopProps): VNode {
  const [code, setCode] = useState<string>("");
  const names = Object.keys(vocab.icon_glyphs || {}).sort();
  const value = iconText(spelled);
  const label = html`<${Glyph} name=${value || placeholder} vocab=${vocab} />
      <span class=${value ? "" : "dim"}>${value || placeholder || "icon"}</span>`;
  return html`<${Popover} buttonClass="chip-button" bodyClass="pop" title=${value || placeholder || "pick an icon"} label=${label}
    onOpen=${() => setCode("")}>${(close: () => void) => {
    const pick = (v: IconSpelling | null) => { close(); setCode(""); onPick(v); };
    return html`
      <div class="pop-grid icons">${names.map((n) => html`<button class=${"swatch icon" + (n === value ? " on" : "")}
        title=${n} aria-label=${n} aria-pressed=${n === value} onClick=${() => pick(n)}><${Glyph} name=${n} vocab=${vocab} /></button>`)}</div>
      <div class="pop-custom">
        ${allowNone ? html`<button title="draw no icon for this one" onClick=${() => pick("none")}>none</button>` : null}
        <input type="text" class="mono codepoint" aria-label="codepoint" placeholder="U+F0000" value=${code}
          onInput=${(e: InputEvent) => setCode(e.currentTarget.value)} />
        <button disabled=${!/^U\+[0-9A-Fa-f]{4,6}$/.test(code)} onClick=${() => pick({ codepoint: code.trim().toUpperCase() })}>Use</button>
        ${value ? html`<button class="reset" title=${placeholder ? `back to ${placeholder}` : "remove"}
          aria-label=${placeholder ? `back to ${placeholder}` : "remove"} onClick=${() => pick(null)}>×</button>` : null}
      </div>`;
  }}</${Popover}>`;
}

interface YamlBoxProps {
  /** The value as text. */
  text: string;
  onCommit: (value: Value) => void;
}

// A value no control covers (a mapping or a list under a key the schema
// gives a scalar control), edited as the YAML it is written as: the text is
// read as a YAML value when the box loses focus, and written when it reads;
// text that is not YAML is marked and kept, not written.
function YamlBox({ text, onCommit }: YamlBoxProps): VNode {
  const [value, setValue] = useState<string>(text);
  const [bad, setBad] = useState<boolean>(false);
  useEffect(() => { setValue(text); setBad(false); }, [text]);
  const commit = (e: TextAreaEvent) => {
    const typed = e.currentTarget.value;
    if (typed === text) return;
    let parsed: unknown;
    try {
      parsed = YAML.parse(typed, { version: "1.1" });
    } catch (_) {
      setBad(true);
      return;
    }
    if (parsed === undefined) { setBad(true); return; }
    setBad(false);
    onCommit(parsed as Value);
  };
  return html`<textarea class="mono" rows="2" value=${value} aria-invalid=${bad} title=${bad ? "not YAML: nothing written" : "the value, as YAML"}
    onInput=${(e: TextAreaEvent) => setValue(e.currentTarget.value)} onBlur=${commit} />`;
}

// -- the scalar controls ----------------------------------------------------------------------

interface WidgetProps {
  field: Field;
  /** The value shown: what the editing context reads for the key. */
  value: Value | undefined;
  ctx: WidgetCtx;
  onCommit: (value: Value) => void;
  onPickColor: (value: string) => void;
  /** The value an override would replace, for a quantity's starting unit. */
  like?: Value | undefined;
}

/**
 * The compile-time check that `Widget`'s switch names every kind in
 * `protocol.ts`'s `Widget`: a new kind lands here as a type error. At run
 * time, a kind this page does not know is edited as its YAML.
 */
function unknownWidget(_widget: never, fallback: VNode): VNode {
  return fallback;
}

function Widget({ field, value, ctx, onCommit, onPickColor, like }: WidgetProps): VNode {
  const enumSelect = (options: string[], extra?: string[]) => html`<select value=${value ?? ""} onChange=${(e: SelectEvent) => e.currentTarget.value !== "" && onCommit(e.currentTarget.value)}>
    <option value="">${field.default != null ? `default (${field.default})` : "—"}</option>
    ${(extra || []).map((o) => html`<option value=${o}>${o}</option>`)}
    ${options.map((o) => html`<option value=${o}>${o}</option>`)}
  </select>`;
  // a value no scalar control covers: edited as its YAML
  const asYaml = () => html`<${YamlBox} text=${value == null ? "" : field.text ?? (typeof value === "string" ? value : JSON.stringify(value))} onCommit=${onCommit} />`;
  switch (field.widget) {
    case "readonly": return html`<code>${String(value)}</code>`;
    case "length": return html`<${Quantity} value=${value} like=${like} units=${lengthUnitsFor(ctx.elementType)} bareUnit="px" onCommit=${onCommit} />`;
    case "angle": return html`<${Quantity} value=${value} like=${like} units=${ANGLE_UNITS} bareUnit="deg" onCommit=${onCommit} />`;
    case "align": return html`<${AlignPicker} value=${value} onCommit=${onCommit} />`;
    case "color": {
      // an expression choosing a colour is edited as text
      if (value != null && !colorName(value) && !parseHex(value)) return html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`;
      const ref = colorName(value);
      const isRole = ref && !(ctx.globals.palette || []).some((p) => p.name === ref) && (ctx.globals.roles || []).includes(ref);
      return html`<span class="color-field"><${ColorPop} value=${value} ctx=${ctx} onPick=${onPickColor} />
        ${isRole ? html`<span class="dim">role <code>${ref}</code></span>
          ${ctx.onFaceSection ? html`<a href="#" title="jump to the Schemes section"
            onClick=${(e: LinkClick) => { e.preventDefault(); ctx.onFaceSection?.("schemes"); }}>Schemes</a>` : null}` : null}</span>`;
    }
    case "template": return html`<${Template} value=${shown(value)} sources=${ctx.vocab.sources || {}} onCommit=${onCommit} />`;
    case "font": return enumSelect(ctx.systemFonts, (ctx.globals.fonts || []).map((f) => `font.${f.name}`));
    case "icon": return html`<${IconPop} value=${value as IconSpelling | null} vocab=${ctx.vocab} onPick=${(v: IconSpelling | null) => v && onCommit(v)} />`;
    case "complication": return enumSelect((field.enum || ctx.vocab.complications || []).map(String));
    case "slot": return enumSelect((ctx.globals.slots || []).map((s) => s.name));
    case "handset": {
      const set = (ctx.globals.hands || []).find((h) => h.name === value);
      return html`<span class="handset">${enumSelect(ctx.globals.hand_sets || [])}
        ${set && ctx.onReveal ? html`<a href="#" title="its hands' parts, in the YAML tab"
          onClick=${(e: LinkClick) => { e.preventDefault(); ctx.onReveal(set.line, set.end); }}>edit the set</a>` : null}</span>`;
    }
    case "enum": return enumSelect((field.enum || []).map(String));
    case "bool": return html`<select value=${value == null ? "" : String(value)}
        onChange=${(e: SelectEvent) => e.currentTarget.value !== "" && onCommit(e.currentTarget.value === "true")}>
      <option value="">${field.default != null ? `default (${field.default})` : "—"}</option>
      <option value="true">true</option><option value="false">false</option></select>`;
    case "number": return html`<${Commit} value=${shown(value)} width="6em"
        onCommit=${(t: string) => t.trim() !== "" && !Number.isNaN(Number(t)) && onCommit(Number(t))} />`;
    case "expression":
    case "text": return html`<${Commit} value=${shown(value)} mono=${field.widget === "expression"} onCommit=${onCommit} />`;
    case "object":
    case "yaml": return asYaml();
    default: return unknownWidget(field.widget, asYaml());
  }
}

// -- where an edit lands ---------------------------------------------------------------------

/** How one top-level key and everything under it is edited: the scope its ops carry, or shown read-only. */
interface Lane {
  scope: EditScope;
  readonly: boolean;
}

/** A `display:` selector's class as the context names it: `amoled` is "AMOLED", `mip` "MIP", `lcd` "LCD". */
export const displayLabel = (cls: string | null | undefined): string => String(cls || "").toUpperCase();

/** The selector an override scope writes on the viewed device (`fr955`, `shape:round`, `display:amoled`). */
function selectorOf(ins: Inspect, scope: Exclude<Scope, "all">): string {
  return scope === "device" ? String(ins.device) : scope === "shape" ? `shape:${ins.shape}` : `display:${ins.display}`;
}

/** `at` walks a `Value` tree, so what it finds is a `Value`, or nothing. */
const valueAt = (keys: Record<string, Value> | undefined, path: Path): Value | undefined => at(keys, path) as Value | undefined;

/** The badge naming where an effective value comes from, when that is not the key itself. */
function badgeOf(effective: Effective): string | null {
  switch (effective.from) {
    case "override": return effective.selector ?? "override";
    case "aod": return "aod";
    case "group": return `from ${effective.group ?? "group"}`;
    case "defaults": return "defaults";
    default: return null;
  }
}

/** What a field's control shows and where its edit goes, in its lane. */
interface Reading {
  /** The control's value: what the context reads. */
  value: Value | undefined;
  /** The value written in the edited scope, which × removes; nothing when the scope does not hold the key. */
  own: Value | undefined;
  /** The value an override would replace, for a quantity's starting unit. */
  like: Value | undefined;
  badge: string | null;
  /** Where an edit is written, when that is not simply the key. */
  title: string;
  note: string | null;
}

function reading(field: Field, ins: Inspect, lane: Lane, depth: number): Reading {
  const effective = field.effective ?? { value: field.value, from: "own" as const };
  const key = dotted(field.path);
  if (lane.readonly) {
    return { value: effective.value ?? field.value, own: undefined, like: undefined, badge: badgeOf(effective), title: "",
             note: depth === 0 ? "not restyled in AOD; edit it in the awake frame" : null };
  }
  if (lane.scope === "aod") {
    return { value: effective.value, own: field.value, like: undefined, badge: badgeOf(effective), title: `writes aod: ${key} on this element`, note: null };
  }
  if (lane.scope !== "all") {
    const held = ins.overrides[lane.scope];
    const override = held ? valueAt(held.keys, field.path) : undefined;
    const selector = held ? held.selector : selectorOf(ins, lane.scope);
    return { value: override, own: override, like: field.value, badge: override !== undefined ? selector : null,
             title: `writes the ${selector} override's ${key}`,
             note: override === undefined && field.value != null && field.kind !== "object" ? `inherits ${JSON.stringify(field.value)}` : null };
  }
  if (effective.from === "override") {
    return { value: effective.value, own: field.value, like: undefined, badge: badgeOf(effective),
             title: `writes ${key} on this element, for every watch; ${ins.device} reads its ${effective.selector} override`, note: null };
  }
  return { value: field.value, own: field.value, like: undefined, badge: null, title: "", note: null };
}

/**
 * The value a new key, item or branch starts as: the schema's default, else
 * an object of its required children's seeds, an empty list, a choice's
 * first branch, an enum's first value, false, 0, or the empty string (a
 * colour: the face's first swatch).
 */
export function seedOf(field: Field, ctx?: FaceCtx): Value {
  if (field.default !== null && field.default !== undefined) return field.default;
  switch (field.kind) {
    case "object": {
      const out: Record<string, Value> = {};
      for (const c of field.children ?? []) if (c.required) out[c.key] = seedOf(c, ctx);
      return out;
    }
    case "list": return [];
    case "choice": return field.branches && field.branches[0] ? seedOf(field.branches[0], ctx) : null;
    default: {
      if (field.enum && field.enum.length) return field.enum[0] ?? null;
      switch (field.widget) {
        case "bool": return false;
        case "number": case "length": case "angle": return 0;
        case "color": { const first = ctx?.globals.palette[0]; return first ? `color.${first.name}` : "#FFFFFF"; }
        default: return "";
      }
    }
  }
}

/** A choice's branch as a button names it: its enum values, its control's kind, or an object's required keys. */
function branchLabel(branch: Field): string {
  if (branch.enum && branch.enum.length) return branch.enum.map(String).join("/");
  if (branch.kind === "object") {
    const required = (branch.children ?? []).filter((c) => c.required).map((c) => c.key);
    return required.length ? required.join(",") : "object";
  }
  if (branch.kind === "list") return "list";
  if (branch.kind === "choice") return "choice";
  switch (branch.widget) {
    case "bool": return "on/off";
    case "number": return "number";
    case "length": return "length";
    case "angle": return "angle";
    case "color": return "colour";
    case "expression": return "expression";
    case "template": return "text";
    default: return branch.widget;
  }
}

/** Whether `value`'s shape is what a branch admits, as the worker matches it: an enum value, an object with its required keys, a list, or a scalar of its control's kind. */
function admits(branch: Field, value: Value): boolean {
  if (branch.enum && branch.enum.length) return branch.enum.some((e) => JSON.stringify(e) === JSON.stringify(value));
  if (branch.kind === "object") return typeof value === "object" && value !== null && !Array.isArray(value)
    && (branch.children ?? []).every((c) => !c.required || c.key in value);
  if (branch.kind === "list") return Array.isArray(value);
  if (branch.kind === "choice") return (branch.branches ?? []).some((b) => admits(b, value));
  switch (branch.widget) {
    case "bool": return typeof value === "boolean";
    case "number": return typeof value === "number";
    case "length": case "angle": return typeof value === "number" || typeof value === "string";
    default: return typeof value === "string";
  }
}

/** The branch of `field` the shown `value` has the shape of: the worker's when the value is the key's own, else matched here. */
function chosenBranch(field: Field, value: Value | undefined): number | null {
  if (value === undefined || value === null) return null;
  if (JSON.stringify(value) === JSON.stringify(field.value)) return field.chosen ?? null;
  const i = (field.branches ?? []).findIndex((b) => admits(b, value));
  return i >= 0 ? i : null;
}

// -- the form ---------------------------------------------------------------------------------

/** `field` with the `aod` step dropped from its path and its descendants': the key as the always-on frame edits it, in the aod scope. */
function rebased(field: Field): Field {
  const out: Field = { ...field, path: field.path.slice(1) };
  if (field.children) out.children = field.children.map(rebased);
  if (field.items) out.items = field.items.map(rebased);
  if (field.item) out.item = rebased(field.item);
  if (field.branches) out.branches = field.branches.map(rebased);
  return out;
}

/** The keys an element's kind restyles in the always-on frame: `aod_keys`, and every kind's `visible` and `dim`. */
const restyled = (ins: Inspect): Set<string> => new Set([...(ins.aod_keys ?? []), "visible", "dim"]);

/**
 * The fields the always-on frame edits: the element's keys in their order,
 * each restyled one taken from the `aod:` block's own field (its shape
 * there: `visible` a boolean or an expression, `outline` `none` or a ring),
 * `dim` beside `visible`, and the block itself left out, since the frame is
 * the block.
 */
function aodFields(ins: Inspect): Field[] {
  const block = ins.fields.find((f) => f.key === "aod");
  const inBlock = (key: string): Field | undefined => block?.children?.find((c) => c.key === key);
  const keys = restyled(ins);
  const out: Field[] = [];
  const add = (key: string, fallback: Field | null): void => {
    const own = inBlock(key);
    if (own) out.push(rebased(own));
    else if (fallback) out.push(fallback);
  };
  for (const f of ins.fields) {
    if (f.key === "aod") continue;
    if (keys.has(f.key)) add(f.key, f); else out.push(f);
    if (f.key === "visible") add("dim", null);
  }
  if (!out.some((f) => f.key === "visible")) { add("visible", null); add("dim", null); }
  return out;
}

/** Where a top-level key's edits go: the `aod:` block in the always-on frame (else read-only), the Edit for target for a geometry key, else the key itself. */
function laneOf(field: Field, ins: Inspect, target: Scope): Lane {
  if ((ins.context?.frame ?? "awake") === "aod") return restyled(ins).has(field.key) ? { scope: "aod", readonly: false } : { scope: "all", readonly: true };
  return { scope: field.geometry && target !== "all" ? target : "all", readonly: false };
}

export interface FormProps {
  /** The selected element's field tree, as the worker answered it for the editing context. */
  ins: Inspect;
  /** Where a geometry edit lands: the element's own key, or its override for the viewed watch, its shape or its display class (Edit for). */
  target: Scope;
  ctx: WidgetCtx;
  onEdit: OnEdit;
}

/** The generic form: every key of the element, in the frame the tree answers for. */
export function Form({ ins, target, ctx, onEdit }: FormProps): VNode {
  const fields = (ins.context?.frame ?? "awake") === "aod" ? aodFields(ins) : ins.fields;
  return html`${fields.map((f) => html`<${FieldView} key=${f.key} field=${f} ins=${ins} lane=${laneOf(f, ins, target)} ctx=${ctx} onEdit=${onEdit} depth=${0} />`)}`;
}

interface FieldViewProps {
  field: Field;
  ins: Inspect;
  lane: Lane;
  ctx: WidgetCtx;
  onEdit: OnEdit;
  depth: number;
}

/** One field, by its kind. */
function FieldView(props: FieldViewProps): VNode {
  switch (props.field.kind) {
    case "object": return html`<${ObjectField} ...${props} />`;
    case "list": return html`<${ListField} ...${props} />`;
    case "choice": return html`<${ChoiceField} ...${props} />`;
    default: return html`<${ScalarField} ...${props} />`;
  }
}

/** The element and scope every op of a lane carries. */
const baseOf = (ins: Inspect, lane: Lane): { element: Path; scope: EditScope; device: string | null } =>
  ({ element: ins.element, scope: lane.scope, device: ins.device });

interface NameProps {
  field: Field;
  badge: string | null;
}

/** A field's name: its key, a star when required, and the badge naming where its value comes from. */
function Name({ field, badge }: NameProps): VNode {
  return html`<div class="name" title=${field.description}><span class="key">${field.key}</span>${field.required ? html`<span class="req">*</span>` : null}${badge ? html`<span class="badge">${badge}</span>` : null}</div>`;
}

interface RemoveProps {
  lane: Lane;
  onClick: () => void;
}

/** The × that removes the key from the edited scope. */
function Remove({ lane, onClick }: RemoveProps): VNode {
  const override = lane.scope !== "all" && lane.scope !== "aod";
  const label = override ? "remove the override" : "remove the key";
  const title = override ? "remove the override" : lane.scope === "aod" ? "remove the key from the aod: block" : "remove the key (back to the default)";
  return html`<button class="reset" title=${title} aria-label=${label} onClick=${onClick}>×</button>`;
}

function ScalarField({ field, ins, lane, ctx, onEdit, depth }: FieldViewProps): VNode {
  const r = reading(field, ins, lane, depth);
  const base = { ...baseOf(ins, lane), path: field.path };
  const classes = "field" + (r.value == null ? " absent" : "") + (lane.readonly ? " readonly" : "");
  return html`<div class=${classes} style=${`--depth:${depth}`}>
    <${Name} field=${field} badge=${r.badge} />
    <div class="value" title=${r.title}>
      ${lane.readonly ? html`<code class="shown">${asText(r.value)}</code>`
        : html`<${Widget} field=${field} value=${r.value} ctx=${ctx} like=${r.like}
            onCommit=${(v: Value) => onEdit({ op: "set", ...base, value: v })}
            onPickColor=${(v: string) => onEdit({ op: "use_color", ...base, value: v })} />`}
      ${!lane.readonly && r.own != null && !field.required && field.widget !== "readonly"
        ? html`<${Remove} lane=${lane} onClick=${() => onEdit({ op: "remove", ...base })} />` : null}
      ${r.note ? html`<div class="note">${r.note}</div>` : null}
    </div>
  </div>`;
}

/** The name a keyed object's new entry may have: a device id or a `shape:`/`display:` selector, a palette or font name. */
const isKeyName = (text: string): boolean => /^[A-Za-z0-9_][A-Za-z0-9_:.-]*$/.test(text);

/**
 * An object: a fieldset of its children. Folded while every child is
 * absent and the object is optional, with a + that opens it. A keyed object
 * (one whose keys the author names, `overrides:` by selector) lists the keys
 * present and adds one by name, seeded from its template, or, when that
 * seed would be empty, with a copy of the element's own key the template
 * admits (a new override starts as a copy of the element's `at:`).
 */
function ObjectField({ field, ins, lane, ctx, onEdit, depth }: FieldViewProps): VNode {
  const r = reading(field, ins, lane, depth);
  const base = baseOf(ins, lane);
  const kids = field.children ?? [];
  const foldable = !field.required && kids.every((c) => !c.present) && r.own == null;
  const [opened, setOpened] = useState<boolean>(false);
  const open = opened || !foldable;
  const classes = "field object" + (r.value == null ? " absent" : "") + (lane.readonly ? " readonly" : "") + (open ? "" : " folded");
  // a child set while the object is absent and has required siblings goes out as the whole object, seeded
  const needsSeed = r.own == null && lane.scope !== "device" && lane.scope !== "shape" && lane.scope !== "display" && kids.some((c) => c.required);
  const onChildEdit: OnEdit = (op) => {
    if (needsSeed && op.op === "set" && op.path.length === field.path.length + 1) {
      const seed = seedOf(field, ctx) as Record<string, Value>;
      return onEdit({ op: "set", ...base, path: field.path, value: { ...seed, [String(op.path[op.path.length - 1])]: op.value } });
    }
    return onEdit(op);
  };
  const addKey = (name: string): void => {
    const item = field.item;
    let seed: Value = item ? seedOf(item, ctx) : {};
    if (typeof seed === "object" && seed !== null && !Array.isArray(seed) && Object.keys(seed).length === 0 && item) {
      const copied = (item.children ?? []).map((c) => ins.fields.find((f) => f.key === c.key)).find((f) => f !== undefined && f.present);
      if (copied) seed = { [copied.key]: copied.value };
    }
    void onEdit({ op: "set", ...base, path: [...field.path, name], value: seed });
  };
  return html`<div class=${classes} style=${`--depth:${depth}`}>
    <div class="head" title=${r.title}>
      <${Name} field=${field} badge=${r.badge} />
      ${!open && !lane.readonly ? html`<button class="add" title=${`add ${field.key}`} onClick=${() => setOpened(true)}>+ ${field.key}</button>` : null}
      ${!lane.readonly && r.own != null && !field.required ? html`<${Remove} lane=${lane} onClick=${() => onEdit({ op: "remove", ...base, path: field.path })} />` : null}
      ${r.note ? html`<div class="note">${r.note}</div>` : null}
    </div>
    ${open ? html`<div class="children">
      ${kids.map((c) => html`<${FieldView} key=${c.key} field=${c} ins=${ins} lane=${lane} ctx=${ctx} onEdit=${onChildEdit} depth=${depth + 1} />`)}
      ${field.item && !lane.readonly ? html`<${AddName} label="+ key" placeholder=${`a new ${field.key} key`} valid=${isKeyName}
          title=${`add a ${field.key} key by name`} onAdd=${addKey} />` : null}
    </div>` : null}
  </div>`;
}

/** A list: its items, each a field with ↑ ↓ × (`move_item`, `remove_item`), and + add, which inserts the item template's seed at the end. */
function ListField({ field, ins, lane, ctx, onEdit, depth }: FieldViewProps): VNode {
  const r = reading(field, ins, lane, depth);
  const base = { ...baseOf(ins, lane), path: field.path };
  const items = field.items ?? [];
  const classes = "field list" + (items.length === 0 ? " absent" : "") + (lane.readonly ? " readonly" : "");
  return html`<div class=${classes} style=${`--depth:${depth}`}>
    <div class="head" title=${r.title}>
      <${Name} field=${field} badge=${r.badge} />
      ${!lane.readonly && r.own != null && !field.required ? html`<${Remove} lane=${lane} onClick=${() => onEdit({ op: "remove", ...base })} />` : null}
      ${r.note ? html`<div class="note">${r.note}</div>` : null}
    </div>
    <div class="children">
      ${items.map((it, i) => html`<div class="list-item" key=${i}>
        ${lane.readonly ? null : html`<span class="list-controls">
          <button class="reset" title="move up" aria-label="move up" disabled=${i === 0} onClick=${() => onEdit({ op: "move_item", ...base, from: i, to: i - 1 })}>↑</button>
          <button class="reset" title="move down" aria-label="move down" disabled=${i === items.length - 1} onClick=${() => onEdit({ op: "move_item", ...base, from: i, to: i + 1 })}>↓</button>
          <button class="reset" title="remove this item" aria-label="remove" onClick=${() => onEdit({ op: "remove_item", ...base, at: i })}>×</button>
        </span>`}
        <${FieldView} field=${it} ins=${ins} lane=${lane} ctx=${ctx} onEdit=${onEdit} depth=${depth + 1} />
      </div>`)}
      ${lane.readonly ? null : html`<button class="add" title="add an item at the end"
        onClick=${() => onEdit({ op: "insert_item", ...base, at: items.length, value: field.item ? seedOf(field.item, ctx) : null })}>+ add</button>`}
    </div>
  </div>`;
}

/**
 * A choice between schema branches: a segmented control naming each, the
 * one the value's shape matches on; picking another writes that branch's
 * seed in one set. The chosen branch's own field renders with it: a scalar
 * branch's control inline, an object's or a list's children beneath.
 */
function ChoiceField({ field, ins, lane, ctx, onEdit, depth }: FieldViewProps): VNode {
  const r = reading(field, ins, lane, depth);
  const base = { ...baseOf(ins, lane), path: field.path };
  const branches = field.branches ?? [];
  const chosen = chosenBranch(field, r.value);
  const branch = chosen !== null ? branches[chosen] : undefined;
  const classes = "field choice" + (r.value == null ? " absent" : "") + (lane.readonly ? " readonly" : "");
  const pick = (i: number): void => {
    const to = branches[i];
    if (i === chosen || !to) return;
    void onEdit({ op: "set", ...base, value: seedOf(to, ctx) });
  };
  return html`<div class=${classes} style=${`--depth:${depth}`}>
    <${Name} field=${field} badge=${r.badge} />
    <div class="value" title=${r.title}>
      <span class="seg" role="radiogroup">${branches.map((b, i) => html`
        <button class=${i === chosen ? "on" : ""} aria-pressed=${i === chosen} disabled=${lane.readonly} title=${b.description || branchLabel(b)}
          onClick=${() => pick(i)}>${branchLabel(b)}</button>`)}</span>
      ${branch && branch.kind === "scalar" ? (lane.readonly ? html`<code class="shown">${asText(r.value)}</code>`
        : html`<${Widget} field=${branch} value=${r.value} ctx=${ctx} like=${r.like}
            onCommit=${(v: Value) => onEdit({ op: "set", ...base, value: v })}
            onPickColor=${(v: string) => onEdit({ op: "use_color", ...base, value: v })} />`) : null}
      ${!lane.readonly && r.own != null && !field.required ? html`<${Remove} lane=${lane} onClick=${() => onEdit({ op: "remove", ...base })} />` : null}
      ${r.note ? html`<div class="note">${r.note}</div>` : null}
    </div>
    ${branch && branch.kind === "object" ? html`<div class="children">
      ${(branch.children ?? []).map((c) => html`<${FieldView} key=${c.key} field=${c} ins=${ins} lane=${lane} ctx=${ctx} onEdit=${onEdit} depth=${depth + 1} />`)}
    </div>` : null}
    ${branch && branch.kind === "list" ? html`<div class="children">
      <${FieldView} field=${branch} ins=${ins} lane=${lane} ctx=${ctx} onEdit=${onEdit} depth=${depth + 1} />
    </div>` : null}
  </div>`;
}
