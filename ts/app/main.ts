// The page's entry: the editor rendered into `#app`. The server bundles
// this file and everything it imports as `/dist/app.js`.

import { html } from "htm/preact";
import { render } from "preact";
import { api, call } from "./api.ts";
import { App } from "./app.ts";

// The faces live only in this browser's storage, which it may clear when
// the disk runs low unless asked to keep it; a refusal changes nothing.
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});

// A test hook, not an API: the browser tests drive the worker from the
// page through it. Nothing on the page reads it.
(globalThis as typeof globalThis & { wfbStudio?: unknown }).wfbStudio = { api, call };

render(html`<${App} />`, document.getElementById("app")!);
