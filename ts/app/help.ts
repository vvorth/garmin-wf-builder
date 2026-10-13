// Help: the README and the guide, rendered in a popup. A link to another
// page opens it here, with Back to return; an image or any other file comes
// from the server's `/help/`, and a link off this computer opens a new tab.

import type { JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { marked } from "./vendor/marked.esm.js";
import { Modal } from "./dialogs.ts";

export const HELP_HOME = "docs/README.md";

/** A place in the docs: a repo-relative path and "#anchor" or "". */
interface Place {
  path: string;
  hash: string;
}

// `href` read from the page at `base`: [repo-relative path, "#anchor" or ""].
function resolve(base: string, href: string): [string, string] {
  const url = new URL(href, "http://repo/" + base);
  return [decodeURIComponent(url.pathname.slice(1)), url.hash];
}

// GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens.
function slug(text: string): string {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\- _]/gu, "").replace(/ /g, "-");
}

// The vendored marked is typed loosely (`vendor/marked.esm.d.ts`): its answer is the page's HTML.
function rendered(markdown: string): string {
  return String(marked.parse(markdown));
}

export interface HelpDialogProps {
  /** The page opened first, repo-relative. */
  start?: string;
  onClose: () => void;
}

export function HelpDialog({ start = HELP_HOME, onClose }: HelpDialogProps): VNode {
  const [at, setAt] = useState<Place>({ path: start, hash: "" });
  const [back, setBack] = useState<Place[]>([]);
  const [page, setPage] = useState<{ path: string | null; html: string }>({ path: null, html: "" });
  const body = useRef<HTMLDivElement | null>(null);

  const open = (path: string, hash = ""): void => {
    if (path === at.path && hash) { setAt({ path, hash }); return; }
    setBack((b) => [...b, at]);
    setAt({ path, hash });
  };

  useEffect(() => {
    let live = true;
    fetch("/help/" + at.path).then(async (r) => {
      const text = await r.text();
      if (!live) return;
      setPage({ path: at.path, html: r.ok ? rendered(text) : `<p class="error-text">${at.path} is not here.</p>` });
    }, (e: unknown) => live && setPage({ path: at.path, html: `<p class="error-text">${String(e)}</p>` }));
    return () => { live = false; };
  }, [at.path]);

  // Once a page is in: anchors on its headings, its images from the server, then the scroll.
  useEffect(() => {
    const root = body.current;
    if (!root || page.path !== at.path) return;
    const seen: Record<string, number> = {};
    for (const h of root.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
      const s = slug(h.textContent ?? "");
      const n = seen[s];
      h.id = n ? `${s}-${n}` : s;
      seen[s] = (n || 0) + 1;
    }
    for (const img of root.querySelectorAll<HTMLImageElement>("img[src]")) {
      const src = img.getAttribute("src") ?? "";
      if (!/^[a-z]+:|^\/\//i.test(src)) img.src = "/help/" + resolve(page.path, src)[0];
    }
    const target = at.hash && root.querySelector(`[id="${CSS.escape(decodeURIComponent(at.hash.slice(1)))}"]`);
    if (target) target.scrollIntoView();
    else root.scrollTop = 0;
  }, [page, at.hash]);

  const click = (e: JSX.TargetedMouseEvent<HTMLDivElement>): void => {
    // the DOM boundary: the click's target is an element inside the page's HTML
    const a = (e.target as Element | null)?.closest("a[href]");
    if (!a || e.ctrlKey || e.metaKey) return;
    const href = a.getAttribute("href") ?? "";
    e.preventDefault();
    if (/^[a-z]+:|^\/\//i.test(href)) { window.open(href, "_blank", "noopener"); return; }
    const [path, hash] = resolve(at.path, href);
    if (path.endsWith(".md")) open(path, hash);
    else window.open("/help/" + path + hash, "_blank", "noopener");
  };

  const goBack = (): void => {
    const last = back[back.length - 1];
    if (!last) return;
    setAt(last); setBack((b) => b.slice(0, -1));
  };
  return html`<${Modal} title="Help" onClose=${onClose} className="help">
    <div class="help-nav">
      <button disabled=${!back.length} onClick=${goBack} title="The page before">← Back</button>
      <button disabled=${at.path === HELP_HOME} onClick=${() => open(HELP_HOME)} title="Every guide chapter">Contents</button>
      <button disabled=${at.path === "README.md"} onClick=${() => open("README.md")}>README</button>
      <code class="dim">${at.path}</code>
    </div>
    <div class="modal-body markdown" ref=${body} onClick=${click} dangerouslySetInnerHTML=${{ __html: page.html }}></div>
  </${Modal}>`;
}
