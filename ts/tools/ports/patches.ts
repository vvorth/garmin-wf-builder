// Parity port of the `patches` stage: replays every call
// tools/oracle_patches.py recorded on a design, with the same arguments,
// and records each outcome in the same form.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { REPO_ROOT } from "../../src/devices/node.ts";
import * as colors from "../../src/edit/colors.ts";
import * as hands from "../../src/edit/hands.ts";
import * as edit from "../../src/edit/patch.ts";
import * as schemes from "../../src/edit/schemes.ts";
import { type Path, Refused, SpanIndex } from "../../src/edit/spans.ts";
import * as structure from "../../src/edit/structure.ts";
import { type Data, type DataKey, PyFloat } from "../../src/edit/yaml.ts";
import { canonical, PyError } from "../../src/py.ts";
import type { Case } from "../stages.ts";
import { codePoints } from "./text.ts";

hands.loadPresets(readFileSync(join(REPO_ROOT, "wfb", "templates", "hands", "sets.yaml"), "utf8"));

interface OracleRecord {
  op: string;
  args: unknown[];
  kw: Record<string, unknown>;
  [outcome: string]: unknown;
}

/** JSON from the oracle as YAML data: an object is a mapping, in its key order. */
function data(value: unknown): Data {
  if (Array.isArray(value)) return value.map(data);
  if (value !== null && typeof value === "object") {
    return new Map(Object.entries(value).map(([k, v]) => [k as DataKey, data(v)]));
  }
  return value as Data;
}

const path = (value: unknown): Path => value as Path;
const str = (value: unknown): string => value as string;

type Op = (index: SpanIndex, args: unknown[], kw: Record<string, unknown>) => unknown;

const OPS: Record<string, Op> = {
  set_value: (i, [p, v], kw) => edit.setValue(i, path(p), data(v), { block: kw["block"] === true }),
  remove: (i, [p]) => edit.remove(i, path(p)),
  rename_key: (i, [p, n]) => edit.renameKey(i, path(p), str(n)),
  delete_element: (i, [p]) => edit.deleteElement(i, path(p)),
  duplicate_element: (i, [p]) => edit.duplicateElement(i, path(p)),
  move_element: (i, [p, to]) => edit.moveElement(i, path(p), to as number),
  delete_elements: (i, [ps]) => edit.deleteElements(i, (ps as unknown[]).map(path)),
  set_scalars: (i, [values]) => edit.setScalars(i, (values as [unknown, unknown][]).map(([p, v]) => [path(p), data(v)])) ?? null,
  add_element: (i, [t]) => edit.addElement(i, str(t)),
  face_color: (i) => edit.faceColor(i),
  rename_reference: (i, [p, n, prefix]) => edit.renameReference(i, path(p), str(n), str(prefix)),
  rewrite_scalars: (i) => edit.rewriteScalars(i, (s) => s.replaceAll("color.", "colour."), "respell"),
  rename_slot: (i, [o, n]) => edit.renameSlot(i, str(o), str(n)),
  remove_slot: (i, [n]) => edit.removeSlot(i, str(n)),
  ungroup: (i, [p]) => structure.ungroup(i, path(p)),
  move_to_block: (i, [p, b]) => structure.moveToBlock(i, path(p), path(b)),
  group: (i, [ps], kw) => structure.group(i, (ps as unknown[]).map(path), (kw["group_id"] as string | undefined) ?? null),
  paste: (i, [clip, block]) => structure.paste(i, str(clip), block === undefined ? ["elements"] : path(block)),
  add: (i, [t, b], kw) => structure.add(i, str(t), path(b), null, null, (kw["choice"] as string | null | undefined) ?? null),
  use_color: (i, [p, v]) => colors.useColor(i, path(p), str(v)),
  add_swatch: (i, [v]) => colors.addSwatch(i, str(v)),
  set_swatch: (i, [n, v]) => colors.setSwatch(i, str(n), str(v)),
  remove_unused: (i) => colors.removeUnused(i),
  swatches: (i) => colors.swatches(i),
  roles: (i) => colors.roles(i),
  user_names: (i, [n]) => colors.userNames(i, str(n)),
  make_switchable: (i, [names, s]) => schemes.makeSwitchable(i, names as string[], str(s)),
  add_scheme: (i, [n]) => schemes.addScheme(i, str(n)),
  rename_scheme: (i, [o, n]) => schemes.renameScheme(i, str(o), str(n)),
  delete_scheme: (i, [n]) => schemes.deleteScheme(i, str(n)),
  remove_theme: (i, [n]) => schemes.removeTheme(i, str(n)),
  add_role: (i, [n, v]) => schemes.addRole(i, str(n), data(v)),
  rename_role: (i, [o, n]) => schemes.renameRole(i, str(o), str(n)),
  delete_role: (i, [n]) => schemes.deleteRole(i, str(n)),
  add_hand_set: (i, [n, preset]) => hands.addHandSet(i, str(n), str(preset)),
  duplicate_hand_set: (i, [n]) => hands.duplicateHandSet(i, str(n)),
  rename_hand_set: (i, [o, n]) => hands.renameHandSet(i, str(o), str(n)),
  delete_hand_set: (i, [n]) => hands.deleteHandSet(i, str(n)),
  hand_summary: (i) => hands.summary(i),
};

function isPatch(value: unknown): value is edit.Patch {
  return value !== null && typeof value === "object" && "text" in value && "expected" in value && "what" in value;
}

/** A value as the oracle's `to_json` writes it: a mapping as an object. */
function plain(value: unknown): unknown {
  if (value instanceof PyFloat) return value.value;
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [String(k), plain(v)]));
  if (Array.isArray(value)) return value.map(plain);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  return value ?? null;
}

const isHigh = (c: number): boolean => c >= 0xd800 && c <= 0xdbff;
const isLow = (c: number): boolean => c >= 0xdc00 && c <= 0xdfff;

/** `after` as one cut of `before`, in code points: where, how many cut, what inserted. */
function splice(before: string, after: string, cp: (i: number) => number): [number, number, string] {
  let start = 0;
  const limit = Math.min(before.length, after.length);
  while (start < limit && before.charCodeAt(start) === after.charCodeAt(start)) start++;
  if (start > 0 && isHigh(before.charCodeAt(start - 1))) start--;
  let endB = before.length, endA = after.length;
  while (endB > start && endA > start && before.charCodeAt(endB - 1) === after.charCodeAt(endA - 1)) { endB--; endA--; }
  if (endB < before.length && isLow(before.charCodeAt(endB))) { endB++; endA++; }
  return [cp(start), cp(endB) - cp(start), after.slice(start, endA)];
}

export function patches(input: Case): unknown {
  const recorded = input.oracle("patches") as OracleRecord[];
  if (recorded.length === 0) return [];
  const index = new SpanIndex(input.text);
  const cp = codePoints(input.text);
  return recorded.map((r) => {
    const out: Record<string, unknown> = { op: r.op, args: r.args, kw: r.kw };
    const op = OPS[r.op];
    if (op === undefined) {
      out["crash"] = `unported: ${r.op}`;
      return out;
    }
    let result: unknown;
    try {
      result = op(index, r.args, r.kw);
    } catch (error) {
      if (error instanceof Refused) out["refused"] = error.message;
      else if (error instanceof PyError) out["crash"] = error.pyType;
      else out["crash"] = `JS ${String(error)}`;
      return out;
    }
    let name: string | undefined;
    if (Array.isArray(result) && result.length === 2 && isPatch(result[0])) [result, name] = result as [edit.Patch, string];
    if (isPatch(result)) {
      out["splice"] = splice(input.text, result.text, cp);
      out["what"] = result.what;
      out["expected"] = createHash("sha256").update(canonical(result.expected), "ascii").digest("hex");
      if (name !== undefined) out["name"] = name;
    } else {
      out["value"] = plain(result);
    }
    return out;
  });
}
