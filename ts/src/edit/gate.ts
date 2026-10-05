// The gate every patch passes before it is accepted. Port of
// wfb/edit/gate.py.
//
// A patched text is accepted only when
//
// 1. it parses to exactly the data the patch intended, key order included,
//    so a patch that touched anything else fails loudly; and
// 2. it loads through the whole front end (`build.load`: parse, schema,
//    lowering, desugaring, the IR) with no error the text before it did not
//    already have, and still loads if it loaded before. A text that did not
//    load (a font file not yet added, say) may be patched towards loading.
//
// The text is loaded under the design's own path, so relative font paths
// resolve as they do for the design and every diagnostic names the design.
import { load } from "../build.ts";
import { Bag, type Diagnostic } from "../diagnostics.ts";
import type { FileExists } from "../ir/builder/index.ts";
import type { Face } from "../ir/model.ts";
import type { Patch } from "./patch.ts";
import { indexFor, Refused, sameData } from "./spans.ts";
import type { YamlNode } from "./yaml.ts";

/** A text loaded under the design's path: the face (`null` when it did not load) and every diagnostic. */
export class Loaded {
  readonly text: string;
  readonly face: Face | null;
  readonly bag: Bag;

  constructor(text: string, face: Face | null, bag: Bag) {
    this.text = text;
    this.face = face;
    this.bag = bag;
  }

  get errors(): Diagnostic[] {
    return this.bag.errors;
  }
}

export function loadText(path: string, text: string, fileExists: FileExists): Loaded {
  const bag = new Bag();
  const face = load(path, bag, text, fileExists, composed(text));
  return new Loaded(text, face, bag);
}

/**
 * `text`'s node tree from its shared index, which an edit has composed
 * already (`null` for an empty document); `undefined` when the load must
 * parse it itself: text that is not YAML, whose error the load reports, or
 * text with a merge key, whose node the index's own construction has
 * already merged away.
 */
function composed(text: string): YamlNode | null | undefined {
  if (text.includes("<<")) return undefined;
  try {
    return indexFor(text).root;
  } catch (error) {
    if (error instanceof Refused) return undefined;
    throw error;
  }
}

/** Positions shift with every edit, so an error is known by what it says. */
function errorKeys(loaded: Loaded): Map<string, number> {
  const counts = new Map<string, number>();
  for (const d of loaded.errors) {
    const key = JSON.stringify([d.code, d.message]);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

/** Accepts or refuses patches to one text of one design. */
export class Gate {
  readonly path: string;
  readonly fileExists: FileExists;
  readonly before: Loaded;

  /** `before` is `text` already loaded, when the caller has it. */
  constructor(path: string, text: string, fileExists: FileExists, before: Loaded | null = null) {
    this.path = path;
    this.fileExists = fileExists;
    this.before = before !== null && before.text === text ? before : loadText(path, text, fileExists);
  }

  /** The patched text, loaded; or `Refused`, saying why. `after` is that text already loaded, when the caller has it. */
  check(patch: Patch, after: Loaded | null = null): Loaded {
    if (!sameData(indexFor(patch.text).data, patch.expected)) {
      throw new Refused(`${patch.what}: the edit would change more than intended`);
    }
    const loaded = after !== null && after.text === patch.text ? after : loadText(this.path, patch.text, this.fileExists);
    const before = errorKeys(this.before);
    const fresh = new Map([...errorKeys(loaded)].map(([key, n]): [string, number] => [key, n - (before.get(key) ?? 0)])
      .filter(([, n]) => n > 0));
    if (fresh.size > 0) {
      const first = loaded.errors.find((d) => fresh.has(JSON.stringify([d.code, d.message])))!;
      const where = first.span !== null ? ` (line ${first.span.line})` : "";
      throw new Refused(`${patch.what}: ${first.message}${where}`);
    }
    if (loaded.face === null && this.before.face !== null) throw new Refused(`${patch.what}: the design no longer loads`);
    return loaded;
  }
}
