// The Face tab's sections over the face as a whole: Face (`face:`), Target
// devices (`build: targets:`), Defaults (`defaults:`), Layouts (`layouts:`)
// and the Styles matrix (`config: style:`), with the reorder control (↑ ↓)
// every ordered list of the tab shares. Every change is one edit sent to the
// worker, which patches the text, checks it and answers with the face; a
// refused edit leaves the face as it was and says why.

import { html } from "htm/preact";
import { useEffect, useState } from "preact/hooks";
import type { JSX, VNode } from "preact";
import { AddName, InlineName } from "./ui.ts";
import { newStyleEntry } from "./values.ts";
import type { OnEdit } from "./panels.ts";
import type {
  DefaultsInfo, DeviceInfo, FaceInfo, LayoutEntry, Path, Schemes, Styles, UnreadableDevice, Value,
} from "../src/studio/protocol.ts";

type InputEvent = JSX.TargetedEvent<HTMLInputElement>;
type SelectEvent = JSX.TargetedEvent<HTMLSelectElement>;
type KeyEvent = JSX.TargetedKeyboardEvent<HTMLInputElement>;

/** A Connect IQ application id: the UUID the schema asks for. */
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** A value as a text box shows it: an absent one as nothing. */
const shown = (value: Value | undefined): string => (value == null ? "" : String(value));

interface TextFieldProps {
  value: string;
  onCommit: (text: string) => void;
  label: string;
  placeholder?: string | undefined;
  mono?: boolean;
  width?: string;
  title?: string | undefined;
}

// A text input that commits on Enter or when it loses focus, when its text
// differs from the value it shows, and resets when that value changes
// underneath it. It reads the input's own value, not its state: a blur can
// arrive before the re-render that typing schedules.
function TextField({ value, onCommit, label, placeholder, mono = false, width, title }: TextFieldProps): VNode {
  const [text, setText] = useState<string>(value);
  useEffect(() => setText(value), [value]);
  const commit = (e: InputEvent) => { if (e.currentTarget.value !== value) onCommit(e.currentTarget.value); };
  return html`<input type="text" class=${mono ? "mono" : ""} value=${text} placeholder=${placeholder || ""} aria-label=${label}
    title=${title || ""} style=${width ? `width:${width}` : ""}
    onInput=${(e: InputEvent) => setText(e.currentTarget.value)} onBlur=${commit}
    onKeyDown=${(e: KeyEvent) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setText(value); }} />`;
}

export interface ReorderProps {
  /** The entry's position, from 0, among `count` siblings. */
  index: number;
  count: number;
  /** What moves, as the buttons name it ("move <what> up"). */
  what: string;
  onMove: (to: number) => void;
}

// ↑ ↓: move an entry one place among its siblings. The first cannot move
// up, nor the last down; each button names what it moves.
export function Reorder({ index, count, what, onMove }: ReorderProps): VNode {
  return html`<span class="reorder">
    <button class="reset" title="move up" aria-label=${`move ${what} up`} disabled=${index === 0} onClick=${() => onMove(index - 1)}>↑</button>
    <button class="reset" title="move down" aria-label=${`move ${what} down`} disabled=${index >= count - 1} onClick=${() => onMove(index + 1)}>↓</button>
  </span>`;
}

export interface FaceIdentityProps {
  face: FaceInfo;
  onEdit: OnEdit;
}

// `face:`: the name, the version and the id. The id is the app the watch
// knows the face as, so it is edited in place and only as a UUID.
export function FaceIdentity({ face, onEdit }: FaceIdentityProps): VNode {
  const set = (key: string, value: string) => onEdit({ op: "set", path: ["face", key], value });
  return html`<ul class="rows face-keys">
    <li>
      <span class="key">name</span>
      <${TextField} value=${shown(face.name)} label="face name" width="12em" title="the face's display name, on the watch and in the store"
        onCommit=${(t: string) => { if (t.trim()) set("name", t.trim()); }} />
    </li>
    <li class=${face.version == null ? "absent" : ""}>
      <span class="key">version</span>
      <${TextField} value=${shown(face.version)} label="face version" placeholder="1.0.0" width="6em" mono
        onCommit=${(t: string) => { if (t.trim()) set("version", t.trim()); else if (face.version != null) onEdit({ op: "remove", path: ["face", "version"] }); }} />
    </li>
    <li>
      <span class="key">id</span>
      <${TextField} value=${shown(face.id)} label="face id" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" width="22em" mono
        title="a UUID; a text that is not one is not written"
        onCommit=${(t: string) => { if (UUID.test(t.trim())) set("id", t.trim()); }} />
      <div class="note">The app's id on the watch: changing it makes the watch treat the face as a different app, kept beside the old one.</div>
    </li>
  </ul>`;
}

export interface TargetsSectionProps {
  targets: string[];
  /** A target the installed devices lack, with why. */
  problems: Record<string, string>;
  devices: DeviceInfo[];
  unreadable: UnreadableDevice[];
  onEdit: OnEdit;
}

// `build: targets:`, in the order the face lists them (the first is the
// watch the library's covers and the hand sets' thumbnails are drawn on):
// each with ↑ ↓ and ×, and a select adding any installed watch not yet a
// target, each change one list-item edit.
export function TargetsSection({ targets, problems, devices, unreadable, onEdit }: TargetsSectionProps): VNode {
  const path: Path = ["build", "targets"];
  const offered = devices.filter((d) => !targets.includes(d.id));
  return html`<ul class="rows">${targets.map((t, i) => html`<li key=${t}>
      <span>${devices.find((d) => d.id === t)?.name || t}</span> <code class="dim">${t}</code>
      ${problems[t] ? html`<span class="warn" title=${problems[t]}>⚠ not available here</span>` : null}
      <${Reorder} index=${i} count=${targets.length} what=${t} onMove=${(to: number) => onEdit({ op: "move_item", path, from: i, to })} />
      <button class="reset" title="remove this target" aria-label=${`remove ${t}`} onClick=${() => onEdit({ op: "remove_item", path, at: i })}>×</button>
    </li>`)}</ul>
    <div class="row">
      <select value="" aria-label="add a target" title="add an installed watch that can run a face" disabled=${!offered.length}
        onChange=${(e: SelectEvent) => { const id = e.currentTarget.value; e.currentTarget.value = ""; if (id) onEdit({ op: "insert_item", path, at: targets.length, value: id }); }}>
        <option value="">+ add target…</option>
        ${offered.map((d) => html`<option value=${d.id}>${d.name} (${d.size}, ${d.shape})</option>`)}
      </select>
    </div>
    ${unreadable.length ? html`<div class="note warn"
        title=${unreadable.map((d) => `${d.id}: ${d.reason}`).join("\n")}>
      ⚠ ${unreadable.length} installed watch${unreadable.length > 1 ? "es" : ""}
      could not be read, so ${unreadable.length > 1 ? "they are" : "it is"} not offered
      (${unreadable.map((d) => d.id).join(", ")})</div>` : null}`;
}

export interface DefaultsSectionProps {
  defaults: DefaultsInfo;
  onEdit: OnEdit;
}

/** One `defaults:` key: where it is written, how it is shown, and the schema's default an absent one shows. */
interface DefaultKey {
  path: Path;
  label: string;
  kind: "bool" | "dim";
  fallback: boolean | number;
  title: string;
}

const DEFAULT_KEYS: DefaultKey[] = [
  { path: ["defaults", "antialias"], label: "antialias", kind: "bool", fallback: false,
    title: "soften every edge the face draws, unless an element says otherwise; costs memory for a font and dithers a primitive's edge on a MIP screen" },
  { path: ["defaults", "min_1px"], label: "min_1px", kind: "bool", fallback: false,
    title: "a relative size that would round to nothing on a watch is drawn 1 px instead, unless an element says otherwise" },
  { path: ["defaults", "aod", "visible"], label: "aod.visible", kind: "bool", fallback: false,
    title: "whether an element with no aod: of its own is drawn in an AMOLED watch's always-on frame" },
  { path: ["defaults", "aod", "dim"], label: "aod.dim", kind: "dim", fallback: 1,
    title: "scale every colour in the always-on frame: 1 leaves them, 0.5 halves them; above 0, at most 1" },
  { path: ["defaults", "aod", "mask"], label: "aod.mask", kind: "bool", fallback: true,
    title: "the moving 2×2 pixel mask over the always-on frame, which keeps any one pixel lit at most one minute in four" },
];

/** The value `defaults:` holds for a key, as written, or `null` when absent. */
function written(defaults: DefaultsInfo, key: DefaultKey): Value {
  const last = String(key.path[key.path.length - 1]);
  return key.path[1] === "aod" ? defaults.aod[last as keyof DefaultsInfo["aod"]] : defaults[last as "antialias" | "min_1px"];
}

// `defaults:`: each key the face may set face-wide, present or not. An
// absent key is greyed and shows the schema's default in place of a value,
// with no × to remove; writing a value adds it (the block too, when the
// face has none), and choosing the default again, or ×, removes it.
export function DefaultsSection({ defaults, onEdit }: DefaultsSectionProps): VNode {
  return html`<ul class="rows defaults">${DEFAULT_KEYS.map((key) => {
    const value = written(defaults, key);
    const present = value !== null;
    const remove = () => onEdit({ op: "remove", path: key.path });
    const control = key.kind === "bool"
      ? html`<select value=${present ? String(value) : ""} aria-label=${key.label} title=${key.title}
          onChange=${(e: SelectEvent) => { const v = e.currentTarget.value; if (v === "") { if (present) remove(); } else onEdit({ op: "set", path: key.path, value: v === "true" }); }}>
          <option value="">default (${String(key.fallback)})</option>
          <option value="true">true</option><option value="false">false</option></select>`
      : html`<${TextField} value=${shown(value)} label=${key.label} placeholder=${String(key.fallback)} width="5em" title=${key.title}
          onCommit=${(t: string) => {
            if (t.trim() === "") { if (present) remove(); return; }
            const n = Number(t);
            if (Number.isFinite(n) && n > 0 && n <= 1) onEdit({ op: "set", path: key.path, value: n });
          }} />`;
    return html`<li key=${key.label} class=${present ? "" : "absent"}>
      <span class="key" title=${key.title}>${key.label}</span>
      ${control}
      ${present ? html`<button class="reset" title="remove the key (back to the default)" aria-label=${`remove ${key.label}`} onClick=${remove}>×</button>` : null}
    </li>`;
  })}</ul>
  <div class="note">What every element inherits unless it, or a group around it, says otherwise; <code>aod</code> is the always-on frame of an AMOLED watch.</div>`;
}

const plural = (n: number, noun: string): string => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** The layout name a new one takes: `layout`, then `layout2`, …, the first not in use. */
export function suggestLayoutName(layouts: readonly string[]): string {
  let n = "layout", i = 2;
  while (layouts.includes(n)) n = `layout${i++}`;
  return n;
}

export interface LayoutsSectionProps {
  entries: LayoutEntry[];
  styles: Styles;
  onEdit: OnEdit;
}

// `layouts:`, one row each: its name (edited in place; every style's
// `layout:` follows), its `label:` (the editor's own name for it), how many
// elements its two blocks hold, the styles
// picking it, ↑ ↓ and ×. A delete takes the styles picking the layout with
// it; when the worker refuses it because the default style is one of them,
// the row offers the styles that stay, and the delete is sent again naming
// the one to start in instead.
export function LayoutsSection({ entries, styles, onEdit }: LayoutsSectionProps): VNode {
  // the layout whose delete was refused for its default style, awaiting the style to start in
  const [moving, setMoving] = useState<string | null>(null);
  useEffect(() => { if (moving !== null && !entries.some((l) => l.name === moving)) setMoving(null); }, [entries]);
  const remove = async (layout: LayoutEntry) => {
    const answer = await onEdit({ op: "delete_layout", name: layout.name });
    const kept = styles.entries.filter((s) => !layout.styles.includes(s.name));
    if (answer === null && styles.default !== null && layout.styles.includes(styles.default) && kept.length > 0) setMoving(layout.name);
  };
  return html`${entries.length ? html`<ul class="rows">${entries.map((l, i) => {
    const kept = styles.entries.filter((s) => !l.styles.includes(s.name));
    return html`<li key=${l.name} class="layout">
      <${InlineName} value=${l.name} title="click to rename (every style naming it follows)"
        onRename=${(n: string) => onEdit({ op: "rename_layout", name: l.name, to: n })} />
      <${TextField} value=${l.label ?? ""} label=${`label of ${l.name}`} placeholder="label" width="8em"
        title="the layout's name in the editor (the Styles matrix and this list); nothing on the watch reads it"
        onCommit=${(t: string) => {
          if (t.trim()) onEdit({ op: "set", path: ["layouts", l.name, "label"], value: t.trim() });
          else if (l.label != null) onEdit({ op: "remove", path: ["layouts", l.name, "label"] });
        }} />
      <span class="dim counts">${plural(l.elements, "element")} · ${l.static} static</span>
      <span class=${"picked-by" + (l.styles.length ? "" : " warn")} title=${l.styles.length ? "the config: style: entries whose layout: names it" : "no style picks it, so the wearer cannot reach it"}>${l.styles.length ? `${l.styles.length === 1 ? "style" : "styles"} ${l.styles.join(", ")}` : "⚠ no style picks it"}</span>
      <${Reorder} index=${i} count=${entries.length} what=${l.name} onMove=${(to: number) => onEdit({ op: "move_key", path: ["layouts", l.name], to })} />
      <button class="reset" title="delete this layout, with the styles that pick it" aria-label=${`delete ${l.name}`} onClick=${() => { void remove(l); }}>×</button>
      ${moving === l.name ? html`<div class="note start-in">the default style ${styles.default} picks it; start in
        <select value="" aria-label="style to start in instead" onChange=${(e: SelectEvent) => {
          const to = e.currentTarget.value;
          if (!to) return;
          setMoving(null);
          onEdit({ op: "delete_layout", name: l.name, also_default: to });
        }}>
          <option value="">a style that stays…</option>
          ${kept.map((s) => html`<option value=${s.name}>${s.name}</option>`)}
        </select> instead</div>` : null}
    </li>`; })}</ul>`
    : html`<div class="dim note">A layout is a named set of elements the wearer switches to through a style; this face has none yet.</div>`}
    <${AddName} label="+ Layout" placeholder="layout name" suggest=${() => suggestLayoutName(entries.map((l) => l.name))}
      onAdd=${(n: string) => onEdit({ op: "add_layout", name: n })} />`;
}

export interface StylesMatrixProps {
  styles: Styles;
  layouts: string[];
  /** Each layout's `label:`, which names it in the layout select. */
  labels?: Record<string, string | null> | undefined;
  schemes: Schemes;
  onEdit: OnEdit;
}

// `config: style:` as a table, one row per entry in the order the wearer's
// Style list shows: the layout and scheme it picks, the label the wearer
// sees, the radio for the one the face opens in, ↑ ↓ and ×. Below it, a new
// style shaped like the others, and a new layout.
export function StylesMatrix({ styles, layouts, labels = {}, schemes, onEdit }: StylesMatrixProps): VNode {
  const entries = [...styles.entries].sort((a, b) => a.index - b.index);
  const choices: Path = ["config", "style", "choices"];
  const pick = (name: string, key: "layout" | "scheme", value: string) =>
    onEdit(value ? { op: "set", path: [...choices, name, key], value } : { op: "remove", path: [...choices, name, key] });
  const hasAxes = layouts.length > 0 || schemes.names.length > 0;
  return html`${entries.length ? html`<table class="styles-matrix">
      <tr><th>style</th><th>layout</th><th>colour scheme</th><th>label the wearer sees</th><th title="the one style the face opens in; the wearer's own pick, where the watch has a picker, starts here too">opens in</th><th></th></tr>
      ${entries.map((e, i) => html`<tr key=${e.name}>
        <td><code>${e.name}</code></td>
        <td>${layouts.length ? html`<select value=${e.layout || ""} aria-label=${`layout of ${e.name}`} onChange=${(ev: SelectEvent) => pick(e.name, "layout", ev.currentTarget.value)}>
            <option value="">no layout</option>${layouts.map((l) => html`<option value=${l}>${labels[l] ? `${labels[l]} (${l})` : l}</option>`)}</select>`
          : html`<span class="dim">—</span>`}</td>
        <td>${schemes.names.length ? html`<select value=${e.scheme || ""} aria-label=${`scheme of ${e.name}`} onChange=${(ev: SelectEvent) => pick(e.name, "scheme", ev.currentTarget.value)}>
            <option value="">no scheme</option>${schemes.names.map((s) => html`<option value=${s}>${s}</option>`)}</select>`
          : html`<span class="dim">—</span>`}</td>
        <td><${TextField} value=${e.label || ""} label=${`label of ${e.name}`} placeholder="label" width="8em"
          onCommit=${(t: string) => onEdit(t.trim() ? { op: "set", path: [...choices, e.name, "label"], value: t.trim() }
                                                     : { op: "remove", path: [...choices, e.name, "label"] })} /></td>
        <td><input type="radio" name="default-style" aria-label=${`open in ${e.name}`} checked=${styles.default === e.name}
          title="the one style the face opens in" onChange=${() => onEdit({ op: "set_default_style", name: e.name })} /></td>
        <td class="actions">
          <${Reorder} index=${i} count=${entries.length} what=${`style ${e.name}`} onMove=${(to: number) => onEdit({ op: "move_key", path: [...choices, e.name], to })} />
          <button class="reset" title="delete this style" aria-label=${`delete style ${e.name}`} onClick=${() => onEdit({ op: "remove", path: [...choices, e.name] })}>×</button>
        </td>
      </tr>`)}
    </table>` : html`<div class="dim">${hasAxes ? "No styles yet." : "Styles pair a layout with a colour scheme; this face has neither yet."}</div>`}
    <div class="row">
      ${hasAxes ? html`<${AddName} label="+ Style" placeholder="style name"
        onAdd=${(n: string) => {
          const entry = newStyleEntry(entries, layouts, schemes.names);
          onEdit(entries.length
            ? { op: "set", path: [...choices, n], value: entry }
            : { op: "set", path: ["config", "style"], value: { default: n, choices: { [n]: entry } } });
        }} />` : null}
      <${AddName} label="+ Layout" placeholder="layout name" suggest=${() => suggestLayoutName(layouts)}
        onAdd=${(n: string) => onEdit({ op: "add_layout", name: n })} />
    </div>`;
}
