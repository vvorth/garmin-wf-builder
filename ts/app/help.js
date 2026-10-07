// Help: the README and the guide, rendered in a popup. A link to another
// page opens it here, with Back to return; an image or any other file comes
// from the server's `/help/`, and a link off this computer opens a new tab.

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import { marked } from "./vendor/marked.esm.js";
import { Modal } from "./dialogs.js";

export const HELP_HOME = "docs/README.md";

// `href` read from the page at `base`: [repo-relative path, "#anchor" or ""].
function resolve(base, href) {
  const url = new URL(href, "http://repo/" + base);
  return [decodeURIComponent(url.pathname.slice(1)), url.hash];
}

// GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens.
function slug(text) {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\- _]/gu, "").replace(/ /g, "-");
}

export function HelpDialog({ start = HELP_HOME, onClose }) {
  const [at, setAt] = useState({ path: start, hash: "" });
  const [back, setBack] = useState([]);
  const [page, setPage] = useState({ path: null, html: "" });
  const body = useRef(null);

  const open = (path, hash = "") => {
    if (path === at.path && hash) { setAt({ path, hash }); return; }
    setBack((b) => [...b, at]);
    setAt({ path, hash });
  };

  useEffect(() => {
    let live = true;
    fetch("/help/" + at.path).then(async (r) => {
      const text = await r.text();
      if (!live) return;
      setPage({ path: at.path, html: r.ok ? marked.parse(text) : `<p class="error-text">${at.path} is not here.</p>` });
    }, (e) => live && setPage({ path: at.path, html: `<p class="error-text">${String(e)}</p>` }));
    return () => { live = false; };
  }, [at.path]);

  // Once a page is in: anchors on its headings, its images from the server, then the scroll.
  useEffect(() => {
    const root = body.current;
    if (!root || page.path !== at.path) return;
    const seen = {};
    for (const h of root.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
      const s = slug(h.textContent);
      h.id = seen[s] ? `${s}-${seen[s]}` : s;
      seen[s] = (seen[s] || 0) + 1;
    }
    for (const img of root.querySelectorAll("img[src]")) {
      const src = img.getAttribute("src");
      if (!/^[a-z]+:|^\/\//i.test(src)) img.src = "/help/" + resolve(page.path, src)[0];
    }
    const target = at.hash && root.querySelector(`[id="${CSS.escape(decodeURIComponent(at.hash.slice(1)))}"]`);
    if (target) target.scrollIntoView();
    else root.scrollTop = 0;
  }, [page, at.hash]);

  const click = (e) => {
    const a = e.target.closest("a[href]");
    if (!a || e.ctrlKey || e.metaKey) return;
    const href = a.getAttribute("href");
    e.preventDefault();
    if (/^[a-z]+:|^\/\//i.test(href)) { window.open(href, "_blank", "noopener"); return; }
    const [path, hash] = resolve(at.path, href);
    if (path.endsWith(".md")) open(path, hash);
    else window.open("/help/" + path + hash, "_blank", "noopener");
  };

  const goBack = () => { setAt(back[back.length - 1]); setBack((b) => b.slice(0, -1)); };
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
