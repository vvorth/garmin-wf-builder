// The page's test harness: the page's own modules run in Node, over the
// minimal DOM in `studio_dom.mjs`, against a stand-in worker answering
// from a real face's summary (`tools/summary.ts`). Each script runs in its
// own Node process, as the page's modules keep module-level state.
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { REPO_ROOT } from "../src/devices/node.ts";
import { instantiate } from "../src/starters.ts";

export { instantiate };

const APP = join(REPO_ROOT, "ts", "app");
const SUMMARY = join(REPO_ROOT, "ts", "tools", "summary.ts");

export const appUri = (name: string): string => pathToFileURL(join(APP, name)).href;
// The page's view library as Node resolves it for the page's own modules,
// so a script rendering a component itself shares their Preact instance.
export const htmPreactUri: string = import.meta.resolve("htm/preact");
export const preactUri: string = import.meta.resolve("preact");
export const testUri = (name: string): string => pathToFileURL(join(import.meta.dirname, name)).href;
export const appText = (name: string): string => readFileSync(join(APP, name), "utf8");
export const repoText = (path: string): string => readFileSync(join(REPO_ROOT, path), "utf8");

// Python's comparisons, as the assertions were first written.
export const eq = (a: unknown, b: unknown): boolean => isDeepStrictEqual(a, b);
export const has = (container: unknown, item: unknown): boolean =>
  typeof container === "string" ? container.includes(item as string)
    : Array.isArray(container) ? container.some((x) => eq(x, item))
      : container instanceof Set ? container.has(item)
        : Object.hasOwn(container as object, item as string);
export const len = (x: unknown): number => (typeof x === "string" || Array.isArray(x) ? x.length : Object.keys(x as object).length);
export const count = (container: string | unknown[], item: unknown): number =>
  typeof container === "string" ? container.split(item as string).length - 1 : container.filter((x) => eq(x, item)).length;

/** A script run as an ES module in a fresh Node: its exit code and output. */
export function node(script: string): { returncode: number; stdout: string; stderr: string } {
  const done = spawnSync(process.execPath, ["--import", testUri("dist_hook.mjs"), "--input-type=module", "-e", script], { encoding: "utf8", maxBuffer: 64 << 20 });
  return { returncode: done.status ?? 1, stdout: done.stdout, stderr: done.stderr };
}

/** What a script printed, one JSON value a line; it must exit cleanly. */
function printed(script: string): unknown[] {
  const done = node(script);
  if (done.returncode !== 0) throw new Error(done.stderr.slice(-2000));
  return done.stdout.split("\n").filter((l) => l !== "").map((l) => JSON.parse(l));
}

const MODULES = ["hit", "values", "snap", "tree", "zoom", "outbox", "textsync", "session", "linediff", "keys"];

/** `script` run with the page's pure modules imported (`tree.ts` as `treeMod`): the one JSON value it prints. */
export async function run(script: string): Promise<any> {
  const imports = MODULES.map((m) => `import * as ${m === "tree" ? "treeMod" : m} from ${JSON.stringify(appUri(`${m}.ts`))};`).join("\n");
  return printed(`${imports}\n${script}`)[0];
}

let VOCABULARY: Record<string, unknown> = {};

/** `text` opened as the editor's worker opens it, after `steps`: its summary, documents and vocabulary. */
function summarised(text: string, steps: unknown[] | null = null): { summary: any; vocabulary: any; documents: any[] } {
  const out = JSON.parse(execFileSync(process.execPath, [SUMMARY, ...(steps ? [JSON.stringify(steps)] : [])],
    { input: text, cwd: join(REPO_ROOT, "ts"), encoding: "utf8", maxBuffer: 64 << 20 }));
  VOCABULARY = { ...VOCABULARY, ...out.vocabulary };
  return out;
}

/** `text`'s summary. */
export const summary = (text: string): any => summarised(text).summary;

const vocabulary = (): Record<string, unknown> => {
  if (Object.keys(VOCABULARY).length === 0) summary(instantiate("minimal", "T"));
  return VOCABULARY;
};

/**
 * The Face panel rendered over `summary`, then `body` run (it has `root`,
 * `find`, `click`, `settle`, `typeName`, `out` and `edits`): what it printed.
 */
export async function render(summary: unknown, body: string): Promise<any[]> {
  return printed(`
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { FacePanel } = await import(${JSON.stringify(appUri("panels.ts"))});
      const edits = [];
      const root = document.createElement("div");
      render(html\`<\${FacePanel} doc=\${${JSON.stringify(summary)}} vocab=\${${JSON.stringify({ ...vocabulary(), devices: [] })}}
        onEdit=\${(op) => edits.push(op)} onSelect=\${(id) => edits.push({select: id})}
        onUpload=\${() => {}} onStructure=\${() => {}}
        onReveal=\${(line, end) => edits.push({reveal: [line, end]})} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => root.all(pred);
      const within = (e, c) => { for (let p = e.parentNode; p; p = p.parentNode) if (cls(p) === c) return true; return false; };
      // Quiet: a few timer turns, which covers an effect's work (rendered,
      // then two timer turns). Counted in turns, not milliseconds, so a
      // slow machine waits as long as it needs.
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const click = async (e) => { e.click(); await settle(); };
      // the Face tab's nav: switch to the section whose title starts with \`title\`
      const openSection = async (title) => { await click(find((e) => e.localName === "button" && e.textContent.startsWith(title))[0]); };
      // a name typed into the open inline input, then Enter
      const typeName = async (value) => {
        const inputs = find((e) => e.localName === "input" && cls(e).startsWith("inline-name"));
        const input = inputs[inputs.length - 1];
        input.value = value; input.dispatch("input", { target: input }); await settle();
        input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      };
      const out = (v) => console.log(JSON.stringify(v));
      ${body}
    `);
}

/** A face with three changes and an error, its summary and the home list. */
export function faceFixture(): { summary: any; vocabulary: any; home: any } {
  const text = instantiate("minimal", "Morning");
  const steps: unknown[] = ["1.0.1", "1.0.2"].map((value) => ({ edit: { op: "set", path: ["face", "version"], value } }));
  const final = text.replace("version: 1.0.0", "version: 1.0.2");
  steps.push({ text: final.replace("color: color.dim", "color: color.nope") });
  const out = summarised(text, steps);
  out.summary.name = "Morning";
  return { summary: out.summary, vocabulary: out.vocabulary, home: {
    templates: [{ name: "minimal", blurb: "" }], store: "this browser", shared: true,
    documents: out.documents.map((d) => ({ ...d, name: "Morning" })) } };
}

/** The stand-in worker and browser the page's modules run against: `requests`, `sent()`, `unanswered`, `settle()`, `storage`, `press()`. */
function standIn(face: { summary: any; vocabulary: any; home: any; devices?: any[] }, route: string): string {
  return `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const app = document.createElement("div");
      document.getElementById = () => app;
      // the page's own query, over what it rendered (a popover's body is always in the DOM; an open one is not matched here)
      document.querySelector = (sel) => app.querySelector(sel);
      document.documentElement = document.createElement("html");   // CodeMirror reads it on import
      globalThis.window = globalThis;
      // the page's own listeners on the window, so a test can press keys
      const listeners = {};
      globalThis.addEventListener = (t, f) => { (listeners[t] ||= []).push(f); };
      globalThis.removeEventListener = (t, f) => { listeners[t] = (listeners[t] || []).filter((g) => g !== f); };
      const press = (key, mods = {}) => {
        const event = { key, ...mods, target: { closest: () => null }, prevented: false,
                         preventDefault() { this.prevented = true; } };
        for (const f of listeners.keydown || []) f(event);
        return event.prevented;
      };
      // this page's own storage, empty at load
      const storage = new Map();
      globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => { storage.set(k, String(v)); } };
      globalThis.location = { hash: ${JSON.stringify(route)}, href: "http://studio/", reload() {} };
      const summary = ${JSON.stringify(face["summary"])};
      const answers = {
        home: ${JSON.stringify(face["home"])},
        vocabulary: ${JSON.stringify({ ...face["vocabulary"], devices: face["devices"] ?? [] })},
      };
      answers[\`get \${summary.id}\`] = summary;
      // each face's editor-only state, as the worker keeps it beside the face
      const uiStates = {};
      // every request the page made, [op, args]; \`sent()\` the changes among them
      const requests = [];
      const READS = new Set(["home", "vocabulary", "get", "frame", "skin", "inspect", "history", "cover", "thumbnail", "handset", "ui_state"]);
      const sent = () => requests.filter(([op]) => !READS.has(op));
      // the editor's worker, answering from the face's summary; a test
      // replaces \`respond\` to answer differently
      let respond = (request, reply) => {
        const { op, args } = request;
        requests.push([op, args]);
        let body = answers[op === "get" ? \`get \${args.id}\` : op];
        if (op === "goto") body = summary;
        if (op === "rename") body = { id: summary.id, name: args.name };
        if (op === "ui_state") {
          if (args.action === "set") uiStates[args.id] = args.state;
          body = { state: uiStates[args.id] ?? {} };
        }
        // a frame is never drawn here: its answer waits in \`unanswered\` for a test to give
        if (body !== undefined) reply({ status: 200, json: body });
        else unanswered.push(reply);
      };
      const unanswered = [];
      // answers on their way to the page, which \`settle\` waits out
      let inflight = 0;
      globalThis.Worker = class {
        postMessage({ id, request }) {
          respond(request, (response) => {
            inflight++;
            setTimeout(() => { inflight--; this.onmessage({ data: { id, response } }); }, 0);
          });
        }
      };
      // Quiet: no answer on its way for a few timer turns, which covers an
      // effect's request (rendered, then two timer turns). Counted in turns,
      // not milliseconds, so a slow machine waits as long as it needs.
      const settle = async () => {
        for (let idle = 0; idle < 5;) {
          await new Promise((r) => setTimeout(r, 0));
          idle = inflight > 0 ? 0 : idle + 1;
        }
      };
      const out = (v) => console.log(JSON.stringify(v));
  `;
}

/**
 * The whole page loaded at `route` over a stand-in worker, then `body` run
 * (every request the page makes is in `requests`): what it printed.
 */
export async function page(face: { summary: any; vocabulary: any; home: any; devices?: any[] }, route: string, body: string): Promise<any[]> {
  return printed(`${standIn(face, route)}
      await import(${JSON.stringify(appUri("main.ts"))});
      await settle(); await settle();
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => app.all(pred);
      const button = (text) => find((e) => e.localName === "button" && e.textContent.trim().startsWith(text))[0];
      const click = async (e) => { e.click(); await settle(); };
      // a name typed into the open inline input, then Enter
      const typeName = async (value) => {
        const inputs = find((e) => e.localName === "input" && cls(e).startsWith("inline-name"));
        const input = inputs[inputs.length - 1];
        input.value = value; input.dispatch("input", { target: input }); await settle();
        input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      };
      ${body}
    `);
}

/**
 * The editor's store (`app/store.ts`) alone, over the same stand-in worker,
 * then `body` run with `EditorStore` and the store module (`storeMod`) in
 * scope: what it printed.
 */
export async function store(face: { summary: any; vocabulary: any; home: any; devices?: any[] }, body: string): Promise<any[]> {
  return printed(`${standIn(face, "#/")}
      const storeMod = await import(${JSON.stringify(appUri("store.ts"))});
      const { EditorStore } = storeMod;
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      ${body}
    `);
}

/**
 * Wraps the stand-in worker so a test holds back the answer to each change
 * until it calls `release(i, status)` (200 answers the face one version
 * on, anything else refuses).
 */
export const DEFERRED_FETCH = `
      const held = [];
      const serve = respond;
      respond = (request, reply) => {
        if (READS.has(request.op)) return serve(request, reply);
        requests.push([request.op, request.args]);
        held.push((status) => reply({ status, json: status === 200 ? { ...summary, version: summary.version + 1 }
                                                                   : { error: "refused for the test" } }));
      };
      const release = async (i, status = 200) => {
        if (!held[i]) throw new Error(\`change \${i} was never sent: \${held.length} held\`);
        held[i](status); await settle(); await settle();
      };
    `;
