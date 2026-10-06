// Dialogs: building a face for one watch, and calibrating real size.

import { call } from "./api.js";
import { html, useState } from "./vendor/preact-htm.module.js";
import { CARD_MM, CSS_PX_PER_INCH, calibrate } from "./zoom.js";

export function Modal({ title, onClose, children }) {
  return html`<div class="modal-back" onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div class="modal" role="dialog" aria-label=${title}>
      <div class="modal-head"><strong>${title}</strong>
        <button class="reset" onClick=${onClose} title="Close">×</button></div>
      ${children}
    </div>
  </div>`;
}

// Build the face for one watch, then download its .prg.
export function BuildDialog({ doc, vocab, device, onClose }) {
  const devices = vocab.devices || [];
  const targets = doc.targets.map((t) => devices.find((d) => d.id === t) || { id: t, name: t });
  const others = devices.filter((d) => !doc.targets.includes(d.id));
  const [chosen, setChosen] = useState(device || doc.targets[0] || "");
  const [state, setState] = useState({ phase: "choose" });

  const build = async () => {
    setState({ phase: "building" });
    try {
      const r = await call(`/api/documents/${doc.id}/build?device=${encodeURIComponent(chosen)}&version=${doc.version}`,
                           { method: "POST" });
      const body = r.json;
      if (r.status >= 400) { setState({ phase: "failed", error: body.error }); return; }
      if (body.ok && body.download) {
        const a = document.createElement("a");
        a.href = body.download;
        a.download = "";
        document.body.appendChild(a); a.click(); a.remove();
      }
      setState({ phase: body.ok ? "built" : "failed", result: body });
    } catch (e) { setState({ phase: "failed", error: String(e) }); }
  };

  const result = state.result;
  return html`<${Modal} title="Build" onClose=${onClose}>
    ${state.phase === "choose" ? html`
      <div class="modal-body">
        <div class="dim">Which watch? The face's own targets first.</div>
        <ul class="choices">
          ${targets.map((d) => html`<li><label>
            <input type="radio" name="build-device" checked=${chosen === d.id} onChange=${() => setChosen(d.id)} />
            ${d.name} <code class="dim">${d.id}</code></label></li>`)}
        </ul>
        ${others.length ? html`<label class="dim">Another installed watch
          <select value=${targets.some((t) => t.id === chosen) ? "" : chosen}
                  onChange=${(e) => e.target.value && setChosen(e.target.value)}>
            <option value="">—</option>
            ${others.map((d) => html`<option value=${d.id}>${d.name} (${d.id})</option>`)}
          </select></label>` : null}
      </div>
      <div class="modal-foot">
        <button onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${!chosen} onClick=${build}>Build and download</button>
      </div>` : null}
    ${state.phase === "building" ? html`<div class="modal-body">Building for <code>${chosen}</code>… (monkeyc takes a few seconds)</div>` : null}
    ${state.phase === "built" ? html`<div class="modal-body">
        <div>Built <code>${result.device}</code> in ${result.seconds} s: ${result.memory || ""}</div>
        <div class="dim">The .prg is downloading. If it did not, <a href=${result.download} download>download it</a>.
          Copy it to the watch's <code>GARMIN/APPS</code> folder to install it.</div>
        <details><summary>Log</summary><pre class="log">${result.log}</pre></details>
      </div>
      <div class="modal-foot"><button class="primary" onClick=${onClose}>Close</button></div>` : null}
    ${state.phase === "failed" ? html`<div class="modal-body">
        <div class="error-text">${state.error || `The build for ${result.device} failed.`}</div>
        ${result ? html`<pre class="log">${result.log}</pre>` : null}
      </div>
      <div class="modal-foot"><button onClick=${() => setState({ phase: "choose" })}>Back</button>
        <button class="primary" onClick=${onClose}>Close</button></div>` : null}
  </${Modal}>`;
}

// Match a bank card on the screen: how many CSS pixels make a real inch.
export function CalibrateDialog({ current, onSave, onClose }) {
  const [width, setWidth] = useState(Math.round((current / 25.4) * CARD_MM[0]));
  const height = Math.round(width * CARD_MM[1] / CARD_MM[0]);
  return html`<${Modal} title="Real size" onClose=${onClose}>
    <div class="modal-body">
      <div>Hold a bank card against the screen and drag until the box matches it.</div>
      <div class="card-box" style=${`width:${width}px;height:${height}px`}>85.6 × 54 mm</div>
      <input type="range" min="150" max="900" step="1" value=${width} style="width:100%"
             onInput=${(e) => setWidth(Number(e.target.value))} />
      <div class="dim">${calibrate(width).toFixed(1)} CSS px per inch on this screen (CSS assumes ${CSS_PX_PER_INCH}). Kept in this browser only.</div>
    </div>
    <div class="modal-foot">
      <button onClick=${() => onSave(CSS_PX_PER_INCH)}>Reset</button>
      <button class="primary" onClick=${() => onSave(calibrate(width))}>Save</button>
    </div>
  </${Modal}>`;
}
