// Backend 1: a draw program's values spelt as Monkey C. Port of the value
// half of wfb/draw/printer.py (`num_code`, `cond_code`, `str_code`,
// `color_code`), which lowering reads to tell two colours apart; the ops'
// own printing comes with the view.
import * as formatting from "../formatting.ts";
import { localName } from "../ir/naming.ts";
import { stringLiteral } from "../mcsource.ts";
import { AodStyle, glyphYExpr, mcColor, mcFloat, NO_AOD, plus, shifted } from "../emit/monkeyc/common.ts";
import { val } from "./barrel.ts";
import type { Cond, Num, Paint, Str } from "./program.ts";

export function numCode(n: Num, aod: AodStyle = NO_AOD): string {
  switch (n.t) {
    case "Const": return `Layout.${n.name}`;
    case "Lit": {
      const v = val(n.value);
      return Number.isInteger(v) ? String(v) : mcFloat(v);
    }
    case "Shifted": return shifted(numCode(n.base, aod), n.by);
    case "AodPick": return aod.value(n.asleep !== null ? numCode(n.asleep, aod) : null, numCode(n.awake, aod));
    case "FloatLit": return mcFloat(n.value) + n.suffix;
    case "NumLocal": return n.name;
    case "Read": return n.expr.code;
    case "Bin": return `${numCode(n.a, aod)} ${n.op} ${numCode(n.b, aod)}`;
    case "Paren": return `(${numCode(n.inner, aod)})`;
    case "Call": return `${n.fn}(${n.args.map((a) => numCode(a, aod)).join(", ")})`;
    case "Conv": return `${numCode(n.inner, aod)}.${n.method}()`;
    case "NumPick": return `(${condCode(n.cond, aod)}) ? ${numCode(n.then, aod)} : ${numCode(n.otherwise, aod)}`;
    case "FontDrop": return glyphYExpr(numCode(n.base, aod), n.valign, n.font);
    case "HandAngle": return `WfbHands.${n.function}(clock)`;
    case "TextWidth": return `dc.getTextWidthInPixels(${strCode(n.text, aod)}, ${n.font.code})`;
    case "FontHeight": return `dc.getFontHeight(${n.font.code})`;
    case "Grown": return plus(numCode(n.base, aod), String(n.by), n.times);
  }
}

export function condCode(c: Cond, aod: AodStyle = NO_AOD): string {
  switch (c.t) {
    case "Present": return c.guards.map((name) => `${name} != null`).join(" && ");
    case "LocalsSet": return c.names.map((name) => `${name} != null`).join(" && ");
    case "Cmp": return `${numCode(c.a, aod)} ${c.op} ${numCode(c.b, aod)}`;
    case "AnyOf": return c.conds.map((term) => condCode(term, aod)).join(" || ");
    case "Truthy": return c.expr.code;
    case "NotSleeping": return "!_sleeping";
    case "IsPulsing": return `_pulsing == ${c.unique}`;
    case "NotPulsing": return `_pulsing != ${c.unique}`;
  }
}

export function strCode(s: Str, aod: AodStyle = NO_AOD): string {
  switch (s.t) {
    case "AodStr": return aod.value(strCode(s.asleep, aod), strCode(s.awake, aod));
    case "StrLit": return stringLiteral(s.text);
    case "Reading": return formatting.emit(s.spec, s.value.code, s.value.value.type, { unitCode: s.unit !== null ? s.unit.code : null });
    case "Concat": return s.parts.map((part) => strCode(part, aod)).join(" + ");
    case "IconChoice": return `IconGlyphs.glyph(WfbWeather.chooseIcon(${localName(s.value.sources[0]!)}))`;
    case "PerCopy": return strCode(s.printed, aod);
    case "Local": return s.name;
  }
}

export function colorCode(c: Paint, aod: AodStyle = NO_AOD): string {
  switch (c.t) {
    case "Color": return mcColor(c.expr);
    case "AodRestyled": return aod.color(c.element, c.key, c.awake !== null ? colorCode(c.awake, aod) : null);
    case "AodDimmed": return aod.dimmed(c.element, c.expr);
    case "AodPaint": return aod.value(colorCode(c.asleep, aod), colorCode(c.awake, aod));
    case "AodPart": return aod.partColor(c.element, c.expr);
    case "PaintPick": return `(${condCode(c.cond, aod)}) ? ${colorCode(c.then, aod)} : ${colorCode(c.otherwise, aod)}`;
    case "RingColor": return "ringColor";
  }
}
