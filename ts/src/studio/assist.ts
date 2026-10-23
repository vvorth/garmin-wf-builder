// The editor's assistant: a chat with a vision model that writes the face.
// Shared by the server (which talks to the model) and the page (which
// keeps the transcript and applies each answer): no `node:` imports.
//
// The server streams the model's answer as newline-delimited JSON events
// (`Event`): `thinking` and `text` as they arrive, then `done`, or `error`.
// Two providers: Ollama's own `/api/chat` (which streams a model's
// thinking separately) and any OpenAI-compatible `/chat/completions`.
import * as catalog from "../catalog.ts";
import * as complications from "../complications.ts";
import type { DeviceDatabase } from "../devices/device.ts";
import * as icons from "../icons.ts";
import { PROMPT } from "./assist-prompt.ts";
import type { Diagnostic } from "./protocol.ts";

export type Provider = "ollama" | "openai";

export interface AssistConfig {
  provider: Provider;
  /** Ollama: the server's address. OpenAI: the base ending in `/v1`. */
  url: string;
  model: string;
  /** `Authorization: Bearer`, OpenAI only. */
  key?: string | null;
  /** Ollama: `num_ctx`, the context window in tokens. */
  context?: number;
}

export const DEFAULTS = { url: "http://127.0.0.1:11434", model: "qwen3-vl:8b", context: 16384 } as const;

/** One turn of the chat, as the page sends it. Images are data URLs (`data:image/jpeg;base64,…`). */
export interface Message {
  role: "user" | "assistant";
  content: string;
  images?: string[];
}

export type Event =
  | { kind: "thinking"; text: string }
  | { kind: "text"; text: string }
  | { kind: "done" }
  | { kind: "error"; message: string };

/** What the page posts to `/api/assist`. */
export interface AssistRequest {
  messages: Message[];
  /** The face's targets: the vocabulary names their fonts. */
  targets: string[];
}

/** What `GET /api/assist` answers. */
export interface AssistStatus {
  enabled: boolean;
  provider?: Provider;
  model?: string;
  url?: string;
}

/** The automatic rounds of "fix these errors" after one answer. */
export const MAX_FIX_ROUNDS = 3;

// -- the prompt ---------------------------------------------------------------

/** The vocabulary the model may use, for `targets`: the watches, their fonts, every source, icon and complication type. */
export function vocabulary(db: DeviceDatabase, targets: readonly string[]): string {
  const lines: string[] = ["## The watches and their fonts", ""];
  for (const id of targets) {
    let device;
    try { device = db.get(id); } catch { continue; }
    lines.push(`- ${id}: ${device.width}x${device.height} ${device.shape}, ${device.displayType ?? "mip"}, API ${device.apiLevel}`);
    const system = [...device.systemFonts.values()].map((m) => `${m.symbol} (${m.size_px}px)`);
    if (system.length > 0) lines.push(`  system fonts: ${system.join(", ")}`);
    if (device.scalableFaces.length > 0) lines.push(`  scalable faces: ${device.scalableFaces.join(", ")}`);
  }
  lines.push("", "## Data sources (path, type, meaning; nullable ones need absent:)", "");
  for (const [namespace, paths] of catalog.namespaces()) {
    lines.push(`${namespace}:`);
    for (const path of paths) {
      const source = catalog.CATALOG.get(path)!;
      lines.push(`  ${path}  ${source.type}  ${source.doc}${catalog.guardNeeded(source) ? "  [nullable]" : ""}`);
    }
  }
  lines.push("", `## Icons: ${icons.names().join(", ")}`);
  lines.push("", `## Slot choices and on_hold: targets: auto, ${complications.names().join(", ")}`);
  return lines.join("\n");
}

export function systemPrompt(vocabularyText: string): string {
  return `${PROMPT}\n${vocabularyText}\n`;
}

/** The first request: the picture (when there is one), the request, and the face as it is. */
export function firstRequest(text: string, yaml: string, withImage: boolean): string {
  const ask = text.trim() || (withImage ? "Make the face look like the attached picture." : "Improve the face.");
  const picture = withImage ? "The attached picture is the face to reproduce. " : "";
  return `${picture}${ask}\n\nThe face as it is now:\n\`\`\`yaml\n${yaml.trimEnd()}\n\`\`\``;
}

/** A later request: the change asked for. */
export function changeRequest(text: string): string {
  return text.trim();
}

/** The diagnostics as the model reads them, errors first. */
export function diagnosticsText(diagnostics: readonly Diagnostic[]): string {
  const order = { error: 0, warning: 1, note: 2 } as Record<string, number>;
  return [...diagnostics]
    .sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3))
    .map((d) => `${d.severity}${d.line !== undefined ? ` (line ${d.line})` : ""} [${d.code}]: ${d.message}${d.notes.length ? "\n" + d.notes.map((n) => `    ${n}`).join("\n") : ""}`)
    .join("\n");
}

/** The request after an answer the editor refused or faulted: what to fix. */
export function fixRequest(problems: string): string {
  return `The editor reports these problems with your YAML:\n${problems}\n\nFix them and return the whole face.yaml again in one \`\`\`yaml block.`;
}

/** The YAML in an answer: the last fenced yaml block, or the whole answer when it is bare YAML. */
export function extractYaml(answer: string): string | null {
  const fences = [...answer.matchAll(/```(?:ya?ml)?[ \t]*\r?\n([\s\S]*?)```/g)];
  if (fences.length > 0) {
    const yaml = fences.map((m) => m[1]!).filter((b) => /^\s*format:/m.test(b));
    return (yaml.length > 0 ? yaml[yaml.length - 1] : fences[fences.length - 1]![1])!.trimEnd() + "\n";
  }
  const bare = answer.trim();
  return /^format:\s*2/m.test(bare) && !/^[A-Z][^\n]*\.$/m.test(bare.split("\n")[0]!) ? bare + "\n" : null;
}

// -- the providers ------------------------------------------------------------

const dataUrl = /^data:([^;,]+);base64,(.*)$/s;

/** A data URL's bytes, base64, as Ollama takes them. */
function base64Of(image: string): string {
  const m = dataUrl.exec(image);
  return m ? m[2]! : image;
}

async function* lines(body: ReadableStream<Uint8Array> | null): AsyncGenerator<string> {
  if (body === null) return;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let rest = "";
  for (;;) {
    const { done, value } = await reader.read();
    rest += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const parts = rest.split("\n");
    rest = done ? "" : parts.pop()!;
    for (const line of parts) if (line.trim() !== "") yield line;
    if (done) return;
  }
}

async function* ollama(config: AssistConfig, system: string, messages: Message[], signal: AbortSignal | undefined, fetcher: Fetch): AsyncGenerator<Event> {
  const body: Record<string, unknown> = {
    model: config.model, stream: true, think: true, options: { num_ctx: config.context ?? DEFAULTS.context },
    messages: [{ role: "system", content: system }, ...messages.map((m) => ({ role: m.role, content: m.content, ...(m.images?.length ? { images: m.images.map(base64Of) } : {}) }))],
  };
  const post = (): Promise<Response> => fetcher(`${config.url.replace(/\/$/, "")}/api/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: signal ?? null,
  });
  let response = await post();
  if (response.status === 400) {
    // a model with no thinking refuses `think`: ask again without it
    const text = await response.text();
    if (!/think/i.test(text)) { yield { kind: "error", message: `${config.model}: ${text}` }; return; }
    delete body["think"];
    response = await post();
  }
  if (!response.ok) { yield { kind: "error", message: `${response.status} from ${config.url}: ${(await response.text()).slice(0, 500)}` }; return; }
  for await (const line of lines(response.body)) {
    let chunk: { message?: { content?: string; thinking?: string }; done?: boolean; error?: string };
    try { chunk = JSON.parse(line); } catch { continue; }
    if (chunk.error) { yield { kind: "error", message: chunk.error }; return; }
    if (chunk.message?.thinking) yield { kind: "thinking", text: chunk.message.thinking };
    if (chunk.message?.content) yield { kind: "text", text: chunk.message.content };
    if (chunk.done) { yield { kind: "done" }; return; }
  }
  yield { kind: "done" };
}

async function* openai(config: AssistConfig, system: string, messages: Message[], signal: AbortSignal | undefined, fetcher: Fetch): AsyncGenerator<Event> {
  const content = (m: Message): unknown => m.images?.length
    ? [{ type: "text", text: m.content }, ...m.images.map((url) => ({ type: "image_url", image_url: { url } }))]
    : m.content;
  const body = { model: config.model, stream: true, messages: [{ role: "system", content: system }, ...messages.map((m) => ({ role: m.role, content: content(m) }))] };
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (config.key) headers["Authorization"] = `Bearer ${config.key}`;
  const response = await fetcher(`${config.url.replace(/\/$/, "")}/chat/completions`, { method: "POST", headers, body: JSON.stringify(body), signal: signal ?? null });
  if (!response.ok) { yield { kind: "error", message: `${response.status} from ${config.url}: ${(await response.text()).slice(0, 500)}` }; return; }
  for await (const line of lines(response.body)) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (data === "[DONE]") { yield { kind: "done" }; return; }
    let chunk: { choices?: { delta?: { content?: string | null; reasoning?: string | null; reasoning_content?: string | null } }[]; error?: { message?: string } | string };
    try { chunk = JSON.parse(data); } catch { continue; }
    if (chunk.error) { yield { kind: "error", message: typeof chunk.error === "string" ? chunk.error : chunk.error.message ?? "the model failed" }; return; }
    const delta = chunk.choices?.[0]?.delta;
    const thinking = delta?.reasoning ?? delta?.reasoning_content;
    if (thinking) yield { kind: "thinking", text: thinking };
    if (delta?.content) yield { kind: "text", text: delta.content };
  }
  yield { kind: "done" };
}

/** The model's answer to `messages` under `system`, as it streams. A failure to reach the model is an `error` event, not a throw. */
/** The one call a provider makes: `fetch`'s shape, so the server can hand in one without its timeouts. */
export type Fetch = (url: string, init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal | null }) => Promise<Response>;

export async function* chat(config: AssistConfig, system: string, messages: Message[], signal?: AbortSignal, fetcher: Fetch = fetch): AsyncGenerator<Event> {
  try {
    yield* config.provider === "ollama" ? ollama(config, system, messages, signal, fetcher) : openai(config, system, messages, signal, fetcher);
  } catch (e) {
    if (signal?.aborted) return;
    yield { kind: "error", message: `cannot reach ${config.url}: ${(e as Error).message}` };
  }
}

/** `events` read back from the server's newline-delimited stream. */
export async function* readEvents(body: ReadableStream<Uint8Array> | null): AsyncGenerator<Event> {
  for await (const line of lines(body)) {
    try { yield JSON.parse(line) as Event; } catch { /* a cut-off line */ }
  }
}
