// `type: hands`: places a declared `hand_sets:` entry on screen..
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { dedupAppend } from "../ir/builder/state.ts";
import { type Element, type Expression, HandsElement } from "../ir/model.ts";
import { type Placed, PlacedHands, ResolvedHand, type Resolver, rotatableParts } from "../layout.ts";
import { quoted, roundHalfEven as round, str } from "../py.ts";
import { Box } from "../units.ts";
import { type Common, type ContrastSubject, ElementKind, register } from "./base.ts";
import {
  AodDimmed, AodPart, AodPick, Assign, Blank, Call, Comment, Const, type DrawContext, HandAngle, If, Let, type Num, NumLocal,
  NotSleeping, type Op, type Paint, Part, RingColor, SetColor,
} from "../draw/program.ts";
import { colorCode } from "../draw/printer.ts";
import { andList, constPrefix } from "../emit/monkeyc/common.ts";
import * as lc from "../emit/monkeyc/layout_constants.ts";
import type { RotatablePart } from "../layout.ts";

type Node = Map<DataKey, Data>;

/** Each hand's `WfbHands` angle function, in drawing order. */
const HAND_ANGLE_FUNCTIONS: readonly (readonly [string, string])[] = [["hour", "hourAngle"], ["minute", "minuteAngle"], ["second", "secondAngle"]];

class HandsKind extends ElementKind<HandsElement> {
  readonly name = "hands";
  readonly irClass = HandsElement;
  override readonly ringed = true;
  override readonly staticForbidden = [
    "analog hands",
    "a hand's angle is the time -- a buffer filled once would freeze "
    + "it at whatever it showed on the first frame",
  ] as const;
  override readonly antialiased = true;

  override resolve(r: Resolver, element: HandsElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const handSet = r.face.hands.get(element.hands)!;
    const resolved = new Map<string, ResolvedHand>();
    let reach = 0.0;
    for (const [name, hand] of handSet.hands()) {
      if (name === "second" && element.seconds === "never") continue; // not drawn
      const [parts, handReach] = r.resolveParts(hand.parts, `${element.id}.${name}`, element.resolved_min_1px);
      resolved.set(name, ResolvedHand.create({ parts: rotatableParts(parts, `${element.id}.${name}`) }));
      reach = Math.max(reach, handReach);
    }
    const box = new Box(cx - reach, cy - reach, 2 * reach, 2 * reach);
    const aodThickness = r.aodExtent(element, "thickness", parent, 1);
    return PlacedHands.create({
      element, box: box.rounded(), center: [round(cx), round(cy)], depth,
      hour: resolved.get("hour") ?? null, minute: resolved.get("minute") ?? null, second: resolved.get("second") ?? null,
      reach, aod_thickness: aodThickness,
    });
  }

  override circularExtent(placed: Placed): [number, number, number] | null {
    const p = placed as PlacedHands;
    return [p.center[0], p.center[1], p.reach];
  }

  /** `common.at` is already the axis; the element's extent is the disc it sweeps, computed in layout. */
  build(b: Builder, node: Node, common: Common): Element | null {
    const name = node.get("set") as string;
    const elementId = common.id;
    const handSet = b.hand_sets.resolve(b.bag, name, b.doc.span(node, "set"),
      { code: "hands", message: `${elementId}: unknown hand set ${quoted(name)}`, note: "declared hand sets" });
    if (handSet === null) return null;

    let seconds = (node.get("seconds") ?? null) as string | null;
    if (seconds !== null && handSet.second === null) {
      const declared = handSet.hands().map(([n]) => n).join(", ") || "(none)";
      b.bag.error("hands", `${elementId}: 'seconds: ${str(seconds)}' needs a second hand, but hand_sets.${name} declares none`,
        b.doc.span(node, "seconds"), { notes: [`hand_sets.${name} declares: ${declared}`] });
      return null;
    }
    if (seconds === null && handSet.second !== null) seconds = "awake"; // the default
    if (seconds === "never" && handSet.hour === null && handSet.minute === null) {
      // The one combination that draws nothing at all.
      b.bag.error("hands", `${elementId}: 'seconds: never' on hand_sets.${name}, which has only a second hand, draws nothing`,
        b.doc.span(node, "seconds"), { notes: ["remove the element, or place a set with an hour or minute hand"] });
      return null;
    }
    if (common.modes.includes("low_power")) {
      b.bag.error("hands", `${elementId}: 'sleep_update: true' is not accepted on analog hands`,
        b.doc.span(node, "sleep_update") ?? common.span, {
          notes: ["the hour and minute hands never need it -- they change once a "
            + "minute, and the sleeping onUpdate already redraws them",
          "a second hand while asleep is 'seconds: always', which is not implemented yet (docs/limitations.md)"],
        });
      return null;
    }
    const colors: Expression[] = [];
    for (const [handName, hand] of handSet.hands()) {
      if (handName === "second" && seconds === "never") continue; // never drawn
      dedupAppend(colors, hand.color);
      for (const part of hand.parts) dedupAppend(colors, part.color);
    }
    return HandsElement.create({ ...common, hands: name, seconds, colors });
  }

  override lower(ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedHands;
    const element = p.element;
    const prefix = constPrefix(p.id);
    const override = p.aod_thickness !== null ? Const(`${prefix}_AOD_THICKNESS`, p.aod_thickness) : null;
    let stamp: [Paint, number] | null = null;
    if (ctx.ring !== null) stamp = [RingColor(), ctx.ring.width];
    else if (element.outline !== null) stamp = [AodDimmed(element, element.outline.color), element.outline.width];
    const ops: Op[] = [Let("cx", Const(`${prefix}_CX`, p.center[0])), Let("cy", Const(`${prefix}_CY`, p.center[1]))];
    let declared = false;
    for (const [handName, angleFn] of HAND_ANGLE_FUNCTIONS) {
      const hand = (p as unknown as Record<string, ResolvedHand | null>)[handName]!;
      if (hand === null) continue;
      const gated = handName === "second" && element.seconds === "awake";
      const angle = NumLocal("angle");
      const assign = (name: string, value: Num): Op => (declared ? Assign(name, value) : Let(name, value));
      const body: Op[] = [
        assign("angle", HandAngle(angleFn, handName)),
        assign("sin", Call("Math.sin", [angle])),
        assign("cos", Call("Math.cos", [angle])),
      ];
      const parts = hand.parts.map((part, index): [string, RotatablePart] => [`${prefix}_${handName.toUpperCase()}_${index}`, part]);
      const pen = (partPrefix: string, part: RotatablePart): AodPick =>
        AodPick(Const(`${partPrefix}_THICKNESS`, "thickness" in part ? part.thickness : 1), override);
      if (stamp !== null) {
        body.push(SetColor(stamp[0]));
        for (const [partPrefix, part] of parts) body.push(Part(part, partPrefix, true, pen(partPrefix, part), { ring: stamp[1] }));
      }
      if (ctx.ring === null) {
        let current: string | null = null;
        for (const [partPrefix, part] of parts) {
          const paint = AodPart(element, part.color);
          const code = colorCode(paint, ctx.aod);
          if (code !== current) {
            body.push(SetColor(paint));
            current = code;
          }
          body.push(Part(part, partPrefix, true, pen(partPrefix, part)));
        }
      }
      ops.push(Blank(), Comment(handName + (gated ? " -- seconds: awake" : "")));
      if (gated) ops.push(If(NotSleeping(), body)); else ops.push(...body);
      declared = true;
    }
    return ops;
  }

  override layoutConstants(prefix: string, placed: Placed): lc.Constants {
    const p = placed as PlacedHands;
    const out: lc.Constants = [[`${prefix}_CX`, p.center[0], "the axis"], [`${prefix}_CY`, p.center[1], ""]];
    out.push(...lc.aodThicknessConstant(prefix, p, lc.EVERY_PART_NOTE));
    for (const handName of ["hour", "minute", "second"]) {
      const hand = (p as unknown as Record<string, ResolvedHand | null>)[handName]!;
      if (hand === null) continue;
      hand.parts.forEach((part, index) => out.push(...lc.handPartConstants(`${prefix}_${handName.toUpperCase()}_${index}`, `${handName} hand`, index, part)));
    }
    return out;
  }

  override contrastSubjects(placed: Placed): ContrastSubject[] {
    const p = placed as PlacedHands;
    const ring = p.element.outline !== null ? p.element.outline.color : null;
    const out: ContrastSubject[] = [];
    for (const hand of ["hour", "minute", "second"]) {
      const resolved = (p as unknown as Record<string, ResolvedHand | null>)[hand]!;
      if (resolved === null) continue;
      resolved.parts.forEach((part, index) => out.push([`${p.id}.${hand}.parts[${index}]`, part.color, ring, true]));
    }
    return out;
  }

  override describe(placed: Placed): string {
    const p = placed as PlacedHands;
    const element = p.element;
    const drawn = ["hour", "minute", "second"].filter((n) => (p as unknown as Record<string, unknown>)[n] !== null);
    const secondsNote = element.seconds ? `, seconds: ${element.seconds}` : "";
    return `analog hands (hands.${element.hands}): ${andList(drawn)}${secondsNote}`;
  }
}

register(new HandsKind());
