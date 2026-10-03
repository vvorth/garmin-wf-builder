// A minimal DOM for tests/test_studio_panels.py: enough for preact to render
// the editor's panels in Node, and for a test to read their text, find
// elements and click them.
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
const EVENTS = ["click", "change", "input", "keydown", "blur", "focus", "mousedown", "pointerdown"];
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
  click() { this.dispatch("click"); }
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
