// A slot added with the element that draws it, as one change: the wearer
// picks what a slot shows, but a slot nothing draws shows nothing..
import * as complications from "../complications.ts";
import { quoted } from "../py.ts";
import { chain, type Patch, patch, setValue } from "./patch.ts";
import { Refused, type SpanIndex } from "./spans.ts";
import { add } from "./structure.ts";
import type { Data } from "./yaml.ts";

/**
 * Declare the `config: slots:` entry `name`, showing `defaultType` until
 * the wearer picks and offering every type (`choices: any`), and add a
 * `data` element drawing it at the end of `elements:`.
 */
export function addSlot(index: SpanIndex, name: string, defaultType: string): Patch {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name || "")) {
    throw new Refused(`${quoted(name)} is not a slot name: letters, digits and _, not starting with a digit`);
  }
  if (!complications.TYPES.has(defaultType)) {
    throw new Refused(`${quoted(defaultType)} is not a complication type: see \`wfb complications\``);
  }
  const data = index.data instanceof Map ? index.data : new Map<string, Data>();
  const config = data.get("config");
  const slots = config instanceof Map ? config.get("slots") : undefined;
  if (slots instanceof Map && slots.has(name)) throw new Refused(`there is a slot called ${name} already`);
  let result = setValue(index, ["config", "slots", name], new Map<string, Data>([["default", defaultType], ["choices", "any"]]),
    { block: true });
  result = chain(result, (i) => add(i, "data", ["elements"], null, null, name));
  return patch(result.text, result.expected, `add the slot ${name}, showing ${complications.label(defaultType)}, and draw it`);
}
