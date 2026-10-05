// Small controls the panels share: a popover behind a button, a name
// edited in place, and a button that asks for a new name in place. None
// of them uses the browser's own prompt().

import { html, useEffect, useRef, useState } from "./vendor/preact-htm.module.js";
import { isIdentifier } from "./values.js";

// A button that opens `children` below it; a click outside or Escape
// closes it. `children` may be a function of `close`, for an item that
// closes the popover once chosen. `align`: "left" or "right" edge.
export function Popover({ label, title, className = "", align = "left", children, onOpen }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("mousedown", away);
    addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", away); removeEventListener("keydown", esc); };
  }, [open]);
  const close = () => setOpen(false);
  return html`<span class=${"popover " + className} ref=${box}>
    <button class=${open ? "on" : ""} title=${title || ""} aria-expanded=${open}
            onClick=${() => { if (!open && onOpen) onOpen(); setOpen(!open); }}>${label}</button>
    ${open ? html`<div class=${"popover-body " + align}>${typeof children === "function" ? children(close) : children}</div>` : null}
  </span>`;
}

// A name shown as text; a click turns it into an input, where Enter (or
// leaving it) renames and Escape keeps the name. `valid(text)` says
// whether a name may be given (letters, digits and _ by default); while it
// may not, the input says why and Enter does nothing.
export function InlineName({ value, title, onRename, valid = isIdentifier,
                             why = "letters, digits and _, not starting with a digit",
                             className = "name" }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  const input = useRef(null);
  // settled once Enter, Escape or leaving the input has decided: a blur
  // that follows Enter or Escape must not decide again
  const settled = useRef(false);
  useEffect(() => {
    if (editing && input.current && input.current.focus) { input.current.focus(); input.current.select(); }
  }, [editing]);
  if (!editing) {
    return html`<span class=${className + " renamable"} title=${title || "click to rename"}
                      onClick=${() => { settled.current = false; setText(value); setEditing(true); }}>${value}</span>`;
  }
  const ok = valid(text.trim());
  const commit = (raw) => {
    if (settled.current) return;
    settled.current = true;
    const name = raw.trim();
    setEditing(false);
    if (name !== value && valid(name)) onRename(name);
  };
  return html`<input type="text" ref=${input} class=${"inline-name" + (ok ? "" : " invalid")} value=${text}
    title=${ok ? "Enter to rename, Escape to keep the name" : why} aria-invalid=${!ok}
    onInput=${(e) => setText(e.target.value)}
    onBlur=${(e) => commit(e.target.value)}
    onKeyDown=${(e) => {
      if (e.key === "Enter" && valid(e.target.value.trim())) commit(e.target.value);
      else if (e.key === "Escape") { settled.current = true; setEditing(false); }
    }} />`;
}

// A button that, pressed, becomes an input for a new name, suggested by
// `suggest()`; Enter or ✓ gives it to `onAdd`, Escape or × leaves it
// (and tells `onCancel`). `startOpen`: shown as the input from the start.
export function AddName({ label, title, suggest = () => "", onAdd, onCancel, disabled = false,
                          valid = isIdentifier, placeholder = "name", startOpen = false }) {
  const [text, setText] = useState(startOpen ? suggest() || "" : null);
  const cancel = () => { setText(null); if (onCancel) onCancel(); };
  const input = useRef(null);
  useEffect(() => {
    if (text !== null && input.current && input.current.focus) { input.current.focus(); input.current.select(); }
  }, [text === null]);
  if (text === null) {
    return html`<button disabled=${disabled} title=${title || ""} onClick=${() => setText(suggest() || "")}>${label}</button>`;
  }
  const ok = valid(text.trim());
  const add = () => { if (ok) { onAdd(text.trim()); setText(null); } };
  return html`<span class="add-name">
    <input type="text" ref=${input} class=${"inline-name" + (ok ? "" : " invalid")} value=${text}
      placeholder=${placeholder} aria-label=${label} aria-invalid=${!ok}
      title=${ok ? "Enter to add, Escape to cancel" : "letters, digits and _, not starting with a digit"}
      onInput=${(e) => setText(e.target.value)}
      onKeyDown=${(e) => {
        if (e.key === "Enter") { if (valid(e.target.value.trim())) { onAdd(e.target.value.trim()); setText(null); } }
        else if (e.key === "Escape") cancel();
      }} />
    <button class="primary" disabled=${!ok} title="add" onClick=${add}>✓</button>
    <button class="reset" title="cancel" onClick=${cancel}>×</button>
  </span>`;
}
