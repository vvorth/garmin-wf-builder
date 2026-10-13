// Dialogs: a question to confirm, building a face for one watch, and
// calibrating real size.

import type { ComponentChildren, JSX, VNode } from "preact";
import { call } from "./api.ts";
import { html } from "htm/preact";
import { useEffect, useState } from "preact/hooks";
import type { BuildResult, DeviceInfo, Summary, Vocabulary } from "../src/studio/protocol.ts";
import { CARD_MM, CSS_PX_PER_INCH, calibrate } from "./zoom.ts";

export interface ModalProps {
  title: string;
  onClose: () => void;
  children?: ComponentChildren;
  className?: string;
}

export function Modal({ title, onClose, children, className = "" }: ModalProps): VNode {
  return html`<div class="modal-back" onClick=${(e: JSX.TargetedMouseEvent<HTMLDivElement>) => { if (e.target === e.currentTarget) onClose(); }}>
    <div class=${"modal " + className} role="dialog" aria-label=${title}>
      <div class="modal-head"><strong>${title}</strong>
        <button class="reset" onClick=${onClose} title="Close" aria-label="Close">×</button></div>
      ${children}
    </div>
  </div>`;
}

/** A question on its way to `AskHost`: the message, the yes button's label, and who waits for the answer. */
interface Question {
  message: string;
  yes: string;
  resolve: (yes: boolean) => void;
}

// A question with a yes and a no, in the page's own dialog: `ask(message,
// yes)` resolves true or false once answered. `AskHost` (mounted once, by
// the app) shows it; with none mounted, the browser's confirm() asks.
let asking: ((question: Question) => void) | null = null;
export function ask(message: string, yes = "OK"): Promise<boolean> {
  if (asking === null) return Promise.resolve(confirm(message));
  const show = asking;
  return new Promise((resolve) => show({ message, yes, resolve }));
}

export function AskHost(): VNode | null {
  const [question, setQuestion] = useState<Question | null>(null);
  useEffect(() => { asking = setQuestion; return () => { asking = null; }; }, []);
  if (!question) return null;
  const answer = (yes: boolean): void => { setQuestion(null); question.resolve(yes); };
  return html`<${Modal} title="Are you sure?" onClose=${() => answer(false)}>
    <div class="modal-body ask">${question.message}</div>
    <div class="modal-foot">
      <button onClick=${() => answer(false)}>Cancel</button>
      <button class="primary" autofocus onClick=${() => answer(true)}>${question.yes}</button>
    </div>
  </${Modal}>`;
}

export interface BuildDialogProps {
  doc: Summary;
  vocab: Partial<Vocabulary>;
  /** The watch viewed, offered first. */
  device: string | null;
  onClose: () => void;
}

/** Where the build is: choosing a watch, building, built, or failed (with the server's answer, or the error that stopped it). */
interface BuildState {
  phase: "choose" | "building" | "built" | "failed";
  error?: string;
  result?: BuildResult;
}

// Build the face for one watch, then download its .prg.
export function BuildDialog({ doc, vocab, device, onClose }: BuildDialogProps): VNode {
  const devices = vocab.devices || [];
  const targets: Pick<DeviceInfo, "id" | "name">[] = doc.targets.map((t) => devices.find((d) => d.id === t) || { id: t, name: t });
  const others = devices.filter((d) => !doc.targets.includes(d.id));
  const [chosen, setChosen] = useState(device || doc.targets[0] || "");
  const [state, setState] = useState<BuildState>({ phase: "choose" });

  const build = async (): Promise<void> => {
    setState({ phase: "building" });
    try {
      const r = await call("build", { id: doc.id, device: chosen, version: doc.version });
      if (r.status !== 200) { setState({ phase: "failed", error: r.json.error }); return; }
      const body = r.json;
      if (body === undefined) { setState({ phase: "failed", error: "the build answered with no result" }); return; }
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
                  onChange=${(e: JSX.TargetedEvent<HTMLSelectElement>) => e.currentTarget.value && setChosen(e.currentTarget.value)}>
            <option value="">—</option>
            ${others.map((d) => html`<option value=${d.id}>${d.name} (${d.id})</option>`)}
          </select></label>` : null}
      </div>
      <div class="modal-foot">
        <button onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${!chosen} onClick=${build}>Build and download</button>
      </div>` : null}
    ${state.phase === "building" ? html`<div class="modal-body">Building for <code>${chosen}</code>… (monkeyc takes a few seconds)</div>` : null}
    ${state.phase === "built" && result ? html`<div class="modal-body">
        <div>Built <code>${result.device}</code> in ${result.seconds} s: ${result.memory || ""}</div>
        <div class="dim">The .prg is downloading. If it did not, <a href=${result.download} download>download it</a>.
          Copy it to the watch's <code>GARMIN/APPS</code> folder to install it.</div>
        <details><summary>Log</summary><pre class="log">${result.log}</pre></details>
      </div>
      <div class="modal-foot"><button class="primary" onClick=${onClose}>Close</button></div>` : null}
    ${state.phase === "failed" ? html`<div class="modal-body">
        <div class="error-text">${state.error || `The build for ${result ? result.device : chosen} failed.`}</div>
        ${result ? html`<pre class="log">${result.log}</pre>` : null}
      </div>
      <div class="modal-foot"><button onClick=${() => setState({ phase: "choose" })}>Back</button>
        <button class="primary" onClick=${onClose}>Close</button></div>` : null}
  </${Modal}>`;
}

export interface CalibrateDialogProps {
  /** CSS pixels per real inch, as calibrated so far. */
  current: number;
  onSave: (cssPxPerInch: number) => void;
  onClose: () => void;
}

// Match a bank card on the screen: how many CSS pixels make a real inch.
export function CalibrateDialog({ current, onSave, onClose }: CalibrateDialogProps): VNode {
  const [width, setWidth] = useState(Math.round((current / 25.4) * CARD_MM[0]));
  const height = Math.round(width * CARD_MM[1] / CARD_MM[0]);
  return html`<${Modal} title="Real size" onClose=${onClose}>
    <div class="modal-body">
      <div>Hold a bank card against the screen and drag until the box matches it.</div>
      <div class="card-box" style=${`width:${width}px;height:${height}px`}>85.6 × 54 mm</div>
      <input type="range" class="wide" min="150" max="900" step="1" value=${width}
             onInput=${(e: JSX.TargetedInputEvent<HTMLInputElement>) => setWidth(Number(e.currentTarget.value))} />
      <div class="dim">${calibrate(width).toFixed(1)} CSS px per inch on this screen (CSS assumes ${CSS_PX_PER_INCH}). Kept in this browser only.</div>
    </div>
    <div class="modal-foot">
      <button onClick=${() => onSave(CSS_PX_PER_INCH)}>Reset</button>
      <button class="primary" onClick=${() => onSave(calibrate(width))}>Save</button>
    </div>
  </${Modal}>`;
}
