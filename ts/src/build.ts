// The front end of a build: a design's text through every load pass to its
// IR. Port of wfb/build.py's `load`; the rest of that module (device
// selection, resolving, the project) comes with the later stages.
import type { Bag } from "./diagnostics.ts";
import { desugar } from "./desugar.ts";
import type { YamlNode } from "./edit/yaml.ts";
import { build as buildIr, type FileExists } from "./ir/builder/index.ts";
import type { Face } from "./ir/model.ts";
import { lower } from "./lower.ts";
import { validate } from "./validate.ts";
import { load as loadYaml } from "./yamlsrc.ts";

/**
 * Parse and validate a design into its IR, or report why not: YAML, the
 * schema on the author's own document, lowering, desugaring, then the IR.
 * `node` is the text already composed; `fileExists` answers for a baked
 * font's `source:`, relative to the design's own path.
 */
export function load(path: string, bag: Bag, text: string, fileExists: FileExists, node?: YamlNode | null): Face | null {
  const doc = loadYaml(path, bag, text, node);
  if (doc === null) return null;
  if (!validate(doc, bag)) return null;
  if (!lower(doc, bag)) return null;
  if (!desugar(doc, bag)) return null;
  return buildIr(doc, bag, fileExists);
}
