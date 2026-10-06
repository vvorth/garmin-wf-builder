// `source/SlotScale.mc`: a gauge's automatic scale for the complication
// type it shows. Port of wfb/emit/monkeyc/slot_scale.py.
import * as complications from "../../complications.ts";
import { type Face, Gauge } from "../../ir/model.ts";
import { floatRepr } from "../../py.ts";
import { Writer } from "../writer.ts";
import { header, type SourceFile } from "./common.ts";

export const SLOT_SCALE_MODULE = "SlotScale";

/** A scale figure as a Monkey C literal: whole figures as Numbers. */
function figure(value: number): string {
  return Number.isInteger(value) ? String(value) : floatRepr(value);
}

/** `WfbProfileScale.vo2max`'s table: the female rows then the male rows, each a minimum then a maximum. */
function vo2maxEnds(): number[] {
  const ends: number[] = [];
  for (const sex of ["female", "male"]) {
    for (const [fair, , , superior] of complications.VO2MAX_RATINGS.get(sex)!) ends.push(...complications.vo2maxEnds(fair, superior));
  }
  return ends;
}

/** The module's source: a case for each of `names` with a scale, and with `apps`, one for an app's complication. */
export function slotScaleText(names: Iterable<string>, apps: boolean, headerText: string): string {
  const scaled = [...new Set(names)].sort().filter((name) => complications.SCALE.has(name));
  const byKind = new Map<string, string[]>();
  for (const name of scaled) {
    const kind = complications.SCALE.get(name)!.kind;
    if (!byKind.has(kind)) byKind.set(kind, []);
    byKind.get(kind)!.push(name);
  }
  const caseOf = (name: string): string => `case Complications.${complications.TYPES.get(name)!.constant}:`;
  const w = new Writer();
  w.doc(headerText).blank();
  const imports = ["import Toybox.Complications;", "import Toybox.Lang;"];
  if (byKind.has("goal")) imports.unshift("import Toybox.ActivityMonitor;");
  w.lines(...imports).blank();
  w.doc("A gauge's automatic scale for the complication type it shows,\ngenerated from wfb.complications.SCALE.");
  w.block(`module ${SLOT_SCALE_MODULE}`, () => {
    if (byKind.has("vo2max")) {
      w.doc("WfbProfileScale.vo2max's table, from wfb.complications.VO2MAX_RATINGS.");
      w.line(`const VO2MAX_ENDS = [${vo2maxEnds().map((v) => floatRepr(v)).join(", ")}] as Array<Float>;`);
      w.blank();
    }
    w.doc("`[minimum, maximum]` for the pulled complication `c`, of type `t`, or\nnull when it has no scale.");
    w.block("function scale(t as Complications.Type, c as Complications.Complication)\n        as Array<Numeric>?", () => {
      if (byKind.has("goal")) w.line("var info = ActivityMonitor.getInfo();");
      w.block("switch (t)", () => {
        const fixed = new Map<string, [number, number, string[]]>();
        for (const name of byKind.get("fixed") ?? []) {
          const scale = complications.SCALE.get(name)!;
          const key = `${scale.minimum}\0${scale.maximum}`;
          if (!fixed.has(key)) fixed.set(key, [scale.minimum, scale.maximum, []]);
          fixed.get(key)![2].push(name);
        }
        for (const [low, high, group] of fixed.values()) {
          for (const name of group) w.line(caseOf(name));
          w.line(`    return [${figure(low)}, ${figure(high)}] as Array<Numeric>;`);
        }
        for (const name of byKind.get("goal") ?? []) {
          const field = complications.SCALE.get(name)!.goal;
          w.line(caseOf(name));
          w.line(`    return WfbScale.upTo((info has :${field}) ? info.${field} : null);`);
        }
        for (const name of byKind.get("heart_rate_zones") ?? []) {
          w.line(caseOf(name));
          w.line("    return WfbProfileScale.heartRate();");
        }
        for (const name of byKind.get("vo2max") ?? []) w.line(caseOf(name));
        if (byKind.has("vo2max")) w.line("    return WfbProfileScale.vo2max(VO2MAX_ENDS, c);");
        if (apps) {
          w.line("case Complications.COMPLICATION_TYPE_INVALID:");
          w.line("    return WfbScale.ranges(c);");
        }
      });
      w.line("return null;");
    });
  });
  return w.render();
}

export function emitSlotScale(face: Face, names: Iterable<string>, apps: boolean): SourceFile {
  return { path: `source/${SLOT_SCALE_MODULE}.mc`, text: slotScaleText(names, apps, header(face)) };
}

/** Every gauge drawing a declared `config: slots:` slot, in draw order. */
export function slotGauges(face: Face): Gauge[] {
  return face.walk().filter((e): e is Gauge => e instanceof Gauge && e.slot !== null && face.config_data.has(e.slot));
}

/** Every gauge with `max: auto` on a bare complication. */
export function autoScaleGauges(face: Face): Gauge[] {
  return face.walk().filter((e): e is Gauge => e instanceof Gauge && e.auto_scale !== null);
}

/** The complication types a gauge scales by, and whether any can show an app's complication. */
export function slotScaleTypes(face: Face): [string[], boolean] {
  const names = new Set<string>();
  let apps = false;
  for (const gauge of slotGauges(face)) {
    const slot = face.config_data.get(gauge.slot!)!;
    for (const name of slot.choices === "any" ? complications.TYPES.keys() : slot.choices) names.add(name);
    apps = apps || slot.choices === "any";
  }
  for (const gauge of autoScaleGauges(face)) names.add(gauge.auto_scale!);
  return [[...names].sort(), apps];
}

/** The scale kinds that read `Toybox.UserProfile`. */
export const PROFILE_SCALES: ReadonlySet<string> = new Set(["heart_rate_zones", "vo2max"]);

/** Does a slot gauge's scale read the wearer's profile, needing the `UserProfile` permission? */
export function readsUserProfile(face: Face): boolean {
  const [names] = slotScaleTypes(face);
  return names.some((name) => complications.SCALE.has(name) && PROFILE_SCALES.has(complications.SCALE.get(name)!.kind));
}
