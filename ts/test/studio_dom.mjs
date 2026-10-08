// A minimal DOM for the page tests (`page-harness.ts`): enough for preact
// to render the editor's panels in Node, and for a test to read their text,
// find elements and click them. A popover opens and closes on its button's
// click (`popovertarget`), as a browser's does.
class Node {
  constructor(type, name) { this.nodeType = type; this.nodeName = name; this.childNodes = []; this.parentNode = null; }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return p.childNodes[i + 1] || null; }
  appendChild(c) { return this.insertBefore(c, null); }
  insertBefore(c, ref) {
    if (c.parentNode) c.parentNode.removeChild(c);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    if (i < 0) this.childNodes.push(c); else this.childNodes.splice(i, 0, c);
    c.parentNode = this; return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get textContent() { return this.nodeType === 3 ? this.data : this.childNodes.map((c) => c.textContent).join(""); }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
}
class Text extends Node { constructor(d) { super(3, "#text"); this.data = String(d); } set nodeValue(v) { this.data = String(v); } get nodeValue() { return this.data; } }
const EVENTS = ["click", "change", "input", "keydown", "blur", "focus", "mousedown", "pointerdown", "toggle",
                "dragstart", "dragover", "dragleave", "drop"];
class Element extends Node {
  constructor(name) { super(1, name.toUpperCase()); this.localName = name; this.attributes = {}; this.style = { setProperty(k, v) { this[k] = v; }, cssText: "" }; this.listeners = {};
    // preact lower-cases `onClick` to "click" only when the element has an
    // `onclick` property, as a browser's does
    for (const e of EVENTS) this["on" + e] = null; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  getAttribute(k) { return this.attributes[k] ?? null; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter((g) => g !== f); }
  all(pred, out = []) { for (const c of this.childNodes) if (c.nodeType === 1) { if (pred(c)) out.push(c); c.all(pred, out); } return out; }
  dispatch(type, extra = {}) {
    const event = { type, target: this, currentTarget: this, preventDefault() {}, stopPropagation() {}, ...extra };
    for (const f of this.listeners[type] || []) f.call(this, event);
  }
  click() {
    this.dispatch("click");
    const target = this.attributes.popovertarget;
    if (target === undefined) return;
    let top = this;
    while (top.parentNode) top = top.parentNode;
    const found = top.all((e) => e.attributes.id === target)[0];
    if (found) found.togglePopover();
  }
  togglePopover() { if (this.popoverOpen) this.hidePopover(); else this.showPopover(); }
  showPopover() { if (!this.popoverOpen) { this.popoverOpen = true; this.dispatch("toggle", { newState: "open" }); } }
  hidePopover() { if (this.popoverOpen) { this.popoverOpen = false; this.dispatch("toggle", { newState: "closed" }); } }
  getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; }
  // Enough CSS to cover the app's own selectors: a comma list of
  // descendant chains (space-separated), each step a tag name, `.class`es
  // and `[attr]`/`[attr="value"]`, any of which may be omitted.
  querySelectorAll(sel) {
    const matchers = sel.split(",").map((s) => chainMatcher(s.trim()));
    return this.all((e) => matchers.some((m) => m(e)));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }
}
const SIMPLE = /^([a-zA-Z0-9_-]*)((?:\.[a-zA-Z0-9_-]+)*)((?:\[[a-zA-Z0-9_-]+(?:="[^"]*")?\])*)$/;
function simpleMatcher(sel) {
  const m = SIMPLE.exec(sel);
  if (!m) return () => false;
  const [, tag, classes, attrs] = m;
  const classList = classes ? classes.slice(1).split(".") : [];
  const attrList = [...attrs.matchAll(/\[([a-zA-Z0-9_-]+)(?:="([^"]*)")?\]/g)].map((mm) => [mm[1], mm[2]]);
  return (e) => (!tag || e.localName === tag.toLowerCase())
    && classList.every((c) => (e.attributes.class || "").split(/\s+/).includes(c))
    && attrList.every(([k, v]) => k in e.attributes && (v === undefined || e.attributes[k] === v));
}
function chainMatcher(sel) {
  const steps = sel.split(/\s+/).filter(Boolean).map(simpleMatcher);
  return (e) => {
    let node = e;
    for (let i = steps.length - 1; i >= 0; i--) {
      if (i === steps.length - 1) { if (!steps[i](node)) return false; continue; }
      let p = node.parentNode;
      while (p && !steps[i](p)) p = p.parentNode;
      if (!p) return false;
      node = p;
    }
    return true;
  };
}
export function install() {
  const document = {
    createElement: (n) => new Element(n), createElementNS: (_, n) => new Element(n),
    createTextNode: (d) => new Text(d), body: new Element("body"),
  };
  globalThis.document = document;
  globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {};
  globalThis.requestAnimationFrame = (f) => setTimeout(f, 0);
  globalThis.cancelAnimationFrame = (t) => clearTimeout(t);
  return document;
}
