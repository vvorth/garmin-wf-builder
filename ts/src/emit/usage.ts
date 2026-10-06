// What generated Monkey C actually calls: runtime-lib barrel modules and
// `Toybox` modules, read straight off the emitted source text. Port of
// wfb/emit/usage.py.
//
// The generated source is the one complete record of what the code calls:
// a barrel call is as often built inline as a string (from an expression,
// a strftime code, a reader's own call) as written by an emitter.
import runtimeLib from "../data/runtime-lib.json" with { type: "json" };

/** The support barrel's files, by name. */
export const RUNTIME_LIB: ReadonlyMap<string, string> = new Map(Object.entries(runtimeLib as Record<string, string>));

/** Generated code calls into a `Wfb<Name>` module with no `runtime-lib/Wfb<Name>.mc`: a compiler bug. */
export class UnknownBarrelModule extends Error {}

/** A `//` comment to end of line, or a `"..."` string literal; whichever starts first wins. */
const STRIP_RE = /\/\/[^\n]*|"(?:\\.|[^"\\])*"/g;

/** `text` with every line comment and string literal blanked out. */
export function stripCommentsAndStrings(text: string): string {
  return text.replace(STRIP_RE, " ");
}

const BARREL_CALL_RE = /\bWfb[A-Za-z0-9]+(?=\.)/g;

function directBarrelFiles(text: string): Set<string> {
  const files = new Set<string>();
  for (const match of stripCommentsAndStrings(text).matchAll(BARREL_CALL_RE)) {
    const name = `${match[0]}.mc`;
    if (!RUNTIME_LIB.has(name)) {
      throw new UnknownBarrelModule(`generated code calls ${match[0]}.<member>, but runtime-lib/${name} does not exist -- `
        + "a generated program cannot call into a barrel module that was never written");
    }
    files.add(name);
  }
  return files;
}

/** The `runtime-lib/*.mc` files generated code calls into, closed over the barrel files themselves. */
export function barrelModules(texts: string | Iterable<string>): Set<string> {
  const files = new Set<string>();
  for (const text of typeof texts === "string" ? [texts] : texts) for (const f of directBarrelFiles(text)) files.add(f);
  const pending = [...files];
  while (pending.length > 0) {
    const name = pending.pop()!;
    for (const found of directBarrelFiles(RUNTIME_LIB.get(name)!)) {
      if (!files.has(found)) {
        files.add(found);
        pending.push(found);
      }
    }
  }
  return files;
}

/** Every `Toybox` module generated view code can reference, by the identifier the text uses. */
export const TOYBOX_MODULES: ReadonlyMap<string, string> = new Map([
  ["Graphics", "Toybox.Graphics"],
  ["Lang", "Toybox.Lang"],
  ["WatchUi", "Toybox.WatchUi"],
  ["System", "Toybox.System"],
  ["Time", "Toybox.Time"],
  ["Gregorian", "Toybox.Time.Gregorian"],
  ["ActivityMonitor", "Toybox.ActivityMonitor"],
  ["Activity", "Toybox.Activity"],
  ["Weather", "Toybox.Weather"],
  ["UserProfile", "Toybox.UserProfile"],
  ["Complications", "Toybox.Complications"],
  ["Math", "Toybox.Math"],
  ["Application", "Toybox.Application"],
  ["WatchFaceConfig", "Toybox.Application.WatchFaceConfig"],
]);

const TOYBOX_PATTERNS = new Map([...TOYBOX_MODULES.keys()].map((name) => [name, new RegExp(`\\b${name}\\.|\\b${name}\\s+has\\b`)]));

/** The `Toybox.*` imports `text` needs: each module named as a member reference or a `has` check. */
export function toyboxModules(text: string): Set<string> {
  const stripped = stripCommentsAndStrings(text);
  return new Set([...TOYBOX_MODULES].filter(([name]) => TOYBOX_PATTERNS.get(name)!.test(stripped)).map(([, module]) => module));
}
