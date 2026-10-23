// The Assist chat itself: the picture, the turns, the chat as the model
// sees it and the request in flight. The editor's store owns one for the
// page's lifetime, so closing the dialog (or clicking outside it) only
// hides the chat: a running request goes on, and the dialog shows it again
// as it left it. `stop` ends the run in flight, the automatic fix rounds
// with it; `reset` forgets the chat, as opening another face does.

import {
  type AssistStatus, type Message, MAX_FIX_ROUNDS, changeRequest, diagnosticsText, extractYaml, firstRequest, fixRequest, readEvents,
} from "../src/studio/assist.ts";
import type { Summary } from "../src/studio/protocol.ts";
import { api, call, objectUrl } from "./api.ts";

/** The longest side a picture is sent at: enough to read a face, cheap in tokens. */
const IMAGE_SIDE = 1024;

/** What applying an answer came to. */
export interface Applied {
  /** The editor took the text. */
  ok: boolean;
  errors: number;
  warnings: number;
  /** The diagnostics, or the refusal, as shown. */
  problems: string;
  /** The face as drawn after the change, a PNG's object URL. */
  thumb: string | null;
}

export interface Turn {
  role: "user" | "assistant";
  /** What is sent (a user turn), or the model's answer so far. */
  content: string;
  /** A user turn as typed, without the face's text. */
  shown: string;
  thinking: string;
  image?: string;
  streaming?: boolean;
  error?: string;
  applied?: Applied;
  /** The automatic fix round this turn is (0 for the person's own). */
  round: number;
  /** When the request went (`Date.now()`), on the model's turn: the dialog shows how long it has waited. */
  since?: number;
}

/** What the dialog shows: replaced as a whole on every change. */
export interface AssistState {
  /** What `GET /api/assist` said; null until asked. */
  status: AssistStatus | null;
  /** The picture to send with the first request. */
  image: string | null;
  turns: Turn[];
  /** The request being typed. */
  input: string;
  /** A request, the applying of its answer, or a fix round, is under way. */
  busy: boolean;
  sendPreview: boolean;
}

/** What the session needs of the editor: the face open, the watch viewed, and taking a changed face. */
export interface AssistHost {
  doc(): Summary | null;
  device(): string | null;
  accept(doc: Summary): void;
}

/** `file` as a JPEG data URL, at most `IMAGE_SIDE` on its longest side. */
async function shrink(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, IMAGE_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", 0.85);
}

async function dataUrlOf(url: string): Promise<string> {
  const blob = await (await fetch(url)).blob();
  return new Promise((done) => { const r = new FileReader(); r.onload = () => done(String(r.result)); r.readAsDataURL(blob); });
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

export class AssistSession {
  state: AssistState = { status: null, image: null, turns: [], input: "", busy: false, sendPreview: false };
  private readonly listeners = new Set<() => void>();
  // The chat as the model sees it, every request and answer so far.
  private history: Message[] = [];
  // The face the chat is about: a request made with another face open starts a new chat.
  private faceId: string | null = null;
  private controller: AbortController | null = null;
  // Counts the runs: `stop` and `reset` move it on, and whatever a run still
  // has in flight sees it moved and leaves the state alone.
  private run = 0;
  private statusAsked = false;
  private readonly host: AssistHost;

  constructor(host: AssistHost) { this.host = host; }

  /** The model has been told something: a later request is a change, and the picture has gone. */
  get started(): boolean { return this.history.length > 0; }

  /** `listener` is called after every change; the returned function stops it. */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private set(patch: Partial<AssistState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of [...this.listeners]) listener();
  }

  /** Ask the server, once, whether it was started with a model. */
  loadStatus(): void {
    if (this.statusAsked) return;
    this.statusAsked = true;
    fetch("api/assist").then((r) => r.json() as Promise<AssistStatus>).then(
      (status) => this.set({ status }),
      () => { this.statusAsked = false; this.set({ status: { enabled: false } }); },
    );
  }

  setInput(input: string): void { this.set({ input }); }
  setSendPreview(sendPreview: boolean): void { this.set({ sendPreview }); }

  async pick(file: File | undefined): Promise<void> {
    if (!file) return;
    try { this.set({ image: await shrink(file) }); } catch (e) { this.push({ role: "assistant", content: "", shown: "", thinking: "", error: `cannot read the picture: ${String(e)}`, round: 0 }); }
  }

  /** Stop the run in flight: the model's answer so far stays shown, and no fix round follows. */
  stop(): void {
    if (!this.state.busy) return;
    this.run++;
    this.controller?.abort();
    this.controller = null;
    const last = this.state.turns[this.state.turns.length - 1];
    const turns = last?.streaming ? [...this.state.turns.slice(0, -1), { ...last, streaming: false, error: "stopped" }] : this.state.turns;
    // a request without its answer is not part of the chat
    if (this.history[this.history.length - 1]?.role === "user") this.history.pop();
    this.set({ turns, busy: false });
  }

  /** Forget the chat: the turns, the picture and what the model was told. A run in flight is stopped. */
  reset(): void {
    this.run++;
    this.controller?.abort();
    this.controller = null;
    for (const turn of this.state.turns) if (turn.applied?.thumb) URL.revokeObjectURL(turn.applied.thumb);
    this.history = [];
    this.faceId = null;
    this.set({ image: null, turns: [], input: "", busy: false });
  }

  /** The editor shows the face `docId` (null: the home screen): a chat about another face is reset. */
  follow(docId: string | null): void {
    if (docId !== null && this.faceId !== null && docId !== this.faceId) this.reset();
  }

  /** Send what was typed (and the picture, on the first request), then the fix rounds its answer needs. */
  async submit(): Promise<void> {
    const doc = this.host.doc();
    if (doc === null || this.state.busy) return;
    if (this.faceId !== null && this.faceId !== doc.id) this.reset();
    const { input, image } = this.state;
    const first = this.history.length === 0;
    if (!input.trim() && !(first && image)) return;
    this.faceId = doc.id;
    const run = ++this.run;
    this.set({ input: "", busy: true });
    const content = first ? firstRequest(input, doc.text, image !== null) : changeRequest(input);
    const images = first && image ? [image] : !first && this.state.sendPreview ? await this.previewImage(doc) : undefined;
    if (run !== this.run) return;
    let request = { content, shown: input.trim() || "Make the face look like the picture", images };
    for (let round = 0; ; round++) {
      const answer = await this.ask(run, request.content, request.shown, round, request.images);
      if (answer === null) break;
      const applied = await this.apply(answer);
      if (run !== this.run) break;
      this.edit(run, (t) => ({ ...t, applied }));
      // the editor's errors go back by themselves, a few rounds at most
      if ((applied.ok && applied.errors === 0) || round >= MAX_FIX_ROUNDS) break;
      const attach = this.state.sendPreview && applied.thumb ? [await dataUrlOf(applied.thumb)] : undefined;
      if (run !== this.run) break;
      request = { content: fixRequest(applied.problems), shown: applied.ok ? `Fix the ${plural(applied.errors, "error")}` : "Fix: the answer could not be applied", images: attach };
    }
    if (run === this.run) { this.controller = null; this.set({ busy: false }); }
  }

  private push(...turns: Turn[]): void { this.set({ turns: [...this.state.turns, ...turns] }); }

  // Change the newest turn, unless the run that made it was stopped or reset since.
  private edit(run: number, f: (turn: Turn) => Turn): void {
    if (run !== this.run) return;
    this.set({ turns: this.state.turns.map((t, i, ts) => (i === ts.length - 1 ? f(t) : t)) });
  }

  // One request: the chat so far plus `content`, streamed into a new turn. The answer, or null when it failed or was stopped.
  private async ask(run: number, content: string, shown: string, round: number, images?: string[]): Promise<string | null> {
    this.history.push({ role: "user", content, ...(images?.length ? { images } : {}) });
    const messages = [...this.history];
    this.push(
      { role: "user", content, shown, thinking: "", round, ...(images?.[0] ? { image: images[0] } : {}) },
      { role: "assistant", content: "", shown: "", thinking: "", streaming: true, round, since: Date.now() },
    );
    const controller = new AbortController();
    this.controller = controller;
    let answer = "";
    let failed = false;
    try {
      const response = await fetch("api/assist", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages, targets: this.host.doc()?.targets ?? [] }), signal: controller.signal,
      });
      if (!response.ok) {
        let message = `${response.status}`;
        try { message = ((await response.json()) as { error?: string }).error ?? message; } catch { /* no body */ }
        this.edit(run, (t) => ({ ...t, error: message }));
        failed = true;
      } else {
        for await (const event of readEvents(response.body)) {
          if (event.kind === "thinking") this.edit(run, (t) => ({ ...t, thinking: t.thinking + event.text }));
          else if (event.kind === "text") { answer += event.text; this.edit(run, (t) => ({ ...t, content: t.content + event.text })); }
          else if (event.kind === "error") { this.edit(run, (t) => ({ ...t, error: event.message })); failed = true; }
        }
      }
    } catch (e) {
      if (!controller.signal.aborted) this.edit(run, (t) => ({ ...t, error: String(e) }));
      failed = true;
    }
    // stopped or reset meanwhile: `stop` has already set the chat and the turns right
    if (run !== this.run || controller.signal.aborted) return null;
    this.edit(run, (t) => ({ ...t, streaming: false }));
    // a request that failed is not part of the chat
    if (failed) { this.history.pop(); return null; }
    this.history.push({ role: "assistant", content: answer });
    return answer;
  }

  // Apply the answer's YAML to the chat's face; what came of it, with the thumbnail.
  private async apply(answer: string): Promise<Applied> {
    const yaml = extractYaml(answer);
    if (yaml === null || this.faceId === null) return { ok: false, errors: 1, warnings: 0, problems: "the answer holds no YAML block", thumb: null };
    const open = this.host.doc();
    let face = open?.id === this.faceId ? open : await api("get", { id: this.faceId });
    let response = await call("text", { id: face.id, version: face.version, text: yaml, label: "Assist" });
    if (response.status === 409) {
      // the face moved on meanwhile (another tab, the YAML pane): apply over where it is now
      face = await api("get", { id: face.id });
      response = await call("text", { id: face.id, version: face.version, text: yaml, label: "Assist" });
    }
    if (response.status !== 200) return { ok: false, errors: 1, warnings: 0, problems: response.json?.error ?? `${response.status}`, thumb: null };
    const summary = response.json!;
    this.host.accept(summary);
    const errors = summary.diagnostics.filter((d) => d.severity === "error").length;
    const warnings = summary.diagnostics.filter((d) => d.severity === "warning").length;
    const device = this.host.device();
    const target = device && summary.targets.includes(device) ? device : summary.targets[0];
    let thumb: string | null = null;
    if (target && summary.loads) {
      try { thumb = await objectUrl("thumbnail", { id: summary.id, device: target, v: summary.version }); } catch { thumb = null; }
    }
    return { ok: true, errors, warnings, problems: diagnosticsText(summary.diagnostics), thumb };
  }

  // The face as drawn for the watch viewed, to send with a later request.
  private async previewImage(face: Summary): Promise<string[] | undefined> {
    const device = this.host.device();
    const target = device && face.targets.includes(device) ? device : face.targets[0];
    if (!target || !face.loads) return undefined;
    try { return [await dataUrlOf(await objectUrl("thumbnail", { id: face.id, device: target, v: face.version }))]; } catch { return undefined; }
  }
}
