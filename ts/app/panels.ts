// The inspector (the selected element's keys) and the Face panel (targets,
// colours, schemes, styles, slots, fonts). Every change is one edit sent to the
// worker, which patches the text, checks it and answers with the face;
// a refused edit leaves the face as it was and says why.

import { html } from "htm/preact";
import { useState, useEffect, useRef } from "preact/hooks";
import type { JSX, VNode } from "preact";
import {
  ANGLE_UNITS, afterRemovingSchemes, at, colorName, convertQuantity, formatQuantity, lengthUnitsFor,
  newStyleEntry, parseHex, parseQuantity, safeOn, swatchFor, toHex,
} from "./values.ts";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.ts";
import { api } from "./api.ts";
import { ask } from "./dialogs.ts";
import { HelpDialog } from "./help.ts";
import type { IconSpelling,
  Axes, EditOp, Field as FieldInfo, Globals, HandSet, Inspect, Path, PaletteEntry, Schemes as SchemesInfo, Scope,
  SlotChoice, SlotEntry, StructureOp, Styles as StylesInfo, Summary, TreeNode, Value, Vocabulary,
} from "../src/studio/protocol.ts";

// -- the callbacks and the context the panels share ---------------------------------------

/** One edit sent to the worker: the face it produced, or null when it was refused. The Inspector awaits a rename's to select the renamed element. */
export type OnEdit = (op: EditOp) => Promise<Summary | null> | void;
export type OnStructure = (op: StructureOp) => Promise<void> | void;
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

/** The Inspector's widgets' context: the viewed device's system fonts, the selected element's type, and where a link may jump. */
export interface WidgetCtx extends FaceCtx {
  systemFonts: string[];
  elementType: string;
  onReveal: OnReveal;
  onFaceSection?: OnFaceSection | undefined;
}

// An event on the input, select or link the handler is on: `currentTarget` is that element.
type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;
type KeyEvent = JSX.TargetedKeyboardEvent<HTMLInputElement>;
type LinkClick = JSX.TargetedMouseEvent<HTMLAnchorElement>;

const ALIGN: string[][] = [["top_left", "top", "top_right"], ["left", "center", "right"],
                           ["bottom_left", "bottom", "bottom_right"]];

// The Face tab's own guide chapter, by section: its "? Guide" link.
const FACE_SECTION_GUIDE: Record<FaceSectionKey, string> = {
  targets: "docs/guide/getting-started.md",
  colours: "docs/guide/colors.md",
  colour_settings: "docs/guide/configuration.md",
  schemes: "docs/guide/colors.md",
  styles: "docs/guide/styles-and-layouts.md",
  hand_sets: "docs/guide/analog-hands.md",
  slots: "docs/guide/configuration.md",
  fonts: "docs/guide/fonts.md",
};

/** A value as a text box shows it: an absent one as nothing. */
const shown = (value: Value | undefined): string => (value == null ? "" : String(value));

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
function Commit({ value, onCommit, placeholder, mono, list, width, focus = false }: CommitProps): VNode {
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
function Quantity({ value, units, bareUnit, onCommit, placeholder, like }: QuantityProps): VNode {
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

interface WidgetProps {
  field: FieldInfo;
  /** The value shown: the key's own, or its override in the chosen scope. */
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
 * time, a kind this page does not know is shown as its YAML.
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
  // a value this panel has no control for: shown as its YAML
  const inYaml = () => (value == null ? html`<span class="dim">in the YAML</span>`
    : html`<code class="yaml" title="edit this in the YAML">${field.text ?? JSON.stringify(value)}</code>`);
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
    case "yaml": return inYaml();
    default: return unknownWidget(field.widget, inYaml());
  }
}

/** A `display:` selector's class as the buttons name it: `amoled` is "AMOLED", `mip` "MIP", `lcd` "LCD". */
const displayLabel = (cls: string | null): string => String(cls || "").toUpperCase();

/** The override scopes an element has, as the note names them. */
const OVERRIDE_SCOPES: [Exclude<Scope, "all">, string][] = [["device", "device"], ["shape", "shape"], ["display", "display class"]];

/** `at` walks a `Value` tree, so what it finds is a `Value`, or nothing. */
const valueAt = (keys: Record<string, Value> | undefined, path: Path): Value | undefined => at(keys, path) as Value | undefined;

interface FieldProps {
  field: FieldInfo;
  ins: Inspect;
  scope: Scope;
  ctx: WidgetCtx;
  onEdit: OnEdit;
  depth?: number;
}

function Field({ field, ins, scope, ctx, onEdit, depth = 0 }: FieldProps): VNode {
  const overridden = field.geometry && scope !== "all";
  const override = field.geometry && scope !== "all" ? valueAt(ins.overrides[scope]?.keys, field.path) : undefined;
  const value = overridden ? override : field.value;
  const base = { element: ins.element, path: field.path, scope, device: ins.device };
  if (field.widget === "object") {
    return html`<div class="field object" style=${`--depth:${depth}`}>
      <div class="name" title=${field.description}>${field.key}</div>
      <div class="children">
        ${(field.children || []).map((c) => html`<${Field} field=${c} ins=${ins} scope=${scope} ctx=${ctx} onEdit=${onEdit} depth=${depth + 1} />`)}
      </div>
    </div>`;
  }
  // the override scopes the viewed device reads this key from, as the note names them
  const local = OVERRIDE_SCOPES
    .map(([s, name]) => (ins.overrides[s] && valueAt(ins.overrides[s]?.keys, field.path) !== undefined ? name : null))
    .filter((name): name is string => name !== null);
  return html`<div class=${"field" + (value == null ? " absent" : "")}>
    <div class="name" title=${field.description}>${field.key}${field.required ? html`<span class="req">*</span>` : null}</div>
    <div class="value">
      <${Widget} field=${field} value=${value} ctx=${ctx} like=${overridden ? field.value : undefined}
        onCommit=${(v: Value) => onEdit({ op: "set", ...base, value: v })}
        onPickColor=${(v: string) => onEdit({ op: "use_color", ...base, scope: "all", value: v })} />
      ${value != null && !field.required && field.widget !== "readonly"
        ? html`<button class="reset" title=${overridden ? "remove the override" : "remove the key (back to the default)"}
          aria-label=${overridden ? "remove the override" : "remove the key"}
            onClick=${() => onEdit({ op: "remove", ...base })}>×</button>` : null}
      ${overridden && value == null && field.value != null ? html`<div class="note">inherits ${JSON.stringify(field.value)}</div>` : null}
      ${!overridden && local.length ? html`<div class="note">overridden on this ${local.join(" and ")}</div>` : null}
    </div>
  </div>`;
}

export interface InspectorProps {
  doc: Summary;
  /** The selected element (its path is what is inspected), or none. */
  element: Pick<TreeNode, "path"> | null | undefined;
  /** The device viewed, whose overrides the scope chooser edits. */
  device: string | null;
  vocab: Partial<Vocabulary>;
  scope: Scope;
  onScope: (scope: Scope) => void;
  onEdit: OnEdit;
  onError: (error: Error) => void;
  onReveal: OnReveal;
  onSelect: OnSelect;
  onFaceSection?: OnFaceSection | undefined;
}

export function Inspector({ doc, element, device, vocab, scope, onScope, onEdit, onError, onReveal, onSelect, onFaceSection }: InspectorProps): VNode {
  // the selected element's keys as the worker answered them (`protocol.ts`'s Inspect)
  const [ins, setIns] = useState<Inspect | null>(null);
  const setScope = onScope;
  useEffect(() => {
    if (!element) { setIns(null); return; }
    let live = true;
    api("inspect", { id: doc.id, element: element.path, device: device || "" }).then(
      (data) => { if (live) setIns(data); }, onError);
    return () => { live = false; };
  }, [doc.id, doc.version, element && element.path.join("."), device]);
  if (!element) return html`<div class="body dim">Select an element on the face or in the layers.</div>`;
  if (!ins || !ins.fields) return html`<div class="body dim">…</div>`;
  const deviceInfo = (vocab.devices || []).find((d) => d.id === device);
  const ctx: WidgetCtx = { globals: doc.globals, vocab, systemFonts: deviceInfo ? deviceInfo.fonts : [], onReveal, onFaceSection,
                           elementType: ins.type };
  // the slot this element draws, edited right here as in the Face tab
  const slotField = ins.fields.find((f) => f.key === "slot");
  const slotCard = slotField && (ctx.globals.slots || []).find((s) => s.name === slotField.value);
  // a `hands` element's own set, likewise
  const setField = ins.type === "hands" && ins.fields.find((f) => f.key === "set");
  const handCard = setField && (ctx.globals.hands || []).find((h) => h.name === setField.value);
  // where an edit is written, as the chooser offers it: the scope, its label and what it means
  const scopes: [Scope, string | null, string][] = [
    ["all", "all targets", "the element's own key, for every target"],
    ["device", ins.device, `an override for ${ins.device} only`],
    ["shape", `${ins.shape} screens`, `an override for every ${ins.shape} watch`],
    ["display", `${displayLabel(ins.display)} screens`, `an override for every ${displayLabel(ins.display)} watch`]];
  return html`<div class="inspector">
    <div class="ins-head">
      <${InlineName} value=${ins.id} title="click to rename"
        onRename=${async (n: string) => { if (await onEdit({ op: "rename", path: ins.element, to: n })) onSelect(n); }} />
      <span class="dim">${ins.type}</span>
      <div class="scope" title="Where at:, size:, radius: and align: edits and drags are written; with all targets, a drag goes where the viewed device reads the key">
        ${scopes.map(([s, label, what]) => html`
          <button class=${scope === s ? "on" : ""} title=${what} onClick=${() => setScope(s)}>${label}</button>`)}
      </div>
    </div>
    ${ins.unknown.length ? html`<div class="note error-text">Not in the format: ${ins.unknown.join(", ")}</div>` : null}
    ${slotCard ? html`<${SlotCard} slot=${slotCard} vocab=${vocab} onEdit=${onEdit} onSelect=${onSelect} />` : null}
    ${handCard ? html`<${HandSetCard} set=${handCard} doc=${doc} ctx=${ctx} onEdit=${onEdit} onReveal=${onReveal} />` : null}
    ${ins.fields.map((f) => html`<${Field} field=${f} ins=${ins} scope=${scope} ctx=${ctx} onEdit=${onEdit} />`)}
    ${ins.parts ? html`<div class="field">
      <div class="name">parts</div>
      <div class="value">
        <span class="dim">${ins.parts.count} part${ins.parts.count === 1 ? "" : "s"}: ${ins.parts.shapes.join(", ")}</span>
        <a href="#" title="a pattern's parts are edited in the YAML" onClick=${(e: LinkClick) => { e.preventDefault(); if (ins.parts) onReveal(ins.parts.line, ins.parts.end); }}>edit in YAML</a>
      </div>
    </div>` : null}
    ${(ins.overridden || []).map((o) => html`<div class="field" key=${o.selector}>
      <div class="name">overrides <code>${o.selector}</code></div>
      <div class="value">
        ${Object.entries(o.keys).map(([k, v]) => html`<code>${k}: ${JSON.stringify(v)}</code>`)}
        <a href="#" title="edit this override in the YAML tab" onClick=${(e: LinkClick) => { e.preventDefault(); onReveal(o.line, o.end); }}>edit in YAML</a>
      </div>
    </div>`)}
  </div>`;
}

// -- the Face panel ------------------------------------------------------------------

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

export interface SlotCardProps {
  slot: SlotEntry;
  vocab: Partial<Vocabulary>;
  onEdit: OnEdit;
  /** Select an element drawing the slot; the card in the Face tab has one, the Inspector's too. */
  onSelect?: OnSelect | undefined;
}

// One `config: slots:` entry, the same card in the Face tab and above a
// selected element drawing it: what the slot shows until the wearer picks
// (the star), what the wearer may pick (a checklist by group, or every
// type), each pick's icon, its title in the settings menu, and what draws it.
export function SlotCard({ slot, vocab, onEdit, onSelect }: SlotCardProps): VNode {
  const path: Path = ["config", "slots", slot.name];
  const types = vocab.complication_types || [];
  const byName = Object.fromEntries(types.map((t) => [t.name, t]));
  const any = !Array.isArray(slot.choices);
  const list: SlotChoice[] = Array.isArray(slot.choices) ? slot.choices : [];
  // the list a switch to "every type" leaves, so switching back restores it
  const [kept, setKept] = useState<SlotChoice[] | null>(null);
  const listed = (name: string) => any || list.some((c) => c.type === name);
  // a choice is written bare unless it carries an icon
  const written = (c: SlotChoice): Value => (c.icon ? { type: c.type, icon: c.icon } : c.type);
  const setChoices = (choices: SlotChoice[]) => onEdit({ op: "set", path: [...path, "choices"], value: choices.map(written) });
  const toggle = (name: string) => setChoices(listed(name) ? list.filter((c) => c.type !== name)
                                                           : [...list, { type: name, icon: null }]);
  const setDefault = (name: string) => {
    if (!listed(name)) setChoices([...list, { type: name, icon: null }]);
    onEdit({ op: "set", path: [...path, "default"], value: name });
  };
  const setIcon = (name: string, icon: IconSpelling | null) => setChoices(list.map((c) => (c.type === name ? { ...c, icon } : c)));
  const first = slot.default === null ? undefined : byName[slot.default];
  return html`<div class="slot-card">
    <div class="slot-head">
      <b><${InlineName} value=${slot.name} title="click to rename (every slot: naming it follows)"
        onRename=${(n: string) => onEdit({ op: "rename", path, to: n })} /></b>
      <button class="reset" title="delete (refused while an element draws it)" aria-label="delete (refused while an element draws it)"
        onClick=${() => onEdit({ op: "remove", path })}>×</button>
    </div>
    <div class="slot-line"><span class="dim">shows first</span>
      <span>${first ? first.label : slot.default}</span>
      <span class="dim">until the wearer picks; click a ★ to change it</span></div>
    <label class="slot-line" title="the watch's own picker, with every type it has, including ones Garmin adds later">
      <input type="checkbox" checked=${any} onChange=${() => {
        if (any) setChoices(kept && kept.length ? kept : [{ type: slot.default, icon: null }]);
        else { setKept(list); onEdit({ op: "set", path: [...path, "choices"], value: "any" }); }
      }} /> the wearer may pick any type, including types Garmin adds later</label>
    <div class="slot-types">${(vocab.categories || []).map((group) => html`<div class="slot-group">
      <div class="pop-title">${group}</div>
      ${types.filter((t) => t.category === group).map((t) => {
        const choice = list.find((c) => c.type === t.name);
        const isDefault = slot.default === t.name;
        return html`<div class=${"slot-type" + (listed(t.name) ? "" : " off")}>
          <input type="checkbox" checked=${listed(t.name)} disabled=${any || isDefault}
            title=${isDefault ? "what the slot shows first stays on the list" : ""} onChange=${() => toggle(t.name)} />
          <button class=${"star" + (isDefault ? " on" : "")} title="show this first" onClick=${() => setDefault(t.name)}>${isDefault ? "★" : "☆"}</button>
          ${!any && choice ? html`<${IconPop} value=${choice.icon} placeholder=${t.icon} vocab=${vocab} allowNone
              onPick=${(v: IconSpelling | null) => setIcon(t.name, v)} />` : html`<${Glyph} name=${t.icon} vocab=${vocab} />`}
          <span class="label">${t.label}</span>
          <span class="dim mono">${t.sample || ""}</span>
        </div>`; })}
    </div>`)}</div>
    ${!any && list.length > 1 ? html`<div class="slot-line">
      <span class="dim">order</span>
      <ol class="choice-order" title="the order the wearer's list shows">${list.map((c, i) => html`<li key=${String(c.type ?? i)}>
        <code>${String(c.type ?? "")}</code>
        <${Reorder} index=${i} count=${list.length} what=${String(c.type ?? i)}
          onMove=${(to: number) => onEdit({ op: "move_item", path: [...path, "choices"], from: i, to })} />
      </li>`)}</ol>
    </div>` : null}
    <div class="slot-line">
      <span class="dim">menu title</span>
      <${Commit} value=${slot.label || ""} placeholder=${slot.name} width="10em"
        onCommit=${(v: string) => onEdit(v.trim() ? { op: "set", path: [...path, "label"], value: v.trim() }
                                                   : { op: "remove", path: [...path, "label"] })} />
      <span class="dim">in the settings menu of a watch without the native editor (fr955)</span>
    </div>
    <div class="slot-line">
      <span class="dim">drawn by</span>
      ${slot.drawn_by.length
        ? slot.drawn_by.map((id) => html`<a href="#" onClick=${(e: LinkClick) => { e.preventDefault(); onSelect && onSelect(id); }}>${id}</a>`)
        : html`<span class="dim">nothing yet: add a data element in Layers</span>`}
    </div>
  </div>`;
}

// The sections over the face as a whole, and the reorder control the lists share.
import { DefaultsSection, FaceIdentity, LayoutsSection, Reorder, StylesMatrix, TargetsSection } from "./face-sections.ts";

interface SchemesProps {
  schemes: SchemesInfo;
  palette: PaletteEntry[];
  styles: StylesInfo;
  ctx: FaceCtx;
  onEdit: OnEdit;
}

// `theme: schemes:`: with none, which colours should follow the wearer's
// style; with some, the roles × schemes table. Every change is one of the
// compound edits of `src/edit/schemes.ts`, so it never leaves the schemes out
// of step.
function Schemes({ schemes, palette, styles, ctx, onEdit }: SchemesProps): VNode {
  const [picked, setPicked] = useState<string[]>([]);
  const [keep, setKeep] = useState<string>("");
  if (!schemes.names.length) {
    const toggle = (n: string) => setPicked(picked.includes(n) ? picked.filter((x) => x !== n) : [...picked, n]);
    return html`<div class="dim note">Colours in a scheme follow the style the wearer picks. Tick the
        colours that should change with it; they keep their names.</div>
      <div class="axis-choices">${palette.map((p) => { const v = parseHex(p.value); return html`<label>
        <input type="checkbox" checked=${picked.includes(p.name)} onChange=${() => toggle(p.name)} />
        <span class="chip" style=${v ? `background:${toHex(v)}` : ""}></span>${p.name}</label>`; })}</div>
      <${AddName} label="Make switchable…" disabled=${!picked.length} suggest=${() => "dark"}
        placeholder="the first scheme's name" title="the ticked colours move into a first scheme, named here"
        onAdd=${(n: string) => { onEdit({ op: "make_switchable", names: picked, scheme: n }); setPicked([]); }} />`;
  }
  const keepName = keep || schemes.names[0] || "";
  const outcome = afterRemovingSchemes(styles.entries);
  return html`<table class="schemes">
      <tr><th></th>${schemes.names.map((s) => html`<th>
        <${InlineName} value=${s} title="click to rename (every style naming it follows)"
          onRename=${(n: string) => onEdit({ op: "rename_scheme", name: s, to: n })} />
        <button class="reset" title="delete this scheme and the styles that pick it" aria-label="delete this scheme and the styles that pick it" onClick=${() => onEdit({ op: "delete_scheme", name: s })}>×</button>
      </th>`)}</tr>
      ${schemes.roles.map((r) => html`<tr><td>
        <${InlineName} value=${r} title=${`click to rename (every color.${r} follows)`}
          onRename=${(n: string) => onEdit({ op: "rename_role", name: r, to: n })} />
        <button class="reset" title="delete this role (refused while something uses it)" aria-label="delete this role (refused while something uses it)" onClick=${() => onEdit({ op: "delete_role", name: r })}>×</button>
      </td>${schemes.names.map((s) => html`<td>
        <${ColorPop} value=${(schemes.colors[s] || {})[r]} ctx=${ctx} roles=${false}
          onPick=${(v: string) => onEdit({ op: "use_color", path: ["theme", "schemes", s, "colors", r], value: v })} /></td>`)}</tr>`)}
    </table>
    <div class="row">
      <${AddName} label="+ Scheme" placeholder="scheme name" title="a copy of the first scheme, and the styles that reach it"
        onAdd=${(n: string) => onEdit({ op: "add_scheme", name: n })} />
      <${AddName} label="+ Role" placeholder="role name" title="a role in every scheme, white until you set it"
        onAdd=${(n: string) => onEdit({ op: "add_role", name: n, value: "#FFFFFF" })} />
    </div>
    <div class="row">
      <select value=${keepName} title="the scheme whose colours become palette colours" onChange=${(e: SelectEvent) => setKeep(e.currentTarget.value)}>
        ${schemes.names.map((s) => html`<option value=${s}>keep ${s}</option>`)}
      </select>
      <button onClick=${() => {
        const parts = [`Every role becomes a palette colour with ${keepName}'s value.`];
        if (outcome.removed) parts.push(`${outcome.removed} style${outcome.removed > 1 ? "s" : ""} naming only a scheme will go.`);
        if (outcome.duplicates) parts.push(`${outcome.duplicates} style${outcome.duplicates > 1 ? "s" : ""} will look like another one; Diagnostics will name them.`);
        ask(parts.join("\n"), "Remove schemes").then((yes: boolean) => { if (yes) onEdit({ op: "remove_theme", keep: keepName }); });
      }}>Remove schemes…</button>
    </div>`;
}

type Axis = keyof Axes;

const AXES: Record<Axis, { title: string; role: string }> = {
  accent_color: { title: "Accent colour", role: "accent" },
  data_color: { title: "Data colour", role: "data" },
};

interface AxisRowProps {
  axis: Axis;
  entry: Axes[Axis];
  palette: PaletteEntry[];
  onEdit: OnEdit;
}

// One `config:` colour axis: what the wearer may pick, always written as an
// explicit list of the face's swatches, so adding a colour to the palette
// never changes what the wearer is offered. `choices: any` is shown, not
// edited.
function AxisRow({ axis, entry, palette, onEdit }: AxisRowProps): VNode {
  const meta = AXES[axis];
  const path: Path = ["config", axis];
  const legal = palette.filter((p) => !p.dithers_on.length);
  if (!entry) {
    const firstLegal = legal[0];
    return html`<div class="axis"><span class="dim">${meta.title}: none</span>
      <button disabled=${!firstLegal} title=${`the wearer picks color.${meta.role} from a list you choose`}
        onClick=${() => { if (firstLegal) onEdit({ op: "set", path, value: { default: `color.${firstLegal.name}`, choices: [`color.${firstLegal.name}`] } }); }}>+ ${meta.title}</button></div>`;
  }
  const list = Array.isArray(entry.raw) ? entry.raw : null;
  const listed = (name: string) => list !== null && list.includes(`color.${name}`);
  const toggle = (name: string) => { if (list) onEdit({ op: "set", path: [...path, "choices"],
    value: listed(name) ? list.filter((c) => c !== `color.${name}`) : [...list, `color.${name}`] }); };
  const other = list ? list.filter((c) => typeof c !== "string" || !colorName(c)) : [];
  // what the default select offers: the list's names, or every swatch when the choice is `any`
  const offered: Value[] = list ? list.filter((c) => typeof c === "string") : palette.map((p) => `color.${p.name}`);
  return html`<div class="axis">
    <div class="axis-head"><b>${meta.title}</b> <span class="dim">binds</span>
      <${Commit} value=${entry.role} width="7em" placeholder=${meta.role}
        onCommit=${(v: string) => onEdit(v.trim() && v.trim() !== meta.role ? { op: "set", path: [...path, "role"], value: v.trim() }
                                                                           : { op: "remove", path: [...path, "role"] })} />
      <button class="reset" title="remove this setting" aria-label="remove this setting" onClick=${() => onEdit({ op: "remove", path })}>×</button></div>
    <div class="slot-line"><span class="dim">default</span>
      <select value=${entry.default || ""} onChange=${(e: SelectEvent) => onEdit({ op: "set", path: [...path, "default"], value: e.currentTarget.value })}>
        ${offered.map((c) => html`<option value=${c}>${colorName(c) || c}</option>`)}
      </select></div>
    ${list ? html`<div class="axis-choices">${palette.map((p) => { const v = parseHex(p.value); return html`
        <label title=${p.dithers_on.length ? `dithers on ${p.dithers_on.join(", ")}` : p.value}>
          <input type="checkbox" checked=${listed(p.name)} disabled=${entry.default === `color.${p.name}`}
            onChange=${() => toggle(p.name)} />
          <span class="chip" style=${v ? `background:${toHex(v)}` : ""}></span>${p.name}${p.dithers_on.length ? html`<span class="warn">⚠</span>` : null}
        </label>`; })}
        ${other.length ? html`<div class="note">and ${other.length} written in the YAML</div>` : null}</div>`
      : html`<div class="note">choices: any. On a fēnix 8 the watch's own colour picker; on a watch
          without it (fr955), every colour in the palette, which grows as colours are added.
          <button onClick=${() => onEdit({ op: "set", path: [...path, "choices"], value: [...new Set([entry.default, ...legal.map((p) => `color.${p.name}`)])] })}>Make it a list</button></div>`}
  </div>`;
}

// A hand set's hands, each with its colour (a part may set its own) and
// part count: the row every hand set is shown by, in the Face tab's list
// and, for the `hands` element placing it, the Inspector's card.
function handColorRows(set: HandSet, ctx: FaceCtx, onEdit: OnEdit): VNode[] {
  return Object.entries(set.hands).map(([hand, h]) => html`<div class="slot-line">
    <span class="dim">${hand}</span>
    <${ColorPop} value=${h.color} ctx=${ctx} title=${`the ${hand} hand's colour (a part may set its own)`}
      onPick=${(v: string) => onEdit({ op: "use_color", path: ["resources", "hand_sets", set.name, hand, "color"], value: v })} />
    <span class="dim">${h.parts} part${h.parts === 1 ? "" : "s"}</span></div>`);
}

export interface HandSetCardProps {
  set: HandSet;
  doc: Summary;
  ctx: FaceCtx;
  onEdit: OnEdit;
  onReveal: OnReveal;
}

// The card a selected `hands` element shows above its keys: the set drawn
// alone, its hands' colours, and a link to its parts in the YAML tab.
export function HandSetCard({ set, doc, ctx, onEdit, onReveal }: HandSetCardProps): VNode {
  const device = (doc.targets || [])[0] || "";
  return html`<div class="hand-set-card">
    <${WorkerImage} class="hand-thumb" alt=${set.name} title="drawn alone at 10:09:42"
      op="handset" args=${{ id: doc.id, name: set.name, device, scale: 1, v: doc.version }} />
    <div class="hand-body">
      ${handColorRows(set, ctx, onEdit)}
      <div class="slot-line"><a href="#" title="a hand's parts are edited in the YAML"
        onClick=${(e: LinkClick) => { e.preventDefault(); onReveal(set.line, set.end); }}>edit the set</a></div>
    </div>
  </div>`;
}

interface HandSetsProps {
  doc: Summary;
  ctx: FaceCtx;
  onEdit: OnEdit;
  onSelect: OnSelect;
  onReveal: OnReveal;
}

// `resources: hand_sets:`: each set drawn alone, its hands' colours, what
// places it, and its parts in the YAML; new ones from a preset.
function HandSets({ doc, ctx, onEdit, onSelect, onReveal }: HandSetsProps): VNode {
  const sets = ctx.globals.hands || [];
  const presets = ctx.vocab.hand_presets || [];
  const [preset, setPreset] = useState<string>("");
  const device = (doc.targets || [])[0] || "";
  const taken = new Set(sets.map((s) => s.name));
  return html`${sets.length ? html`<ul class="rows">${sets.map((s) => html`<li class="hand-set">
      <${WorkerImage} class="hand-thumb" alt=${s.name} title="drawn alone at 10:09:42"
        op="handset" args=${{ id: doc.id, name: s.name, device, scale: 1, v: doc.version }} />
      <div class="hand-body">
        <div class="slot-head">
          <${InlineName} value=${s.name} title="click to rename (every set: naming it follows)"
            onRename=${(n: string) => onEdit({ op: "rename_hand_set", name: s.name, to: n })} />
          <button title="a copy, to change without touching this one" onClick=${() => onEdit({ op: "duplicate_hand_set", name: s.name })}>Duplicate</button>
          <button class="reset" title="delete (refused while an element places it)" aria-label="delete (refused while an element places it)" onClick=${() => onEdit({ op: "delete_hand_set", name: s.name })}>×</button>
        </div>
        ${handColorRows(s, ctx, onEdit)}
        <div class="slot-line"><span class="dim">placed by</span>
          ${s.placed_by.length ? s.placed_by.map((id) => html`<a href="#" onClick=${(e: LinkClick) => { e.preventDefault(); onSelect(id); }}>${id}</a>`)
                               : html`<span class="dim">nothing</span>`}</div>
        <div class="slot-line"><a href="#" title="a hand's parts are edited in the YAML" onClick=${(e: LinkClick) => { e.preventDefault(); onReveal(s.line, s.end); }}>Edit in YAML</a></div>
      </div>
    </li>`)}</ul>`
    : html`<div class="dim note">A hand set is the shape of an analog dial's hands, drawn pointing at 12;
        a <code>hands</code> element places it on the face and turns it with the time. Its parts are
        edited in the YAML.</div>`}
    <div class="row">
      <select value=${preset} onChange=${(e: SelectEvent) => setPreset(e.currentTarget.value)}>
        <option value="">from a preset…</option>
        ${presets.map((p) => html`<option value=${p}>${p}</option>`)}
      </select>
      <${AddName} label="+ Hand set" disabled=${!preset} placeholder="hand set name"
        title=${sets.some((s) => s.placed_by.length) ? "" : "also places it at the centre"}
        suggest=${() => (taken.has(preset) ? `${preset}_2` : preset)}
        onAdd=${(name: string) => { onEdit({ op: "add_hand_set", name, preset }); setPreset(""); }} />
    </div>`;
}

interface NewSlotProps {
  vocab: Partial<Vocabulary>;
  /** The slot names in use, so the suggested name is free. */
  taken: string[];
  onEdit: OnEdit;
}

// A new slot: what it shows first, then its name; it is drawn by a new data
// element, in the same change.
function NewSlot({ vocab, taken, onEdit }: NewSlotProps): VNode {
  const [first, setFirst] = useState<string>("");
  const types = vocab.complication_types || [];
  return html`<div class="row">
    <select value=${first} onChange=${(e: SelectEvent) => setFirst(e.currentTarget.value)} title="what the new slot shows first">
      <option value="">a new slot, showing…</option>
      ${(vocab.categories || []).map((group) => html`<optgroup label=${group}>
        ${types.filter((t) => t.category === group).map((t) => html`<option value=${t.name}>${t.label}</option>`)}
      </optgroup>`)}
    </select>
    <${AddName} label="+ Slot" disabled=${!first} placeholder="slot name"
      suggest=${() => { const base = first.split("_")[0] ?? first; return taken.includes(base) ? `${base}_2` : base; }}
      onAdd=${(n: string) => { onEdit({ op: "add_slot", name: n, default: first }); setFirst(""); }} />
  </div>`;
}

/** A font file added to the bundle: declared as the font `font` at `size`, or pointed at by every font whose `source:` is `reference`. */
export type OnUpload = (file: File, what: { font?: string; size?: string; reference?: string | null }) => unknown;

export interface FacePanelProps {
  doc: Summary;
  vocab: Partial<Vocabulary>;
  onEdit: OnEdit;
  onUpload: OnUpload;
  onSelect: OnSelect;
  onStructure: OnStructure;
  onReveal?: OnReveal | undefined;
  /** The open section, when the editor holds it; the panel keeps its own otherwise. */
  section?: string | null | undefined;
  onSection?: ((key: SectionKey) => void) | undefined;
}

/** Every section of the Face tab: the ones the pickers jump to (`FaceSectionKey`) and the face's own. */
type SectionKey = FaceSectionKey | "face" | "defaults" | "layouts";

// Every section's guide chapter: its "? Guide" link.
const SECTION_GUIDE: Record<SectionKey, string> = {
  ...FACE_SECTION_GUIDE,
  face: "docs/guide/design-file.md",
  defaults: "docs/guide/design-file.md",
  layouts: "docs/guide/styles-and-layouts.md",
};

/** One section of the Face tab: its nav button (title and count) and its body. */
interface FaceSection {
  key: SectionKey;
  title: string;
  count?: number;
  body: VNode;
}

/**
 * The Face tab: one section at a time (`section`, a key below, and
 * `onSection` to switch), as the editor holds it.
 */
export function FacePanel({ doc, vocab, onEdit, onUpload, onSelect, onReveal, section, onSection }: FacePanelProps): VNode {
  const g = doc.globals;
  const palette = g.palette;
  const schemes = g.schemes;
  const styles = g.styles;
  const devices = vocab.devices || [];
  const unreadable = vocab.unreadable_devices || [];
  // a font file chosen and waiting for its name
  const [newFont, setNewFont] = useState<File | null>(null);
  const fontFile = useRef<HTMLInputElement | null>(null);
  const replaceFor = useRef<string | null>(null);
  const replaceFile = useRef<HTMLInputElement | null>(null);

  const ctx: FaceCtx = { globals: g, vocab };
  const unused = palette.filter((p) => !p.used_by.length && !p.launcher);
  // who uses a colour: an element id selects it, anything else is a path
  const users = (list: string[]) => list.map((u, i) => html`${i ? ", " : ""}${u.includes(".") ? html`<code>${u}</code>`
    : html`<a href="#" onClick=${(e: LinkClick) => { e.preventDefault(); onSelect(u); }}>${u}</a>`}`);
  // a chosen file, taken from its input so the same file can be chosen again
  const chosen = (e: InputEvent): File | undefined => {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = "";
    return file;
  };

  const SECTIONS: [FaceSection, ...FaceSection[]] = [
    { key: "face", title: "Face", body: html`
      <${FaceIdentity} face=${g.face} onEdit=${onEdit} />
    ` },

    { key: "targets", title: "Target devices", count: (g.targets || []).length, body: html`
      <${TargetsSection} targets=${g.targets || []} problems=${g.target_problems || {}} devices=${devices} unreadable=${unreadable} onEdit=${onEdit} />
    ` },

    { key: "colours", title: "Colours", count: palette.length, body: html`
      <ul class="rows">${palette.map((p, i) => html`<li class="swatch-row">
          <${InlineName} value=${p.name} title=${`click to rename (every color.${p.name} follows)`}
            onRename=${(n: string) => onEdit({ op: "rename", path: ["resources", "palette", p.name], to: n, prefix: "color." })} />
          <${ColorPop} value=${p.value} ctx=${ctx} faceGroup=${false}
            title=${p.used_by.length ? `changes ${p.used_by.length} use${p.used_by.length > 1 ? "s" : ""}: ${p.used_by.join(", ")}` : "not used yet"}
            onPick=${(v: string) => onEdit({ op: "set_swatch", name: p.name, value: v })} />
          ${p.dithers_on.length ? html`<span class="warn" title=${`dithers on ${p.dithers_on.join(", ")}`}>⚠</span>` : null}
          ${p.problem ? html`<span class="warn" title=${p.problem}>⚠ not a colour</span>` : null}
          ${p.automatic ? html`<span class="tag" title="named after its colour: renamed when its colour changes, removed when nothing uses it">auto</span>` : null}
          <${Reorder} index=${i} count=${palette.length} what=${p.name} onMove=${(to: number) => onEdit({ op: "move_key", path: ["resources", "palette", p.name], to })} />
          <button class="reset" title="delete (refused while something uses it)" aria-label="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "palette", p.name] })}>×</button>
          <div class="note">${p.used_by.length ? html`used by ${users(p.used_by)}`
            : p.launcher ? "the launcher icon reads it" : "not used"}</div>
        </li>`)}</ul>
      <div class="row">
        <${ColorPop} ctx=${ctx} faceGroup=${false} label="+ Colour" title="add one of the 64, or your own" onPick=${(v: string) => onEdit({ op: "add_swatch", value: v })} />
        <button disabled=${!unused.length} title=${unused.length ? `remove ${unused.map((p) => p.name).join(", ")}` : "every colour is in use"}
          onClick=${() => ask(`Remove ${unused.map((p) => p.name).join(", ")}?`, "Remove").then((yes: boolean) => { if (yes) onEdit({ op: "remove_unused" }); })}>Remove unused</button>
      </div>
    ` },

    { key: "colour_settings", title: "Colour settings", body: html`
      ${(["accent_color", "data_color"] as const).map((axis) => html`<${AxisRow} axis=${axis} entry=${g.axes[axis]}
        palette=${palette} onEdit=${onEdit} />`)}
    ` },

    { key: "schemes", title: "Colour schemes", count: schemes.names.length, body: html`
      <${Schemes} schemes=${schemes} palette=${palette} styles=${styles} ctx=${ctx} onEdit=${onEdit} />
    ` },

    { key: "defaults", title: "Defaults", body: html`
      <${DefaultsSection} defaults=${g.defaults} onEdit=${onEdit} />
    ` },

    { key: "layouts", title: "Layouts", count: (g.layout_entries || []).length, body: html`
      <${LayoutsSection} entries=${g.layout_entries || []} styles=${styles} onEdit=${onEdit} />
    ` },

    { key: "styles", title: "Styles", count: styles.entries.length, body: html`
      <${StylesMatrix} styles=${styles} layouts=${g.layouts || []} schemes=${schemes} onEdit=${onEdit} />
    ` },

    { key: "hand_sets", title: "Hand sets", count: (g.hands || []).length, body: html`
      <${HandSets} doc=${doc} ctx=${ctx} onEdit=${onEdit} onSelect=${onSelect} onReveal=${onReveal || (() => {})} />
    ` },

    { key: "slots", title: "Slots", count: (g.slots || []).length, body: html`
      ${(g.slots || []).length ? (g.slots || []).map((s) => html`<${SlotCard} slot=${s} vocab=${vocab}
          onEdit=${onEdit} onSelect=${onSelect} />`)
        : html`<div class="dim note">A slot shows whichever complication the wearer picks on the watch.</div>`}
      <${NewSlot} vocab=${vocab} taken=${(g.slots || []).map((s) => s.name)} onEdit=${onEdit} />
    ` },

    { key: "fonts", title: "Fonts", count: (g.fonts || []).length, body: html`
      <ul class="rows">${(g.fonts || []).map((f) => html`<li class="font">
        <code>font.${f.name}</code>
        <span class="dim">${f.source || f.face || ""}</span>
        ${f.size != null ? html`<${Quantity} value=${f.size} units=${["%r", "px"]} bareUnit="px"
          onCommit=${(v: string | number) => onEdit({ op: "set", path: ["resources", "fonts", f.name, "size"], value: v })} />` : null}
        ${f.source ? html`<button title="replace the font file" onClick=${() => { replaceFor.current = f.source; replaceFile.current?.click(); }}>Replace…</button>` : null}
        <button class="reset" title="delete (refused while something uses it)" aria-label="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "fonts", f.name] })}>×</button>
      </li>`)}</ul>
      ${newFont ? html`<div class="row"><span class="dim">${newFont.name} as</span>
          <${AddName} key=${newFont.name} label="font name" placeholder="font name" startOpen=${true}
            suggest=${() => newFont.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1").toLowerCase()}
            onAdd=${(n: string) => { onUpload(newFont, { font: n, size: "10%r" }); setNewFont(null); }}
            onCancel=${() => setNewFont(null)} /></div>`
        : html`<button onClick=${() => fontFile.current?.click()}>+ Font from a file…</button>`}
      <input type="file" accept=".ttf,.otf" hidden ref=${fontFile} onChange=${(e: InputEvent) => {
        const file = chosen(e); if (file) setNewFont(file);
      }} />
      <input type="file" accept=".ttf,.otf" hidden ref=${replaceFile} onChange=${(e: InputEvent) => {
        const file = chosen(e); if (file) onUpload(file, { reference: replaceFor.current });
      }} />
    ` },
  ];

  // the open section is the editor's (`section`, `onSection`), so a jump
  // from elsewhere switches it while the tab is showing; rendered alone,
  // the panel keeps its own
  const [own, setOwn] = useState<string>(SECTIONS[0].key);
  const activeKey = section ?? own;
  const setActiveKey: (key: SectionKey) => void = onSection ?? setOwn;
  const active = SECTIONS.find((s) => s.key === activeKey) || SECTIONS[0];
  const [helpTopic, setHelpTopic] = useState<string | null>(null);
  const guide = SECTION_GUIDE[active.key];

  return html`<div class="face-panel">
    <div class="tabs face-nav">${SECTIONS.map((s) => html`<button key=${s.key} class=${s.key === active.key ? "on" : ""}
        onClick=${() => setActiveKey(s.key)}>${s.title}${s.count != null ? html`<span class="count">${s.count}</span>` : null}</button>`)}</div>
    <div class="face-section-body">
      ${guide ? html`<a href="#" class="face-section-guide" title="Open the guide to this section"
          onClick=${(e: LinkClick) => { e.preventDefault(); setHelpTopic(guide); }}>? Guide</a>` : null}
      ${active.body}
    </div>
    ${helpTopic ? html`<${HelpDialog} start=${helpTopic} onClose=${() => setHelpTopic(null)} />` : null}
  </div>`;
}
