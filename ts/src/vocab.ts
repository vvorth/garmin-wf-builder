// How a generated comment spells an IR value the author wrote as a key.
//

/**
 * An element's absence policy as a generated comment spells it: `absent: hide`,
 * `absent: "--"` (a placeholder, which the author writes `absent: {text: "--"}`)
 * or `absent: {value: ...}` (a fallback reading).
 */
export function absent(element: { absent?: string | null; placeholder?: string; fallback?: { shown?: string } | null }): string {
  const policy = element.absent || "hide";
  if (policy === "placeholder") return `absent: "${element.placeholder ?? ""}"`;
  if (policy === "fallback") return `absent: {value: ${element.fallback?.shown ?? "..."}}`;
  return `absent: ${policy}`;
}

/** `left_register` to `Left register`: a label for a name with none. */
export function humanise(name: string): string {
  const text = name.replaceAll("_", " ").trim();
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}
