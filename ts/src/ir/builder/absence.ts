// Null handling and `format:`: the platform makes absence normal
// (constraint 8), so a nullable binding must say what to draw without it.
// Port of wfb/ir/builder/absence.py.
import * as catalog from "../../catalog.ts";
import type { Span } from "../../diagnostics.ts";
import * as formatting from "../../formatting.ts";
import { repr } from "../../py.ts";
import { type Element, type Expression, ROLE_VISIBLE } from "../model.ts";
import { Readers } from "./reading.ts";
import type { Node } from "./state.ts";

/** Shared note of every "can be absent, so 'absent:' is required" error. */
export const ABSENCE_IS_NORMAL = "every ActivityMonitor field is nullable and sensors are simply missing "
  + "on some devices, so absence is the normal case, not an error";
const WHEN_ABSENT_CHOICES = "choose one of: 'absent: hide', a text to draw instead "
  + "('absent: \"--\"'), or a value to use instead ('absent: {value: <expression>}')";

/** An internal `{:spec}` format as the author's `text:` template, the bound expression back inside each placeholder. */
function asTemplate(spec: string, bound: Expression): string {
  return spec.replace(/\{(:[^{}]*)?\}/g, (_, fmt: string | undefined) => "{" + bound.shown + (fmt ?? "") + "}");
}

const absentOf = (element: Element): string | null => ((element as unknown as { absent?: string | null }).absent ?? null);

/** `absent:` and `format:` checks for a bound value. */
export class AbsenceChecks extends Readers {
  /** ADR 0005 3: null handling is part of the binding, not an afterthought. */
  checkAbsence(node: Node, element: Element, bound: Expression, absent: string | null, placeholder: string | null,
    fallback: Expression | null, key = "value"): void {
    if (!bound.nullable) {
      // "No effect" only when nothing else on the element (but `visible:`) is nullable either.
      const othersNullable = element.boundExpressions()
        .some(([role, expression]) => expression !== bound && role !== ROLE_VISIBLE && expression.nullable);
      if (absent !== null && !othersNullable) {
        this.bag.note("when-absent", `${element.id}: 'absent:' has no effect -- ${bound.shown} is never absent`,
          this.doc.span(node, "absent"));
      }
      return;
    }
    if (absent === null) {
      this.bag.error("when-absent", `${element.id}: ${repr(bound.shown)} can be absent, so 'absent:' is required`,
        this.doc.span(node, key), { notes: [ABSENCE_IS_NORMAL, WHEN_ABSENT_CHOICES] });
      return;
    }
    if (absent === "fallback" && fallback !== null && fallback.nullable) {
      this.bag.error("when-absent", `${element.id}: the 'absent: {value:}' expression can itself be absent`,
        this.fallbackSpan(node), { notes: ["the value used instead of an absent reading must always exist"] });
    }
  }

  /** A nullable binding outside `value` still needs an explicit `absent:`. */
  checkOtherAbsence(node: Node, element: Element, key: string, bound: Expression | null, span: Span | null = null): void {
    if (bound === null || !bound.nullable) return;
    if (absentOf(element) !== null) return;
    this.bag.error("when-absent",
      `${element.id}: ${repr(key)} reads ${repr(bound.shown)}, which can be absent, so 'absent:' is required`,
      span !== null ? span : this.doc.span(node, key), {
        notes: [
          ABSENCE_IS_NORMAL,
          `'absent:' is required once anything on this element is nullable, not `
          + `just the reading it draws -- a nullable ${key} always hides the `
          + "element when absent, whatever 'absent:' says for the reading",
          WHEN_ABSENT_CHOICES,
        ],
      });
  }

  /** Warn when a placeholder or fallback can never be drawn: every nullable source behind the value hides the element first. */
  checkReachableSubstitute(node: Node, element: Element, key: string, valueBindings: readonly (Expression | null)[],
    otherBindings: readonly (Expression | null)[]): void {
    const policy = absentOf(element);
    if (policy !== "placeholder" && policy !== "fallback") return;
    const valueSources = this.nullableSources(valueBindings);
    if (valueSources.size === 0) return;
    let others = otherBindings;
    if (element.visible !== null) {
      others = [...otherBindings, element.visible];
      key = `${key}/'visible'`;
    }
    const otherSources = this.nullableSources(others);
    if (![...valueSources].every((s) => otherSources.has(s))) return;
    const shared = [...valueSources].sort().join(", ");
    const substitute = policy === "fallback" ? "'absent: {value:}' value" : "'absent:' text";
    const shown = key;
    this.bag.warning("when-absent",
      `${element.id}: the ${substitute} can never be drawn -- ${shared} is also read `
      + `by ${shown}, which hides the element whenever it is absent`,
      (policy === "fallback" ? this.fallbackSpan(node) : this.doc.span(node, "absent")) ?? this.doc.span(node, key), {
        notes: [
          `a nullable ${shown} always hides the element, and that guard runs before `
          + `the reading's own ${substitute}`,
          `either drop the ${substitute}, or stop reading ${shared} from ${shown} so the `
          + "element can still draw when the reading is missing",
        ],
        confidence: "exact -- the same guard order codegen emits",
      });
  }

  /** Catalogue paths among `bindings` that the generated code null-checks. */
  nullableSources(bindings: readonly (Expression | null)[]): Set<string> {
    const out = new Set<string>();
    for (const bound of bindings) {
      if (bound === null) continue;
      for (const path of bound.sources) {
        const source = catalog.get(path);
        if (source !== undefined && catalog.guardNeeded(source)) out.add(path);
      }
    }
    return out;
  }

  /** A `text:` placeholder's format against the value it reads. */
  checkFormat(node: Node, bound: Expression, spec: string | null): void {
    const span = this.doc.span(node, "text");
    if (spec === null) {
      if (catalog.isFormatted(bound.value.type)) {
        const example = bound.value.type === "date" ? "{:%a %e %b}" : "{:%H:%M}";
        this.bag.error("format", `a ${bound.value.type} value needs a format spec in its `
          + `placeholder, e.g. '{${bound.shown}${example.slice(1)}'`, span);
      }
      return;
    }
    this.checkFormatSpec(bound, spec, span);
  }

  /** The coded-versus-type checks a `format:` spec needs against the value it formats. */
  checkFormatSpec(bound: Expression, spec: string, span: Span | null): void {
    const report = (fn: () => unknown): void => {
      try {
        fn();
      } catch (error) {
        if (!(error instanceof formatting.FormatError)) throw error;
        this.bag.error("format", error.message, span);
      }
    };
    try {
      formatting.parse(spec);
    } catch (error) {
      if (!(error instanceof formatting.FormatError)) throw error;
      this.bag.error("format", error.message, span);
      return;
    }
    const type = bound.value.type;
    const coded = formatting.isTimeSpec(spec);
    if (formatting.isDuration(spec, type)) {
      // strftime codes on a Number or Float read it as seconds.
      report(() => {
        for (const part of formatting.parse(spec)) {
          if (part.kind === "field") formatting.parseTime(part.spec, formatting.DURATION_CODES);
        }
      });
    } else if (coded && !catalog.isFormatted(type)) {
      this.bag.error("format", `strftime-style format ${repr(asTemplate(spec, bound))} needs a time, date or `
        + `number value, got ${bound.value}`, span);
    } else if (!coded && catalog.isFormatted(type)) {
      const example = type === "date" ? "{:%a %e %b}" : "{:%H:%M}";
      this.bag.error("format", `a ${type} value needs a strftime-style format `
        + `such as ${repr(asTemplate(example, bound))}`, span);
    } else if (coded) {
      // A date spec on a clock value and the reverse both parse, and the wrong one renders nonsense.
      report(() => formatting.strftimeParts(spec, type));
    } else {
      // A plain number (or string); `{unit}` is checked against `units:` elsewhere.
      report(() => formatting.emit(spec, "value", type, { unitCode: "unit" }));
    }
  }
}
