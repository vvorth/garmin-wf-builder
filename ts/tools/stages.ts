// The oracle's stage boundaries (tools/oracle.py), and the TypeScript
// port of each. A stage with no port reports every case missing; a slice
// registers its stage's port here when it lands.
import type { DeviceFiles } from "../src/devices/files.ts";

/** Stages of the whole design, in pipeline order. */
export const DESIGN_STAGES = [
  "spans", "data", "lowered", "desugared", "face", "diagnostics-load", "diagnostics-lint", "project",
] as const;
/** Stages per device. */
export const DEVICE_STAGES = ["fonts", "layout", "draw", "preview"] as const;
export const STAGES = [...DESIGN_STAGES, ...DEVICE_STAGES] as const;
export type Stage = (typeof STAGES)[number];

/** The dump format this runner reads: tools/oracle.py's `FORMAT`. */
export const ORACLE_FORMAT = 2;

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

export const PORTS: Partial<Record<Stage, Port>> = {};

export function isDeviceStage(stage: Stage): boolean {
  return (DEVICE_STAGES as readonly string[]).includes(stage);
}
