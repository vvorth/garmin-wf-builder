// Assist… against the real page and a fake Ollama: the model's thinking and
// answer stream into the transcript, the answer's YAML is applied to the
// face, the editor's errors go back by themselves, and the corrected
// answer lands as a change undo takes back.

import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after } from "node:test";
import { suite } from "./harness.ts";

/** The YAML of the face the page sent, from the first request's fenced block. */
function faceOf(messages: { role: string; content: string }[]): string {
  const first = messages.find((m) => m.role === "user")!;
  return /```yaml\n([\s\S]*?)```/.exec(first.content)![1]!;
}

// The model: its first answer puts an unknown key in `face:` (one error for
// the editor to report), its second returns the face renamed. Asked to take
// its time, it thinks and never answers, until the page gives up.
let rounds = 0;
let slow = { asked: 0, closed: 0 };
const model = createServer((request, response) => {
  const chunks: Buffer[] = [];
  request.on("data", (c: Buffer) => chunks.push(c));
  request.on("end", () => {
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as { messages: { role: string; content: string; images?: string[] }[] };
    const last = body.messages[body.messages.length - 1]!;
    if (last.content.startsWith("take your time")) {
      slow.asked++;
      response.on("close", () => { slow.closed++; });
      response.writeHead(200, { "Content-Type": "application/x-ndjson" });
      response.write(JSON.stringify({ message: { role: "assistant", thinking: "pondering" } }) + "\n");
      return;
    }
    rounds++;
    const fixing = last.content.startsWith("The editor reports these problems");
    const yaml = fixing
      ? faceOf(body.messages).replace(/^  name: .*$/m, "  name: Assisted")
      : faceOf(body.messages).replace(/^face:\n/m, "face:\n  colour: red\n");
    const lines = [
      { message: { role: "assistant", thinking: fixing ? "the key was wrong" : "a first try" } },
      { message: { role: "assistant", content: fixing ? "Fixed.\n```yaml\n" : "Here.\n```yaml\n" } },
      { message: { role: "assistant", content: yaml } },
      { message: { role: "assistant", content: "```\n" } },
      { message: { role: "assistant", content: "" }, done: true },
    ];
    response.writeHead(200, { "Content-Type": "application/x-ndjson" });
    response.end(lines.map((l) => JSON.stringify(l)).join("\n") + "\n");
  });
});
await new Promise<void>((done) => model.listen(0, "127.0.0.1", done));
after(() => new Promise<void>((done) => model.close(() => done())));
const modelUrl = `http://127.0.0.1:${(model.address() as { port: number }).port}`;

const h = await suite(import.meta.url, { args: ["--assist", "ollama", "--assist-url", modelUrl, "--assist-model", "fake"] });

h.test("Assist… applies the model's face, sends its errors back, and the fixed answer is one undoable change", async (s) => {
  const doc = await s.openTemplate("minimal", "Before");
  await s.waitFace();
  await s.waitIdle();
  await s.page.locator(".topbar button", { hasText: "Assist…" }).click();
  const modal = s.page.locator(".modal.assist");
  await modal.waitFor();
  await s.expectText(modal.locator(".assist-body > .dim.small"), /ollama · fake at http/);
  await modal.locator("input[type=text]").fill("rename it");
  await modal.locator("button.primary", { hasText: "Send" }).click();
  // two answers: the first with an error the editor reports, then the fix, each with its thinking
  await modal.locator(".assist-turn.assistant").nth(1).locator(".assist-result").waitFor({ timeout: 60_000 });
  assert.equal(rounds, 2);
  assert.deepEqual(await modal.locator(".assist-thinking pre").allTextContents(), ["a first try", "the key was wrong"]);
  const results = await modal.locator(".assist-result > div > div:first-child").allTextContents();
  assert.match(results[0]!, /error/);
  assert.equal(results[1], "Applied");
  // the editor's own turn carried the error to the model
  await s.expectText(modal.locator(".assist-turn.user.auto .said"), /^Fix the 1 error$/);
  assert.equal((await modal.locator(".assist-result img").count()), 1, "the fixed face is drawn; the broken one is not");
  assert.match((await s.doc()).text, /^  name: Assisted$/m);
  await modal.locator(".modal-head button").click();
  await modal.waitFor({ state: "detached" });
  // each applied answer is one change: undo takes the fix back, then the first answer
  await s.undo();
  const undone = (await s.doc()).text;
  assert.doesNotMatch(undone, /Assisted/);
  assert.match(undone, /^  colour: red$/m);
  await s.undo();
  assert.equal((await s.doc()).text, doc.text);
  assert.deepEqual(s.errors, []);
});

h.test("Assist… keeps its chat when closed, a request going on; Stop cancels it at the model; Reset and another face clear it", async (s) => {
  await s.openTemplate("minimal", "Slow");
  await s.waitFace();
  await s.waitIdle();
  slow = { asked: 0, closed: 0 };
  const button = s.page.locator(".topbar button", { hasText: "Assist…" });
  await button.click();
  const modal = s.page.locator(".modal.assist");
  await modal.locator("input[type=text]").fill("take your time");
  await modal.locator("button.primary", { hasText: "Send" }).click();
  await s.expectText(modal.locator(".assist-thinking pre"), /^pondering$/);
  // closed (here by a click outside it): the request goes on, and the top bar says so
  await s.page.locator(".modal-back").click({ position: { x: 4, y: 4 } });
  await modal.waitFor({ state: "detached" });
  await s.expectText(button, /●/);
  assert.equal(slow.closed, 0, "closing the dialog does not cancel the request");
  await button.click();
  await s.expectText(modal.locator(".assist-thinking pre"), /^pondering$/);
  assert.equal(await modal.locator(".assist-turn.user .said").textContent(), "take your time");
  // Stop: the turn says so, the model's connection is closed, and Send is back
  await modal.locator("button.assist-stop").click();
  await s.expectText(modal.locator(".assist-turn.assistant .error-text"), /^stopped$/);
  for (let i = 0; i < 50 && slow.closed === 0; i++) await new Promise((r) => setTimeout(r, 100));
  assert.equal(slow.closed, 1, "the server cancels the model's request");
  assert.equal(slow.asked, 1);
  await modal.locator("button.primary", { hasText: "Send" }).waitFor();
  assert.doesNotMatch((await button.textContent())!, /●/);
  // what is typed survives closing too
  await modal.locator("input[type=text]").fill("a draft");
  await modal.locator(".modal-head button").click();
  await button.click();
  assert.equal(await modal.locator("input[type=text]").inputValue(), "a draft");
  // Reset: the chat and the draft are gone, and the picture can be chosen again
  await modal.locator("button.assist-reset").click();
  assert.equal(await modal.locator(".assist-turn").count(), 0);
  assert.equal(await modal.locator("input[type=text]").inputValue(), "");
  await modal.locator("button", { hasText: "Picture…" }).waitFor();
  // a chat belongs to its face: opening another one starts afresh
  await modal.locator("input[type=text]").fill("take your time");
  await modal.locator("button.primary", { hasText: "Send" }).click();
  await s.expectText(modal.locator(".assist-thinking pre"), /^pondering$/);
  await modal.locator(".modal-head button").click();
  await s.openTemplate("minimal", "Other");
  await s.waitFace();
  for (let i = 0; i < 50 && slow.closed < 2; i++) await new Promise((r) => setTimeout(r, 100));
  assert.equal(slow.closed, 2, "the other face's request is cancelled");
  await button.click();
  assert.equal(await modal.locator(".assist-turn").count(), 0);
  assert.doesNotMatch((await button.textContent())!, /●/);
  assert.deepEqual(s.errors, []);
});
