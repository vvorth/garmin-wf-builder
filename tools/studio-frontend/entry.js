// What the editor's YAML tab imports, as one ES module
// (wfb/studio/static/vendor/codemirror.module.js).
export { EditorView, keymap } from "@codemirror/view";
export { EditorState, EditorSelection, Compartment, Annotation, StateEffect } from "@codemirror/state";
export { basicSetup } from "codemirror";
export { yaml } from "@codemirror/lang-yaml";
export { linter, lintGutter, setDiagnostics, forceLinting } from "@codemirror/lint";
export { yamlSchema, yamlSchemaLinter, yamlSchemaHover, yamlCompletion } from "codemirror-json-schema/yaml";
export { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
export { tags } from "@lezer/highlight";
