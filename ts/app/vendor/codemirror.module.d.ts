// What the page imports from the vendored module, for `tsconfig.app.json`:
// the CodeMirror 6 packages' exports, declared as those packages declare
// them, to what the YAML tab uses. The vendored code itself is not
// type-checked.

// -- @codemirror/state -----------------------------------------------------------

/** One line of a document: its offsets, 1-based number and text. */
export interface Line {
  readonly from: number;
  readonly to: number;
  readonly number: number;
  readonly text: string;
  readonly length: number;
}

/** A document's text, by offset or by line. */
export interface Text {
  readonly length: number;
  readonly lines: number;
  line(n: number): Line;
  lineAt(pos: number): Line;
  sliceString(from: number, to?: number): string;
  toString(): string;
}

export interface SelectionRange {
  readonly from: number;
  readonly to: number;
  readonly anchor: number;
  readonly head: number;
  readonly empty: boolean;
}

export declare class EditorSelection {
  readonly ranges: readonly SelectionRange[];
  readonly main: SelectionRange;
  static single(anchor: number, head?: number): EditorSelection;
  static range(anchor: number, head: number): SelectionRange;
  static create(ranges: readonly SelectionRange[], mainIndex?: number): EditorSelection;
}

/** A tag on a transaction, saying where it came from. */
export declare class Annotation<T> {
  readonly type: AnnotationType<T>;
  readonly value: T;
  static define<T>(): AnnotationType<T>;
}

export declare class AnnotationType<T> {
  of(value: T): Annotation<T>;
}

export declare class StateEffect<Value> {
  readonly value: Value;
  is<T>(type: StateEffectType<T>): this is StateEffect<T>;
  static define<Value = null>(): StateEffectType<Value>;
}

export declare class StateEffectType<Value> {
  of(value: Value): StateEffect<Value>;
}

/** An extension: a value carrying one, or a (nested) list of them. */
export type Extension = { extension: Extension } | readonly Extension[];

export declare class Facet<Input, Output = readonly Input[]> {
  of(value: Input): Extension;
}

export declare class Compartment {
  of(ext: Extension): Extension;
  reconfigure(content: Extension): StateEffect<unknown>;
  get(state: EditorState): Extension | undefined;
}

/** One change: replace `from` to `to` (or insert at `from`) with `insert`. */
export interface ChangeSpec {
  from: number;
  to?: number;
  insert?: string | Text;
}

export interface TransactionSpec {
  changes?: ChangeSpec | readonly ChangeSpec[];
  selection?: EditorSelection | { anchor: number; head?: number };
  effects?: StateEffect<unknown> | readonly StateEffect<unknown>[];
  annotations?: Annotation<unknown> | readonly Annotation<unknown>[];
  scrollIntoView?: boolean;
  userEvent?: string;
}

export declare class Transaction {
  readonly state: EditorState;
  readonly startState: EditorState;
  readonly docChanged: boolean;
  readonly effects: readonly StateEffect<unknown>[];
  annotation<T>(type: AnnotationType<T>): T | undefined;
  isUserEvent(event: string): boolean;
}

export interface EditorStateConfig {
  doc?: string | Text;
  selection?: EditorSelection | { anchor: number; head?: number };
  extensions?: Extension;
}

export declare class EditorState {
  readonly doc: Text;
  readonly selection: EditorSelection;
  update(...specs: TransactionSpec[]): Transaction;
  static create(config?: EditorStateConfig): EditorState;
}

// -- @codemirror/view ------------------------------------------------------------

/** A line's (or block's) place in the view: document offsets and vertical pixels. */
export interface BlockInfo {
  readonly from: number;
  readonly length: number;
  readonly top: number;
  readonly height: number;
  readonly to: number;
  readonly bottom: number;
}

export declare class ViewUpdate {
  readonly view: EditorView;
  readonly state: EditorState;
  readonly startState: EditorState;
  readonly transactions: readonly Transaction[];
  readonly docChanged: boolean;
  readonly selectionSet: boolean;
  readonly focusChanged: boolean;
  readonly viewportChanged: boolean;
}

export interface EditorViewConfig extends EditorStateConfig {
  state?: EditorState;
  parent?: Element | DocumentFragment;
  root?: Document | ShadowRoot;
}

/** A layout read, then a write once every read of the batch is done. */
export interface MeasureRequest<T> {
  read(view: EditorView): T;
  write?(measure: T, view: EditorView): void;
  key?: unknown;
}

export type ScrollStrategy = "nearest" | "start" | "end" | "center";

/** A `style-mod` spec: CSS properties, or nested selectors. */
export type StyleSpec = { [propOrSelector: string]: string | number | StyleSpec | null };

export declare class EditorView {
  constructor(config?: EditorViewConfig);
  readonly state: EditorState;
  readonly dom: HTMLElement;
  readonly scrollDOM: HTMLElement;
  readonly contentDOM: HTMLElement;
  readonly hasFocus: boolean;
  dispatch(...specs: TransactionSpec[]): void;
  dispatch(tr: Transaction): void;
  focus(): void;
  destroy(): void;
  lineBlockAt(pos: number): BlockInfo;
  lineBlockAtHeight(height: number): BlockInfo;
  requestMeasure<T>(request?: MeasureRequest<T>): void;
  static updateListener: Facet<(update: ViewUpdate) => void>;
  static theme(spec: { [selector: string]: StyleSpec }, options?: { dark?: boolean }): Extension;
  static scrollIntoView(pos: number | SelectionRange, options?: { y?: ScrollStrategy; x?: ScrollStrategy; yMargin?: number; xMargin?: number }): StateEffect<unknown>;
}

export interface KeyBinding {
  key?: string;
  mac?: string;
  win?: string;
  linux?: string;
  run?: (view: EditorView) => boolean;
  shift?: (view: EditorView) => boolean;
  preventDefault?: boolean;
}

export declare const keymap: Facet<readonly KeyBinding[]>;

// -- @lezer/highlight ------------------------------------------------------------

/** A syntax category a highlight style colours. */
export declare class Tag {
  readonly name: string;
}

/** The standard tags the YAML pane colours, and the modifiers deriving one tag from another. */
export declare const tags: {
  readonly propertyName: Tag;
  readonly string: Tag;
  readonly number: Tag;
  readonly bool: Tag;
  readonly null: Tag;
  readonly atom: Tag;
  readonly comment: Tag;
  readonly meta: Tag;
  readonly labelName: Tag;
  readonly typeName: Tag;
  readonly keyword: Tag;
  readonly punctuation: Tag;
  readonly separator: Tag;
  readonly squareBracket: Tag;
  readonly brace: Tag;
  definition(tag: Tag): Tag;
  constant(tag: Tag): Tag;
  function(tag: Tag): Tag;
  standard(tag: Tag): Tag;
  local(tag: Tag): Tag;
  special(tag: Tag): Tag;
};

// -- @codemirror/language --------------------------------------------------------

/** One rule of a highlight style: the tags it covers and their CSS properties. */
export interface TagStyle {
  tag: Tag | readonly Tag[];
  class?: string;
  [styleProperty: string]: unknown;
}

export declare class HighlightStyle {
  static define(specs: readonly TagStyle[], options?: { scope?: unknown; all?: string | StyleSpec; themeType?: "dark" | "light" }): HighlightStyle;
}

export declare function syntaxHighlighting(highlighting: HighlightStyle, options?: { fallback: boolean }): Extension;

/** A language and its support extensions, usable as one extension. */
export declare class LanguageSupport {
  readonly extension: Extension;
}

// -- @codemirror/lint ------------------------------------------------------------

export interface Action {
  name: string;
  apply: (view: EditorView, from: number, to: number) => void;
}

/** A finding shown in the gutter and as a mark. */
export interface Diagnostic {
  from: number;
  to: number;
  severity: "hint" | "info" | "warning" | "error";
  markClass?: string;
  source?: string;
  message: string;
  renderMessage?: (view: EditorView) => Node;
  actions?: readonly Action[];
}

export type LintSource = (view: EditorView) => readonly Diagnostic[] | Promise<readonly Diagnostic[]>;

export interface LintConfig {
  delay?: number;
  needsRefresh?: null | ((update: ViewUpdate) => boolean);
  markerFilter?: null | ((diagnostics: readonly Diagnostic[], state: EditorState) => Diagnostic[]);
  tooltipFilter?: null | ((diagnostics: readonly Diagnostic[], state: EditorState) => Diagnostic[]);
  hideOn?: (tr: Transaction, from: number, to: number) => boolean | null;
  autoPanel?: boolean;
}

export declare function linter(source: LintSource | null, config?: LintConfig): Extension;
export declare function lintGutter(config?: LintConfig): Extension;
export declare function forceLinting(view: EditorView): void;
export declare function setDiagnostics(state: EditorState, diagnostics: readonly Diagnostic[]): TransactionSpec;

// -- codemirror ------------------------------------------------------------------

export declare const basicSetup: Extension;

// -- @codemirror/lang-yaml -------------------------------------------------------

export declare function yaml(): LanguageSupport;

// -- codemirror-json-schema ------------------------------------------------------

/** A JSON Schema document, as `/api/schema` serves it. */
export type JSONSchema7 = { [key: string]: unknown };

export interface JSONSchemaOptions {
  mode?: "json" | "json5" | "yaml";
}

/** A completion request and its answer, as `@codemirror/autocomplete` shapes them. */
export interface CompletionContext {
  readonly state: EditorState;
  readonly pos: number;
  readonly explicit: boolean;
}

export interface CompletionResult {
  from: number;
  to?: number;
  options: readonly { label: string; type?: string; detail?: string; info?: string }[];
}

/** A hover tooltip, as `@codemirror/view` shapes it. */
export interface Tooltip {
  pos: number;
  end?: number;
  create(view: EditorView): { dom: HTMLElement };
}

/** Completion, hovers and the schema's own checks for a YAML document, as one list of extensions. */
export declare function yamlSchema(schema?: JSONSchema7): Extension[];
export declare function yamlCompletion(options?: JSONSchemaOptions): (context: CompletionContext) => CompletionResult | null;
export declare function yamlSchemaHover(options?: JSONSchemaOptions): (view: EditorView, pos: number, side: -1 | 1) => Tooltip | null;
export declare function yamlSchemaLinter(options?: JSONSchemaOptions): (view: EditorView) => Diagnostic[];
