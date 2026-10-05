// The oracle's stage boundaries (tools/oracle.py), and the TypeScript
// port of each. A stage with no port reports every case missing; a slice
// registers its stage's port here when it lands.
import type { DeviceFiles } from "../src/devices/files.ts";
import { patches } from "./ports/patches.ts";
import * as text from "./ports/text.ts";

/** Stages of the whole design, in pipeline order. */
export const DESIGN_STAGES = [
  "nodes", "spans", "patches", "data", "lowered", "desugared", "face", "diagnostics-load", "diagnostics-lint", "project",
] as const;
/** Stages per device. */
export const DEVICE_STAGES = ["fonts", "layout", "draw", "preview"] as const;
export const STAGES = [...DESIGN_STAGES, ...DEVICE_STAGES] as const;
export type Stage = (typeof STAGES)[number];

/** The dump format this runner reads: tools/oracle.py's `FORMAT`. */
export const ORACLE_FORMAT = 4;

/** One case a port is run on: a design, and for a device stage, one device. */
export interface Case {
  /** The design's id, e.g. `examples/showcase/face`. */
  design: string;
  /** Its path relative to the repository root. */
  path: string;
  /** The design's text. */
  text: string;
  /** The device, for a device stage. */
  device: string | undefined;
  files: DeviceFiles;
  /**
   * The oracle's dump of an earlier stage for this design (and device), so a
   * port can start from Python's input to it while the stage before it is
   * not ported yet.
   */
  oracle(stage: Stage, device?: string): unknown;
}

export type Port = (input: Case) => unknown;

export const PORTS: Partial<Record<Stage, Port>> = {
  nodes: text.nodes,
  spans: text.spans,
  patches,
  data: text.data,
};

/**
 * Deliberate differences from Python, each with its reason. `normalise` is
 * applied to both sides before they are compared, so the deviation is
 * tolerated where it applies and nowhere else; parity counts the cases it
 * changed, so none goes unnoticed.
 */
export interface Deviation {
  stages: readonly Stage[];
  reason: string;
  normalise(value: unknown): unknown;
}

/** A YAML error's text, wherever a stage reports one. */
function yamlMessage(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  if (record["$error"] === "yaml") return { ...record, message: "<the yaml package's message>" };
  if (typeof record["$error"] === "string" && record["$error"].startsWith("the text is not valid YAML: ")) {
    return { ...record, $error: "the text is not valid YAML: <the yaml package's message>" };
  }
  return value;
}

export const DEVIATIONS: readonly Deviation[] = [
  {
    stages: ["nodes", "spans"],
    reason: "an invalid text's message is the yaml package's, not ruamel's: which text is invalid agrees",
    normalise: yamlMessage,
  },
];

export function isDeviceStage(stage: Stage): boolean {
  return (DEVICE_STAGES as readonly string[]).includes(stage);
}
