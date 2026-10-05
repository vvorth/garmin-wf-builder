// How a generated comment spells an IR value the author wrote as a key.
// Port of wfb/vocab.py.

/**
 * An element's absence policy as the author writes it: `absent: hide`,
 * `absent: "--"` (a placeholder) or `absent: {value: ...}` (a fallback
 * reading). Generated code comments quote this.
 */
export function absent(element: { absent?: string | null; placeholder?: string; fallback?: { shown?: string } | null }): string {
  const policy = element.absent || "hide";
  if (policy === "placeholder") return `absent: "${element.placeholder ?? ""}"`;
  if (policy === "fallback") return `absent: {value: ${element.fallback?.shown ?? "..."}}`;
  return `absent: ${policy}`;
}
