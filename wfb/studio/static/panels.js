// The inspector (the selected element's keys) and the Face panel (targets,
// colours, schemes, styles, fonts). Every change is one edit sent to the
// server, which patches the text, checks it and answers with the face;
// a refused edit leaves the face as it was and says why.

import { html, useState, useEffect, useRef } from "./vendor/preact-htm.module.js";
import {
  ANGLE_UNITS, LENGTH_UNITS, at, colorName, formatQuantity, isIdentifier, mipLegal,
  mipNearest, newStyleEntry, parseHex, parseQuantity, toHex,
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

function ColorPicker({ value, palette, roles, onCommit }) {
  const names = [...palette.map((p) => p.name), ...roles.filter((r) => !palette.some((p) => p.name === r))];
  const ref = colorName(value);
  const literal = parseHex(value);
  const swatch = (name) => {
    const entry = palette.find((p) => p.name === name);
    return entry ? parseHex(entry.value) : null;
  };
  const shown = literal || (ref && swatch(ref));
  if (value != null && !ref && !literal) {
    // an expression choosing a colour: edited as text
    return html`<${Commit} value=${String(value)} mono onCommit=${onCommit} />`;
  }
  return html`<span class="color">
    <span class="chip" style=${shown ? `background:${toHex(shown)}` : ""}></span>
    <select value=${ref ? `color.${ref}` : literal ? "#" : ""}
      onChange=${(e) => { const v = e.target.value; if (v && v !== "#") onCommit(v); }}>
      <option value="">—</option>
      ${names.map((n) => html`<option value=${`color.${n}`}>${n}</option>`)}
      <option value="#">custom</option>
    </select>
    ${literal || !ref ? html`<input type="color" value=${shown ? toHex(shown) : "#000000"}
        onChange=${(e) => onCommit(toHex(parseHex(e.target.value)))} />` : null}
    ${literal && !mipLegal(literal) ? html`<span class="warn" title=${`dithers on a 64-colour MIP panel; nearest: ${toHex(mipNearest(literal))}`}>⚠</span>` : null}
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

function Widget({ field, value, ctx, onCommit, like }) {
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
    case "color": return html`<${ColorPicker} value=${value} palette=${ctx.globals.palette || []}
      roles=${(ctx.globals.schemes || {}).roles || []} onCommit=${onCommit} />`;
    case "template": return html`<${Template} value=${value} sources=${ctx.vocab.sources || {}} onCommit=${onCommit} />`;
    case "font": return enumSelect(ctx.systemFonts, (ctx.globals.fonts || []).map((f) => `font.${f.name}`));
    case "icon": return html`<${Commit} value=${value} list="wfb-icons" onCommit=${onCommit} />`;
    case "complication": return enumSelect(ctx.vocab.complications || []);
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
        onCommit=${(v) => onEdit({ op: "set", ...base, value: v })} />
      ${value != null && !field.required && field.widget !== "readonly"
        ? html`<button class="reset" title=${overridden ? "remove the override" : "remove the key (back to the default)"}
            onClick=${() => onEdit({ op: "remove", ...base })}>×</button>` : null}
      ${overridden && value == null && field.value != null ? html`<div class="note">inherits ${JSON.stringify(field.value)}</div>` : null}
      ${!overridden && local.length ? html`<div class="note">overridden on this ${local.join(" and ")}</div>` : null}
    </div>
  </div>`;
}

export function Inspector({ doc, element, device, vocab, scope, onScope, onEdit, onError }) {
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
  const ctx = { globals: doc.globals || {}, vocab, systemFonts: deviceInfo ? deviceInfo.fonts : [] };
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

export function FacePanel({ doc, vocab, onEdit, onUpload }) {
  const g = doc.globals || {};
  const palette = g.palette || [];
  const schemes = g.schemes || { names: [], roles: [], colors: {} };
  const styles = g.styles || { entries: [] };
  const devices = vocab.devices || [];
  const [adding, setAdding] = useState("");
  const fontFile = useRef(null);
  const replaceFor = useRef(null);
  const replaceFile = useRef(null);

  const hexInput = (value, path) => html`<span class="color">
    <span class="chip" style=${parseHex(value) ? `background:${toHex(parseHex(value))}` : ""}></span>
    <${Commit} value=${value} mono width="6.5em" onCommit=${(v) => onEdit({ op: "set", path, value: v })} />
    <input type="color" value=${parseHex(value) ? toHex(parseHex(value)) : "#000000"}
      onChange=${(e) => onEdit({ op: "set", path, value: toHex(parseHex(e.target.value)) })} />
  </span>`;

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
      <ul class="rows">${palette.map((p) => {
        const path = ["resources", "palette", p.name, ...(p.long ? ["value"] : [])];
        return html`<li>
          <span class="name" title="rename" onClick=${() => { const n = askName("Colour", p.name); if (n && n !== p.name) onEdit({ op: "rename", path: ["resources", "palette", p.name], to: n, prefix: "color." }); }}>${p.name}</span>
          ${hexInput(p.value, path)}
          ${p.dithers_on.length ? html`<span class="warn" title=${`dithers on ${p.dithers_on.join(", ")}`}>⚠</span>` : null}
          <button class="reset" title="delete (refused while something uses it)" onClick=${() => onEdit({ op: "remove", path: ["resources", "palette", p.name] })}>×</button>
        </li>`; })}</ul>
      <button onClick=${() => { const n = askName("New colour"); if (n) onEdit({ op: "set", path: ["resources", "palette", n], value: "#FFFFFF" }); }}>+ Colour</button>
    </${Section}>

    ${schemes.names.length ? html`<${Section} title="Schemes">
      <table class="schemes"><tr><th></th>${schemes.names.map((s) => html`<th>${s}</th>`)}</tr>
        ${schemes.roles.map((r) => html`<tr><td>${r}</td>${schemes.names.map((s) => {
          const v = (schemes.colors[s] || {})[r];
          const path = ["theme", "schemes", s, "colors", r];
          return html`<td>${colorName(v)
            ? html`<select value=${v} onChange=${(e) => onEdit({ op: "set", path, value: e.target.value })}>
                ${palette.map((p) => html`<option value=${`color.${p.name}`}>${p.name}</option>`)}</select>`
            : hexInput(v, path)}</td>`; })}</tr>`)}
      </table>
    </${Section}>` : null}

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
