// The face templates a new design starts from: `wfb new` and the editor's
// New both copy one through `instantiate`, so they cannot drift..
import { uuid } from "./uuid.ts";
import { quoted } from "./py.ts";
import templates from "./data/templates.json" with { type: "json" };

const TEMPLATES = templates as Record<string, { blurb: string; text: string }>;

export class UnknownTemplate extends Error {}

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
