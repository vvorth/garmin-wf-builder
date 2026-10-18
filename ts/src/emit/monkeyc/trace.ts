// `wfb build --trace`: a `System.println` at the top of every lifecycle and
// editor callback the generated sources define, for reading what the watch
// calls and when (`wfb simulate --follow`, or a watch's GARMIN/APPS/LOGS file).
// A pass over the finished sources, so the build for wearing never carries it.
// A watch keeps about 10 KB of log (5 KB, then one .BAK), so lines are short.
import type { SourceFile } from "./common.ts";

/** What a traced callback prints after its name, from its file's text; null prints the name alone. */
type Extra = (text: string) => string | null;

/** Each traced callback's `Extra`, by source suffix then function name. */
const TRACED: ReadonlyArray<readonly [string, ReadonlyMap<string, Extra>]> = [
  ["App.mc", new Map<string, Extra>([
    ["onStart", () => `" state=" + state`],
    ["getInitialView", () => null],
    ["getSettingsView", () => null],
  ])],
  ["View.mc", new Map<string, Extra>([
    ["initialize", (text) => (/function initialize\(editMode as Boolean\)/.test(text) ? `" editMode=" + editMode` : null)],
    ["onLayout", () => null],
    ["onShow", () => null],
    ["onHide", () => null],
    ["onUpdate", (text) => `" s=" + System.getClockTime().sec`
      + (/private var _pulsing\b/.test(text) ? ` + " pulsing=" + _pulsing + " fresh=" + _pulseFresh + " tick=" + _editTick` : "")],
    ["onEnterSleep", () => null],
    ["onExitSleep", () => null],
    ["startEditTicks", () => `" editMode=" + _editMode + " awake=" + _editAwake + " running=" + (_editTimer != null)`],
    ["stopEditTicks", () => `" running=" + (_editTimer != null)`],
    ["onEditTick", () => null],
    ["applyConfig", () => null],
    ["setPulsing", () => `" unique=" + unique`],
    ["drawableFor", () => `" unique=" + unique`],
  ])],
  ["Delegate.mc", new Map<string, Extra>([
    ["onWatchFaceConfigEdited", () => `" type=" + options[:type] + " committed=" + options[:committed]`],
    ["onTap", () => null],
    ["getComplicationDrawable", () => null],
    ["onPress", () => null],
  ])],
  ["SlotDrawable.mc", new Map<string, Extra>([["draw", () => null]])],
];

/** `source` with a trace line opening every callback `TRACED` names for it. */
export function traced(source: SourceFile): SourceFile {
  const table = TRACED.find(([suffix]) => source.path.endsWith(suffix) && !source.path.endsWith("ConfigMenuDelegate.mc"))?.[1];
  if (table === undefined) return source;
  const lines = source.text.split("\n");
  const out: string[] = [];
  let pending: string | null = null;
  let depth = 0;
  for (const line of lines) {
    out.push(line);
    const match = /^(\s*)(?:private\s+)?function (\w+)\(/.exec(line);
    if (match !== null && table.has(match[2]!)) {
      const extra = table.get(match[2]!)!(source.text);
      const tail = extra !== null ? ` + ${extra}` : "";
      pending = `${match[1]}    System.println("wfb " + System.getTimer() + " ${className(source.path)}.${match[2]}"${tail});`;
      depth = 0;
    }
    if (pending === null) continue;
    // the body opens where the signature's parentheses close: a parameter's
    // dictionary type opens a brace inside them first
    for (const ch of line) depth += ch === "(" ? 1 : ch === ")" ? -1 : 0;
    if (depth === 0 && line.trimEnd().endsWith("{")) {
      out.push(pending);
      pending = null;
    }
  }
  let text = out.join("\n");
  if (!/^import Toybox\.System;$/m.test(text)) {
    const imports = [...text.matchAll(/^import [\w.]+;$/gm)];
    const last = imports[imports.length - 1]!;
    const at = last.index! + last[0].length;
    text = `${text.slice(0, at)}\nimport Toybox.System;${text.slice(at)}`;
  }
  return { ...source, text };
}

/** `source/FooView.mc` -> `View`: the line's class, short. */
function className(path: string): string {
  const suffix = TRACED.map(([s]) => s).find((s) => path.endsWith(s))!;
  return suffix.replace(".mc", "");
}
