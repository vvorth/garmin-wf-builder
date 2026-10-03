// The inspector (the selected element's keys) and the Face panel (targets,
// colours, schemes, styles, slots, fonts). Every change is one edit sent to the
// server, which patches the text, checks it and answers with the face;
// a refused edit leaves the face as it was and says why.

import { html, useState, useEffect, useRef } from "./vendor/preact-htm.module.js";
import {
  ANGLE_UNITS, LENGTH_UNITS, afterRemovingSchemes, at, colorName, formatQuantity, isIdentifier,
  newStyleEntry, parseHex, parseQuantity, safeOn, swatchFor, toHex,
} from "./values.js";

const ALIGN = [["top_left", "top", "top_right"], ["left", "center", "right"],
               ["bottom_left", "bottom", "bottom_right"]];

// A text input that commits on Enter or when it loses focus, and resets
// when the value it shows changes underneath it.
function Commit({ value, onCommit, placeholder, mono, list, width }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  // The input's own value, not the state: a blur can arrive before the
  // re-render that typing schedules.
  const commit = (e) => { if (e.target.value !== (value ?? "")) onCommit(e.target.value); };
  return html`<input type="text" class=${mono ? "mono" : ""} value=${text} placeholder=${placeholder || ""}
    list=${list} style=${width ? `width:${width}` : ""}
    onInput=${(e) => setText(e.target.value)} onBlur=${commit}
    onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setText(value ?? ""); }} />`;
}

// A number and its unit. An absent value starts in the unit of ``like`` (the
// value an override would replace), so an override is written in the
// author's own unit.
function Quantity({ value, units, bareUnit, onCommit, placeholder, like }) {
  const q = parseQuantity(value, bareUnit);
  const l = parseQuantity(like, bareUnit);
  const initial = q ? q.unit : l && units.includes(l.unit) ? l.unit : units[0];
  const [unit, setUnit] = useState(initial);
  useEffect(() => setUnit(initial), [value, like]);
  const send = (numberText, u) => {
    if (numberText === "") return;
    const out = formatQuantity(Number(numberText), u, bareUnit, q ? q.bare : false);
    if (out !== null) onCommit(out);
  };
  if (value != null && !q) {
    return html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`;
  }
  return html`<span class="qty">
    <${Commit} value=${q ? String(q.number) : ""} placeholder=${placeholder ?? (l ? String(l.number) : "")} width="5em"
      onCommit=${(t) => send(t, unit)} />
    <select value=${unit} onChange=${(e) => { setUnit(e.target.value); if (q) send(String(q.number), e.target.value); }}>
      ${units.map((u) => html`<option value=${u}>${u}</option>`)}
    </select>
  </span>`;
}

function AlignPicker({ value, onCommit }) {
  return html`<span class="align">
    ${ALIGN.map((row) => html`<span class="align-row">${row.map((a) => html`
      <button class=${value === a ? "on" : ""} title=${a} onClick=${() => onCommit(a)}></button>`)}</span>`)}
  </span>`;
}

// The colour picker: a chip that opens three groups, the face's own colours
// (its swatches, then its roles where a role is allowed), the 64 named MIP
// colours, and a custom colour. A swatch or role is picked as
// `color.<name>`; one of the 64 or a custom colour as its hex, which the
// server turns into the swatch holding it (`wfb.edit.colors`).
export function ColorPop({ value, ctx, roles = true, faceGroup = true, title, label, onPick }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const box = useRef(null);
  const palette = ctx.globals.palette || [];
  const mip = ctx.vocab.mip || [];
  const displays = ctx.globals.displays || [];
  const ref = colorName(value);
  const swatch = ref && palette.find((p) => p.name === ref);
  const shown = parseHex(value) || (swatch && parseHex(swatch.value));
  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("mousedown", away);
    addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", away); removeEventListener("keydown", esc); };
  }, [open]);
  const pick = (v) => { setOpen(false); setCustom(""); onPick(v); };
  const customRgb = parseHex(custom) || shown || [255, 255, 255];
  const target = swatchFor(customRgb, palette, mip);
  const safe = safeOn(customRgb, displays);
  const warn = shown && !safeOn(shown, displays).ok;
  return html`<span class="color pop-anchor" ref=${box}>
    <button class="chip-button" title=${title || "pick a colour"} onClick=${() => setOpen(!open)}>
      ${label ? null : html`<span class="chip" style=${shown ? `background:${toHex(shown)}` : ""}></span>`}
      <span class=${ref || label ? "" : "dim"}>${label || ref || (shown ? toHex(shown) : "—")}</span>
    </button>
    ${warn ? html`<span class="warn" title=${`dithers on this face's ${displays.join("/")}-colour screens`}>⚠</span>` : null}
    ${open ? html`<div class="pop">
      ${faceGroup ? html`<div class="pop-group">
        <div class="pop-title">This face</div>
        <div class="pop-swatches">${palette.map((p) => { const v = parseHex(p.value); return html`
          <button class=${"swatch" + (ref === p.name ? " on" : "")} title=${`${p.name} ${p.value}`}
            style=${v ? `background:${toHex(v)}` : ""} onClick=${() => pick(`color.${p.name}`)}></button>`; })}</div>
        ${roles && (ctx.globals.roles || []).length ? html`<div class="pop-roles">${ctx.globals.roles.map((r) => html`
          <button class=${ref === r ? "on" : ""} title="a role: follows the wearer's style or pick" onClick=${() => pick(`color.${r}`)}>${r}</button>`)}</div>` : null}
      </div>` : null}
      <div class="pop-group">
        <div class="pop-title">MIP 64</div>
        <div class="pop-grid">${mip.map((m) => {
          const held = palette.find((p) => { const v = parseHex(p.value); return v && toHex(v) === m.value; });
          return html`<button class=${"swatch" + (held ? " held" : "")} style=${`background:${m.value}`}
            title=${`${m.label} ${m.value}${held ? ` (this face: ${held.name})` : ""}`} onClick=${() => pick(m.value)}></button>`; })}</div>
      </div>
      <div class="pop-group">
        <div class="pop-title">Custom</div>
        <div class="pop-custom">
          <input type="color" value=${toHex(customRgb)} onInput=${(e) => setCustom(e.target.value.toUpperCase())} />
          <input type="text" class="mono" value=${custom || toHex(customRgb)} style="width:6.5em"
            onInput=${(e) => setCustom(e.target.value)}
            onKeyDown=${(e) => { if (e.key === "Enter" && parseHex(custom)) pick(toHex(parseHex(custom))); }} />
          <button class="primary" disabled=${!parseHex(custom)} onClick=${() => pick(toHex(customRgb))}>Use</button>
        </div>
        ${parseHex(custom) ? html`<div class="note">${target.adds ? `adds ${target.name}` : `uses ${target.name}`}
          ${!safe.ok ? html` · <span class="warn">⚠ dithers</span> <a href="#" onClick=${(e) => { e.preventDefault(); setCustom(toHex(safe.nearest)); }}>nearest ${toHex(safe.nearest)}</a>` : null}</div>` : null}
      </div>
    </div>` : null}
  </span>`;
}

function Template({ value, sources, onCommit }) {
  const input = useRef(null);
  const insert = (path) => {
    if (!path) return;
    const el = input.current;
    const text = el ? el.value : (value || "");
    const at = el && el.selectionStart != null ? el.selectionStart : text.length;
    onCommit(text.slice(0, at) + `{${path}}` + text.slice(at));
  };
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  return html`<span class="template">
    <input type="text" class="mono" ref=${input} value=${text} onInput=${(e) => setText(e.target.value)}
      onBlur=${(e) => { if (e.target.value !== (value ?? "")) onCommit(e.target.value); }}
      onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); }} />
    <select value="" onChange=${(e) => { insert(e.target.value); e.target.value = ""; }} title="Insert a data placeholder">
      <option value="">+ data</option>
      ${Object.entries(sources).map(([ns, paths]) => html`<optgroup label=${ns}>
        ${paths.map((p) => html`<option value=${p}>${p}</option>`)}</optgroup>`)}
    </select>
  </span>`;
}

function Widget({ field, value, ctx, onCommit, onPickColor, like }) {
  const enumSelect = (options, extra) => html`<select value=${value ?? ""} onChange=${(e) => e.target.value !== "" && onCommit(e.target.value)}>
    <option value="">${field.default != null ? `default (${field.default})` : "—"}</option>
    ${(extra || []).map((o) => html`<option value=${o}>${o}</option>`)}
    ${options.map((o) => html`<option value=${o}>${o}</option>`)}
  </select>`;
  switch (field.widget) {
    case "readonly": return html`<code>${String(value)}</code>`;
    case "length": return html`<${Quantity} value=${value} like=${like} units=${LENGTH_UNITS} bareUnit="px" onCommit=${onCommit} />`;
    case "angle": return html`<${Quantity} value=${value} like=${like} units=${ANGLE_UNITS} bareUnit="deg" onCommit=${onCommit} />`;
    case "align": return html`<${AlignPicker} value=${value} onCommit=${onCommit} />`;
    case "color":
      // an expression choosing a colour is edited as text
      return value != null && !colorName(value) && !parseHex(value)
        ? html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`
        : html`<${ColorPop} value=${value} ctx=${ctx} onPick=${onPickColor} />`;
    case "template": return html`<${Template} value=${value} sources=${ctx.vocab.sources || {}} onCommit=${onCommit} />`;
    case "font": return enumSelect(ctx.systemFonts, (ctx.globals.fonts || []).map((f) => `font.${f.name}`));
    case "icon": return html`<${Commit} value=${value} list="wfb-icons" onCommit=${onCommit} />`;
    case "complication": return enumSelect(ctx.vocab.complications || []);
    case "slot": return enumSelect((ctx.globals.slots || []).map((s) => s.name));
    case "handset": {
      const set = (ctx.globals.hands || []).find((h) => h.name === value);
      return html`<span class="handset">${enumSelect(ctx.globals.hand_sets || [])}
        ${set && ctx.onReveal ? html`<a href="#" title="its hands' parts, in the YAML tab"
          onClick=${(e) => { e.preventDefault(); ctx.onReveal(set.line, set.end); }}>edit the set</a>` : null}</span>`;
    }
    case "enum": return enumSelect(field.enum.map(String));
    case "bool": return html`<select value=${value == null ? "" : String(value)}
        onChange=${(e) => e.target.value !== "" && onCommit(e.target.value === "true")}>
      <option value="">${field.default != null ? `default (${field.default})` : "—"}</option>
      <option value="true">true</option><option value="false">false</option></select>`;
    case "number": return html`<${Commit} value=${value == null ? "" : String(value)} width="6em"
        onCommit=${(t) => t.trim() !== "" && !Number.isNaN(Number(t)) && onCommit(Number(t))} />`;
    case "expression":
    case "text": return html`<${Commit} value=${value == null ? "" : String(value)} mono=${field.widget === "expression"} onCommit=${onCommit} />`;
    default:
      return value == null ? html`<span class="dim">in the YAML</span>`
        : html`<code class="yaml" title="edit this in the YAML">${field.text ?? JSON.stringify(value)}</code>`;
  }
}

function Field({ field, ins, scope, ctx, onEdit, depth = 0 }) {
  const overridden = field.geometry && scope !== "all";
  const override = overridden ? at(ins.overrides[scope] && ins.overrides[scope].keys, field.path) : undefined;
  const value = overridden ? override : field.value;
  const base = { element: ins.element, path: field.path, scope, device: ins.device };
  if (field.widget === "object") {
    return html`<div class="field object" style=${`--depth:${depth}`}>
      <div class="name" title=${field.description}>${field.key}</div>
      <div class="children">
        ${field.children.map((c) => html`<${Field} field=${c} ins=${ins} scope=${scope} ctx=${ctx} onEdit=${onEdit} depth=${depth + 1} />`)}
      </div>
    </div>`;
  }
  const local = ["device", "shape"].map((s) => ins.overrides[s] && at(ins.overrides[s].keys, field.path) !== undefined ? s : null).filter(Boolean);
  return html`<div class=${"field" + (value == null ? " absent" : "")}>
    <div class="name" title=${field.description}>${field.key}${field.required ? html`<span class="req">*</span>` : null}</div>
    <div class="value">
      <${Widget} field=${field} value=${value} ctx=${ctx} like=${overridden ? field.value : undefined}
        onCommit=${(v) => onEdit({ op: "set", ...base, value: v })}
        onPickColor=${(v) => onEdit({ op: "use_color", ...base, scope: "all", value: v })} />
      ${value != null && !field.required && field.widget !== "readonly"
        ? html`<button class="reset" title=${overridden ? "remove the override" : "remove the key (back to the default)"}
            onClick=${() => onEdit({ op: "remove", ...base })}>×</button>` : null}
      ${overridden && value == null && field.value != null ? html`<div class="note">inherits ${JSON.stringify(field.value)}</div>` : null}
      ${!overridden && local.length ? html`<div class="note">overridden on this ${local.join(" and ")}</div>` : null}
    </div>
  </div>`;
}

export function Inspector({ doc, element, device, vocab, scope, onScope, onEdit, onError, onReveal }) {
  const [ins, setIns] = useState(null);
  const setScope = onScope;
  useEffect(() => {
    if (!element) { setIns(null); return; }
    let live = true;
    const q = new URLSearchParams({ element: JSON.stringify(element.path), device: device || "" });
    fetch(`/api/documents/${doc.id}/inspect?${q}`).then((r) => r.json()).then(
      (data) => { if (live) setIns(data); }, onError);
    return () => { live = false; };
  }, [doc.id, doc.version, element && element.path.join("."), device]);
  if (!element) return html`<div class="body dim">Select an element on the face or in the layers.</div>`;
  if (!ins || !ins.fields) return html`<div class="body dim">…</div>`;
  const deviceInfo = (vocab.devices || []).find((d) => d.id === device);
  const ctx = { globals: doc.globals || {}, vocab, systemFonts: deviceInfo ? deviceInfo.fonts : [], onReveal };
  return html`<div class="inspector">
    <div class="ins-head">
      <code>${ins.id}</code> <span class="dim">${ins.type}</span>
      <div class="scope" title="Where at:, size:, radius: and align: edits and drags are written; with all targets, a drag goes where the viewed device reads the key">
        ${[["all", "all targets"], ["device", ins.device], ["shape", ins.shape]].map(([s, label]) => html`
          <button class=${scope === s ? "on" : ""} onClick=${() => setScope(s)}>${label}</button>`)}
      </div>
    </div>
    ${ins.unknown.length ? html`<div class="note error-text">Not in the format: ${ins.unknown.join(", ")}</div>` : null}
    ${ins.fields.map((f) => html`<${Field} field=${f} ins=${ins} scope=${scope} ctx=${ctx} onEdit=${onEdit} />`)}
    <datalist id="wfb-icons">${(vocab.icons || []).map((i) => html`<option value=${i} />`)}</datalist>
  </div>`;
}

// -- the Face panel ------------------------------------------------------------------

function Section({ title, children, open = true }) {
  const [shown, setShown] = useState(open);
  return html`<div class="section">
    <div class="section-head" onClick=${() => setShown(!shown)}>${shown ? "▾" : "▸"} ${title}</div>
    ${shown ? html`<div class="section-body">${children}</div>` : null}
  </div>`;
}

function askName(what, current) {
  const name = prompt(`${what} name (letters, digits and _):`, current || "");
  if (name == null) return null;
  if (!isIdentifier(name.trim())) { alert(`"${name}" is not a valid name.`); return null; }
  return name.trim();
}

// One `config: slots:` entry: its menu label, its default, and the
// wearer's choices -- the editor's whole picker (`any`) or a list, each
// type with its own icon -- and the elements that draw it.
function SlotRow({ slot, types, onEdit, onSelect, onStructure }) {
  const path = ["config", "slots", slot.name];
  const list = Array.isArray(slot.choices) ? slot.choices : null;
  const [adding, setAdding] = useState("");
  // a choice is written bare unless it carries an icon
  const written = (c) => (c.icon ? { type: c.type, icon: c.icon } : c.type);
  const setChoices = (choices) => onEdit({ op: "set", path: [...path, "choices"], value: choices.map(written) });
  const defaults = list ? list.map((c) => c.type) : types;
  return html`<li class="slot">
    <div class="slot-head">
      <span class="name" title="rename (every slot: naming it follows)" onClick=${() => {
        const n = askName("Slot", slot.name);
        if (n && n !== slot.name) onEdit({ op: "rename", path, to: n });
      }}>${slot.name}</span>
      <${Commit} value=${slot.label || ""} placeholder="menu label" width="9em"
        onCommit=${(v) => onEdit(v.trim() ? { op: "set", path: [...path, "label"], value: v.trim() }
                                           : { op: "remove", path: [...path, "label"] })} />
      <button class="reset" title="delete (refused while an element draws it)"
        onClick=${() => onEdit({ op: "remove", path })}>×</button>
    </div>
    <div class="slot-line">
      <span class="dim">default</span>
      <select value=${slot.default || ""} title="what the slot shows until the wearer picks"
        onChange=${(e) => onEdit({ op: "set", path: [...path, "default"], value: e.target.value })}>
        ${defaults.map((t) => html`<option value=${t}>${t}</option>`)}
      </select>
    </div>
    <div class="slot-line">
      <span class="dim">choices</span>
      <label title="the watch's own picker: every complication"><input type="radio" checked=${!list}
        onChange=${() => onEdit({ op: "set", path: [...path, "choices"], value: "any" })} /> any</label>
      <label title="only the types listed here"><input type="radio" checked=${!!list}
        onChange=${() => onEdit({ op: "set", path: [...path, "choices"], value: [slot.default || types[0]] })} /> a list</label>
    </div>
    ${list ? html`<ul class="choices">
      ${list.map((c, i) => html`<li>
        <code>${c.type}</code>
        <${Commit} value=${c.icon || ""} placeholder="its icon" list="wfb-slot-icons" width="8em"
          onCommit=${(v) => setChoices(list.map((x, j) => (j === i ? { ...x, icon: v.trim() || null } : x)))} />
        <button class="reset" disabled=${c.type === slot.default}
          title=${c.type === slot.default ? "the default; pick another default first" : "remove this choice"}
          onClick=${() => setChoices(list.filter((_, j) => j !== i))}>×</button>
      </li>`)}
      <li><select value=${adding} onChange=${(e) => setAdding(e.target.value)}>
          <option value="">add a type…</option>
          ${types.filter((t) => !list.some((c) => c.type === t)).map((t) => html`<option value=${t}>${t}</option>`)}
        </select>
        <button disabled=${!adding} onClick=${() => { setChoices([...list, { type: adding, icon: null }]); setAdding(""); }}>Add</button></li>
    </ul>` : null}
    <div class="slot-line">
      <span class="dim">drawn by</span>
      ${slot.drawn_by.length
        ? slot.drawn_by.map((id) => html`<a href="#" onClick=${(e) => { e.preventDefault(); onSelect(id); }}>${id}</a>`)
        : html`<span class="dim">nothing</span>
               <button title="add a data element drawing this slot, at the end of elements:"
                 onClick=${() => onStructure({ op: "add", type: "data", block: ["elements"], before: null, choice: slot.name })}>+ data element</button>`}
    </div>
  </li>`;
}

// `theme: schemes:`: with none, which colours should follow the wearer's
// style; with some, the roles × schemes table. Every change is one of the
// compound edits of `wfb.edit.schemes`, so it never leaves the schemes out
// of step.
function Schemes({ schemes, palette, styles, ctx, onEdit }) {
  const [picked, setPicked] = useState([]);
  const [keep, setKeep] = useState("");
  if (!schemes.names.length) {
    const toggle = (n) => setPicked(picked.includes(n) ? picked.filter((x) => x !== n) : [...picked, n]);
    return html`<div class="dim note">Colours in a scheme follow the style the wearer picks. Tick the
        colours that should change with it; they keep their names.</div>
      <div class="axis-choices">${palette.map((p) => { const v = parseHex(p.value); return html`<label>
        <input type="checkbox" checked=${picked.includes(p.name)} onChange=${() => toggle(p.name)} />
        <span class="chip" style=${v ? `background:${toHex(v)}` : ""}></span>${p.name}</label>`; })}</div>
      <button disabled=${!picked.length} onClick=${() => {
        const n = askName("First scheme", "dark"); if (!n) return;
        onEdit({ op: "make_switchable", names: picked, scheme: n }); setPicked([]);
      }}>Make switchable…</button>`;
  }
  const keepName = keep || schemes.names[0];
  const outcome = afterRemovingSchemes(styles.entries);
  return html`<table class="schemes">
      <tr><th></th>${schemes.names.map((s) => html`<th>
        <span class="name" title="rename (every style naming it follows)" onClick=${() => {
          const n = askName("Scheme", s); if (n && n !== s) onEdit({ op: "rename_scheme", name: s, to: n }); }}>${s}</span>
        <button class="reset" title="delete this scheme and the styles that pick it" onClick=${() => onEdit({ op: "delete_scheme", name: s })}>×</button>
      </th>`)}</tr>
      ${schemes.roles.map((r) => html`<tr><td>
        <span class="name" title=${`rename (every color.${r} follows)`} onClick=${() => {
          const n = askName("Role", r); if (n && n !== r) onEdit({ op: "rename_role", name: r, to: n }); }}>${r}</span>
        <button class="reset" title="delete this role (refused while something uses it)" onClick=${() => onEdit({ op: "delete_role", name: r })}>×</button>
      </td>${schemes.names.map((s) => html`<td>
        <${ColorPop} value=${(schemes.colors[s] || {})[r]} ctx=${ctx} roles=${false}
          onPick=${(v) => onEdit({ op: "use_color", path: ["theme", "schemes", s, "colors", r], value: v })} /></td>`)}</tr>`)}
    </table>
    <div class="row">
      <button title="a copy of the first scheme, and the styles that reach it" onClick=${() => {
        const n = askName("New scheme"); if (n) onEdit({ op: "add_scheme", name: n }); }}>+ Scheme</button>
      <button title="a role in every scheme, white until you set it" onClick=${() => {
        const n = askName("New role"); if (n) onEdit({ op: "add_role", name: n, value: "#FFFFFF" }); }}>+ Role</button>
    </div>
    <div class="row">
      <select value=${keepName} title="the scheme whose colours become palette colours" onChange=${(e) => setKeep(e.target.value)}>
        ${schemes.names.map((s) => html`<option value=${s}>keep ${s}</option>`)}
      </select>
      <button onClick=${() => {
        const parts = [`Every role becomes a palette colour with ${keepName}'s value.`];
        if (outcome.removed) parts.push(`${outcome.removed} style${outcome.removed > 1 ? "s" : ""} naming only a scheme will go.`);
        if (outcome.duplicates) parts.push(`${outcome.duplicates} style${outcome.duplicates > 1 ? "s" : ""} will look like another one; Diagnostics will name them.`);
        if (confirm(parts.join("\n"))) onEdit({ op: "remove_theme", keep: keepName });
      }}>Remove schemes…</button>
    </div>`;
}

const AXES = {
  accent_color: { title: "Accent colour", role: "accent" },
  data_color: { title: "Data colour", role: "data" },
};

// One `config:` colour axis: what the wearer may pick, always written as an
// explicit list of the face's swatches, so adding a colour to the palette
// never changes what the wearer is offered. `choices: any` is shown, not
// edited.
function AxisRow({ axis, entry, palette, onEdit }) {
  const meta = AXES[axis];
  const path = ["config", axis];
  const legal = palette.filter((p) => !p.dithers_on.length);
  if (!entry) {
    return html`<div class="axis"><span class="dim">${meta.title}: none</span>
      <button disabled=${!legal.length} title=${`the wearer picks color.${meta.role} from a list you choose`}
        onClick=${() => onEdit({ op: "set", path, value: { default: `color.${legal[0].name}`, choices: [`color.${legal[0].name}`] } })}>+ ${meta.title}</button></div>`;
  }
  const list = Array.isArray(entry.raw) ? entry.raw : null;
  const listed = (name) => list && list.includes(`color.${name}`);
  const toggle = (name) => onEdit({ op: "set", path: [...path, "choices"],
    value: listed(name) ? list.filter((c) => c !== `color.${name}`) : [...list, `color.${name}`] });
  const other = list ? list.filter((c) => typeof c !== "string" || !colorName(c)) : [];
  return html`<div class="axis">
    <div class="axis-head"><b>${meta.title}</b> <span class="dim">binds</span>
      <${Commit} value=${entry.role} width="7em" placeholder=${meta.role}
        onCommit=${(v) => onEdit(v.trim() && v.trim() !== meta.role ? { op: "set", path: [...path, "role"], value: v.trim() }
                                                                   : { op: "remove", path: [...path, "role"] })} />
      <button class="reset" title="remove this setting" onClick=${() => onEdit({ op: "remove", path })}>×</button></div>
    <div class="slot-line"><span class="dim">default</span>
      <select value=${entry.default || ""} onChange=${(e) => onEdit({ op: "set", path: [...path, "default"], value: e.target.value })}>
        ${(list ? list.filter((c) => typeof c === "string") : palette.map((p) => `color.${p.name}`)).map((c) => html`<option value=${c}>${colorName(c) || c}</option>`)}
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

// `resources: hand_sets:`: each set drawn alone, its hands' colours, what
// places it, and its parts in the YAML; new ones from a preset.
function HandSets({ doc, ctx, onEdit, onSelect, onReveal }) {
  const sets = ctx.globals.hands || [];
  const presets = ctx.vocab.hand_presets || [];
  const [preset, setPreset] = useState("");
  const device = (doc.targets || [])[0] || "";
  const add = () => {
    const taken = new Set(sets.map((s) => s.name));
    const name = askName("Hand set", taken.has(preset) ? `${preset}_2` : preset);
    if (name) onEdit({ op: "add_hand_set", name, preset });
    setPreset("");
  };
  return html`${sets.length ? html`<ul class="rows">${sets.map((s) => html`<li class="hand-set">
      <img class="hand-thumb" alt=${s.name} title="drawn alone at 10:09:42"
        src=${`/api/documents/${doc.id}/handset?${new URLSearchParams({ name: s.name, device, scale: 1, v: doc.version })}`} />
      <div class="hand-body">
        <div class="slot-head">
          <span class="name" title="rename (every set: naming it follows)" onClick=${() => {
            const n = askName("Hand set", s.name); if (n && n !== s.name) onEdit({ op: "rename_hand_set", name: s.name, to: n }); }}>${s.name}</span>
          <button title="a copy, to change without touching this one" onClick=${() => onEdit({ op: "duplicate_hand_set", name: s.name })}>Duplicate</button>
          <button class="reset" title="delete (refused while an element places it)" onClick=${() => onEdit({ op: "delete_hand_set", name: s.name })}>×</button>
        </div>
        ${Object.entries(s.hands).map(([hand, h]) => html`<div class="slot-line">
          <span class="dim">${hand}</span>
          <${ColorPop} value=${h.color} ctx=${ctx} title=${`the ${hand} hand's colour (a part may set its own)`}
            onPick=${(v) => onEdit({ op: "use_color", path: ["resources", "hand_sets", s.name, hand, "color"], value: v })} />
          <span class="dim">${h.parts} part${h.parts === 1 ? "" : "s"}</span></div>`)}
        <div class="slot-line"><span class="dim">placed by</span>
          ${s.placed_by.length ? s.placed_by.map((id) => html`<a href="#" onClick=${(e) => { e.preventDefault(); onSelect(id); }}>${id}</a>`)
                               : html`<span class="dim">nothing</span>`}</div>
        <div class="slot-line"><a href="#" title="a hand's parts are edited in the YAML" onClick=${(e) => { e.preventDefault(); onReveal(s.line, s.end); }}>Edit in YAML</a></div>
      </div>
    </li>`)}</ul>`
    : html`<div class="dim note">A hand set is the shape of an analog dial's hands, drawn pointing at 12;
        a <code>hands</code> element places it on the face and turns it with the time. Its parts are
        edited in the YAML.</div>`}
    <div class="row">
      <select value=${preset} onChange=${(e) => setPreset(e.target.value)}>
        <option value="">from a preset…</option>
        ${presets.map((p) => html`<option value=${p}>${p}</option>`)}
      </select>
      <button disabled=${!preset} title=${sets.some((s) => s.placed_by.length) ? "" : "also places it at the centre"} onClick=${add}>+ Hand set</button>
    </div>`;
}

export function FacePanel({ doc, vocab, onEdit, onUpload, onSelect, onStructure, onReveal }) {
  const g = doc.globals || {};
  const palette = g.palette || [];
  const schemes = g.schemes || { names: [], roles: [], colors: {} };
  const styles = g.styles || { entries: [] };
  const devices = vocab.devices || [];
  // what a slot may show: every complication type (`auto` is on_hold:'s own)
  const slotTypes = (vocab.complications || []).filter((t) => t !== "auto");
  const [adding, setAdding] = useState("");
  const fontFile = useRef(null);
  const replaceFor = useRef(null);
  const replaceFile = useRef(null);

  const ctx = { globals: g, vocab };
  const unused = palette.filter((p) => !p.used_by.length && !p.launcher);
  // who uses a colour: an element id selects it, anything else is a path
  const users = (list) => list.map((u, i) => html`${i ? ", " : ""}${u.includes(".") ? html`<code>${u}</code>`
    : html`<a href="#" onClick=${(e) => { e.preventDefault(); onSelect(u); }}>${u}</a>`}`);

  return html`<div class="face-panel">
    <${Section} title=${`Targets (${(g.targets || []).length})`}>
      <ul class="rows">${(g.targets || []).map((t) => html`<li>
        <span>${(devices.find((d) => d.id === t) || {}).name || t}</span> <code class="dim">${t}</code>
        <button class="reset" title="remove this target" onClick=${() => onEdit({ op: "set", path: ["build", "targets"], value: g.targets.filter((x) => x !== t) })}>×</button>
      </li>`)}</ul>
      <div class="row">
        <select value=${adding} onChange=${(e) => setAdding(e.target.value)}>
          <option value="">add a watch…</option>
          ${devices.filter((d) => !(g.targets || []).includes(d.id)).map((d) => html`<option value=${d.id}>${d.name} (${d.size}, ${d.shape})</option>`)}
        </select>
        <button disabled=${!adding} onClick=${() => { onEdit({ op: "set", path: ["build", "targets"], value: [...(g.targets || []), adding] }); setAdding(""); }}>Add</button>
      </div>
    </${Section}>

    <${Section} title=${`Colours (${palette.length})`}>
      <ul class="rows">${palette.map((p) => html`<li class="swatch-row">
          <span class="name" title="rename (every color.${p.name} follows)" onClick=${() => { const n = askName("Colour", p.name); if (n && n !== p.name) onEdit({ op: "rename", path: ["resources", "palette", p.name], to: n, prefix: "color." }); }}>${p.name}</span>
          <${ColorPop} value=${p.value} ctx=${ctx} faceGroup=${false}
            title=${p.used_by.length ? `changes ${p.used_by.length} use${p.used_by.length > 1 ? "s" : ""}: ${p.used_by.join(", ")}` : "not used yet"}
            onPick=${(v) => onEdit({ op: "set_swatch", name: p.name, value: v })} />
          ${p.dithers_on.length ? html`<span class="warn" title=${`dithers on ${p.dithers_on.join(", ")}`}>⚠</span>` : null}
          ${p.automatic ? html`<span class="tag" title="named after its colour: renamed when its colour changes, removed when nothing uses it">auto</span>` : null}
          <button class="reset" title="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "palette", p.name] })}>×</button>
          <div class="note">${p.used_by.length ? html`used by ${users(p.used_by)}`
            : p.launcher ? "the launcher icon reads it" : "not used"}</div>
        </li>`)}</ul>
      <div class="row">
        <${ColorPop} ctx=${ctx} faceGroup=${false} label="+ Colour" title="add one of the 64, or your own" onPick=${(v) => onEdit({ op: "add_swatch", value: v })} />
        <button disabled=${!unused.length} title=${unused.length ? `remove ${unused.map((p) => p.name).join(", ")}` : "every colour is in use"}
          onClick=${() => { if (confirm(`Remove ${unused.map((p) => p.name).join(", ")}?`)) onEdit({ op: "remove_unused" }); }}>Remove unused</button>
      </div>
    </${Section}>

    <${Section} title="Colour settings">
      ${["accent_color", "data_color"].map((axis) => html`<${AxisRow} axis=${axis} entry=${(g.axes || {})[axis]}
        palette=${palette} onEdit=${onEdit} />`)}
    </${Section}>

    <${Section} title=${`Schemes (${schemes.names.length})`}>
      <${Schemes} schemes=${schemes} palette=${palette} styles=${styles} ctx=${ctx} onEdit=${onEdit} />
    </${Section}>

    <${Section} title=${`Styles (${styles.entries.length})`}>
      ${styles.entries.length ? html`<ul class="rows">${styles.entries.map((e) => html`<li class="style">
        <label title="the style the face starts in"><input type="radio" name="default-style" checked=${styles.default === e.name}
          onChange=${() => onEdit({ op: "set", path: ["config", "style", "default"], value: e.name })} /> ${e.name}</label>
        ${g.layouts.length ? html`<select value=${e.layout || ""} onChange=${(ev) => onEdit(ev.target.value
            ? { op: "set", path: ["config", "style", "choices", e.name, "layout"], value: ev.target.value }
            : { op: "remove", path: ["config", "style", "choices", e.name, "layout"] })}>
          <option value="">no layout</option>${g.layouts.map((l) => html`<option value=${l}>${l}</option>`)}</select>` : null}
        ${schemes.names.length ? html`<select value=${e.scheme || ""} onChange=${(ev) => onEdit(ev.target.value
            ? { op: "set", path: ["config", "style", "choices", e.name, "scheme"], value: ev.target.value }
            : { op: "remove", path: ["config", "style", "choices", e.name, "scheme"] })}>
          <option value="">no scheme</option>${schemes.names.map((s) => html`<option value=${s}>${s}</option>`)}</select>` : null}
        <button class="reset" title="delete this style" onClick=${() => onEdit({ op: "remove", path: ["config", "style", "choices", e.name] })}>×</button>
      </li>`)}</ul>` : html`<div class="dim">${g.layouts.length || schemes.names.length ? "No styles yet." : "Styles pair a layout with a colour scheme; this face has neither yet."}</div>`}
      ${g.layouts.length || schemes.names.length ? html`<button onClick=${() => {
        const n = askName("New style"); if (!n) return;
        const entry = newStyleEntry(styles.entries, g.layouts, schemes.names);
        onEdit(styles.entries.length
          ? { op: "set", path: ["config", "style", "choices", n], value: entry }
          : { op: "set", path: ["config", "style"], value: { default: n, choices: { [n]: entry } } });
      }}>+ Style</button>` : null}
      ${g.layouts.length ? html`<div class="dim note">Layouts: ${g.layouts.join(", ")}</div>` : null}
    </${Section}>

    <${Section} title=${`Hand sets (${(g.hands || []).length})`}>
      <${HandSets} doc=${doc} ctx=${ctx} onEdit=${onEdit} onSelect=${onSelect} onReveal=${onReveal || (() => {})} />
    </${Section}>

    <${Section} title=${`Slots (${(g.slots || []).length})`}>
      ${(g.slots || []).length ? html`<ul class="rows">${g.slots.map((s) => html`<${SlotRow} slot=${s}
          types=${slotTypes} onEdit=${onEdit} onSelect=${onSelect} onStructure=${onStructure} />`)}</ul>`
        : html`<div class="dim">A slot shows whichever complication the wearer picks on the watch.</div>`}
      <button onClick=${() => {
        const n = askName("New slot"); if (!n) return;
        const taken = new Set((g.slots || []).map((s) => s.default));
        const value = { default: slotTypes.find((t) => !taken.has(t)) || slotTypes[0], choices: "any" };
        onEdit({ op: "set", path: ["config", "slots", n], value });
      }}>+ Slot</button>
      <datalist id="wfb-slot-icons"><option value="none" />${(vocab.icons || []).map((i) => html`<option value=${i} />`)}</datalist>
    </${Section}>

    <${Section} title=${`Fonts (${(g.fonts || []).length})`}>
      <ul class="rows">${(g.fonts || []).map((f) => html`<li class="font">
        <code>font.${f.name}</code>
        <span class="dim">${f.source || f.face || ""}</span>
        ${f.size != null ? html`<${Quantity} value=${f.size} units=${["%r", "px"]} bareUnit="px"
          onCommit=${(v) => onEdit({ op: "set", path: ["resources", "fonts", f.name, "size"], value: v })} />` : null}
        ${f.source ? html`<button title="replace the font file" onClick=${() => { replaceFor.current = f.source; replaceFile.current.click(); }}>Replace…</button>` : null}
        <button class="reset" title="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "fonts", f.name] })}>×</button>
      </li>`)}</ul>
      <button onClick=${() => fontFile.current.click()}>+ Font from a file…</button>
      <input type="file" accept=".ttf,.otf" style="display:none" ref=${fontFile} onChange=${(e) => {
        const file = e.target.files[0]; e.target.value = ""; if (!file) return;
        const n = askName("Font", file.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1").toLowerCase());
        if (n) onUpload(file, { font: n, size: "10%r" });
      }} />
      <input type="file" accept=".ttf,.otf" style="display:none" ref=${replaceFile} onChange=${(e) => {
        const file = e.target.files[0]; e.target.value = ""; if (file) onUpload(file, { reference: replaceFor.current });
      }} />
    </${Section}>
  </div>`;
}
