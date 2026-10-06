// A tiny indentation-aware source writer. Port of wfb/emit/writer.py.
//
// Generated Monkey C is read by humans: it is what the author debugs when a
// face misbehaves on the wrist. Getting the indentation right by
// construction is cheaper than formatting it afterwards.
import { splitlines } from "../py.ts";

export class Writer {
  private lines_: string[] = [];
  private readonly indent: string;
  private level = 0;

  constructor(indent = "    ") {
    this.indent = indent;
  }

  line(text = ""): this {
    this.lines_.push(text ? `${this.indent.repeat(this.level)}${text}` : "");
    return this;
  }

  lines(...texts: string[]): this {
    for (const text of texts) this.line(text);
    return this;
  }

  blank(): this {
    if (this.lines_.length > 0 && this.lines_[this.lines_.length - 1] !== "") this.lines_.push("");
    return this;
  }

  comment(text: string, marker = "//"): this {
    const parts = splitlines(text);
    for (const part of parts.length > 0 ? parts : [""]) this.line(`${marker} ${part}`.trimEnd());
    return this;
  }

  doc(text: string): this {
    return this.comment(text, "//!");
  }

  /** `header {`, `body()` one level in, then `closing`. */
  block(header: string, body: () => void, closing = "}"): this {
    this.line(header.endsWith("{") ? header : `${header} {`);
    this.level++;
    try {
      body();
    } finally {
      this.level--;
    }
    this.line(closing);
    return this;
  }

  /** `block(header, body)` when `header` is given, else `body()` at the current level. */
  blockIf(header: string | null, body: () => void, closing = "}"): this {
    if (header === null) {
      body();
      return this;
    }
    return this.block(header, body, closing);
  }

  /** Splice `other`'s lines in before this writer's own. */
  prepend(other: Writer): this {
    this.lines_ = [...other.lines_, ...this.lines_];
    return this;
  }

  /** One call statement, its arguments wrapped one group per line, aligned under the first argument. */
  call(callee: string, groups: readonly string[]): this {
    const head = `${callee}(`;
    const pad = " ".repeat(head.length);
    const last = groups.length - 1;
    groups.forEach((group, index) => this.line(`${index === 0 ? head : pad}${group}${index === last ? ");" : ","}`));
    return this;
  }

  render(): string {
    return this.lines_.join("\n").replace(/\n+$/, "") + "\n";
  }
}
