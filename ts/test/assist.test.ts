// The editor's assistant: the two providers read through a fake model
// server, the prompt's vocabulary, the YAML an answer is read for, and
// the server's `/api/assist` route streaming the events through.
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { after, test } from "node:test";
import { type AssistConfig, type Event, chat, diagnosticsText, extractYaml, fixRequest, firstRequest, readEvents, systemPrompt, vocabulary } from "../src/studio/assist.ts";
import { start } from "../src/studio/server.ts";
import { db } from "./studio-client.ts";

/** A model server answering every POST with `body` (status 200), or `status` with `text`; it records what it was asked. */
function fakeModel(answer: (path: string, body: string) => { status: number; text: string; type?: string }): Promise<{ url: string; asked: { path: string; body: string }[]; close: () => Promise<void> }> {
  const asked: { path: string; body: string }[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (c: Buffer) => chunks.push(c));
    request.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf8");
      asked.push({ path: request.url ?? "", body });
      const a = answer(request.url ?? "", body);
      response.writeHead(a.status, { "Content-Type": a.type ?? "application/json" });
      response.end(a.text);
    });
  });
  return new Promise((done) => server.listen(0, "127.0.0.1", () => {
    const port = (server.address() as { port: number }).port;
    done({ url: `http://127.0.0.1:${port}`, asked, close: () => new Promise((ok) => server.close(() => ok())) });
  }));
}

const ollamaLines = (parts: { thinking?: string; content?: string }[]): string =>
  [...parts.map((p) => JSON.stringify({ message: { role: "assistant", ...p } })), JSON.stringify({ message: { role: "assistant", content: "" }, done: true })].join("\n") + "\n";

const sse = (deltas: Record<string, string>[]): string =>
  [...deltas.map((d) => `data: ${JSON.stringify({ choices: [{ delta: d }] })}`), "data: [DONE]"].join("\n\n") + "\n\n";

async function collect(events: AsyncIterable<Event>): Promise<Event[]> {
  const out: Event[] = [];
  for await (const e of events) out.push(e);
  return out;
}

const ANSWER = "Here it is.\n```yaml\nformat: 2\nface:\n  name: X\n```\n";

test("ollama: thinking and text stream as events, the picture goes as base64, and the system prompt leads", async () => {
  const model = await fakeModel(() => ({ status: 200, text: ollamaLines([{ thinking: "hmm " }, { thinking: "ok" }, { content: "Here" }, { content: " it is." }]), type: "application/x-ndjson" }));
  after(model.close);
  const config: AssistConfig = { provider: "ollama", url: model.url, model: "m", context: 2048 };
  const events = await collect(chat(config, "SYSTEM", [{ role: "user", content: "hi", images: ["data:image/jpeg;base64,AAAA"] }]));
  assert.deepEqual(events, [{ kind: "thinking", text: "hmm " }, { kind: "thinking", text: "ok" }, { kind: "text", text: "Here" }, { kind: "text", text: " it is." }, { kind: "done" }]);
  assert.equal(model.asked[0]!.path, "/api/chat");
  const sent = JSON.parse(model.asked[0]!.body);
  assert.equal(sent.model, "m");
  assert.equal(sent.think, true);
  assert.equal(sent.options.num_ctx, 2048);
  assert.deepEqual(sent.messages[0], { role: "system", content: "SYSTEM" });
  assert.deepEqual(sent.messages[1], { role: "user", content: "hi", images: ["AAAA"] });
});

test("ollama: a model with no thinking refuses `think` once, and is asked again without it", async () => {
  let calls = 0;
  const model = await fakeModel((_, body) => {
    calls++;
    if (JSON.parse(body).think) return { status: 400, text: JSON.stringify({ error: "\"m\" does not support thinking" }) };
    return { status: 200, text: ollamaLines([{ content: "plain" }]), type: "application/x-ndjson" };
  });
  after(model.close);
  const events = await collect(chat({ provider: "ollama", url: model.url, model: "m" }, "S", [{ role: "user", content: "hi" }]));
  assert.deepEqual(events, [{ kind: "text", text: "plain" }, { kind: "done" }]);
  assert.equal(calls, 2);
  assert.equal("think" in JSON.parse(model.asked[1]!.body), false);
});

test("ollama: a failure mid-stream, a refused request and an unreachable server are error events, not throws", async () => {
  const failing = await fakeModel(() => ({ status: 200, text: JSON.stringify({ message: { content: "a" } }) + "\n" + JSON.stringify({ error: "out of memory" }) + "\n", type: "application/x-ndjson" }));
  after(failing.close);
  assert.deepEqual(await collect(chat({ provider: "ollama", url: failing.url, model: "m" }, "S", [])), [{ kind: "text", text: "a" }, { kind: "error", message: "out of memory" }]);
  const refusing = await fakeModel(() => ({ status: 404, text: JSON.stringify({ error: "model 'm' not found" }) }));
  after(refusing.close);
  const [refused] = await collect(chat({ provider: "ollama", url: refusing.url, model: "m" }, "S", []));
  assert.equal(refused!.kind, "error");
  assert.match((refused as { message: string }).message, /404 .*not found/);
  const [unreachable] = await collect(chat({ provider: "ollama", url: "http://127.0.0.1:9", model: "m" }, "S", []));
  assert.equal(unreachable!.kind, "error");
  assert.match((unreachable as { message: string }).message, /cannot reach http:\/\/127\.0\.0\.1:9/);
});

test("openai: SSE deltas with reasoning stream as events, the key is a bearer, the picture is an image_url part", async () => {
  const model = await fakeModel(() => ({ status: 200, text: sse([{ reasoning: "think" }, { content: "Here" }, { reasoning_content: "more" }, { content: " it is." }]), type: "text/event-stream" }));
  after(model.close);
  const config: AssistConfig = { provider: "openai", url: `${model.url}/v1/`, model: "m", key: "sk-1" };
  const events = await collect(chat(config, "SYSTEM", [{ role: "user", content: "hi", images: ["data:image/png;base64,BBBB"] }, { role: "assistant", content: "ok" }]));
  assert.deepEqual(events, [{ kind: "thinking", text: "think" }, { kind: "text", text: "Here" }, { kind: "thinking", text: "more" }, { kind: "text", text: " it is." }, { kind: "done" }]);
  assert.equal(model.asked[0]!.path, "/v1/chat/completions");
  const sent = JSON.parse(model.asked[0]!.body);
  assert.equal(sent.stream, true);
  assert.deepEqual(sent.messages[1].content, [{ type: "text", text: "hi" }, { type: "image_url", image_url: { url: "data:image/png;base64,BBBB" } }]);
  assert.deepEqual(sent.messages[2], { role: "assistant", content: "ok" });
});

test("openai: the key travels as a bearer header and never in the body", async () => {
  let auth: string | undefined;
  const server = createServer((request, response) => {
    auth = request.headers.authorization;
    request.resume();
    request.on("end", () => { response.writeHead(200, { "Content-Type": "text/event-stream" }); response.end(sse([{ content: "x" }])); });
  });
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  after(() => new Promise<void>((done) => server.close(() => done())));
  const url = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  await collect(chat({ provider: "openai", url, model: "m", key: "sk-secret" }, "S", []));
  assert.equal(auth, "Bearer sk-secret");
});

test("extractYaml: the last fenced yaml block, a bare YAML answer, and prose with none", () => {
  assert.equal(extractYaml(ANSWER), "format: 2\nface:\n  name: X\n");
  assert.equal(extractYaml("first:\n```yaml\nformat: 2\na: 1\n```\nthen\n```yaml\nformat: 2\na: 2\n```\n"), "format: 2\na: 2\n");
  // a yaml block that is a snippet loses to the one that is the file
  assert.equal(extractYaml("```yaml\nformat: 2\na: 1\n```\nnote:\n```yaml\n  dy: 3%r\n```"), "format: 2\na: 1\n");
  assert.equal(extractYaml("```\nformat: 2\nb: 1\n```"), "format: 2\nb: 1\n");
  assert.equal(extractYaml("format: 2\nface:\n  name: Y\n"), "format: 2\nface:\n  name: Y\n");
  assert.equal(extractYaml("I cannot see the picture."), null);
});

test("the prompt carries the targets' fonts, every source and icon, and the requests say what they are for", () => {
  const id = db.ids()[0]!;
  const device = db.get(id);
  const text = vocabulary(db, [id, "no-such-watch"]);
  assert.match(text, new RegExp(`^- ${id}: ${device.width}x${device.height}`, "m"));
  for (const metric of device.systemFonts.values()) assert.ok(text.includes(`${metric.symbol} (${metric.size_px}px)`), metric.symbol);
  assert.ok(!text.includes("no-such-watch"));
  assert.match(text, /^  activity\.steps  number  /m);
  assert.match(text, /^  heart_rate\.current  number  .*\[nullable\]$/m);
  assert.match(text, /^## Icons: .*\bheart\b/m);
  assert.match(text, /^## Slot choices and on_hold: targets: auto, .*\bbody_battery\b/m);
  const system = systemPrompt(text);
  assert.ok(system.startsWith("You design Garmin Connect IQ watch faces"));
  assert.ok(system.includes(text));
  const first = firstRequest("  ", "format: 2\n", true);
  assert.match(first, /^The attached picture is the face to reproduce\. Make the face look like the attached picture\./);
  assert.ok(first.endsWith("```yaml\nformat: 2\n```"));
  assert.match(firstRequest("red", "format: 2\n", false), /^red\n/);
  assert.match(fixRequest("error [x]: y"), /^The editor reports these problems with your YAML:\nerror \[x\]: y\n/);
  assert.equal(diagnosticsText([
    { severity: "warning", code: "w", message: "W", notes: [] },
    { severity: "error", code: "e", message: "E", notes: ["n1"], line: 3 },
  ]), "error (line 3) [e]: E\n    n1\nwarning [w]: W");
});

test("the server: GET says what is configured, POST streams the model's events, and without --assist refuses", async () => {
  const model = await fakeModel(() => ({ status: 200, text: ollamaLines([{ thinking: "t" }, { content: ANSWER }]), type: "application/x-ndjson" }));
  after(model.close);
  const assisted = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null, assist: { provider: "ollama", url: model.url, model: "m", key: "never-sent" } });
  after(assisted.close);
  const base = `http://127.0.0.1:${assisted.port}`;
  const status = await (await fetch(`${base}/api/assist`)).json();
  assert.deepEqual(status, { enabled: true, provider: "ollama", model: "m", url: model.url });
  const id = db.ids()[0]!;
  const posted = await fetch(`${base}/api/assist`, {
    method: "POST", headers: { "Content-Type": "application/json", Origin: base },
    body: JSON.stringify({ messages: [{ role: "user", content: "hi" }], targets: [id] }),
  });
  assert.equal(posted.status, 200);
  assert.equal(posted.headers.get("content-type"), "application/x-ndjson");
  const events = await collect(readEvents(posted.body));
  assert.deepEqual(events, [{ kind: "thinking", text: "t" }, { kind: "text", text: ANSWER }, { kind: "done" }]);
  const sent = JSON.parse(model.asked[0]!.body);
  assert.ok(sent.messages[0].content.includes(`- ${id}: `), "the system prompt names the target");
  assert.ok(!model.asked[0]!.body.includes("never-sent"));
  // a page elsewhere cannot use the model
  const foreign = await fetch(`${base}/api/assist`, { method: "POST", headers: { "Content-Type": "application/json", Origin: "http://evil.example" }, body: "{}" });
  assert.equal(foreign.status, 403);
  const bad = await fetch(`${base}/api/assist`, { method: "POST", headers: { "Content-Type": "application/json", Origin: base }, body: JSON.stringify({ messages: "x" }) });
  assert.equal(bad.status, 400);
  const plain = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null });
  after(plain.close);
  assert.deepEqual(await (await fetch(`http://127.0.0.1:${plain.port}/api/assist`)).json(), { enabled: false });
  const refused = await fetch(`http://127.0.0.1:${plain.port}/api/assist`, { method: "POST", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${plain.port}` }, body: JSON.stringify({ messages: [], targets: [] }) });
  assert.equal(refused.status, 503);
});

test("the server: the page has its headers at once and a blank line while the model is quiet; a refused `think` is asked again", async () => {
  // a model that keeps quiet for a while, as one on a CPU reading a long request does, and refuses `think` first
  let answered = false;
  const asked: string[] = [];
  const model = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (c: Buffer) => chunks.push(c));
    request.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf8");
      asked.push(body);
      if (JSON.parse(body).think) { response.writeHead(400, { "Content-Type": "application/json" }); response.end('{"error":"m does not support thinking"}'); return; }
      setTimeout(() => {
        answered = true;
        response.writeHead(200, { "Content-Type": "application/x-ndjson" });
        response.end(ollamaLines([{ content: ANSWER }]));
      }, 400);
    });
  });
  await new Promise<void>((done) => model.listen(0, "127.0.0.1", done));
  after(() => new Promise<void>((done) => model.close(() => done())));
  const url = `http://127.0.0.1:${(model.address() as { port: number }).port}`;
  const ask = async (keepAliveMs: number): Promise<Response> => {
    const server = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null, assist: { provider: "ollama", url, model: "m" }, keepAliveMs });
    after(server.close);
    const base = `http://127.0.0.1:${server.port}`;
    answered = false;
    return fetch(`${base}/api/assist`, {
      method: "POST", headers: { "Content-Type": "application/json", Origin: base },
      body: JSON.stringify({ messages: [{ role: "user", content: "hi" }], targets: [db.ids()[0]!] }),
    });
  };
  // the headers go at once, without waiting for a blank line to carry them
  const first = await ask(60_000);
  assert.equal(first.status, 200);
  assert.equal(answered, false, "the headers come before the model's first word");
  assert.deepEqual(await collect(readEvents(first.body)), [{ kind: "text", text: ANSWER }, { kind: "done" }]);
  assert.equal(asked.length, 2);
  assert.equal(JSON.parse(asked[1]!).think, undefined);
  // blank lines while the model is quiet, which the page's reader skips
  const raw = await (await ask(50)).text();
  assert.match(raw, /^\n\n/, "blank lines while the model is quiet");
  assert.deepEqual(await collect(readEvents(new Response(raw).body)), [{ kind: "text", text: ANSWER }, { kind: "done" }]);
});

test("a labelled text replacement is its own history state; typing within the merge window stays one", async () => {
  const { newStudio, openExample } = await import("./studio-client.ts");
  const studio = await newStudio();
  const doc = openExample(studio, "examples/features/shapes/face.yaml");
  const states = (): string[] => (doc.history()["states"] as { label: string }[]).map((s) => s.label);
  const base = states().length;
  // the model's answers, one after the other, as the dialog applies them
  doc.replaceText(doc.text + "# one\n", doc.version, "Assist");
  doc.replaceText(doc.text + "# two\n", doc.version, "Assist");
  assert.deepEqual(states().slice(0, 2), ["Assist", "Assist"]);
  assert.equal(states().length, base + 2);
  // the YAML tab's typing, sent as it rests: one state while it goes on
  doc.replaceText(doc.text + "# a\n", doc.version);
  doc.replaceText(doc.text + "# b\n", doc.version);
  assert.equal(states().length, base + 3);
  assert.equal(states()[0], "edit the text");
  doc.undo(doc.version);
  assert.ok(doc.text.endsWith("# two\n"), "undo takes the typing back whole");
  doc.undo(doc.version);
  assert.ok(doc.text.endsWith("# one\n"), "then one answer");
});
