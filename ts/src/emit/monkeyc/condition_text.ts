// `source/ConditionText.mc`: the weather condition names, one table for
// every reader of them -- a `data` element's weather reading and a
// `{<source>:name}`/`{<source>:short}` placeholder alike.
import * as complications from "../../complications.ts";
import { CONDITION_TEXT_MODULE } from "../../formatting.ts";
import type { Face } from "../../ir/model.ts";
import { stripCommentsAndStrings } from "../usage.ts";
import { Writer } from "../writer.ts";
import { header, type SourceFile } from "./common.ts";

/** What a packed entry is padded with; `entry` cuts it off. */
const PACK_FILL = "|";

const CALL = new RegExp(`\\b${CONDITION_TEXT_MODULE}\\.(longName|shortName)\\(`, "g");

/**
 * Which name tables the generated sources call for: `false` the long names,
 * `true` the short. Read off the emitted text, as the barrel set is, so the
 * module carries exactly the tables something calls.
 */
export function conditionTables(texts: Iterable<string>): Set<boolean> {
  const out = new Set<boolean>();
  for (const text of texts) {
    for (const match of stripCommentsAndStrings(text).matchAll(CALL)) out.add(match[1] === "shortName");
  }
  return out;
}

/** Every weather condition's name, in value order, padded to one width and joined. */
function packedNames(short: boolean): [string, number] {
  const names = complications.conditionNames(short);
  const width = Math.max(...names.map((n) => n.length));
  return [names.map((n) => n.padEnd(width, PACK_FILL)).join(""), width];
}

/** The module, with the long names, the short names or both (`conditionTables`). */
export function emitConditionText(face: Face, tables: ReadonlySet<boolean>): SourceFile {
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Lang;").blank();
  w.doc("A Weather.CONDITION_* as the text it draws, generated from the\ncomplication table's condition names (ts/src/complications.ts).");
  w.block(`module ${CONDITION_TEXT_MODULE}`, () => {
    const methods: [string, boolean][] = [["longName", false], ["shortName", true]];
    for (const [method, short] of methods) {
      if (!tables.has(short)) continue;
      const [packed, width] = packedNames(short);
      w.block(`function ${method}(condition as Number) as String`, () => {
        w.line(`return entry("${packed}",`);
        w.line(`        ${width}, condition);`);
      });
      w.blank();
    }
    w.doc(`Entry \`index\` of \`names\`, a table of entries padded with "${PACK_FILL}" to\n`
      + "`width` characters each; an index outside it reads as the last entry.\n"
      + "One string in place of a `switch` over every entry, which costs far\nmore code.");
    w.block("function entry(names as String, width as Number, index as Number) as String", () => {
      w.line("var count = names.length() / width;");
      w.block("if (index < 0 || index >= count)", () => w.line("index = count - 1;"));
      w.line("var found = names.substring(index * width, index * width + width);");
      w.block("if (found == null)", () => w.line("return \"\";"));
      w.line(`var end = found.find("${PACK_FILL}");`);
      w.line("var name = (end != null) ? found.substring(0, end) : found;");
      w.line("return (name != null) ? name : found;");
    });
  });
  return { path: `source/${CONDITION_TEXT_MODULE}.mc`, text: w.render() };
}
