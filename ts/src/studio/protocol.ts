// The contract between the editor's page (`app/`) and its worker: every
// request the worker takes (`Ops`, one entry per operation, its arguments
// and its answer), every payload it sends back (the face's `Summary`, a
// `Frame`, an `Inspect`, the `Vocabulary`, `Home`, a `Refusal`) and every
// `Event` it announces. Types only: the worker's builders (`document.ts`,
// `inspect.ts`, `router.ts`) return these, and the page's modules name
// them in JSDoc, so a field read on one side and never sent by the other
// is a type error, not a blank in the panel.
//
// Everything here is what crosses `postMessage`: JSON values, with a YAML
// mapping as an object and a whole float as a number (`json.ts`'s
// `plain`), plus a file's bytes as a `Uint8Array`. The router checks each
// request's arguments at run time as well, since the page's message is
// data, not a typed call.
//
// This file imports nothing: the page's type check (`tsconfig.app.json`)
// reads it, and must not read the compiler through it. The three types
// the compiler also defines are spelled out here, and the worker's code
// holds them to the compiler's where it builds the payloads (`frame()`,
// `diagnostic()`, `handles()`).

// -- values ----------------------------------------------------------------

/** `diagnostics.ts`'s `Severity`. */
export type Severity = "error" | "warning" | "note";

/** `raster/pillow.ts`'s `JsonOp`: one drawing op of a layer, as the page's rasteriser reads it. */
export type JsonOp = Record<string, unknown> & { op: string };

/** `kinds/base.ts`'s `LiveHandle`: what a handle's drag changes in its layer's ops, when the worker predicts the edit exactly. */
export type LiveHandle = { consts: Record<string, number> } | { angle: string };

/** A value the author wrote, as JSON: a mapping is an object, a whole float a number. */
export type Value = null | boolean | number | string | Value[] | { [key: string]: Value };

/** An author path: mapping keys and sequence indices from the text's root (`["elements", "clock", "at", "dx"]`). */
export type Path = (string | number)[];

/** Where a geometry edit or a drag is written: the element's own key, or its override for the viewed device or its screen shape. */
export type Scope = "all" | "device" | "shape" | "display";

// -- the face's summary ------------------------------------------------------

/** A block of elements in the Layers tree: `static:`, `elements:`, or a layout's own. */
export interface TreeBlock {
  kind: "block";
  label: string;
  path: Path;
  /** The block's line in the text, 1-based, or `null` for a block not written yet. */
  line: number | null;
  children: TreeNode[];
}

/** One element in the Layers tree, with the elements of its own blocks (a group's `children:`). */
export interface TreeNode {
  kind: "element";
  id: string;
  /** Its `type:` as written. */
  type: Value;
  path: Path;
  /** Its first and last lines in the text, 1-based. */
  line: number;
  end: number;
  children: TreeNode[];
}

/** One finding of the load, the resolve or the lint; `file`, `line` and `col` are set when it has a place in the text. */
export interface Diagnostic {
  severity: Severity;
  code: string;
  message: string;
  notes: string[];
  file?: string;
  line?: number;
  col?: number;
}

/** One state on the line of history, newest first. */
export interface HistoryState {
  seq: number;
  time: number;
  label: string;
  /** The face is at this state. */
  current: boolean;
  /** Past the current state: reached by redo. */
  redo: boolean;
}

export interface HistorySnapshot {
  name: string;
  time: number;
  /** Why it was taken: `timer`, `download` or `manual`. */
  reason: string;
  seq: number;
  label: string;
  current: boolean;
}

/** The line of history: the newest states (`total` counts them all), what undo and redo would do, and every snapshot. */
export interface History {
  version: number;
  can_undo: boolean;
  can_redo: boolean;
  /** The label of the change undo would take back, or redo would make again. */
  undo: string | null;
  redo: string | null;
  states: HistoryState[];
  total: number;
  snapshots: HistorySnapshot[];
}

/** One `config: style:` entry as the Style select offers it. */
export interface StyleOption {
  name: string;
  label: string;
}

/** One `resources: palette:` entry and who uses it. */
export interface PaletteEntry {
  name: string;
  /** Its colour as written (a hex string, or whatever the author typed). */
  value: Value;
  /** The long form's `label:`, or `null`. */
  label: Value;
  /** Written in the long form (`{value, label}`). */
  long: boolean;
  /** The targets whose screen dithers this colour. */
  dithers_on: string[];
  /** The elements (by id) and paths (dotted) that refer to it. */
  used_by: string[];
  /** Named after its colour, so renamed when the colour changes. */
  automatic: boolean;
  /** Why the value is not a colour, or `null`. */
  problem: string | null;
  /** The launcher icon reads it. */
  launcher: boolean;
}

/** `theme: schemes:`: the scheme names, every role any scheme sets, and each scheme's colours by role. */
export interface Schemes {
  names: string[];
  roles: string[];
  colors: Record<string, Record<string, Value>>;
}

/** One `config: style: choices:` entry: a name the author wrote is text, or `null` when absent or not text. */
export interface StyleEntry {
  name: string;
  label: string | null;
  layout: string | null;
  scheme: string | null;
}

export interface Styles {
  /** `config: style: default:`. */
  default: string | null;
  entries: StyleEntry[];
}

/** One `resources: fonts:` entry. */
export interface FontEntry {
  name: string;
  /** Its `source:` file, or `null` for a system or vector font. */
  source: string | null;
  /** Its `face:` (a vector face name or a list of them), or `null`. */
  face: Value;
  /** Its `size:` as written. */
  size: Value;
}

/** One of a slot's `choices:`: a complication type and the icon drawn for it, when one is given. */
/** An icon as the format spells it: a catalogue name (or `none` on a slot choice), or a codepoint. */
export type IconSpelling = string | { codepoint: string };

export interface SlotChoice {
  type: string | null;
  icon: IconSpelling | null;
}

/** One `config: slots:` entry. */
export interface SlotEntry {
  name: string;
  /** Its title in the generated settings menu, or `null`. */
  label: string | null;
  /** The type it shows until the wearer picks. */
  default: string | null;
  /** The types the wearer may pick: a list, `"any"`, or `null` when absent. */
  choices: SlotChoice[] | string | null;
  /** The elements (by id) drawing it. */
  drawn_by: string[];
}

/** One `config:` colour axis (`accent_color`, `data_color`). */
export interface AxisEntry {
  default: string | null;
  /** The colours offered, each as written (`color.<name>` or a hex), or `"any"`. */
  choices: string | Value[];
  /** `choices:` as written: the list (an entry may be `{color, label}`), the word, or `null`. */
  raw: Value;
  /** The role it binds: its own `role:`, or the axis's default. */
  role: string;
  /** `role:` is written. */
  own_role: boolean;
}

export interface Axes {
  accent_color: AxisEntry | null;
  data_color: AxisEntry | null;
}

/** One hand of a hand set: how many parts it has and its colour as written. */
export interface HandSummary {
  parts: number;
  color: Value;
}

/** One `resources: hand_sets:` entry, with its lines in the text for the YAML tab. */
export interface HandSet {
  name: string;
  hands: Record<string, HandSummary>;
  /** The `hands` elements (by id) placing it. */
  placed_by: string[];
  line: number;
  end: number;
}

/** The face as a whole, for the Face tab, the pickers and Ctrl+K; read from the text, so it is filled in even while the face does not load. */
export interface Globals {
  palette: PaletteEntry[];
  schemes: Schemes;
  styles: Styles;
  layouts: string[];
  fonts: FontEntry[];
  slots: SlotEntry[];
  /** Every colour role: the schemes' and the axes'. */
  roles: string[];
  axes: Axes;
  /** The colour counts of the targets' screens (64, 2, …), ascending, for the dither warnings. */
  displays: number[];
  hand_sets: string[];
  hands: HandSet[];
  /** `build: targets:` as written. */
  targets: string[];
  /** A target the installed devices lack, with why. */
  target_problems: Record<string, string>;
}

/** A face, as every request about it answers: its text, what the pipeline made of it, its history and its globals. */
export interface Summary {
  id: string;
  name: string;
  version: number;
  text: string;
  /** Font files the text names and the bundle lacks. */
  missing: string[];
  /** The text loads: it can be drawn and built. */
  loads: boolean;
  /** The targets the face laid out on. */
  targets: string[];
  styles: StyleOption[];
  tree: TreeBlock[];
  diagnostics: Diagnostic[];
  /** The bundle's files, sorted. */
  assets: string[];
  history: History;
  globals: Globals;
}

/** A structural edit's answer: the face, and the element to select after it. */
export interface Structured extends Summary {
  select: string | null;
}

/** A drag's answer: the face, whether the element landed on the dragged pixel, and the change's label. */
export interface Dragged extends Summary {
  landed: boolean;
  what: string;
}

// -- a frame -----------------------------------------------------------------

/**
 * A handle on a placed element, in device pixels: a line's `end`, a `size`
 * edge (`key` the size key, `axis` the direction, `gain` the pixels of size
 * per pixel of drag) or an arc's `angle` (about `cx`, `cy`, from `start`
 * over `sweep`). `live` is what the browser may redraw by itself while the
 * handle is dragged, when the worker predicts the edit exactly.
 */
export interface Handle {
  kind: "end" | "size" | "angle";
  part?: "at" | "to";
  key?: string | string[];
  axis?: "x" | "y";
  gain?: number;
  x: number;
  y: number;
  cx?: number;
  cy?: number;
  start?: number;
  sweep?: number;
  live?: LiveHandle | null;
}

/** One element the frame places, in device pixels. */
export interface FrameItem {
  id: string;
  kind: string;
  /** The frame draws it (a group in the layout is listed undrawn). */
  drawn: boolean;
  /** Its line in the text, or `null`. */
  line: number | null;
  box: [x: number, y: number, width: number, height: number];
  center: [number, number];
  handles: Handle[];
}

/** A layer the browser draws from its ops. */
export interface OpsLayer {
  id: string;
  kind: string;
  ops: JsonOp[] | null;
  origin?: undefined;
  image?: undefined;
}

/** A layer the worker drew (an outlined group's ring): its PNG, as a data URL, cropped to its ink at `origin`. */
export interface ImageLayer {
  id: string;
  kind: string;
  origin: [number, number] | null;
  image: string | null;
  ops?: undefined;
}

export type FrameLayer = OpsLayer | ImageLayer;

/** One packed tile: its byte offset, width, height and kind. */
export type TileEntry = [offset: number, width: number, height: number, kind: "mask" | "rgba"];

/** The tiles the frame's text and icon ops paste: raw RGBA, zlib-compressed and base64, indexed by tile id. */
export interface Tiles {
  data: string;
  index: Record<string, TileEntry>;
}

/** The face drawn on one device: the image, every element with its handles, and the layers the browser draws itself. */
export interface Frame {
  version: number;
  device: string;
  /** The image's pixels per device pixel. */
  scale: number;
  width: number;
  height: number;
  shape: string;
  minor_radius: number;
  /** The frame as a PNG data URL. */
  frame: string;
  items: FrameItem[];
  layers: FrameLayer[];
  tiles: Tiles;
}

// -- the inspector -------------------------------------------------------------

/** The control a field is edited with; `yaml` is shown as its text and edited in the YAML tab. */
export type Widget =
  | "readonly" | "object" | "length" | "angle" | "align" | "color" | "expression" | "template" | "enum"
  | "slot" | "handset" | "font" | "icon" | "complication" | "bool" | "number" | "text" | "yaml";

/** One key of the selected element, in schema order. */
export interface Field {
  key: string;
  /** The key's path inside the element. */
  path: Path;
  widget: Widget;
  description: string;
  /** The value as written, or `null` when the key is absent. */
  value: Value;
  present: boolean;
  required: boolean;
  /** The schema's default, or `null`. */
  default: Value;
  /** An `at:`, `size:`, `radius:` or `align:` key: editable per device through the scope chooser. */
  geometry: boolean;
  /** The values an `enum` or `complication` widget offers. */
  enum?: Value[];
  /** An `object` widget's own keys. */
  children?: Field[];
  /** A `yaml` widget's value as text. */
  text?: string;
}

/** The element's override for the viewed device, or for its screen shape. */
export interface ScopeOverride {
  /** The selector as written (`fr955`, `shape:round`). */
  selector: string;
  keys: Record<string, Value>;
}

/** Every selector's keys the scope chooser cannot edit (`color`, `visible`, …), with their lines for the YAML tab. */
export interface OverrideSummary {
  selector: string;
  keys: Record<string, Value>;
  line: number;
  end: number;
}

/** A pattern's `parts:`: how many, of what shapes, and their lines for the YAML tab. */
export interface PartsSummary {
  count: number;
  shapes: string[];
  line: number;
  end: number;
}

/** The selected element's keys as widgets. With `error` set, `element` is not an element and the rest is empty. */
export interface Inspect {
  element: Path;
  id: string;
  type: string;
  fields: Field[];
  /** Keys the format does not have for this type. */
  unknown: string[];
  overrides: { device?: ScopeOverride; shape?: ScopeOverride; display?: ScopeOverride };
  overridden: OverrideSummary[];
  parts: PartsSummary | null;
  /** The device viewed, its screen shape and its display class (`amoled`, `mip`, `lcd`), or `null`. */
  device: string | null;
  shape: string | null;
  display: string | null;
  error: string | null;
}

// -- the vocabulary -------------------------------------------------------------

/** One installed device that can run a face. */
export interface DeviceInfo {
  id: string;
  name: string;
  shape: string;
  /** `WxH`. */
  size: string;
  width: number;
  height: number;
  /** Pixels per inch, when the device's files give them. */
  ppi: number | null;
  /** Its files include a skin to draw round the screen. */
  skin: boolean;
  /** The screen's `displayType`: `mip`, `amoled`, …. */
  display: string;
  /** Its system font names. */
  fonts: string[];
}

/** An installed device whose files could not be read. */
export interface UnreadableDevice {
  id: string;
  reason: string;
}

/** One of the 64 MIP colours. */
export interface MipColor {
  name: string;
  value: string;
  label: string;
}

/** One complication type the Data axis offers. */
export interface ComplicationType {
  name: string;
  label: string;
  category: string;
  /** Its catalogue icon, or `null`. */
  icon: string | null;
  /** A sample reading, formatted, or `null`. */
  sample: string | null;
}

/** What the pickers offer, independent of any face: the format's words. */
export interface Words {
  /** Data sources by namespace (`activity` → `activity.steps`, …). */
  sources: Record<string, string[]>;
  /** The icon catalogue's names, sorted. */
  icons: string[];
  /** `auto` and every complication type name. */
  complications: string[];
  series: string[];
  /** Every element type. */
  types: string[];
  mip: MipColor[];
  hand_presets: string[];
  /** The complication categories, in display order. */
  categories: string[];
  complication_types: ComplicationType[];
  /** Each catalogue icon's code point. */
  icon_glyphs: Record<string, number>;
}

/** The words and the installed devices. */
export interface Vocabulary extends Words {
  devices: DeviceInfo[];
  unreadable_devices: UnreadableDevice[];
}

// -- the rest of the answers -----------------------------------------------------

export interface Template {
  name: string;
  blurb: string;
}

/** One face in the library. */
export interface LibraryEntry {
  id: string;
  name: string;
  created: number;
  changed: number;
  version: number;
  snapshots: number;
}

export interface Home {
  templates: Template[];
  /** Newest change first. */
  documents: LibraryEntry[];
  /** Where the faces are kept, for people. */
  store: string;
  shared: boolean;
}

/** A device's skin as a PNG data URL at `scale`, and where the screen sits in it. */
export interface Skin {
  device: string;
  scale: number;
  image: string;
  width: number;
  height: number;
  x: number;
  y: number;
}

export interface Deleted {
  deleted: string;
}

export interface Renamed {
  id: string;
  name: string;
}

/** The server's answer to a build: with `ok`, the `.prg` is at `download`. */
export interface BuildResult {
  ok: boolean;
  device: string;
  log: string;
  seconds: number;
  /** "12,345 B / 131,072 B (9.4%)", when the build measured it. */
  memory: string | null;
  download: string | null;
}

/** Why a request was refused, in the author's terms. */
export interface Refusal {
  error: string;
}

/** The answer is a file: the bytes are in the response's `body`, not its `json`. */
export type FileBytes = Uint8Array;

// -- events --------------------------------------------------------------------

/** What the studio did, told to this tab's page and to every other tab's worker. */
export type Event =
  | { event: "created"; data: { id: string } }
  /** `tab` names the tab that made the change, so it can skip its own. */
  | { event: "changed"; data: { id: string; version: number; tab: string | null } }
  | { event: "deleted"; data: { id: string } }
  | { event: "renamed"; data: { id: string; name: string } }
  | { event: "snapshot"; data: { id: string; name: string; version: number } }
  | { event: "error"; data: { id?: string; message: string } };

export type EventName = Event["event"];
export type EventData<E extends EventName> = Extract<Event, { event: E }>["data"];

/** Every event's fields in one shape, for a listener given the name and the data apart: each is set on the events `Event` lists it for. */
export interface EventFields {
  id?: string;
  version?: number;
  tab?: string | null;
  name?: string;
  message?: string;
}

// -- requests --------------------------------------------------------------------

export interface DocArgs {
  id: string;
}

/** A change: refused as stale (409) unless `version` is the face's. */
export interface VersionArgs extends DocArgs {
  version: number;
}

export interface SkinArgs {
  device: string;
  /** 1 to 4; 2 when absent. */
  scale?: number;
}

export interface NewArgs {
  /** A template name; `minimal` when absent. */
  template?: string;
  name?: string;
}

/** The upload's bytes travel as the request's `body`. */
export interface UploadArgs {
  filename: string;
}

export interface RenameArgs extends DocArgs {
  name: string;
}

export interface GotoArgs extends VersionArgs {
  seq: number;
}

/** What a frame is drawn at. The page adds `v`, the version, so an image is asked for again; the worker ignores it. */
export interface FrameArgs extends DocArgs {
  device: string;
  /** 1 to 4; 2 when absent. A thumbnail is always drawn at 1. */
  scale?: number;
  style?: string;
  /** `HH:MM` or `HH:MM:SS`; empty for the sample moment. */
  time?: string;
  /** `YYYY-MM-DD`; empty for the sample day. */
  date?: string;
  asleep?: boolean;
  aod?: boolean;
  /** `slot:type,slot:type`: what each slot is drawn showing. */
  picks?: string;
  v?: number;
}

export interface CoverArgs extends DocArgs {
  v?: number;
}

export interface HandSetArgs extends DocArgs {
  name: string;
  device: string;
  scale?: number;
  v?: number;
}

/** A gesture on the canvas, in device pixels. */
export type Gesture =
  | { kind: "move"; part?: "both" | "at" | "to"; dx: number; dy: number }
  | { kind: "resize"; key: string[]; delta: number }
  | { kind: "turn"; key: string; degrees: number };

/** One element dragged (`element`), or several moved together (`elements`). */
export interface DragArgs extends VersionArgs {
  device: string;
  /** `auto` (where the viewed device reads the key) when absent. */
  scope?: "auto" | Scope;
  gesture: Gesture;
  element?: string;
  elements?: string[];
}

/** A file added to the bundle (its bytes in `body`): pointed at by every font whose `source:` is `reference`, or declared as the font `font` at `size`. */
export interface AssetArgs extends VersionArgs {
  filename: string;
  reference?: string;
  font?: string;
  size?: string;
}

/** Where an element's key is edited: the element, and for a geometry key the scope and device of its override (`null` while no device is viewed; read only in a scope other than `all`). */
export interface ElementTarget {
  element?: Path;
  scope?: Scope;
  device?: string | null;
}

/** One edit from the inspector or the Face panel, as `Document.edit` takes it. */
export type EditOp =
  | ({ op: "set"; path: Path; value: Value } & ElementTarget)
  | ({ op: "remove"; path: Path } & ElementTarget)
  | ({ op: "rename"; path: Path; to: string; prefix?: string } & ElementTarget)
  | ({ op: "use_color"; path: Path; value: string } & ElementTarget)
  | { op: "add_swatch"; value: string }
  | { op: "set_swatch"; name: string; value: string }
  | { op: "remove_unused" }
  | { op: "make_switchable"; names: string[]; scheme: string }
  | { op: "add_scheme"; name: string; like?: string }
  | { op: "rename_scheme"; name: string; to: string }
  | { op: "delete_scheme"; name: string }
  | { op: "remove_theme"; keep: string }
  | { op: "add_role"; name: string; value: Value }
  | { op: "rename_role"; name: string; to: string }
  | { op: "delete_role"; name: string }
  | { op: "add_slot"; name: string; default: string }
  | { op: "add_hand_set"; name: string; preset: string }
  | { op: "duplicate_hand_set"; name: string }
  | { op: "rename_hand_set"; name: string; to: string }
  | { op: "delete_hand_set"; name: string }
  | { op: "add_layout"; name: string }
  | ({ op: "insert_item"; path: Path; at: number; value: Value; block?: boolean } & ElementTarget)
  | ({ op: "remove_item"; path: Path; at: number } & ElementTarget)
  | ({ op: "move_item"; path: Path; from: number; to: number } & ElementTarget);

export interface EditArgs extends VersionArgs {
  edit: EditOp;
}

/** One structural edit from the Layers panel or the canvas, as `Document.structure` takes it. */
export type StructureOp =
  | { op: "add"; type: string; block?: Path; before?: string | null; choice?: string }
  | { op: "delete"; path: Path }
  | { op: "delete"; paths: Path[] }
  | { op: "duplicate"; path: Path }
  | { op: "ungroup"; path: Path }
  | { op: "move"; path: Path; block?: Path; before?: string | null }
  | { op: "paste"; text: string; block?: Path; before?: string | null }
  | { op: "group"; paths: Path[] };

export interface StructureArgs extends VersionArgs {
  edit: StructureOp;
}

/** Several edits as one change: each step an `EditOp` or a `StructureOp`, made on the text the step before left. */
export interface BatchArgs extends VersionArgs {
  label?: string;
  edits: (EditOp | StructureOp)[];
}

export interface TextArgs extends VersionArgs {
  text: string;
}

export interface InspectArgs extends DocArgs {
  element: Path;
  device?: string;
}

export interface BuildArgs extends VersionArgs {
  device: string;
}

export interface DownloadArgs extends DocArgs {
  /** `auto` (a zip when the bundle has files) when absent. */
  form?: "auto" | "zip" | "yaml";
}

export interface RestoreArgs extends VersionArgs {
  snapshot: string;
}

export interface CopyArgs extends DocArgs {
  snapshot: string;
}

/**
 * The editor's own state for a face, kept beside it in this browser and
 * never in its text: a JSON object the page owns, read and written whole.
 * Nothing is in it yet.
 */
export type FaceUiState = Record<string, Value>;

/** Read (`get`) or replace (`set`, with `state`) a face's `FaceUiState`. */
export interface UiStateArgs extends DocArgs {
  action: "get" | "set";
  state?: FaceUiState;
}

export interface UiState {
  state: FaceUiState;
}

/** Every operation: its arguments and its answer. */
export interface Ops {
  home: { args: Record<string, never>; answer: Home };
  vocabulary: { args: Record<string, never>; answer: Vocabulary };
  skin: { args: SkinArgs; answer: Skin };
  new: { args: NewArgs; answer: Summary };
  upload: { args: UploadArgs; answer: Summary };
  get: { args: DocArgs; answer: Summary };
  delete: { args: DocArgs; answer: Deleted };
  rename: { args: RenameArgs; answer: Renamed };
  cover: { args: CoverArgs; answer: FileBytes };
  goto: { args: GotoArgs; answer: Summary };
  frame: { args: FrameArgs; answer: Frame };
  thumbnail: { args: FrameArgs; answer: FileBytes };
  handset: { args: HandSetArgs; answer: FileBytes };
  drag: { args: DragArgs; answer: Dragged };
  assets: { args: AssetArgs; answer: Summary };
  edit: { args: EditArgs; answer: Summary };
  structure: { args: StructureArgs; answer: Structured };
  batch: { args: BatchArgs; answer: Structured };
  text: { args: TextArgs; answer: Summary };
  inspect: { args: InspectArgs; answer: Inspect };
  build: { args: BuildArgs; answer: BuildResult };
  undo: { args: VersionArgs; answer: Summary };
  redo: { args: VersionArgs; answer: Summary };
  history: { args: DocArgs; answer: History };
  snapshot: { args: DocArgs; answer: History };
  download: { args: DownloadArgs; answer: FileBytes };
  restore: { args: RestoreArgs; answer: Summary };
  copy: { args: CopyArgs; answer: Summary };
  ui_state: { args: UiStateArgs; answer: UiState };
}

export type Op = keyof Ops;
export type Args<O extends Op> = Ops[O]["args"];
export type Answer<O extends Op> = Ops[O]["answer"];

/** One request, as the page posts it: the operation, its arguments, a file's bytes, and the tab asking. */
export type Request<O extends Op = Op> = {
  [K in O]: { op: K; args?: Args<K>; body?: Uint8Array | null; tab?: string | null };
}[O];

export interface JsonResponse<O extends Op = Op> {
  status: 200;
  json: Answer<O>;
  body?: undefined;
  type?: undefined;
  filename?: undefined;
}

/** A file: a PNG, or a download named `filename`. */
export interface FileResponse {
  status: 200;
  body: Uint8Array;
  type: string;
  filename?: string;
  json?: undefined;
}

/** 400 refused, 404 no such face or snapshot, 409 the face moved on, 500 the worker failed, 503 it did not start, 507 the store failed. */
export interface RefusedResponse {
  status: 400 | 404 | 409 | 500 | 503 | 507;
  json: Refusal;
  body?: undefined;
}

export type Response<O extends Op = Op> = JsonResponse<O> | FileResponse | RefusedResponse;
