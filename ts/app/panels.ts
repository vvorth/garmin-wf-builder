// The inspector (the selected element's keys, as the generic form of
// `form.ts` over the worker's field tree) and the Face panel (targets,
// colours, schemes, styles, slots, fonts). Every change is one edit sent to the
// worker, which patches the text, checks it and answers with the face;
// a refused edit leaves the face as it was and says why.

import { html } from "htm/preact";
import { useEffect, useState, useRef } from "preact/hooks";
import type { JSX, VNode } from "preact";
import { afterRemovingSchemes, colorName, newStyleEntry, parseHex, toHex } from "./values.ts";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.ts";
import { ask } from "./dialogs.ts";
import { HelpDialog } from "./help.ts";
import { ColorPop, Commit, Form, Glyph, IconPop, Quantity } from "./form.ts";
import type { FaceCtx, FaceSectionKey, OnEdit, OnFaceSection, OnReveal, OnSelect, WidgetCtx } from "./form.ts";
import type { IconSpelling,
  Axes, EditOp, HandSet, Inspect, PaletteEntry, Path, Schemes as SchemesInfo, Scope,
  SlotChoice, SlotEntry, StructureOp, Styles as StylesInfo, Summary, TreeNode, Value, Vocabulary,
} from "../src/studio/protocol.ts";

// -- the callbacks, the context and the controls the panels share ------------------------------

// The form's controls and the callback types live in `form.ts`; the Face panel's sections read them from here.
export { ColorPop, Commit, Glyph, IconPop, Quantity } from "./form.ts";
export type { ColorPopProps, FaceCtx, FaceSectionKey, GlyphProps, IconPopProps, OnEdit, OnFaceSection, OnReveal, OnSelect, WidgetCtx } from "./form.ts";
export type OnStructure = (op: StructureOp) => Promise<void> | void;

// An event on the input, select or link the handler is on: `currentTarget` is that element.
type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;
type LinkClick = JSX.TargetedMouseEvent<HTMLAnchorElement>;

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

// -- the inspector ---------------------------------------------------------------------------

export interface InspectorProps {
  doc: Summary;
  /** The selected element (its path is what is inspected), or none. */
  element: Pick<TreeNode, "path"> | null | undefined;
  /** The selection's field tree, as the worker answered it for the editing context (`store.ts` asks), or null while it is on its way. */
  ins: Inspect | null;
  /** Where a geometry edit lands (Edit for): the element's own key, or its override for the viewed watch, its shape or its display class. */
  target: Scope;
  vocab: Partial<Vocabulary>;
  onEdit: OnEdit;
  onReveal: OnReveal;
  onSelect: OnSelect;
  onFaceSection?: OnFaceSection | undefined;
  /** The picked point of a polygon's `points:`, marked in its list. */
  vertex?: number | null | undefined;
  /** A `points:` item hovered or focused picks its vertex on the face. */
  onHoverVertex?: ((index: number) => void) | undefined;
  /** Several edits as one change: a control that writes a key in more than one step. */
  onBatch?: ((label: string, edits: EditOp[]) => void) | undefined;
}

/** Whether `ins` answers for the element at `path`. */
const answersFor = (ins: Inspect, path: Path): boolean => ins.element.length === path.length && ins.element.every((step, i) => step === path[i]);

// The selected element: its id (renamed in place), its type, the slot or
// hand set it draws as the Face tab's own card, and every key the format
// has for it as the generic form, edited where the editing context says. A
// hand or a part is named with what it belongs to (`vintage › hour`,
// `hour › blade`, `ticks › tick`); it has no overrides and no `aod:` block,
// so its keys are edited as they are, whatever the frame.
export function Inspector({ doc, element, ins, target, vocab, onEdit, onReveal, onSelect, onFaceSection, vertex = null, onHoverVertex, onBatch }: InspectorProps): VNode {
  if (!element) return html`<div class="body dim">Select an element on the face or in the layers.</div>`;
  if (!ins || !answersFor(ins, element.path)) return html`<div class="body dim">…</div>`;
  if (ins.error) return html`<div class="body dim">${ins.error}</div>`;
  const deviceInfo = (vocab.devices || []).find((d) => d.id === ins.device);
  const ctx: WidgetCtx = { globals: doc.globals, vocab, systemFonts: deviceInfo ? deviceInfo.fonts : [], onReveal, onFaceSection,
                           elementType: ins.type, vertex, onHoverVertex, onBatch, assets: doc.assets ?? [] };
  if (ins.subject === "part" || ins.subject === "hand") {
    // a part under its hand or its pattern, a hand under its set: the step before the `parts:` key, or the set's name
    const under = ins.element[ins.element.length - (ins.subject === "part" ? 3 : 2)];
    return html`<div class="inspector">
      <div class="ins-head">
        <span class="name crumb" title=${ins.element.map(String).join(".")}>${String(under)} › ${ins.id}</span>
        <span class="dim">${ins.type}</span>
      </div>
      ${ins.unknown.length ? html`<div class="note error-text">Not in the format: ${ins.unknown.join(", ")}</div>` : null}
      <${Form} ins=${ins} target="all" ctx=${ctx} onEdit=${onEdit} />
    </div>`;
  }
  // the slot this element draws, edited right here as in the Face tab
  const slotField = ins.fields.find((f) => f.key === "slot");
  const slotCard = slotField && (ctx.globals.slots || []).find((s) => s.name === slotField.value);
  // a `hands` element's own set, likewise
  const setField = ins.type === "hands" && ins.fields.find((f) => f.key === "set");
  const handCard = setField && (ctx.globals.hands || []).find((h) => h.name === setField.value);
  const frame = ins.context?.frame ?? "awake";
  return html`<div class="inspector">
    <div class="ins-head">
      <${InlineName} value=${ins.id} title="click to rename"
        onRename=${async (n: string) => { if (await onEdit({ op: "rename", path: ins.element, to: n })) onSelect(n); }} />
      <span class="dim">${ins.type}</span>
      ${frame === "aod" ? html`<span class="frame-note" title="the always-on frame: the keys the element restyles there are written to its aod: block; the others are edited in the awake frame">AOD frame</span>` : null}
    </div>
    ${ins.unknown.length ? html`<div class="note error-text">Not in the format: ${ins.unknown.join(", ")}</div>` : null}
    ${slotCard ? html`<${SlotCard} slot=${slotCard} vocab=${vocab} onEdit=${onEdit} onSelect=${onSelect} />` : null}
    ${handCard ? html`<${HandSetCard} set=${handCard} doc=${doc} ctx=${ctx} onEdit=${onEdit} onReveal=${onReveal} />` : null}
    <${Form} ins=${ins} target=${target} ctx=${ctx} onEdit=${onEdit} />
  </div>`;
}

// -- the Face panel ------------------------------------------------------------------

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
// style; with some, the roles × schemes table, each scheme with the base it
// inherits from (`base:`) and each role it inherits greyed, "from <base>",
// until a colour picked sets it on the scheme (↺ inherits it again). Every change is one of the
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
  const baseOf = (s: string): string | null => schemes.base?.[s] ?? null;
  // whether `s`'s base chain sets `role`, so removing `s`'s own leaves it inherited
  const inheritable = (s: string, role: string): boolean => {
    const seen = new Set([s]);
    for (let b = baseOf(s); b !== null && !seen.has(b); b = baseOf(b)) {
      seen.add(b);
      if (role in (schemes.colors[b] || {})) return true;
    }
    return false;
  };
  const outcome = afterRemovingSchemes(styles.entries);
  return html`<table class="schemes">
      <tr><th></th>${schemes.names.map((s) => html`<th>
        <${InlineName} value=${s} title="click to rename (every style naming it follows)"
          onRename=${(n: string) => onEdit({ op: "rename_scheme", name: s, to: n })} />
        <button class="reset" title="delete this scheme and the styles that pick it" aria-label="delete this scheme and the styles that pick it" onClick=${() => onEdit({ op: "delete_scheme", name: s })}>×</button>
        <div><${Commit} value=${schemes.labels?.[s] ?? ""} placeholder="label" width="7em" aria=${`label of ${s}`}
          onCommit=${(t: string) => {
            if (t.trim()) onEdit({ op: "set", path: ["theme", "schemes", s, "label"], value: t.trim() });
            else if (schemes.labels?.[s] != null) onEdit({ op: "remove", path: ["theme", "schemes", s, "label"] });
          }} /></div>
        ${schemes.names.length > 1 ? html`<div><select class="scheme-base" value=${baseOf(s) ?? ""} aria-label=${`base of ${s}`}
            title="a scheme it inherits every role from, but the ones it sets itself"
            onChange=${(e: SelectEvent) => {
              const to = e.currentTarget.value;
              if (to) onEdit({ op: "set", path: ["theme", "schemes", s, "base"], value: to });
              else if (baseOf(s) !== null) onEdit({ op: "remove", path: ["theme", "schemes", s, "base"] });
            }}>
            <option value="">no base</option>
            ${schemes.names.filter((o) => o !== s).map((o) => html`<option value=${o}>base: ${o}</option>`)}
            ${baseOf(s) !== null && !schemes.names.includes(baseOf(s)!) ? html`<option value=${baseOf(s)}>base: ${baseOf(s)} (missing)</option>` : null}
          </select></div>` : null}
      </th>`)}</tr>
      ${schemes.roles.map((r) => html`<tr><td>
        <${InlineName} value=${r} title=${`click to rename (every color.${r} follows)`}
          onRename=${(n: string) => onEdit({ op: "rename_role", name: r, to: n })} />
        <button class="reset" title="delete this role (refused while something uses it)" aria-label="delete this role (refused while something uses it)" onClick=${() => onEdit({ op: "delete_role", name: r })}>×</button>
      </td>${schemes.names.map((s) => {
        // a role the scheme takes from its base: greyed, and a pick sets it on this scheme
        const inherited = (schemes.inherited?.[s] || []).includes(r);
        const overrides = !inherited && baseOf(s) !== null && inheritable(s, r);
        return html`<td class=${inherited ? "inherited" : ""} title=${inherited ? `from ${baseOf(s)}: pick a colour to set it on ${s}` : ""}>
        <${ColorPop} value=${(schemes.colors[s] || {})[r]} ctx=${ctx} roles=${false}
          onPick=${(v: string) => onEdit({ op: "use_color", path: ["theme", "schemes", s, "colors", r], value: v })} />
        ${inherited ? html`<span class="dim from">from ${baseOf(s)}</span>` : null}
        ${overrides ? html`<button class="reset" title=${`inherit it from ${baseOf(s)} again`} aria-label=${`inherit ${r} from ${baseOf(s)}`}
          onClick=${() => onEdit({ op: "remove", path: ["theme", "schemes", s, "colors", r] })}>↺</button>` : null}</td>`;
      })}</tr>`)}
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
  ctx: FaceCtx;
  onEdit: OnEdit;
}

// One `config:` colour axis: what the wearer may pick, written as an
// explicit list, so adding a colour to the palette never changes what the
// wearer is offered. The list shows inline, in the wearer's order: each
// choice as its swatch with ↑ ↓ ×, and "+ add" picking another (a face's
// colour as `color.<name>`, any other as an inline `{color}`). The default
// cannot be removed, nor the last choice. `choices: any` is shown, with the
// way to a list.
function AxisRow({ axis, entry, palette, ctx, onEdit }: AxisRowProps): VNode {
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
  const choices: Path = [...path, "choices"];
  // a choice as the default names it: the reference, or an inline choice's colour
  const spelled = (c: Value): string | null => (typeof c === "string" ? c : c !== null && typeof c === "object" && !Array.isArray(c) && typeof c["color"] === "string" ? c["color"] : null);
  // what the default select offers: the list's choices, or every swatch when the choice is `any`
  const offered: string[] = list ? list.map(spelled).filter((c): c is string => c !== null) : palette.map((p) => `color.${p.name}`);
  const add = (v: string): void => {
    if (!list) return;
    const value: Value = colorName(v) ? v : { color: v };
    if (list.some((c) => spelled(c) === spelled(value))) return;
    onEdit({ op: "insert_item", path: choices, at: list.length, value });
  };
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
    ${list ? html`<ol class="axis-list" title="what the wearer may pick, in the order the watch lists them">${list.map((c, i) => {
        const ref = colorName(c);
        const swatch = ref ? palette.find((p) => p.name === ref) : undefined;
        const rgb = parseHex(swatch ? swatch.value : spelled(c));
        const label = typeof c === "object" && c !== null && !Array.isArray(c) && typeof c["label"] === "string" ? c["label"] : swatch && typeof swatch.label === "string" ? swatch.label : null;
        const named = ref ?? spelled(c) ?? JSON.stringify(c);
        const isDefault = spelled(c) !== null && spelled(c) === entry.default;
        return html`<li key=${`${i}:${named}`} class="axis-choice">
          <span class="chip" style=${rgb ? `background:${toHex(rgb)}` : ""}></span>
          <span>${named}</span>${label ? html`<span class="dim">${label}</span>` : null}
          ${swatch && swatch.dithers_on.length ? html`<span class="warn" title=${`dithers on ${swatch.dithers_on.join(", ")}`}>⚠</span>` : null}
          ${isDefault ? html`<span class="tag" title="the default: what the face starts with">default</span>` : null}
          <${Reorder} index=${i} count=${list.length} what=${named} onMove=${(to: number) => onEdit({ op: "move_item", path: choices, from: i, to })} />
          <button class="reset" aria-label=${`remove ${named}`} disabled=${isDefault || list.length < 2}
            title=${isDefault ? "the default stays on the list: pick another default first" : list.length < 2 ? "the list keeps one colour at least" : "take it off the list"}
            onClick=${() => onEdit({ op: "remove_item", path: choices, at: i })}>×</button>
        </li>`; })}
        <li class="axis-add"><${ColorPop} ctx=${ctx} roles=${false} label="+ add" title="offer another colour: one of the face's, or any other as it is"
          onPick=${add} /></li>
      </ol>`
      : html`<div class="note">choices: any. On a fēnix 8 the watch's own colour picker; on a watch
          without it (fr955), every colour in the palette, which grows as colours are added.
          <button onClick=${() => onEdit({ op: "set", path: choices, value: [...new Set([entry.default, ...legal.map((p) => `color.${p.name}`)])] })}>Make it a list</button></div>`}
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
      <div class="slot-line"><a href="#" title="the set's lines in the YAML tab (its parts are edited on the face too: enter this element from Layers)"
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
        <div class="slot-line"><a href="#" title="the set's lines in the YAML tab (its parts are edited on the face too: enter an element placing the set from Layers)" onClick=${(e: LinkClick) => { e.preventDefault(); onReveal(s.line, s.end); }}>Edit in YAML</a></div>
      </div>
    </li>`)}</ul>`
    : html`<div class="dim note">A hand set is the shape of an analog dial's hands, drawn pointing at 12;
        a <code>hands</code> element places it on the face and turns it with the time. Its parts are
        edited on the face, by entering that element from Layers, or in the YAML.</div>`}
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

/** The field tree of a path that is not the selection (a `resources: fonts:` entry), as the worker answers it. */
export type OnInspect = (path: Path) => Promise<Inspect>;

interface FontOptionsProps {
  name: string;
  doc: Summary;
  ctx: FaceCtx;
  onInspect: OnInspect;
  onEdit: OnEdit;
  onBatch?: ((label: string, edits: EditOp[]) => void) | undefined;
}

/** The keys a font's own row edits already: its file and its size. */
const FONT_ROW_KEYS = new Set(["source", "size"]);

// Every other key of one `resources: fonts:` entry, as the generic form over
// the worker's field tree for it: a baked font's `glyphs`, `antialias`,
// `monospace` and `align`, a vector font's `face` (one name, or a list of
// them tried in order, the faces the face's watches publish suggested) and
// `unsupported`. Asked again whenever the face changes.
function FontOptions({ name, doc, ctx, onInspect, onEdit, onBatch }: FontOptionsProps): VNode {
  const [ins, setIns] = useState<Inspect | null>(null);
  const path: Path = ["resources", "fonts", name];
  useEffect(() => {
    let live = true;
    onInspect(path).then((answer) => { if (live) setIns(answer); }, () => { if (live) setIns(null); });
    return () => { live = false; };
  }, [name, doc.version]);
  if (!ins || ins.error) return html`<div class="font-options dim">${ins ? ins.error : "…"}</div>`;
  const devices = (ctx.vocab.devices || []).filter((d) => doc.globals.targets.includes(d.id));
  const faceNames = [...new Set(devices.flatMap((d) => d.faces ?? []))].sort();
  const wctx: WidgetCtx = { ...ctx, systemFonts: [], elementType: "font", onReveal: () => {}, onBatch, faceNames, assets: doc.assets ?? [] };
  return html`<div class="font-options">
    <${Form} ins=${{ ...ins, fields: ins.fields.filter((f) => !FONT_ROW_KEYS.has(f.key)) }} target="all" ctx=${wctx} onEdit=${onEdit} />
  </div>`;
}

/**
 * The edit that gives the palette colour `p` the label `label`: a bare
 * colour becomes the long form (`{value, label}`), a long one has its label
 * set; an empty label goes back to the bare colour. Null when nothing
 * changes.
 */
export function labelOp(p: PaletteEntry, label: string): EditOp | null {
  const path: Path = ["resources", "palette", p.name];
  if (label) return p.long ? { op: "set", path: [...path, "label"], value: label } : { op: "set", path, value: { value: p.value, label } };
  return p.long && p.label != null ? { op: "set", path, value: p.value } : null;
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
  /** A font's field tree, for its options; without it a font shows its file and size only. */
  onInspect?: OnInspect | undefined;
  /** Several edits as one change, under `label`. */
  onBatch?: ((label: string, edits: EditOp[]) => void) | undefined;
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
export function FacePanel({ doc, vocab, onEdit, onUpload, onSelect, onReveal, onInspect, onBatch, section, onSection }: FacePanelProps): VNode {
  const g = doc.globals;
  const palette = g.palette;
  const schemes = g.schemes;
  const styles = g.styles;
  const devices = vocab.devices || [];
  const unreadable = vocab.unreadable_devices || [];
  // a font file chosen and waiting for its name
  const [newFont, setNewFont] = useState<File | null>(null);
  // the fonts whose options are open
  const [fontsOpen, setFontsOpen] = useState<string[]>([]);
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
          <${Commit} value=${typeof p.label === "string" ? p.label : ""} placeholder="label" width="7em" aria=${`label of ${p.name}`}
            onCommit=${(t: string) => { const op = labelOp(p, t.trim()); if (op) onEdit(op); }} />
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
        palette=${palette} ctx=${ctx} onEdit=${onEdit} />`)}
    ` },

    { key: "schemes", title: "Colour schemes", count: schemes.names.length, body: html`
      <${Schemes} schemes=${schemes} palette=${palette} styles=${styles} ctx=${ctx} onEdit=${onEdit} />
    ` },

    { key: "defaults", title: "Defaults", body: html`
      <${DefaultsSection} defaults=${g.defaults} onEdit=${onEdit} />
    ` },

    { key: "layouts", title: "Layouts", count: (g.layout_entries || []).length, body: html`
      <${LayoutsSection} entries=${g.layout_entries || []} styles=${styles} onEdit=${onEdit} onBatch=${onBatch} />
    ` },

    { key: "styles", title: "Styles", count: styles.entries.length, body: html`
      <${StylesMatrix} styles=${styles} layouts=${g.layouts || []} schemes=${schemes} onEdit=${onEdit} onBatch=${onBatch}
        labels=${Object.fromEntries((g.layout_entries || []).map((l) => [l.name, l.label]))} />
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
        ${onInspect ? html`<button class="font-toggle" aria-expanded=${fontsOpen.includes(f.name)} title=${f.source ? "glyphs, antialias, monospace, align" : "face names, unsupported"}
            onClick=${() => setFontsOpen(fontsOpen.includes(f.name) ? fontsOpen.filter((n) => n !== f.name) : [...fontsOpen, f.name])}>${fontsOpen.includes(f.name) ? "options ▾" : "options ▸"}</button>` : null}
        ${onInspect && fontsOpen.includes(f.name) ? html`<${FontOptions} key=${f.name} name=${f.name} doc=${doc} ctx=${ctx} onInspect=${onInspect} onEdit=${onEdit} onBatch=${onBatch} />` : null}
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
