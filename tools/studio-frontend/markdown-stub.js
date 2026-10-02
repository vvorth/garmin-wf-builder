// Replaces codemirror-json-schema's utils/markdown.js in the editor's
// bundle: schema descriptions as escaped text with `code` spans, without
// markdown-it and Shiki (about 400 KB).
const escape = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export function renderMarkdown(markdown) {
  return escape(String(markdown ?? "")).replace(/`([^`]+)`/g, "<code>$1</code>");
}
