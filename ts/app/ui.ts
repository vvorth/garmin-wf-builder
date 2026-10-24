// Small controls the panels share: a popover behind a button, a name
// edited in place, and a button that asks for a new name in place. None
// of them uses the browser's own prompt().

import type { ComponentChildren, JSX, VNode } from "preact";
import { html } from "htm/preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { Args } from "../src/studio/protocol.ts";
import { isIdentifier } from "./values.ts";
import { objectUrl } from "./api.ts";

/** The operations whose answer is a PNG the page shows as an image. */
export type ImageOp = "cover" | "thumbnail" | "handset";

/** `op` and `args` name the image; everything else goes on the `<img>` (`class`, `alt`, `title`). */
export interface WorkerImageProps extends JSX.HTMLAttributes<HTMLImageElement> {
  op: ImageOp;
  args: Args<ImageOp>;
}

// An image the worker draws (`op`: a cover, a thumbnail, a hand set):
// hidden while it loads, and when there is none. `args` may carry a key
// the worker ignores (`v`, the version) to draw it again.
export function WorkerImage({ op, args, ...rest }: WorkerImageProps): VNode {
  const [src, setSrc] = useState<string | null>(null);
  const key = JSON.stringify(args);
  useEffect(() => {
    let url: string | null = null, live = true;
    objectUrl(op, args).then((u) => { if (live) setSrc(url = u); else URL.revokeObjectURL(u); }, () => setSrc(null));
    // revoked a moment later, not at once: an image still fetching a revoked URL logs a load error
    return () => { live = false; if (url) { const u = url; setTimeout(() => URL.revokeObjectURL(u), 1000); } };
  }, [op, key]);
  return html`<img alt="" ...${rest} data-op=${op} data-args=${key} src=${src || undefined}
    style=${src ? undefined : "visibility:hidden"} />`;
}

export interface PopoverProps {
  label: ComponentChildren;
  title?: string | undefined;
  className?: string;
  buttonClass?: string;
  bodyClass?: string;
  /** "left" or "right" edge, plus "up" to open above the button. */
  align?: string;
  /** What the popover shows, or a function of `close` for an item that closes it once chosen. */
  children?: ComponentChildren | ((close: () => void) => ComponentChildren);
  onOpen?: (() => void) | undefined;
}

// A button that opens `children` below it, in the browser's top layer
// (`popover="auto"`): a click outside or Escape closes it, and opening one
// closes any other, natively. Placed by its button once its content has
// rendered, and again whenever the content changes size: on the side
// `align` asks for, or the other when that side has too little room and
// the other more, never past the window's edges (taller than the room, it
// scrolls). Closed when anything behind it scrolls, since it does not move
// with it. `children` may be a function of `close`, for an item that
// closes the popover once chosen. `align`: "left" or "right" edge, plus
// "up" to open above the button; `buttonClass` and `bodyClass` style the
// two halves.
let popovers = 0;
const MARGIN = 8;
export function Popover({ label, title, className = "", buttonClass = "", bodyClass = "", align = "left", children, onOpen }: PopoverProps): VNode {
  const [open, setOpen] = useState(false);
  const id = useRef<string | null>(null);
  id.current ??= `popover-${++popovers}`;
  const button = useRef<HTMLButtonElement | null>(null), body = useRef<HTMLDivElement | null>(null);
  const place = (): void => {
    if (!button.current || !body.current) return;
    const r = button.current.getBoundingClientRect(), el = body.current, s = el.style;
    s.maxHeight = "";
    const height = el.offsetHeight, width = el.offsetWidth;
    const below = innerHeight - r.bottom - 4 - MARGIN, above = r.top - 4 - MARGIN;
    const up = align.includes("up") ? !(above < height && below > above) : below < height && above > below;
    s.top = up ? "auto" : `${r.bottom + 4}px`;
    s.bottom = up ? `${innerHeight - r.top + 4}px` : "auto";
    if (height > (up ? above : below)) s.maxHeight = `${Math.max(up ? above : below, 0)}px`;
    // the edge `align` names, moved in as far as the window needs
    const left = align.includes("right") ? r.right - width : r.left;
    s.left = `${Math.max(MARGIN, Math.min(left, innerWidth - width - MARGIN))}px`;
    s.right = "auto";
  };
  const onToggle = (e: JSX.TargetedToggleEvent<HTMLDivElement>): void => {
    const now = e.newState === "open";
    if (now && onOpen) onOpen();
    setOpen(now);
  };
  const close = (): void => { if (body.current && typeof body.current.hidePopover === "function") body.current.hidePopover(); };
  useLayoutEffect(() => {
    if (!open || !body.current) return;
    place();
    if (typeof ResizeObserver !== "function") return;
    const resized = new ResizeObserver(place);
    resized.observe(body.current);
    return () => resized.disconnect();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const scrolled = (e: Event): void => { if (body.current && !body.current.contains(e.target as Node | null)) close(); };
    addEventListener("scroll", scrolled, true);
    return () => removeEventListener("scroll", scrolled, true);
  }, [open]);
  return html`<span class=${"popover " + className}>
    <button ref=${button} class=${(open ? "on " : "") + buttonClass} title=${title || ""} aria-expanded=${open}
            popovertarget=${id.current}>${label}</button>
    <div ref=${body} id=${id.current} popover="auto" class=${`popover-body ${align} ${bodyClass}`} onToggle=${onToggle}>
      ${open ? (typeof children === "function" ? children(close) : children) : null}</div>
  </span>`;
}

export interface InlineNameProps {
  value: string;
  title?: string | undefined;
  onRename: (name: string) => void;
  /** Whether a name may be given; letters, digits and _ by default. */
  valid?: (text: string) => boolean;
  /** Why not, shown while it may not. */
  why?: string;
  className?: string;
}

// A name shown as text; a click turns it into an input, where Enter (or
// leaving it) renames and Escape keeps the name. `valid(text)` says
// whether a name may be given (letters, digits and _ by default); while it
// may not, the input says why and Enter does nothing.
export function InlineName({ value, title, onRename, valid = isIdentifier,
                             why = "letters, digits and _, not starting with a digit",
                             className = "name" }: InlineNameProps): VNode {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  const input = useRef<HTMLInputElement | null>(null);
  // settled once Enter, Escape or leaving the input has decided: a blur
  // that follows Enter or Escape must not decide again
  const settled = useRef(false);
  useEffect(() => {
    if (editing && input.current && typeof input.current.focus === "function") { input.current.focus(); input.current.select(); }
  }, [editing]);
  if (!editing) {
    return html`<span class=${className + " renamable"} title=${title || "click to rename"}
                      onClick=${() => { settled.current = false; setText(value); setEditing(true); }}>${value}</span>`;
  }
  const ok = valid(text.trim());
  const commit = (raw: string): void => {
    if (settled.current) return;
    settled.current = true;
    const name = raw.trim();
    setEditing(false);
    if (name !== value && valid(name)) onRename(name);
  };
  return html`<input type="text" ref=${input} class=${"inline-name" + (ok ? "" : " invalid")} value=${text}
    title=${ok ? "Enter to rename, Escape to keep the name" : why} aria-invalid=${!ok}
    onInput=${(e: JSX.TargetedInputEvent<HTMLInputElement>) => setText(e.currentTarget.value)}
    onBlur=${(e: JSX.TargetedFocusEvent<HTMLInputElement>) => commit(e.currentTarget.value)}
    onKeyDown=${(e: JSX.TargetedKeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && valid(e.currentTarget.value.trim())) commit(e.currentTarget.value);
      else if (e.key === "Escape") { settled.current = true; setEditing(false); }
    }} />`;
}

export interface AddNameProps {
  label: ComponentChildren;
  title?: string | undefined;
  /** The name offered when the input opens. */
  suggest?: () => string;
  onAdd: (name: string) => void;
  onCancel?: (() => void) | undefined;
  disabled?: boolean;
  valid?: (text: string) => boolean;
  placeholder?: string;
  /** Shown as the input from the start. */
  startOpen?: boolean;
}

// A button that, pressed, becomes an input for a new name, suggested by
// `suggest()`; Enter or ✓ gives it to `onAdd`, Escape or × leaves it
// (and tells `onCancel`). `startOpen`: shown as the input from the start.
export function AddName({ label, title, suggest = () => "", onAdd, onCancel, disabled = false,
                          valid = isIdentifier, placeholder = "name", startOpen = false }: AddNameProps): VNode {
  const [text, setText] = useState<string | null>(startOpen ? suggest() || "" : null);
  const cancel = (): void => { setText(null); if (onCancel) onCancel(); };
  const input = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (text !== null && input.current && typeof input.current.focus === "function") { input.current.focus(); input.current.select(); }
  }, [text === null]);
  if (text === null) {
    return html`<button disabled=${disabled} title=${title || ""} onClick=${() => setText(suggest() || "")}>${label}</button>`;
  }
  const ok = valid(text.trim());
  const add = (): void => { if (ok) { onAdd(text.trim()); setText(null); } };
  return html`<span class="add-name">
    <input type="text" ref=${input} class=${"inline-name" + (ok ? "" : " invalid")} value=${text}
      placeholder=${placeholder} aria-label=${label} aria-invalid=${!ok}
      title=${ok ? "Enter to add, Escape to cancel" : "letters, digits and _, not starting with a digit"}
      onInput=${(e: JSX.TargetedInputEvent<HTMLInputElement>) => setText(e.currentTarget.value)}
      onKeyDown=${(e: JSX.TargetedKeyboardEvent<HTMLInputElement>) => {
        const typed = e.currentTarget.value;
        if (e.key === "Enter") { if (valid(typed.trim())) { onAdd(typed.trim()); setText(null); } }
        else if (e.key === "Escape") cancel();
      }} />
    <button class="primary" disabled=${!ok} title="add" onClick=${add}>✓</button>
    <button class="reset" title="cancel" aria-label="cancel" onClick=${cancel}>×</button>
  </span>`;
}
