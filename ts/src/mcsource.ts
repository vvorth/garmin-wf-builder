// Author text as Monkey C source: a string literal, and a comment..
//
// Author text reaches generated source as string literals (what is drawn)
// and in comments (a widest rendering, a menu label). A quote or a
// backslash breaks a literal, and a line break breaks both: the literal no
// longer closes on its line, and the rest of a `//` comment becomes code.
// Every such text goes through here. `lower` refuses a control character in
// drawn text before it gets this far; these keep the source well formed
// whatever reaches them.

const ESCAPES: Readonly<Record<string, string>> = { "\\": "\\\\", "\"": "\\\"", "\n": "\\n", "\r": "\\r", "\t": "\\t" };

function control(char: string): boolean {
  const c = char.codePointAt(0)!;
  return c < 0x20 || c === 0x7f;
}

const hex4 = (char: string): string => `\\u${char.codePointAt(0)!.toString(16).padStart(4, "0")}`;

/** `value` as a double-quoted Monkey C string literal (`monkeyc` 9.2.0 accepts `\n`, `\r`, `\t` and `\uXXXX`). */
export function stringLiteral(value: string): string {
  let out = "";
  for (const char of value) out += ESCAPES[char] ?? (control(char) ? hex4(char) : char);
  return `"${out}"`;
}

/** `text` as it may stand in a `//` comment: on one line, each control character written as its escape. */
export function commentText(text: string): string {
  let out = "";
  for (const char of text) out += "\n\r\t".includes(char) ? ESCAPES[char]! : control(char) ? hex4(char) : char;
  return out;
}

/** The first control character in `text` (a line break, a tab), as its escape, or `null` when there is none. */
export function controlCharacter(text: string): string | null {
  for (const char of text) if (control(char)) return commentText(char);
  return null;
}
