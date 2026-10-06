// The oracle's stage boundaries (tools/oracle.py), and the TypeScript
// port of each. A stage with no port reports every case missing; a slice
// registers its stage's port here when it lands.
import type { DeviceFiles } from "../src/devices/files.ts";
import { draw, faceRuns, lastBits, outsideText, preview } from "./ports/draw.ts";
import { diagnosticsLoad, face } from "./ports/ir.ts";
import { burnInFigures, diagnosticsLint } from "./ports/lint.ts";
import { fonts, layout } from "./ports/layout.ts";
import { documentAfter, loadPass } from "./ports/load.ts";
import { patches } from "./ports/patches.ts";
import { estimatedWidths, project } from "./ports/project.ts";
import * as text from "./ports/text.ts";

/** Stages of the whole design, in pipeline order. */
export const DESIGN_STAGES = [
  "nodes", "spans", "patches", "load-cases", "load-yaml", "load-validate", "load-lower", "load-desugar", "load-ir", "data", "lowered", "desugared", "face", "diagnostics-load", "diagnostics-lint", "project",
] as const;
/** Stages per device. */
export const DEVICE_STAGES = ["fonts", "layout", "draw", "preview"] as const;
export const STAGES = [...DESIGN_STAGES, ...DEVICE_STAGES] as const;
export type Stage = (typeof STAGES)[number];

/** The dump format this runner reads: tools/oracle.py's `FORMAT`. */
export const ORACLE_FORMAT = 6;

/**
 * Stages read out of another stage's dump: each pass of `load-cases`
 * (tools/oracle_cases.py), so a pass is compared as soon as it is ported.
 */
export const VIRTUAL: Partial<Record<Stage, { source: Stage; pick: (dump: unknown) => unknown }>> = Object.fromEntries(
  (["yaml", "validate", "lower", "desugar", "ir"] as const).map((pass) => [`load-${pass}`, {
    source: "load-cases",
    pick: (dump: unknown) => (dump as Record<string, unknown>[]).map((c) => ({ what: c["what"], [pass]: c[pass] })),
  }]),
);

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
  "load-yaml": loadPass("yaml"),
  "load-validate": loadPass("validate"),
  "load-lower": loadPass("lower"),
  "load-desugar": loadPass("desugar"),
  "load-ir": loadPass("ir"),
  lowered: documentAfter("lower"),
  desugared: documentAfter("desugar"),
  data: text.data,
  face,
  "diagnostics-load": diagnosticsLoad,
  "diagnostics-lint": diagnosticsLint,
  project,
  layout,
  fonts,
  draw,
  preview,
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

/** An invalid text's diagnostic, its message and column the yaml package's. */
function yamlDiagnostic(d: Record<string, unknown>): Record<string, unknown> {
  return d["code"] !== "yaml" || d["message"] === "the document is empty" ? d
    : { ...d, message: "<the yaml package's message>", span: d["span"] === null ? null
      : { ...(d["span"] as object), col: "<the yaml package's column>" } };
}

/** A load case's `yaml` pass, or `diagnostics-load`'s list, with `yamlDiagnostic` applied. */
function yamlDiagnostics(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return value.map((c: Record<string, unknown>) => {
    if (typeof c["code"] === "string") return yamlDiagnostic(c);
    const pass = c["yaml"];
    if (!Array.isArray(pass)) return c;
    return { ...c, yaml: pass.map(yamlDiagnostic) };
  });
}

/** A layout's items hidden by an unavailable vector font, their measured extent set aside. */
function hiddenByFontExtent(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const face = value as Record<string, unknown>;
  const hidden = (face["hidden"] ?? {}) as Record<string, string>;
  const items = face["items"];
  if (!Array.isArray(items)) return value;
  return {
    ...face,
    items: items.map((item: Record<string, unknown>) => {
      const id = (item["element"] as Record<string, unknown> | undefined)?.["id"] as string | undefined;
      return id !== undefined && hidden[id] === "font-unavailable" ? { ...item, box: "<measured>", measured_width: "<measured>" } : item;
    }),
  };
}

/** A bake with its rasterised parts set aside: the sheet, and each glyph's tile box and offsets. */
function bakedMetrics(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value as Record<string, Record<string, unknown>>).map(([name, font]) => [name, {
    ...font, sheet: "<rasterised>", sheet_width: "<rasterised>", sheet_height: "<rasterised>",
    glyphs: Object.fromEntries(Object.entries((font["glyphs"] ?? {}) as Record<string, Record<string, unknown>>)
      .map(([ch, g]) => [ch, { char: g["char"], xadvance: g["xadvance"] }])),
  }]));
}

/** Icon fonts (and their ring fonts) with their nominal size and what follows from it set aside. */
function iconSizing(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value as Record<string, Record<string, unknown>>).map(([name, font]) => {
    if (!name.startsWith("icon_")) return [name, font];
    const glyphs = Object.fromEntries(Object.keys((font["glyphs"] ?? {}) as object).map((ch) => [ch, "<sized>"]));
    return [name, { ...font, size: "<sized>", line_height: "<sized>", base: "<sized>", cell_width: "<sized>", glyphs }];
  }));
}

export const DEVIATIONS: readonly Deviation[] = [
  {
    stages: ["draw"],
    reason: "a system-font or vector-font run's glyphs are rasterised from their outlines by our coverage rasteriser, "
      + "not by FreeType (and, turned, not by rotating a bitmap): its tiles and their offsets differ",
    normalise: faceRuns,
  },
  {
    stages: ["draw"],
    reason: "a turned part's coordinates come from JavaScript's Math.sin/Math.cos, which can differ from glibc's in the last bit: "
      + "compared to 10 significant digits",
    normalise: lastBits,
  },
  {
    stages: ["diagnostics-lint"],
    reason: "aod-burn-in measures rendered frames, whose system-font and vector-font text is rasterised from outlines: "
      + "its percentages, worst time and phase, and contributor shares move; its severity does not",
    normalise: burnInFigures,
  },
  {
    stages: ["project"],
    reason: "a text whose vector font has no face on the device is measured with Pillow's default face's unhinted advances "
      + "(the layout deviation): its estimated width constant moves; layout parity compares every width",
    normalise: estimatedWidths,
  },
  {
    stages: ["preview"],
    reason: "the frame differs only inside system-font and vector-font runs, rasterised from their outlines",
    normalise: outsideText,
  },
  {
    stages: ["fonts"],
    reason: "an icon's nominal size is searched by its unhinted ink height, where Python measures FreeType's hinted box: "
      + "about half the searches land on another size",
    normalise: iconSizing,
  },
  {
    stages: ["fonts"],
    reason: "glyphs are rasterised by our own coverage rasteriser from unhinted outlines, not FreeType: "
      + "sheets, tile boxes and offsets differ at edge pixels",
    normalise: bakedMetrics,
  },
  {
    stages: ["layout"],
    reason: "a text whose vector font has no face on the device (hidden there) is measured with Pillow's default face's "
      + "unhinted advances, not FreeType's hinted ones",
    normalise: hiddenByFontExtent,
  },
  {
    stages: ["load-yaml", "diagnostics-load"],
    reason: "an invalid text's diagnostic gives the yaml package's message and column, not ruamel's: the line agrees",
    normalise: yamlDiagnostics,
  },
  {
    stages: ["face", "project"],
    reason: "a scheme colour no expression reads gets no view field (Python's left monkeyc an unused-member warning): "
      + "the IR records the roles read, and the view's scheme fields are compared without their lines",
    normalise: schemeFields,
  },
  {
    stages: ["nodes", "spans"],
    reason: "an invalid text's message is the yaml package's, not ruamel's: which text is invalid agrees",
    normalise: yamlMessage,
  },
];

export function isDeviceStage(stage: Stage): boolean {
  return (DEVICE_STAGES as readonly string[]).includes(stage);
}

/** A face without its read scheme roles; a project's views without their scheme-colour field lines. */
function schemeFields(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  if ("scheme_roles_used" in record) {
    const { scheme_roles_used: _, ...rest } = record;
    return rest;
  }
  return Object.fromEntries(Object.entries(record as Record<string, { text?: string }>).map(([path, file]) => [path,
    !path.endsWith("View.mc") || typeof file?.text !== "string" ? file
      : { ...file, text: file.text.replace(/^.*_configColors\w+.*\n/gm, "") }]));
}
