// `type: hands`: places a declared `hand_sets:` entry on screen. Port of
// wfb/kinds/hands.py's build half.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { dedupAppend } from "../ir/builder/state.ts";
import { type Element, type Expression, HandsElement } from "../ir/model.ts";
import { repr, str } from "../py.ts";
import { type Common, ElementKind, register } from "./base.ts";

type Node = Map<DataKey, Data>;

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

  /** `common.at` is already the axis; the element's extent is the disc it sweeps, computed in layout. */
  build(b: Builder, node: Node, common: Common): Element | null {
    const name = node.get("set") as string;
    const elementId = common.id;
    const handSet = b.hand_sets.resolve(b.bag, name, b.doc.span(node, "set"),
      { code: "hands", message: `${elementId}: unknown hand set ${repr(name)}`, note: "declared hand sets" });
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
}

register(new HandsKind());
