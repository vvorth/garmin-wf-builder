// Python's `textwrap.wrap` and `fill`, with their defaults: whitespace made
// spaces, words split after hyphens, long words broken, whitespace dropped
// at line ends. Help text and listings wrap through it, so they wrap where
// Python's did.

// Python's `TextWrapper.wordsep_re`, with `\w` spelled as Unicode classes.
const WORD = "[\\p{L}\\p{M}\\p{N}_]";
const LETTER = "[\\p{L}\\p{M}_]";
const WORD_PUNCT = "[\\p{L}\\p{M}\\p{N}_!\"'&.,?]";
const WORDSEP = new RegExp(
  `(\\s+` +
  `|(?<=${WORD_PUNCT})-{2,}(?=${WORD})` +
  `|\\S+?(?:-(?:(?<=${LETTER}{2}-)|(?<=${LETTER}-${LETTER}-))(?=${LETTER}-?${LETTER})` +
  `|(?=\\s|$)` +
  `|(?<=${WORD_PUNCT})(?=-{2,}${WORD})))`,
  "u",
);

/** Python's `str.expandtabs(8)`: each tab to the next multiple of eight columns. */
function expandTabs(text: string): string {
  let out = "", column = 0;
  for (const ch of text) {
    if (ch === "\t") {
      const pad = 8 - (column % 8);
      out += " ".repeat(pad);
      column += pad;
    } else {
      out += ch;
      column = ch === "\n" || ch === "\r" ? 0 : column + 1;
    }
  }
  return out;
}

function chunks(text: string): string[] {
  text = expandTabs(text).replace(/[\n\x0b\f\r]/g, " ");
  return text.split(WORDSEP).filter((c) => c !== undefined && c !== "");
}

export interface WrapOptions {
  initialIndent?: string;
  subsequentIndent?: string;
}

/** `text` wrapped into lines of at most `width` characters. */
export function wrap(text: string, width = 70, { initialIndent = "", subsequentIndent = "" }: WrapOptions = {}): string[] {
  const pending = chunks(text).reverse();
  const lines: string[] = [];
  while (pending.length > 0) {
    const line: string[] = [];
    let length = 0;
    const indent = lines.length > 0 ? subsequentIndent : initialIndent;
    const room = width - indent.length;
    if (lines.length > 0 && pending[pending.length - 1]!.trim() === "") pending.pop();
    while (pending.length > 0) {
      const size = [...pending[pending.length - 1]!].length;
      if (length + size <= room) {
        line.push(pending.pop()!);
        length += size;
      } else break;
    }
    if (pending.length > 0 && [...pending[pending.length - 1]!].length > room) {
      // Break the long word: as much of it as fits, at least one character.
      const space = room < 1 ? 1 : room - length;
      if (space > 0) {
        const chars = [...pending.pop()!];
        let take = space;
        const hyphen = chars.slice(0, space).lastIndexOf("-");
        if (hyphen > 0 && chars.slice(0, hyphen).some((c) => c !== "-")) take = hyphen + 1;
        line.push(chars.slice(0, take).join(""));
        length += take;
        pending.push(chars.slice(take).join(""));
        if (pending[pending.length - 1] === "") pending.pop();
      }
    }
    if (line.length > 0 && line[line.length - 1]!.trim() === "") {
      length -= line[line.length - 1]!.length;
      line.pop();
    }
    if (line.length > 0) lines.push(indent + line.join(""));
  }
  return lines;
}

/** `wrap`'s lines joined by newlines. */
export function fill(text: string, width = 70, options: WrapOptions = {}): string {
  return wrap(text, width, options).join("\n");
}
