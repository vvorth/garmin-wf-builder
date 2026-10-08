// The face templates a new design starts from: `wfb new` and the editor's
// New both copy one through `instantiate`, so they cannot drift..
import { uuid } from "./uuid.ts";
import { quoted } from "./py.ts";
import templates from "./data/templates.json" with { type: "json" };

const TEMPLATES = templates as Record<string, { blurb: string; text: string; files?: Record<string, string> }>;

export class UnknownTemplate extends Error {}

function base64Bytes(text: string): Uint8Array {
  const binary = atob(text);
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

/** Every template name, sorted. */
export function names(): string[] {
  return Object.keys(TEMPLATES).sort();
}

/** One line describing a template. */
export function blurb(name: string): string {
  return TEMPLATES[name]?.blurb ?? "";
}

/**
 * The template's text with a fresh UUID and `name` substituted. Two faces
 * sharing a UUID are the same app to the watch -- installing the second
 * replaces the first -- so every call mints its own.
 */
export function instantiate(template: string, name: string): string {
  const found = Object.hasOwn(TEMPLATES, template) ? TEMPLATES[template] : undefined;
  if (found === undefined) throw new UnknownTemplate(`no template ${quoted(template)}`);
  return found.text.replaceAll("__UUID__", uuid()).replaceAll("__NAME__", name);
}

/** The template's own files (a baked font's source, say), by their bundle-relative path; empty for most templates. */
export function files(template: string): Map<string, Uint8Array> {
  const found = Object.hasOwn(TEMPLATES, template) ? TEMPLATES[template] : undefined;
  if (found === undefined) throw new UnknownTemplate(`no template ${quoted(template)}`);
  return new Map(Object.entries(found.files ?? {}).map(([path, b64]) => [path, base64Bytes(b64)]));
}
