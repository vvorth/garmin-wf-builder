// Backend 1: a draw program as the Monkey C body of `draw<Id>`. It writes through the emitter's own `Writer`, so
// wrapping and spacing come out as the rest of the view's.
import * as formatting from "../formatting.ts";
import { localName } from "../ir/naming.ts";
import { stringLiteral } from "../mcsource.ts";
import { AodStyle, glyphYExpr, HOLDS_SHOWN, maskLiteral, mcColor, mcFloat, NO_AOD, plus, shifted } from "../emit/monkeyc/common.ts";
import { val } from "./barrel.ts";
import type { Cond, Num, Op, Paint, SlotText, Str, Text } from "./program.ts";
import type { Writer } from "../emit/writer.ts";
import { emitPartRing, emitTransformedPart } from "../emit/monkeyc/rotated.ts";
import { RADIAL_DIRECTION, radialRadiusExpr } from "../emit/monkeyc/shapes.ts";
import { truthy } from "../py.ts";

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

/** Write `ops` into `w`, spelling every always-on choice the way this build's `aod` does. */
export function printOps(w: Writer, ops: readonly Op[], aod: AodStyle = NO_AOD): void {
  for (const op of ops) printOp(w, op, aod);
}

const note = (text: string): string => (text ? `  // ${text}` : "");

function printOp(w: Writer, op: Op, aod: AodStyle): void {
  const n = (value: Num): string => numCode(value, aod);
  switch (op.t) {
    case "SetColor": w.line(`dc.setColor(${colorCode(op.color, aod)}, Graphics.COLOR_TRANSPARENT);` + note(op.note)); break;
    case "SetPen": w.line(`dc.setPenWidth(${op.width !== null ? n(op.width) : "1"});` + note(op.note)); break;
    case "Primitive": w.call(`dc.${op.name}`, op.args.map((group) => group.map(n).join(", "))); break;
    case "FillPolygon": w.line(`dc.fillPolygon(Layout.${op.const});`); break;
    case "ArcSpan":
      if (op.pen_first) w.call("WfbArc.drawSpan", [`dc, ${n(op.cx)}, ${n(op.cy)}, ${n(op.radius)}, ${n(op.pen)}`, `${n(op.start)}, ${n(op.sweep)}`]);
      else w.call("WfbArc.drawSpan", [`dc, ${n(op.cx)}, ${n(op.cy)}, ${n(op.radius)}`, `${n(op.pen)}, ${n(op.start)}, ${n(op.sweep)}`]);
      break;
    case "ArcProgress":
      w.call("WfbArc.drawProgress", [`dc, ${n(op.cx)}, ${n(op.cy)}, ${n(op.radius)}`, `${n(op.pen)}, ${n(op.start)}, ${n(op.sweep)}`, n(op.fraction)]);
      break;
    case "Part":
      if (op.ring === null) emitTransformedPart(w, op.part, op.prefix, { radial: op.radial, thicknessExpr: n(op.pen), setPen: op.set_pen });
      else emitPartRing(w, op.part, op.prefix, op.ring, { radial: op.radial, thicknessExpr: n(op.pen), setPen: op.set_pen });
      break;
    case "SeriesRebuild":
      w.line("var graphMinute = System.getClockTime().min;");
      w.block(`if (graphMinute != ${op.built})`, () => {
        w.line(`${op.built} = graphMinute;`);
        w.line(`${op.method}();`);
      });
      break;
    case "SeriesDraw": {
      const width = op.width !== null ? `${n(op.width)}, ` : "";
      w.call(`WfbSeries.draw${op.style.slice(0, 1).toUpperCase()}${op.style.slice(1)}`, [
        `dc, ${n(op.x)}, ${n(op.y)}, ${n(op.w)}, ${n(op.h)}`, `${width}${op.series}, ${n(op.lo)}, ${n(op.hi)}`,
      ]);
      break;
    }
    case "Let": w.line(`var ${op.name} = ${n(op.value)};` + note(op.note)); break;
    case "Assign": w.line(`${op.name} = ${n(op.value)};`); break;
    case "If":
      w.block(`if (${condCode(op.cond, aod)})`, () => printOps(w, op.then, aod));
      if (op.otherwise.length > 0) w.block("else", () => printOps(w, op.otherwise, aod));
      break;
    case "For": w.block(`for (var ${op.var} = 0; ${op.var} < ${n(op.bound)}; ${op.var}++)`, () => printOps(w, op.body, aod)); break;
    case "Continue": w.line("continue;"); break;
    case "Return": w.line("return;"); break;
    case "SlotPull":
      w.line(`var chosenId = ${op.field};`);
      w.line(op.guarded ? "var pulled = (chosenId != null) ? WfbComplications.valueOf(chosenId) : null;" : "var pulled = WfbComplications.valueOf(chosenId);");
      break;
    case "SlotIcon":
      w.line(`var iconFont = _${op.font};`);
      w.comment("the icon is chosen from the wearer's picked *type*, so it still shows");
      w.comment("even on a frame the reading itself could not be pulled -- a name,");
      w.comment("then IconGlyphs.glyph turns it into the actual character");
      w.line(op.guarded ? `var iconName = (chosenId != null) ? ${op.method}(chosenId.getType(), pulled) : null;`
        : `var iconName = ${op.method}(chosenId.getType(), pulled);`);
      w.line("var iconGlyph = (iconName != null) ? IconGlyphs.glyph(iconName) : null;");
      w.blank();
      break;
    case "SlotText": printSlotText(w, op); break;
    case "LetSlotPick":
      w.line(`var chosenId = ${op.field};`);
      if (op.guarded) {
        w.line("var chosenType = (chosenId != null) ? chosenId.getType() : null;");
        w.line("var pulled = (chosenId != null) ? WfbComplications.valueOf(chosenId) : null;");
      } else {
        w.line("var chosenType = chosenId.getType();");
        w.line("var pulled = WfbComplications.valueOf(chosenId);");
      }
      w.line(`var scale = (chosenType != null && pulled != null) ? ${op.module}.scale(chosenType, pulled) : null;`);
      break;
    case "LetAutoScale":
      w.line(`var scale = (${op.reader} != null) ? ${op.module}.scale(Complications.${op.constant}, ${op.reader}) : null;`);
      break;
    case "VisibleGuard": {
      const e = op.expr;
      if (e.constant !== null && truthy(e.constant)) {
        w.comment(`visible: ${e.text} -- always true, nothing to check`);
        w.blank();
      } else {
        const parts = [...op.locals.map((name) => `${name} == null`), op.negated];
        w.comment(`visible: ${e.text}` + (parts.length > 1 ? " -- absent means hidden" : ""));
        w.block(`if (${parts.join(" || ")})`, () => w.line("return;"));
        if (op.shown !== 0) w.line(`${HOLDS_SHOWN} |= ${maskLiteral(op.shown)};  // on screen: a hold may reach it`);
        w.blank();
      }
      break;
    }
    case "NullGuard":
      w.comment(op.note);
      w.block(`if (${op.locals.map((name) => `${name} == null`).join(" || ")})`, () => w.line("return;"));
      w.blank();
      break;
    case "AntiAlias": {
      const on = op.on ? "true" : "false";
      if (op.comment) w.comment(`antialias: ${on}`);
      w.line(`applyAntiAlias(dc, ${on});`);
      break;
    }
    case "LoadFont":
      w.line(`var ${op.local} = ${op.source};`);
      if (op.on_null === "return") w.block(`if (${op.local} == null)`, () => w.line(`return;  // ${op.note}`));
      break;
    case "Text": printText(w, op, aod); break;
    case "Glyph": printUpright(w, op.x, op.y, op.font.code, op.glyph, op.justify, op.valign, aod); break;
    case "LetText":
      w.line(`var ${op.name} = ${strCode(op.initial, aod)};`);
      w.block(`if (${op.guards.map((g) => `${g} != null`).join(" && ")})`, () => w.line(`${op.name} = ${strCode(op.value, aod)};`));
      break;
    case "IfNotNull": w.block(`if (${op.local} != null)`, () => printOps(w, op.body, aod)); break;
    case "IfAod":
      w.block("if (_aod)", () => printOps(w, op.then, aod));
      if (op.otherwise.length > 0) w.block("else", () => printOps(w, op.otherwise, aod));
      break;
    case "IfAwake": w.block("if (!_aod)", () => printOps(w, op.body, aod)); break;
    case "Comment": w.comment(op.text); break;
    case "Blank": w.blank(); break;
  }
}

function printSlotText(w: Writer, op: SlotText): void {
  const absent = (): void => {
    if (op.absent === "placeholder") {
      w.comment(`absent: "${op.placeholder}"`);
      w.line(`text = "${op.placeholder}";`);
    } else {
      w.comment("absent: hide -- the reading blanks, the icon (if any) stays");
    }
  };
  w.line('var text = "";');
  const unit = op.unit ? "true" : "false", short = op.short ? "true" : "false";
  w.block(op.guarded ? "if (pulled == null || chosenId == null)" : "if (pulled == null)", absent);
  w.block("else", () => {
    w.line(`var reading = ${op.module}.reading(chosenId.getType(), pulled, ${unit}, ${short});`);
    w.block("if (reading == null)", absent);
    w.block("else", () => {
      if (op.label === "short" || op.label === "long") {
        w.line(`var label = pulled.${op.label === "short" ? "shortLabel" : "longLabel"};`);
        w.block("if (label != null)", () => w.line('text = label + " ";'));
      }
      w.line("text += reading;");
    });
  });
  w.blank();
}

function printText(w: Writer, op: Text, aod: AodStyle): void {
  const x = numCode(op.x, aod), y = numCode(op.y, aod);
  const justify = op.justify.map((flag) => `Graphics.${flag}`).join(" | ");
  const value = strCode(op.text, aod);
  const font = op.font.code;
  if (op.joined) {
    w.call("dc.drawText", [`${x}, ${y}, ${font}, ${value}`, justify]);
  } else if (op.split_x) {
    printSplit(w, op, x, y, font, value, justify, aod);
  } else if (op.style === "angled") {
    w.call("dc.drawAngledText", [`${x}, ${y}, ${font}, ${value}`, `${justify}, ${numCode(op.angle!, aod)}`]);
  } else if (op.style === "radial") {
    const direction = RADIAL_DIRECTION[op.direction ?? "clockwise"];
    const radius = radialRadiusExpr(numCode(op.radius!, aod), op.valign, op.direction, font);
    w.call("dc.drawRadialText", [`${x}, ${y}, ${font}, ${value}`, `${justify}, ${numCode(op.angle!, aod)}, ${radius}`, `Graphics.${direction}`]);
  } else {
    printUpright(w, op.x, op.y, font, op.text, op.justify, op.shift_y ? op.valign : "center", aod);
  }
}

/** A text call with its `x` on a line of its own: a pattern's text part. */
function printSplit(w: Writer, op: Text, x: string, y: string, font: string, value: string, justify: string, aod: AodStyle): void {
  const head = `${y}, ${font}, ${value}`;
  if (op.style === null) {
    w.call("dc.drawText", [x, head, justify]);
    return;
  }
  const angle = numCode(op.angle!, aod);
  if (op.style === "angled") {
    w.call("dc.drawAngledText", [x, head, `${justify}, ${angle}`]);
    return;
  }
  const direction = RADIAL_DIRECTION[op.direction ?? "clockwise"];
  const radius = radialRadiusExpr(numCode(op.radius!, aod), op.valign, op.direction, font);
  w.call("dc.drawRadialText", [x, head, `${justify}, ${angle}, ${radius}`, `Graphics.${direction}`]);
}

/** An upright `dc.drawText`: `bottom` moves `y` up by the font's height. */
function printUpright(w: Writer, x: Num, y: Num, font: string, text: Str, justify: readonly string[], valign: string, aod: AodStyle): void {
  const flags = justify.map((flag) => `Graphics.${flag}`).join(" | ");
  w.call("dc.drawText", [`${numCode(x, aod)}, ${glyphYExpr(numCode(y, aod), valign, font)}, ${font}`, strCode(text, aod), flags]);
}
