// Inline checks for complication type constants a target lacks.
//
// `Guards.gated_types` names the complication types some target has
// `Toybox.Complications` for but not the type's constant in its own symbol
// table. The module check `monkeyc` accepts around such a constant is no
// guard at run time: the VM resolves the constant when execution reaches it
// and throws Symbol Not Found (docs/lore/platform-constraints.md, 6d). So
// every reference to one is preceded, in its own `&&` chain or an enclosing
// `if`, by `(Complications has :<constant>)`, written at the use, never kept
// in a local (`monkeyc` does not see a check in a local). `generate` refuses
// a reference this module failed to cover (`unguardedTypes` in
// ts/src/emit/project.ts).
import type { Guards as AllGuards } from "../../availability.ts";
import * as complications from "../../complications.ts";
import type { Writer } from "../writer.ts";

/** What these checks read from a build's `Guards`. */
type Guards = Pick<AllGuards, "gated_types">;

/** Type `name`'s constant, `COMPLICATION_TYPE_...`. */
export function constantOf(name: string): string {
  return complications.TYPES.get(name)!.constant;
}

/** Whether a reference to type `name` needs its own `has` check in this build. */
export function gated(guards: Guards, name: string): boolean {
  return guards.gated_types.has(name);
}

/** The type name whose constant is `constant`, or `undefined` for none. */
export function typeOfConstant(constant: string): string | undefined {
  for (const type of complications.TYPES.values()) if (type.constant === constant) return type.name;
  return undefined;
}

/** `(Complications has :<constant>)` when type `name` is gated, else null. */
export function typeCheck(guards: Guards, name: string): string | null {
  return gated(guards, name) ? `(Complications has :${constantOf(name)})` : null;
}

/** `typeCheck` for a reference named by its constant (a reader's `complication_type`). */
export function constantCheck(guards: Guards, constant: string): string | null {
  const name = typeOfConstant(constant);
  return name !== undefined ? typeCheck(guards, name) : null;
}

/** `<subject> == Complications.<constant>`, after the type's own check when it is gated. */
export function typeTest(guards: Guards, name: string, subject = "t"): string {
  const test = `${subject} == Complications.${constantOf(name)}`;
  const check = typeCheck(guards, name);
  return check !== null ? `${check} && ${test}` : test;
}

/** One `switch` case: the types sharing it (fall-through) and the statement it runs. */
export interface TypeCase {
  members: readonly string[];
  body: string;
}

/**
 * `switch (<subject>)` over complication types. A gated member leaves the
 * switch for an `if` before it, testing it behind its own check (a case
 * label is a reference like any other); the members left keep their cases.
 * `sameLine` writes the body after the last label (`case X: return 1;`),
 * otherwise on its own line under it. Every body must leave the function
 * (`return`), so hoisting a case out of the switch keeps its meaning.
 * `fallback` is the `default:` statement, written plainly when hoisting
 * left no case. `tail` holds raw lines for the end of the switch (a case on a
 * constant every target has). A build with no gated types writes exactly
 * the plain switch.
 */
export function emitTypeSwitch(w: Writer, guards: Guards, cases: readonly TypeCase[],
  { subject = "t", sameLine = true, fallback = null, tail = [] }: {
    subject?: string; sameLine?: boolean; fallback?: string | null; tail?: readonly string[];
  } = {}): void {
  const kept: TypeCase[] = [];
  let anyHoisted = false;
  for (const c of cases) {
    const hoisted = c.members.filter((name) => gated(guards, name));
    if (hoisted.length > 0) {
      anyHoisted = true;
      const tests = hoisted.map((name) => typeTest(guards, name, subject));
      const condition = tests.length === 1 ? tests[0]! : tests.map((t) => `(${t})`).join(" || ");
      w.block(`if (${condition})`, () => w.line(c.body));
    }
    const rest = c.members.filter((name) => !gated(guards, name));
    if (rest.length > 0) kept.push({ members: rest, body: c.body });
  }
  if (anyHoisted && kept.length === 0 && tail.length === 0) {
    if (fallback !== null) w.line(fallback);
    return;
  }
  w.block(`switch (${subject})`, () => {
    for (const c of kept) {
      const labels = c.members.map((name) => `case Complications.${constantOf(name)}:`);
      if (sameLine) {
        for (const label of labels.slice(0, -1)) w.line(label);
        w.line(`${labels[labels.length - 1]!} ${c.body}`);
      } else {
        for (const label of labels) w.line(label);
        w.line(`    ${c.body}`);
      }
    }
    for (const line of tail) w.line(line);
    if (fallback !== null) w.line(`default: ${fallback}`);
  });
}
