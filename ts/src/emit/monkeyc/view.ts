// The generated view's own helpers the draw program reads. Port of the
// matching parts of wfb/emit/monkeyc/view.py; the rest comes with codegen.
import type { Expression } from "../../ir/model.ts";

/** The Monkey C for "this condition does not hold": a `not` is un-negated rather than wrapped. */
export function negated(expression: Expression): string {
  const code = expression.code;
  const node = expression.ast;
  if (node !== null && node.kind === "unary" && node.op === "not") {
    if (!(code.startsWith("(!") && code.endsWith(")"))) throw new Error(code);
    return code.slice(2, -1);
  }
  return `!${negatable(code)}`;
}

/** `code` wrapped in parentheses unless it already is one group. */
function negatable(code: string): string {
  if (!(code.startsWith("(") && code.endsWith(")"))) return `(${code})`;
  let depth = 0;
  for (let index = 0; index < code.length; index++) {
    const ch = code[index];
    if (ch === "(") {
      depth++;
    } else if (ch === ")") {
      depth--;
      if (depth === 0 && index !== code.length - 1) return `(${code})`;
    }
  }
  return code;
}
