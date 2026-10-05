// `ReadPlan`: which API calls happen, and where, for one view. Port of
// wfb/emit/monkeyc/readplan.py's analysis, guards and declarations; the
// pulls it writes come with the view.
import * as catalog from "../../catalog.ts";
import { CATALOG, READERS, type Source } from "../../catalog.ts";
import { frameMembers } from "../../draw/frames.ts";
import * as formatting from "../../formatting.ts";
import { type Element, type Expression, HandsElement, Text } from "../../ir/model.ts";
import { localName } from "../../ir/naming.ts";
import type { Placed, ResolvedFace } from "../../layout.ts";
import { type Guards, NO_GUARDS } from "./common.ts";

/**
 * Decides which reader locals each element needs, and hoists the reads.
 * Sources are grouped by reader, so a reader is called once per frame, and
 * every nullable field becomes a named local the element's guard narrows.
 */
export class ReadPlan {
  readonly resolved: ResolvedFace;
  readonly device_guards: Guards;
  readonly modules = new Set<string>();
  readonly barrel: Set<string>;
  /** Every source an element touches, for reader hoisting. */
  private readonly perElement = new Map<string, string[]>();
  /** The subset referenced by compiled expressions. */
  private readonly bound = new Map<string, string[]>();
  /** The subset reached through the element's value expression(s). */
  private readonly valueBound = new Map<string, string[]>();
  /** The subset reached through every other expression. */
  private readonly otherBound = new Map<string, string[]>();
  /** The subset reached through `visible:`, which has its own guard. */
  private readonly visibleBound = new Map<string, string[]>();
  private readonly readersForMode = new Map<string, string[]>();
  private aodIdList: string[] = [];

  constructor(resolved: ResolvedFace, guards: Guards | null = null) {
    this.resolved = resolved;
    this.device_guards = guards ?? NO_GUARDS;
    this.barrel = new Set(resolved.face.barrelFunctions());
    this.analyse();
  }

  private analyse(): void {
    const add = (list: string[], path: string): void => {
      if (!list.includes(path)) list.push(path);
    };
    for (const placed of this.resolved.items) {
      const element = placed.element;
      const valueExprs = ReadPlan.valueExpressions(element);
      const paths: string[] = [], valuePaths: string[] = [], otherPaths: string[] = [], visiblePaths: string[] = [];
      for (const expression of element.expressions()) {
        for (const m of expression.modules) this.modules.add(m);
        const isValue = valueExprs.some((v) => v === expression);
        const isVisible = expression === element.visible;
        for (const path of expression.sources) {
          add(paths, path);
          if (isVisible) add(visiblePaths, path);
          else if (isValue) add(valuePaths, path);
          else add(otherPaths, path);
        }
      }
      // A strftime format reads the clock or the calendar even though it
      // names no source, and some codes a second reader too.
      const formatPaths: string[] = [];
      if (element instanceof Text) {
        element.segments().forEach(([value, spec], index) => {
          if (!formatting.isTimeSpec(spec)) return;
          let valueType = value.value.type;
          if (!catalog.isNumeric(valueType)) {
            valueType = valueType === "date" ? "date" : "time";
            add(formatPaths, valueType === "date" ? "date.today" : "time.clock");
          }
          const specs = [spec];
          if (index === 0 && element.aod !== null && element.aod.format !== null) specs.push(element.aod.format);
          for (const one of specs) for (const extra of formatting.extraPaths(one, valueType)) add(formatPaths, extra);
        });
      }
      // A hands element reads the clock with no author expression at all.
      if (element instanceof HandsElement) formatPaths.push("time.clock");
      this.bound.set(placed.id, [...paths]);
      this.visibleBound.set(placed.id, [...visiblePaths]);
      this.valueBound.set(placed.id, valuePaths.filter((p) => !visiblePaths.includes(p)));
      this.otherBound.set(placed.id, otherPaths.filter((p) => !visiblePaths.includes(p)));
      const all = [...paths, ...formatPaths.filter((p) => !paths.includes(p))];
      this.perElement.set(placed.id, all);
      for (const path of all) this.modules.add(READERS.get(CATALOG.get(path)!.reader)!.module);
    }

    for (const mode of ["active", "low_power"]) {
      let readers: string[] = [];
      for (const placed of this.resolved.items) {
        if (!placed.element.modes.includes(mode)) continue;
        readers = ReadPlan.dedupeReaders(this.perElement.get(placed.id)!, readers);
      }
      this.readersForMode.set(mode, readers);
    }
    this.aodIdList = frameMembers(this.resolved.items, "aod").map((p) => p.id);
    let aodReaders: string[] = [];
    for (const placed of this.resolved.items) {
      const aod = placed.element.aod;
      if (!this.aodIdList.includes(placed.id) || aod === null) continue;
      aodReaders = ReadPlan.dedupeReaders(this.perElement.get(placed.id)!, aodReaders);
      if (aod.visible_override !== null) aodReaders = ReadPlan.dedupeReaders(aod.visible_override.sources, aodReaders);
    }
    this.readersForMode.set("aod", aodReaders);
  }

  /** Ids of every drawn element whose resolved `aod:` is set, in draw order. */
  aodIds(): string[] {
    return [...this.aodIdList];
  }

  /** Reader names this design reads through `Toybox.Complications`. */
  complicationReaders(): string[] {
    const names = new Set<string>();
    for (const readers of this.readersForMode.values()) for (const name of readers) if (READERS.get(name)!.complication_type) names.add(name);
    return [...names].sort();
  }

  /** The readers drawing `items` needs, in first-use order. */
  readersFor(items: readonly Placed[], aod = false): string[] {
    let readers: string[] = [];
    for (const placed of items) {
      readers = ReadPlan.dedupeReaders(this.perElement.get(placed.id)!, readers);
      const extra = aod ? ReadPlan.aodVisibleOverride(placed) : null;
      if (extra !== null) readers = ReadPlan.dedupeReaders(extra.sources, readers);
    }
    return readers;
  }

  readersForModeOf(mode: string): string[] {
    return [...(this.readersForMode.get(mode) ?? [])];
  }

  /** The readers `placed`'s draw method takes, in parameter order. */
  readersOf(placed: Placed): string[] {
    return this.readersUsedBy(placed);
  }

  parameters(placed: Placed): string {
    return this.readersUsedBy(placed).map((name) => {
      const reader = READERS.get(name)!;
      return `, ${reader.name} as ${reader.monkeyc_type}`;
    }).join("");
  }

  arguments(placed: Placed): string {
    return this.readersUsedBy(placed).map((name) => `, ${READERS.get(name)!.name}`).join("");
  }

  /** Whether `declarations()` gave this source's local a nullable type. */
  private guardNeeded(source: Source): boolean {
    if (catalog.guardNeeded(source)) return true;
    const root = source.field_name ? source.field_name.split(".", 1)[0]! : null;
    return root !== null && this.device_guards.fields.has(root);
  }

  /** Every local the element must null-check, less what `visible:` already checks. */
  guards(placed: Placed): string[] {
    const visible = this.visibleBound.get(placed.id)!;
    return this.guardedLocals(this.bound.get(placed.id)!.filter((p) => !visible.includes(p)));
  }

  private guardedLocals(paths: readonly string[]): string[] {
    return paths.filter((path) => this.guardNeeded(CATALOG.get(path)!)).map(localName);
  }

  /** Locals reached through the element's own value expression(s). */
  valueGuards(placed: Placed): string[] {
    return this.guardedLocals(this.valueBound.get(placed.id)!);
  }

  /** Locals `visible:` dereferences, in declaration order. */
  visibleGuards(placed: Placed): string[] {
    return this.guardedLocals(this.visibleBound.get(placed.id)!);
  }

  /** Locals dereferenced by a different expression (colour, track colour, max). */
  otherGuards(placed: Placed): string[] {
    return this.guardedLocals(this.otherBound.get(placed.id)!);
  }

  /** The bound expressions an element's `absent:` policy governs. */
  private static valueExpressions(element: Element): Expression[] {
    return element.boundExpressions().filter(([role]) => element.valueRoles.has(role)).map(([, e]) => e);
  }

  declarations(placed: Placed): [string, string][] {
    return this.declarePaths(this.bound.get(placed.id)!);
  }

  /** The extra condition `aod: {visible: ...}` adds for this element, or `null`. */
  static aodVisibleOverride(placed: Placed): Expression | null {
    const aod = placed.element.aod;
    return aod !== null ? aod.visible_override : null;
  }

  /** Locals `aod: {visible: ...}`'s own extra condition needs at the AOD call site. */
  aodGuardDeclarations(placed: Placed): [string, string][] {
    const extra = ReadPlan.aodVisibleOverride(placed);
    return extra === null ? [] : this.declarePaths(extra.sources);
  }

  /** The Monkey C boolean for `aod: {visible: ...}`'s own extra condition, or `null`. */
  aodGuardCondition(placed: Placed): string | null {
    const extra = ReadPlan.aodVisibleOverride(placed);
    if (extra === null) return null;
    const parts = this.guardedLocals(extra.sources).map((name) => `${name} != null`);
    parts.push(extra.code);
    return parts.join(" && ");
  }

  private declarePaths(paths: readonly string[]): [string, string][] {
    const out: [string, string][] = [];
    for (const path of paths) {
      const source = CATALOG.get(path)!;
      // time.clock/date.today: formatting reads the reader parameter by name.
      if (source.field_name === null && (source.type === "time" || source.type === "date")) continue;
      const reader = READERS.get(source.reader)!;
      const base = source.array_index === null ? reader.name : `${reader.name}[${source.array_index}]`;
      const guardParts: string[] = [];
      if (reader.nullable) guardParts.push(`${reader.name} != null`);
      const arrayGuard = catalog.arrayGuard(source);
      if (arrayGuard !== null) guardParts.push(arrayGuard);
      const intermediate = source.intermediate;
      const fieldRoot = intermediate !== null ? intermediate : source.field_name;
      if (fieldRoot !== null && this.device_guards.fields.has(fieldRoot.split(".", 1)[0]!)) {
        guardParts.push(`${base} has :${fieldRoot.split(".", 1)[0]}`);
      }
      if (intermediate !== null) {
        let objRead = `${base}.${intermediate}`;
        if (guardParts.length > 0) objRead = `(${guardParts.join(" && ")}) ? ${objRead} : null`;
        const objName = `${localName(path)}Obj`;
        out.push([objName, objRead]);
        const suffix = source.field_name!.slice(intermediate.length + 1);
        out.push([localName(path), `(${objName} != null) ? ${objName}.${suffix} : null`]);
        continue;
      }
      let read = catalog.readExpr(source);
      if (source.count) read = `WfbComplications.count(${reader.name})`;
      else if (source.cast !== null) read = `${read} as ${source.cast}`;
      if (guardParts.length > 0) read = `(${guardParts.join(" && ")}) ? ${read} : null`;
      if (source.to_float) {
        const rawName = `${localName(path)}Raw`;
        out.push([rawName, read]);
        out.push([localName(path), `(${rawName} != null) ? ${rawName}.toFloat() : null`]);
        continue;
      }
      out.push([localName(path), read]);
    }
    return out;
  }

  private readersUsedBy(placed: Placed): string[] {
    return ReadPlan.dedupeReaders(this.perElement.get(placed.id)!);
  }

  /** The reader each of `paths` reads through, in first-seen order. */
  private static dedupeReaders(paths: readonly string[], into: readonly string[] | null = null): string[] {
    const readers = into !== null ? [...into] : [];
    for (const path of paths) {
      const reader = CATALOG.get(path)!.reader;
      if (!readers.includes(reader)) readers.push(reader);
    }
    return readers;
  }

  sourcesFor(placed: Placed): string[] {
    return this.perElement.get(placed.id)!;
  }
}
