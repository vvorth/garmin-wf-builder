// The YAML tab's text on its way to the worker: pure functions, no DOM, so
// Node can check them (test/page-modules.test.ts).
//
// The pane's state is `{acked, base, conflict, held}`: `acked` is the
// text the worker holds at version `base`, which is what the pane's text
// was typed over; `held` is a text the worker did not take (not YAML, or
// the request failed), not sent again until the author changes it. A send is made against `base`, never against a newer version the
// editor heard of meanwhile, so a change made elsewhere while the author
// was typing (the inspector, another tab) is refused by the worker rather
// than overwritten. `conflict` is set by that refusal and holds the pane
// until the author chooses (`resolve`).

import type { Summary } from "../src/studio/protocol.ts";

/** The face as the pane follows it: its text and version. */
export type Doc = Pick<Summary, "text" | "version">;

export interface SyncState {
  acked: string;
  base: number;
  conflict: boolean;
  held: string | null;
}

/** What to do with the pane's text; `send` carries the text and the version it is sent against. */
export type Plan = { kind: "idle" } | { kind: "wait" } | { kind: "held" } | { kind: "send"; text: string; version: number };
export type PlanKind = Plan["kind"];

export function initial(doc: Doc): SyncState {
  return { acked: doc.text, base: doc.version, conflict: false, held: null };
}

// What to do with `buffer`, the pane's text: `{kind: "idle"}` when the
// worker has it, `{kind: "wait"}` while a conflict waits for the author,
// `{kind: "held"}` when the worker did not take this very text, or
// `{kind: "send", text, version}`.
export function plan(state: SyncState, buffer: string): Plan {
  if (state.conflict) return { kind: "wait" };
  if (buffer === state.acked) return { kind: "idle" };
  if (buffer === state.held) return { kind: "held" };
  return { kind: "send", text: buffer, version: state.base };
}

// The state after a send of `text` was answered: `status` and, when the
// worker recorded it, the face's new `version` (an answer that recorded
// it without one leaves the base where it was). Any other refusal holds
// the text.
export function answered(state: SyncState, text: string, status: number, version: number | null = null): SyncState {
  if (status >= 200 && status < 300) return { ...state, acked: text, base: version ?? state.base, held: null };
  if (status === 409) return { ...state, conflict: true };
  return { ...state, held: text };
}

// The state once the author asks to send the held text again.
export function retry(state: SyncState): SyncState {
  return { ...state, held: null };
}

// The state after a send of `text` failed on its way (no answer).
export function failed(state: SyncState, text: string): SyncState {
  return { ...state, held: text };
}

// The face as the worker now has it (`doc`), the pane holding `buffer`. A
// pane with nothing unsent follows it, and `replace` is the text to show;
// one with unsent text keeps it, and its base. A face older than the base
// (a late answer) is ignored.
export function follow(state: SyncState, doc: Doc, buffer: string): { state: SyncState; replace: string | null } {
  const keep = { state, replace: null };
  if (state.conflict || buffer !== state.acked || doc.version < state.base) return keep;
  if (doc.version === state.base && doc.text === state.acked) return keep;
  return { state: { ...state, acked: doc.text, base: doc.version },
           replace: doc.text === buffer ? null : doc.text };
}

// The author's choice on a conflict, `doc` being the face as it now is:
// "mine" keeps the pane's text, to be sent against `doc`'s version (so it
// replaces the other change, knowingly); "theirs" shows `doc`'s text.
export function resolve(state: SyncState, doc: Doc, choice: "mine" | "theirs"): { state: SyncState; replace: string | null } {
  const settled: SyncState = { ...state, conflict: false, acked: doc.text, base: doc.version, held: null };
  return { state: settled, replace: choice === "theirs" ? doc.text : null };
}

// The pane closing (the author left the tab) holding `buffer`: `left` is
// the text to show again when it reopens, or null when the worker has it,
// and `kind` is `plan`'s for it. Text not saved, held, or waiting on a
// conflict is never dropped by leaving the tab.
export function closed(state: SyncState, buffer: string): { left: string | null; kind: PlanKind } {
  const kind = plan(state, buffer).kind;
  return { left: kind === "idle" ? null : buffer, kind };
}

// The pane opening on `doc` with `left` (what `closed` left, or null): the
// text to show and the state. With nothing left the face as it now is
// starts afresh, however it changed while the tab was closed.
export function reopened(state: SyncState, left: string | null, doc: Doc): { text: string; state: SyncState } {
  if (left === null) return { text: doc.text, state: initial(doc) };
  return { text: left, state };
}

// The face's text as the author last had it, for the lost-session banner
// to copy: the YAML tab's (`buffer`, while it is open), else the text it
// closed on unsaved (`left`), else the face as the page last heard of it.
export function latestText(buffer: string | null | undefined, left: string | null | undefined, doc: Doc): string {
  return buffer ?? left ?? doc.text;
}
