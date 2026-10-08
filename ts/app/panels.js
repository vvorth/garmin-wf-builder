// The inspector (the selected element's keys) and the Face panel (targets,
// colours, schemes, styles, slots, fonts). Every change is one edit sent to the
// worker, which patches the text, checks it and answers with the face;
// a refused edit leaves the face as it was and says why.

import { html, useState, useEffect, useRef } from "./vendor/preact-htm.module.js";
import {
  ANGLE_UNITS, LENGTH_UNITS, afterRemovingSchemes, at, colorName, formatQuantity,
  newStyleEntry, parseHex, parseQuantity, safeOn, swatchFor, toHex,
} from "./values.js";
import { AddName, InlineName, Popover, WorkerImage } from "./ui.js";
import { api } from "./api.js";
import { ask } from "./dialogs.js";
import { HelpDialog } from "./help.js";

const ALIGN = [["top_left", "top", "top_right"], ["left", "center", "right"],
               ["bottom_left", "bottom", "bottom_right"]];

// The Face tab's own guide chapter, by section: its "? Guide" link.
const FACE_SECTION_GUIDE = {
  targets: "docs/guide/getting-started.md",
  colours: "docs/guide/colors.md",
  colour_settings: "docs/guide/configuration.md",
  schemes: "docs/guide/colors.md",
  styles: "docs/guide/styles-and-layouts.md",
  hand_sets: "docs/guide/analog-hands.md",
  slots: "docs/guide/configuration.md",
  fonts: "docs/guide/fonts.md",
};

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
      <button class=${value === a ? "on" : ""} title=${a} aria-label=${a.replace("_", " ")} aria-pressed=${value === a}
        onClick=${() => onCommit(a)}></button>`)}</span>`)}
  </span>`;
}

// The colour picker: a chip that opens three groups, the face's own colours
// (its swatches, then its roles where a role is allowed), the 64 named MIP
// colours, and a custom colour. A swatch or role is picked as
// `color.<name>`; one of the 64 or a custom colour as its hex, which the
// worker turns into the swatch holding it (`src/edit/colors.ts`).
export function ColorPop({ value, ctx, roles = true, faceGroup = true, title, label, onPick }) {
  const [custom, setCustom] = useState("");
  const palette = ctx.globals.palette || [];
  const mip = ctx.vocab.mip || [];
  const displays = ctx.globals.displays || [];
  const ref = colorName(value);
  const swatch = ref && palette.find((p) => p.name === ref);
  const shown = parseHex(value) || (swatch && parseHex(swatch.value));
  const customRgb = parseHex(custom) || shown || [255, 255, 255];
  const target = swatchFor(customRgb, palette, mip);
  const safe = safeOn(customRgb, displays);
  const warn = shown && !safeOn(shown, displays).ok;
  const chip = html`${label ? null : html`<span class="chip" style=${shown ? `background:${toHex(shown)}` : ""}></span>`}
      <span class=${ref || label ? "" : "dim"}>${label || ref || (shown ? toHex(shown) : "—")}</span>`;
  return html`<span class="color">
    <${Popover} buttonClass="chip-button" bodyClass="pop" title=${title || "pick a colour"} label=${chip}
      onOpen=${() => setCustom("")}>${(close) => {
      const pick = (v) => { close(); setCustom(""); onPick(v); };
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
          const held = palette.find((p) => { const v = parseHex(p.value); return v && toHex(v) === m.value; });
          return html`<button class=${"swatch" + (held ? " held" : "")} style=${`background:${m.value}`} aria-label=${m.label}
            title=${`${m.label} ${m.value}${held ? ` (this face: ${held.name})` : ""}`} onClick=${() => pick(m.value)}></button>`; })}</div>
      </div>
      <div class="pop-group">
        <div class="pop-title">Custom</div>
        <div class="pop-custom">
          <input type="color" value=${toHex(customRgb)} onInput=${(e) => setCustom(e.target.value.toUpperCase())} />
          <input type="text" class="mono hex" aria-label="hex colour" value=${custom || toHex(customRgb)}
            onInput=${(e) => setCustom(e.target.value)}
            onKeyDown=${(e) => { if (e.key === "Enter" && parseHex(custom)) pick(toHex(parseHex(custom))); }} />
          <button class="primary" disabled=${!parseHex(custom)} onClick=${() => pick(toHex(customRgb))}>Use</button>
        </div>
        ${parseHex(custom) ? html`<div class="note">${target.adds ? `adds ${target.name}` : `uses ${target.name}`}
          ${!safe.ok ? html` · <span class="warn">⚠ dithers</span> <a href="#" onClick=${(e) => { e.preventDefault(); setCustom(toHex(safe.nearest)); }}>nearest ${toHex(safe.nearest)}</a>` : null}</div>` : null}
      </div>`;
    }}</${Popover}>
    ${warn ? html`<span class="warn" title=${`dithers on this face's ${displays.join("/")}-colour screens`}>⚠</span>` : null}
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
    case "color": {
      // an expression choosing a colour is edited as text
      if (value != null && !colorName(value) && !parseHex(value)) return html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`;
      const ref = colorName(value);
      const isRole = ref && !(ctx.globals.palette || []).some((p) => p.name === ref) && (ctx.globals.roles || []).includes(ref);
      return html`<span class="color-field"><${ColorPop} value=${value} ctx=${ctx} onPick=${onPickColor} />
        ${isRole ? html`<span class="dim">role <code>${ref}</code></span>
          ${ctx.onFaceSection ? html`<a href="#" title="jump to the Schemes section"
            onClick=${(e) => { e.preventDefault(); ctx.onFaceSection("schemes"); }}>Schemes</a>` : null}` : null}</span>`;
    }
    case "template": return html`<${Template} value=${value} sources=${ctx.vocab.sources || {}} onCommit=${onCommit} />`;
    case "font": return enumSelect(ctx.systemFonts, (ctx.globals.fonts || []).map((f) => `font.${f.name}`));
    case "icon": return html`<${IconPop} value=${value} vocab=${ctx.vocab} onPick=${(v) => v && onCommit(v)} />`;
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
          aria-label=${overridden ? "remove the override" : "remove the key"}
            onClick=${() => onEdit({ op: "remove", ...base })}>×</button>` : null}
      ${overridden && value == null && field.value != null ? html`<div class="note">inherits ${JSON.stringify(field.value)}</div>` : null}
      ${!overridden && local.length ? html`<div class="note">overridden on this ${local.join(" and ")}</div>` : null}
    </div>
  </div>`;
}

export function Inspector({ doc, element, device, vocab, scope, onScope, onEdit, onError, onReveal, onSelect, onFaceSection }) {
  const [ins, setIns] = useState(null);
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
  const ctx = { globals: doc.globals || {}, vocab, systemFonts: deviceInfo ? deviceInfo.fonts : [], onReveal, onFaceSection };
  // the slot this element draws, edited right here as in the Face tab
  const slotField = ins.fields.find((f) => f.key === "slot");
  const slotCard = slotField && (ctx.globals.slots || []).find((s) => s.name === slotField.value);
  // a `hands` element's own set, likewise
  const setField = ins.type === "hands" && ins.fields.find((f) => f.key === "set");
  const handCard = setField && (ctx.globals.hands || []).find((h) => h.name === setField.value);
  return html`<div class="inspector">
    <div class="ins-head">
      <code>${ins.id}</code> <span class="dim">${ins.type}</span>
      <div class="scope" title="Where at:, size:, radius: and align: edits and drags are written; with all targets, a drag goes where the viewed device reads the key">
        ${[["all", "all targets", "the element's own key, for every target"],
           ["device", ins.device, `an override for ${ins.device} only`],
           ["shape", `${ins.shape} screens`, `an override for every ${ins.shape} watch`]].map(([s, label, what]) => html`
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
        <a href="#" title="a pattern's parts are edited in the YAML" onClick=${(e) => { e.preventDefault(); onReveal(ins.parts.line, ins.parts.end); }}>edit in YAML</a>
      </div>
    </div>` : null}
    ${(ins.overridden || []).map((o) => html`<div class="field" key=${o.selector}>
      <div class="name">overrides <code>${o.selector}</code></div>
      <div class="value">
        ${Object.entries(o.keys).map(([k, v]) => html`<code>${k}: ${JSON.stringify(v)}</code>`)}
        <a href="#" title="edit this override in the YAML tab" onClick=${(e) => { e.preventDefault(); onReveal(o.line, o.end); }}>edit in YAML</a>
      </div>
    </div>`)}
  </div>`;
}

// -- the Face panel ------------------------------------------------------------------

// Which Face-tab section is open, as this browser last left it.
function useFaceSection(defaultKey) {
  const [key, setKey] = useState(() => {
    try { return localStorage.getItem("wfb-face-section") || defaultKey; } catch (_) { return defaultKey; }
  });
  return [key, (k) => { setKey(k); try { localStorage.setItem("wfb-face-section", k); } catch (_) { /* private mode */ } }];
}

// A catalogue icon drawn with the icon font (`/api/icon-font`), or its
// name when the catalogue has no such icon.
export function Glyph({ name, vocab }) {
  const cp = name && (vocab.icon_glyphs || {})[name];
  return cp ? html`<span class="glyph" title=${name}>${String.fromCodePoint(cp)}</span>`
            : html`<span class="glyph dim">${name === "none" ? "∅" : ""}</span>`;
}

// An icon picker: every catalogue icon as a glyph, `none` where the key
// takes it, and a codepoint (`U+XXXX`) typed in.
export function IconPop({ value, vocab, allowNone = false, placeholder, onPick }) {
  const [code, setCode] = useState("");
  const names = Object.keys(vocab.icon_glyphs || {}).sort();
  const label = html`<${Glyph} name=${value || placeholder} vocab=${vocab} />
      <span class=${value ? "" : "dim"}>${value || placeholder || "icon"}</span>`;
  return html`<${Popover} buttonClass="chip-button" bodyClass="pop" title=${value || placeholder || "pick an icon"} label=${label}
    onOpen=${() => setCode("")}>${(close) => {
    const pick = (v) => { close(); setCode(""); onPick(v); };
    return html`
      <div class="pop-grid icons">${names.map((n) => html`<button class=${"swatch icon" + (n === value ? " on" : "")}
        title=${n} aria-label=${n} aria-pressed=${n === value} onClick=${() => pick(n)}><${Glyph} name=${n} vocab=${vocab} /></button>`)}</div>
      <div class="pop-custom">
        ${allowNone ? html`<button title="draw no icon for this one" onClick=${() => pick("none")}>none</button>` : null}
        <input type="text" class="mono codepoint" aria-label="codepoint" placeholder="U+F0000" value=${code}
          onInput=${(e) => setCode(e.target.value)} />
        <button disabled=${!/^U\+[0-9A-Fa-f]{4,6}$/.test(code)} onClick=${() => pick(code.trim().toUpperCase())}>Use</button>
        ${value ? html`<button class="reset" title=${placeholder ? `back to ${placeholder}` : "remove"}
          aria-label=${placeholder ? `back to ${placeholder}` : "remove"} onClick=${() => pick(null)}>×</button>` : null}
      </div>`;
  }}</${Popover}>`;
}

// One `config: slots:` entry, the same card in the Face tab and above a
// selected element drawing it: what the slot shows until the wearer picks
// (the star), what the wearer may pick (a checklist by group, or every
// type), each pick's icon, its title in the settings menu, and what draws it.
export function SlotCard({ slot, vocab, onEdit, onSelect }) {
  const path = ["config", "slots", slot.name];
  const types = vocab.complication_types || [];
  const byName = Object.fromEntries(types.map((t) => [t.name, t]));
  const any = !Array.isArray(slot.choices);
  const list = any ? [] : slot.choices;
  // the list a switch to "every type" leaves, so switching back restores it
  const [kept, setKept] = useState(null);
  const listed = (name) => any || list.some((c) => c.type === name);
  // a choice is written bare unless it carries an icon
  const written = (c) => (c.icon ? { type: c.type, icon: c.icon } : c.type);
  const setChoices = (choices) => onEdit({ op: "set", path: [...path, "choices"], value: choices.map(written) });
  const toggle = (name) => setChoices(listed(name) ? list.filter((c) => c.type !== name)
                                                   : [...list, { type: name, icon: null }]);
  const setDefault = (name) => {
    if (!listed(name)) setChoices([...list, { type: name, icon: null }]);
    onEdit({ op: "set", path: [...path, "default"], value: name });
  };
  const setIcon = (name, icon) => setChoices(list.map((c) => (c.type === name ? { ...c, icon } : c)));
  return html`<div class="slot-card">
    <div class="slot-head">
      <b><${InlineName} value=${slot.name} title="click to rename (every slot: naming it follows)"
        onRename=${(n) => onEdit({ op: "rename", path, to: n })} /></b>
      <button class="reset" title="delete (refused while an element draws it)" aria-label="delete (refused while an element draws it)"
        onClick=${() => onEdit({ op: "remove", path })}>×</button>
    </div>
    <div class="slot-line"><span class="dim">shows first</span>
      <span>${byName[slot.default] ? byName[slot.default].label : slot.default}</span>
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
              onPick=${(v) => setIcon(t.name, v)} />` : html`<${Glyph} name=${t.icon} vocab=${vocab} />`}
          <span class="label">${t.label}</span>
          <span class="dim mono">${t.sample || ""}</span>
        </div>`; })}
    </div>`)}</div>
    <div class="slot-line">
      <span class="dim">menu title</span>
      <${Commit} value=${slot.label || ""} placeholder=${slot.name} width="10em"
        onCommit=${(v) => onEdit(v.trim() ? { op: "set", path: [...path, "label"], value: v.trim() }
                                           : { op: "remove", path: [...path, "label"] })} />
      <span class="dim">in the settings menu of a watch without the native editor (fr955)</span>
    </div>
    <div class="slot-line">
      <span class="dim">drawn by</span>
      ${slot.drawn_by.length
        ? slot.drawn_by.map((id) => html`<a href="#" onClick=${(e) => { e.preventDefault(); onSelect && onSelect(id); }}>${id}</a>`)
        : html`<span class="dim">nothing yet: add a data element in Layers</span>`}
    </div>
  </div>`;
}

// `theme: schemes:`: with none, which colours should follow the wearer's
// style; with some, the roles × schemes table. Every change is one of the
// compound edits of `src/edit/schemes.ts`, so it never leaves the schemes out
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
      <${AddName} label="Make switchable…" disabled=${!picked.length} suggest=${() => "dark"}
        placeholder="the first scheme's name" title="the ticked colours move into a first scheme, named here"
        onAdd=${(n) => { onEdit({ op: "make_switchable", names: picked, scheme: n }); setPicked([]); }} />`;
  }
  const keepName = keep || schemes.names[0];
  const outcome = afterRemovingSchemes(styles.entries);
  return html`<table class="schemes">
      <tr><th></th>${schemes.names.map((s) => html`<th>
        <${InlineName} value=${s} title="click to rename (every style naming it follows)"
          onRename=${(n) => onEdit({ op: "rename_scheme", name: s, to: n })} />
        <button class="reset" title="delete this scheme and the styles that pick it" aria-label="delete this scheme and the styles that pick it" onClick=${() => onEdit({ op: "delete_scheme", name: s })}>×</button>
      </th>`)}</tr>
      ${schemes.roles.map((r) => html`<tr><td>
        <${InlineName} value=${r} title=${`click to rename (every color.${r} follows)`}
          onRename=${(n) => onEdit({ op: "rename_role", name: r, to: n })} />
        <button class="reset" title="delete this role (refused while something uses it)" aria-label="delete this role (refused while something uses it)" onClick=${() => onEdit({ op: "delete_role", name: r })}>×</button>
      </td>${schemes.names.map((s) => html`<td>
        <${ColorPop} value=${(schemes.colors[s] || {})[r]} ctx=${ctx} roles=${false}
          onPick=${(v) => onEdit({ op: "use_color", path: ["theme", "schemes", s, "colors", r], value: v })} /></td>`)}</tr>`)}
    </table>
    <div class="row">
      <${AddName} label="+ Scheme" placeholder="scheme name" title="a copy of the first scheme, and the styles that reach it"
        onAdd=${(n) => onEdit({ op: "add_scheme", name: n })} />
      <${AddName} label="+ Role" placeholder="role name" title="a role in every scheme, white until you set it"
        onAdd=${(n) => onEdit({ op: "add_role", name: n, value: "#FFFFFF" })} />
    </div>
    <div class="row">
      <select value=${keepName} title="the scheme whose colours become palette colours" onChange=${(e) => setKeep(e.target.value)}>
        ${schemes.names.map((s) => html`<option value=${s}>keep ${s}</option>`)}
      </select>
      <button onClick=${() => {
        const parts = [`Every role becomes a palette colour with ${keepName}'s value.`];
        if (outcome.removed) parts.push(`${outcome.removed} style${outcome.removed > 1 ? "s" : ""} naming only a scheme will go.`);
        if (outcome.duplicates) parts.push(`${outcome.duplicates} style${outcome.duplicates > 1 ? "s" : ""} will look like another one; Diagnostics will name them.`);
        ask(parts.join("\n"), "Remove schemes").then((yes) => { if (yes) onEdit({ op: "remove_theme", keep: keepName }); });
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
      <button class="reset" title="remove this setting" aria-label="remove this setting" onClick=${() => onEdit({ op: "remove", path })}>×</button></div>
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

// A hand set's hands, each with its colour (a part may set its own) and
// part count: the row every hand set is shown by, in the Face tab's list
// and, for the `hands` element placing it, the Inspector's card.
function handColorRows(set, ctx, onEdit) {
  return Object.entries(set.hands).map(([hand, h]) => html`<div class="slot-line">
    <span class="dim">${hand}</span>
    <${ColorPop} value=${h.color} ctx=${ctx} title=${`the ${hand} hand's colour (a part may set its own)`}
      onPick=${(v) => onEdit({ op: "use_color", path: ["resources", "hand_sets", set.name, hand, "color"], value: v })} />
    <span class="dim">${h.parts} part${h.parts === 1 ? "" : "s"}</span></div>`);
}

// The card a selected `hands` element shows above its keys: the set drawn
// alone, its hands' colours, and a link to its parts in the YAML tab.
export function HandSetCard({ set, doc, ctx, onEdit, onReveal }) {
  const device = (doc.targets || [])[0] || "";
  return html`<div class="hand-set-card">
    <${WorkerImage} class="hand-thumb" alt=${set.name} title="drawn alone at 10:09:42"
      op="handset" args=${{ id: doc.id, name: set.name, device, scale: 1, v: doc.version }} />
    <div class="hand-body">
      ${handColorRows(set, ctx, onEdit)}
      <div class="slot-line"><a href="#" title="a hand's parts are edited in the YAML"
        onClick=${(e) => { e.preventDefault(); onReveal(set.line, set.end); }}>edit the set</a></div>
    </div>
  </div>`;
}

// `resources: hand_sets:`: each set drawn alone, its hands' colours, what
// places it, and its parts in the YAML; new ones from a preset.
function HandSets({ doc, ctx, onEdit, onSelect, onReveal }) {
  const sets = ctx.globals.hands || [];
  const presets = ctx.vocab.hand_presets || [];
  const [preset, setPreset] = useState("");
  const device = (doc.targets || [])[0] || "";
  const taken = new Set(sets.map((s) => s.name));
  return html`${sets.length ? html`<ul class="rows">${sets.map((s) => html`<li class="hand-set">
      <${WorkerImage} class="hand-thumb" alt=${s.name} title="drawn alone at 10:09:42"
        op="handset" args=${{ id: doc.id, name: s.name, device, scale: 1, v: doc.version }} />
      <div class="hand-body">
        <div class="slot-head">
          <${InlineName} value=${s.name} title="click to rename (every set: naming it follows)"
            onRename=${(n) => onEdit({ op: "rename_hand_set", name: s.name, to: n })} />
          <button title="a copy, to change without touching this one" onClick=${() => onEdit({ op: "duplicate_hand_set", name: s.name })}>Duplicate</button>
          <button class="reset" title="delete (refused while an element places it)" aria-label="delete (refused while an element places it)" onClick=${() => onEdit({ op: "delete_hand_set", name: s.name })}>×</button>
        </div>
        ${handColorRows(s, ctx, onEdit)}
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
      <${AddName} label="+ Hand set" disabled=${!preset} placeholder="hand set name"
        title=${sets.some((s) => s.placed_by.length) ? "" : "also places it at the centre"}
        suggest=${() => (taken.has(preset) ? `${preset}_2` : preset)}
        onAdd=${(name) => { onEdit({ op: "add_hand_set", name, preset }); setPreset(""); }} />
    </div>`;
}

// A new slot: what it shows first, then its name; it is drawn by a new data
// element, in the same change.
function NewSlot({ vocab, taken, onEdit }) {
  const [first, setFirst] = useState("");
  const types = vocab.complication_types || [];
  return html`<div class="row">
    <select value=${first} onChange=${(e) => setFirst(e.target.value)} title="what the new slot shows first">
      <option value="">a new slot, showing…</option>
      ${(vocab.categories || []).map((group) => html`<optgroup label=${group}>
        ${types.filter((t) => t.category === group).map((t) => html`<option value=${t.name}>${t.label}</option>`)}
      </optgroup>`)}
    </select>
    <${AddName} label="+ Slot" disabled=${!first} placeholder="slot name"
      suggest=${() => { const base = first.split("_")[0]; return taken.includes(base) ? `${base}_2` : base; }}
      onAdd=${(n) => { onEdit({ op: "add_slot", name: n, default: first }); setFirst(""); }} />
  </div>`;
}

export function FacePanel({ doc, vocab, onEdit, onUpload, onSelect, onStructure, onReveal }) {
  const g = doc.globals || {};
  const palette = g.palette || [];
  const schemes = g.schemes || { names: [], roles: [], colors: {} };
  const styles = g.styles || { entries: [] };
  const devices = vocab.devices || [];
  const [adding, setAdding] = useState("");
  // a font file chosen and waiting for its name
  const [newFont, setNewFont] = useState(null);
  const fontFile = useRef(null);
  const replaceFor = useRef(null);
  const replaceFile = useRef(null);

  const ctx = { globals: g, vocab };
  const unused = palette.filter((p) => !p.used_by.length && !p.launcher);
  // who uses a colour: an element id selects it, anything else is a path
  const users = (list) => list.map((u, i) => html`${i ? ", " : ""}${u.includes(".") ? html`<code>${u}</code>`
    : html`<a href="#" onClick=${(e) => { e.preventDefault(); onSelect(u); }}>${u}</a>`}`);

  const SECTIONS = [
    { key: "targets", title: "Target devices", count: (g.targets || []).length, body: html`
      <ul class="rows">${(g.targets || []).map((t) => html`<li>
        <span>${(devices.find((d) => d.id === t) || {}).name || t}</span> <code class="dim">${t}</code>
        ${(g.target_problems || {})[t] ? html`<span class="warn" title=${g.target_problems[t]}>⚠ not available here</span>` : null}
        <button class="reset" title="remove this target" aria-label="remove this target" onClick=${() => onEdit({ op: "set", path: ["build", "targets"], value: g.targets.filter((x) => x !== t) })}>×</button>
      </li>`)}</ul>
      <div class="row">
        <select value=${adding} onChange=${(e) => setAdding(e.target.value)}>
          <option value="">add a watch…</option>
          ${devices.filter((d) => !(g.targets || []).includes(d.id)).map((d) => html`<option value=${d.id}>${d.name} (${d.size}, ${d.shape})</option>`)}
        </select>
        <button disabled=${!adding} onClick=${() => { onEdit({ op: "set", path: ["build", "targets"], value: [...(g.targets || []), adding] }); setAdding(""); }}>Add</button>
      </div>
      ${(vocab.unreadable_devices || []).length ? html`<div class="note warn"
          title=${vocab.unreadable_devices.map((d) => `${d.id}: ${d.reason}`).join("\n")}>
        ⚠ ${vocab.unreadable_devices.length} installed watch${vocab.unreadable_devices.length > 1 ? "es" : ""}
        could not be read, so ${vocab.unreadable_devices.length > 1 ? "they are" : "it is"} not offered
        (${vocab.unreadable_devices.map((d) => d.id).join(", ")})</div>` : null}
    ` },

    { key: "colours", title: "Colours", count: palette.length, body: html`
      <ul class="rows">${palette.map((p) => html`<li class="swatch-row">
          <${InlineName} value=${p.name} title=${`click to rename (every color.${p.name} follows)`}
            onRename=${(n) => onEdit({ op: "rename", path: ["resources", "palette", p.name], to: n, prefix: "color." })} />
          <${ColorPop} value=${p.value} ctx=${ctx} faceGroup=${false}
            title=${p.used_by.length ? `changes ${p.used_by.length} use${p.used_by.length > 1 ? "s" : ""}: ${p.used_by.join(", ")}` : "not used yet"}
            onPick=${(v) => onEdit({ op: "set_swatch", name: p.name, value: v })} />
          ${p.dithers_on.length ? html`<span class="warn" title=${`dithers on ${p.dithers_on.join(", ")}`}>⚠</span>` : null}
          ${p.problem ? html`<span class="warn" title=${p.problem}>⚠ not a colour</span>` : null}
          ${p.automatic ? html`<span class="tag" title="named after its colour: renamed when its colour changes, removed when nothing uses it">auto</span>` : null}
          <button class="reset" title="delete (refused while something uses it)" aria-label="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "palette", p.name] })}>×</button>
          <div class="note">${p.used_by.length ? html`used by ${users(p.used_by)}`
            : p.launcher ? "the launcher icon reads it" : "not used"}</div>
        </li>`)}</ul>
      <div class="row">
        <${ColorPop} ctx=${ctx} faceGroup=${false} label="+ Colour" title="add one of the 64, or your own" onPick=${(v) => onEdit({ op: "add_swatch", value: v })} />
        <button disabled=${!unused.length} title=${unused.length ? `remove ${unused.map((p) => p.name).join(", ")}` : "every colour is in use"}
          onClick=${() => ask(`Remove ${unused.map((p) => p.name).join(", ")}?`, "Remove").then((yes) => { if (yes) onEdit({ op: "remove_unused" }); })}>Remove unused</button>
      </div>
    ` },

    { key: "colour_settings", title: "Colour settings", body: html`
      ${["accent_color", "data_color"].map((axis) => html`<${AxisRow} axis=${axis} entry=${(g.axes || {})[axis]}
        palette=${palette} onEdit=${onEdit} />`)}
    ` },

    { key: "schemes", title: "Colour schemes", count: schemes.names.length, body: html`
      <${Schemes} schemes=${schemes} palette=${palette} styles=${styles} ctx=${ctx} onEdit=${onEdit} />
    ` },

    { key: "styles", title: "Styles", count: styles.entries.length, body: html`
      ${styles.entries.length ? html`<ul class="rows">${styles.entries.map((e) => html`<li class="style">
        <div class="slot-head">
          <code>${e.name}</code>
          <button class="reset" title="delete this style" aria-label="delete this style" onClick=${() => onEdit({ op: "remove", path: ["config", "style", "choices", e.name] })}>×</button>
        </div>
        <label class="slot-line" title="the one style the face opens in; the wearer's own pick, where the watch has a picker, starts here too">
          <input type="radio" name="default-style" checked=${styles.default === e.name}
            onChange=${() => onEdit({ op: "set", path: ["config", "style", "default"], value: e.name })} />
          <span class="dim">starting style</span>
        </label>
        <div class="slot-line"><span class="dim">label the wearer sees</span>
          <${Commit} value=${e.label} placeholder="label" width="8em"
            onCommit=${(t) => onEdit(t.trim()
              ? { op: "set", path: ["config", "style", "choices", e.name, "label"], value: t.trim() }
              : { op: "remove", path: ["config", "style", "choices", e.name, "label"] })} /></div>
        ${g.layouts.length ? html`<div class="slot-line"><span class="dim">layout</span>
          <select value=${e.layout || ""} onChange=${(ev) => onEdit(ev.target.value
              ? { op: "set", path: ["config", "style", "choices", e.name, "layout"], value: ev.target.value }
              : { op: "remove", path: ["config", "style", "choices", e.name, "layout"] })}>
            <option value="">no layout</option>${g.layouts.map((l) => html`<option value=${l}>${l}</option>`)}</select></div>` : null}
        ${schemes.names.length ? html`<div class="slot-line"><span class="dim">colour scheme</span>
          <select value=${e.scheme || ""} onChange=${(ev) => onEdit(ev.target.value
              ? { op: "set", path: ["config", "style", "choices", e.name, "scheme"], value: ev.target.value }
              : { op: "remove", path: ["config", "style", "choices", e.name, "scheme"] })}>
            <option value="">no scheme</option>${schemes.names.map((s) => html`<option value=${s}>${s}</option>`)}</select></div>` : null}
      </li>`)}</ul>` : html`<div class="dim">${g.layouts.length || schemes.names.length ? "No styles yet." : "Styles pair a layout with a colour scheme; this face has neither yet."}</div>`}
      ${g.layouts.length || schemes.names.length ? html`<${AddName} label="+ Style" placeholder="style name"
        onAdd=${(n) => {
          const entry = newStyleEntry(styles.entries, g.layouts, schemes.names);
          onEdit(styles.entries.length
            ? { op: "set", path: ["config", "style", "choices", n], value: entry }
            : { op: "set", path: ["config", "style"], value: { default: n, choices: { [n]: entry } } });
        }} />` : null}
      <${AddName} label="+ Layout" placeholder="layout name"
        suggest=${() => { let n = "layout", i = 2; while (g.layouts.includes(n)) n = `layout${i++}`; return n; }}
        onAdd=${(n) => onEdit({ op: "add_layout", name: n })} />
      ${g.layouts.length ? html`<div class="dim note">Layouts: ${g.layouts.join(", ")}</div>` : null}
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
          onCommit=${(v) => onEdit({ op: "set", path: ["resources", "fonts", f.name, "size"], value: v })} />` : null}
        ${f.source ? html`<button title="replace the font file" onClick=${() => { replaceFor.current = f.source; replaceFile.current.click(); }}>Replace…</button>` : null}
        <button class="reset" title="delete (refused while something uses it)" aria-label="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "fonts", f.name] })}>×</button>
      </li>`)}</ul>
      ${newFont ? html`<div class="row"><span class="dim">${newFont.name} as</span>
          <${AddName} key=${newFont.name} label="font name" placeholder="font name" startOpen=${true}
            suggest=${() => newFont.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1").toLowerCase()}
            onAdd=${(n) => { onUpload(newFont, { font: n, size: "10%r" }); setNewFont(null); }}
            onCancel=${() => setNewFont(null)} /></div>`
        : html`<button onClick=${() => fontFile.current.click()}>+ Font from a file…</button>`}
      <input type="file" accept=".ttf,.otf" hidden ref=${fontFile} onChange=${(e) => {
        const file = e.target.files[0]; e.target.value = ""; if (file) setNewFont(file);
      }} />
      <input type="file" accept=".ttf,.otf" hidden ref=${replaceFile} onChange=${(e) => {
        const file = e.target.files[0]; e.target.value = ""; if (file) onUpload(file, { reference: replaceFor.current });
      }} />
    ` },
  ];

  const [activeKey, setActiveKey] = useFaceSection(SECTIONS[0].key);
  const active = SECTIONS.find((s) => s.key === activeKey) || SECTIONS[0];
  const [helpTopic, setHelpTopic] = useState(null);
  const guide = FACE_SECTION_GUIDE[active.key];

  return html`<div class="face-panel">
    <div class="tabs face-nav">${SECTIONS.map((s) => html`<button key=${s.key} class=${s.key === active.key ? "on" : ""}
        onClick=${() => setActiveKey(s.key)}>${s.title}${s.count != null ? html`<span class="count">${s.count}</span>` : null}</button>`)}</div>
    <div class="face-section-body">
      ${guide ? html`<a href="#" class="face-section-guide" title="Open the guide to this section"
          onClick=${(e) => { e.preventDefault(); setHelpTopic(guide); }}>? Guide</a>` : null}
      ${active.body}
    </div>
    ${helpTopic ? html`<${HelpDialog} start=${helpTopic} onClose=${() => setHelpTopic(null)} />` : null}
  </div>`;
}
