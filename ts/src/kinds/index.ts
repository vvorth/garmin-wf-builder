// Registry of per-element-kind behaviour: importing this module registers
// all nine kinds, in schema order. The interface is ./base.ts.
import "./group.ts";
import "./shape.ts";
import "./text.ts";
import "./gauge.ts";
import "./icon.ts";
import "./graph.ts";
import "./data.ts";
import "./hands.ts";
import "./pattern.ts";

export {
  ElementKind, faceTextRuns, forElement, forPlaced, get, placedFont, placedTextRuns, IconFont, kindOf, names, NAMES, PRIMITIVES, ringFont, ringFontName, ringFonts,
  ringWidths, shapeOf, TextRun,
} from "./base.ts";
export type { Common, ContrastSubject, Refusal, SchemaPath } from "./base.ts";
