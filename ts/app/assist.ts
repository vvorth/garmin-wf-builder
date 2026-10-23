// The Assist dialog: a view of the store's `AssistSession`, the picture
// and the chat with the model `wfb studio --assist` names. Closing it hides
// the chat and nothing else: a running request goes on, and opening the
// dialog again shows it where it got to.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { MAX_FIX_ROUNDS } from "../src/studio/assist.ts";
import type { AssistSession, AssistState } from "./assist-session.ts";
import { Modal } from "./dialogs.ts";

/** The session's state now, and the component rendered again whenever it changes. */
function useAssist(session: AssistSession): AssistState {
  const [state, setState] = useState(session.state);
  useEffect(() => {
    // a change between this render and the subscription
    setState(session.state);
    return session.subscribe(() => setState(session.state));
  }, [session]);
  return state;
}

/** The top bar's button: it says when a request is under way with the dialog closed. */
export function AssistButton({ session, onClick }: { session: AssistSession; onClick: () => void }): VNode {
  const { busy } = useAssist(session);
  return html`<button class=${busy ? "assist-busy" : ""} onClick=${onClick}
      title=${busy ? "Assist is working on a request: open it to follow or stop it"
        : "A face from a picture, or changes asked for in words, by the model wfb studio --assist names"}>Assist…${busy ? " ●" : ""}</button>`;
}

/** `ms` as `m:ss`. */
const elapsed = (ms: number): string => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export interface AssistDialogProps {
  session: AssistSession;
  onClose: () => void;
}

export function AssistDialog({ session, onClose }: AssistDialogProps): VNode {
  const { status, image, turns, input, busy, sendPreview } = useAssist(session);
  const started = session.started;
  const fileInput = useRef<HTMLInputElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  useEffect(() => { session.loadStatus(); }, [session]);
  // while a request is under way, a tick a second for the time waited
  const [, tick] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => { const t = transcript.current; if (t) t.scrollTop = t.scrollHeight; });

  const submit = (e?: JSX.TargetedEvent<HTMLFormElement>): void => {
    e?.preventDefault();
    void session.submit();
  };

  const disabled = status === null || !status.enabled;
  const empty = turns.length === 0 && image === null && input === "";
  return html`<${Modal} title="Assist" onClose=${onClose} className="assist">
    <div class="modal-body assist-body">
      ${status === null ? html`<div class="dim">Asking the server…</div>` : null}
      ${status && !status.enabled ? html`<div class="error-text">The editor was started without an assistant.
        Start it as <code>wfb studio --assist ollama</code> (Ollama on this computer, model <code>qwen3-vl:8b</code>),
        or <code>--assist openai --assist-url … --assist-model …</code> with the key in <code>WFB_ASSIST_KEY</code>.</div>` : null}
      ${status && status.enabled ? html`<div class="dim small">${status.provider} · <code>${status.model}</code> at <code>${status.url}</code>.
        Each answer is applied to the face as one change: undo takes it back. Closing this keeps the chat, and a request goes on.</div>` : null}
      <div class="assist-transcript" ref=${transcript}>
        ${turns.length === 0 ? html`<div class="dim">Drop a picture of a watch face, say what you want, and send.
          The model answers with the whole face; the editor checks it and sends its errors back, up to ${MAX_FIX_ROUNDS} times.
          Without a picture, ask for a change to the face as it is.</div>` : null}
        ${turns.map((t) => html`<div class=${"assist-turn " + t.role + (t.round > 0 ? " auto" : "")}>
          ${t.role === "user" ? html`<div class="who">${t.round > 0 ? "editor" : "you"}</div>
              ${t.image ? html`<img class="assist-image" src=${t.image} alt="the picture" />` : null}
              <div class="said">${t.shown}</div>` : html`<div class="who">model</div>
              ${t.thinking ? html`<details class="assist-thinking" open=${t.streaming && !t.content}>
                  <summary>Thinking${t.streaming && !t.content ? "…" : ""}</summary><pre>${t.thinking}</pre></details>` : null}
              ${t.content ? html`<pre class="assist-answer">${t.content}</pre>` : t.streaming && !t.thinking ? html`<div class="dim assist-wait">waiting for the model… ${elapsed(Date.now() - (t.since ?? Date.now()))}
                  <span class="small">(on a CPU, reading a long request can take minutes before the first word)</span></div>` : null}
              ${t.error ? html`<div class="error-text">${t.error}</div>` : null}
              ${t.applied ? html`<div class=${"assist-result" + (t.applied.ok && t.applied.errors === 0 ? " ok" : " bad")}>
                  ${t.applied.thumb ? html`<img src=${t.applied.thumb} alt="the face after this answer" />` : null}
                  <div>
                    <div>${t.applied.ok
                      ? (t.applied.errors === 0 ? "Applied" : `Applied, with ${t.applied.errors} error${t.applied.errors === 1 ? "" : "s"}`)
                        + (t.applied.warnings ? `, ${t.applied.warnings} warning${t.applied.warnings === 1 ? "" : "s"}` : "")
                      : "Not applied"}</div>
                    ${t.applied.problems ? html`<details><summary>Details</summary><pre class="log">${t.applied.problems}</pre></details>` : null}
                  </div></div>` : null}`}
        </div>`)}
      </div>
      <form class="assist-compose" onSubmit=${submit}>
        ${image && !started ? html`<img class="assist-image" src=${image} alt="the picture to send" />` : null}
        <div class="row">
          ${!started ? html`<button type="button" disabled=${disabled || busy} onClick=${() => fileInput.current?.click()}>${image ? "Another picture…" : "Picture…"}</button>
            <input type="file" accept="image/*" hidden ref=${fileInput}
                   onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => session.pick(e.currentTarget.files?.[0])} />` : null}
          <input type="text" class="wide" value=${input} disabled=${disabled || busy}
                 placeholder=${started ? "what to change" : "what to make, or leave empty with a picture"}
                 onInput=${(e: JSX.TargetedEvent<HTMLInputElement>) => session.setInput(e.currentTarget.value)} />
          ${busy ? html`<button type="button" class="assist-stop" title="Stop the model's answer, and the fix rounds after it" onClick=${() => session.stop()}>Stop</button>`
            : html`<button type="submit" class="primary" disabled=${disabled || (!input.trim() && !(image && !started))}>Send</button>`}
          <button type="button" class="assist-reset" disabled=${empty} title="Forget the chat and the picture: the next request starts afresh (changes already applied stay; undo takes them back)"
                  onClick=${() => session.reset()}>Reset</button>
        </div>
        <label class="dim small"><input type="checkbox" checked=${sendPreview} onChange=${(e: JSX.TargetedEvent<HTMLInputElement>) => session.setSendPreview(e.currentTarget.checked)} />
          also send the model the face as drawn (costs tokens; a small model rarely uses it)</label>
      </form>
    </div>
  </${Modal}>`;
}
