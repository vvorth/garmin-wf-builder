// The browser bundle's entry (`npm run bundle` → `dist/wfb.js`): what the
// editor's worker imports. It grows as stages are ported. Before loading a
// design the worker hands in the schema (`loadSchema`) and the icon font's
// character map (`setIconFontGlyphs`), which Node reads from disk
// (`src/node.ts`).
export { MemoryDeviceFiles, readJson } from "./devices/files.ts";
export type { DeviceFiles } from "./devices/files.ts";
export * as yaml from "./edit/yaml.ts";
export * as spans from "./edit/spans.ts";
export * as patch from "./edit/patch.ts";
export * as structure from "./edit/structure.ts";
export * as colors from "./edit/colors.ts";
export * as schemes from "./edit/schemes.ts";
export * as hands from "./edit/hands.ts";
export * as palette from "./palette.ts";
export { load } from "./build.ts";
export { loadSchema } from "./validate.ts";
export { setIconFontGlyphs } from "./icons.ts";
export * as ir from "./ir/model.ts";
export * as gate from "./edit/gate.ts";
export * as slots from "./edit/slots.ts";
export { DeviceDatabase, Device, FontMetric } from "./devices/device.ts";
export type { FontFiles, FontFile } from "./fonts/files.ts";
export { BakedFont, GlyphBox } from "./fonts/bmfont.ts";
export * as layout from "./layout.ts";
export * as visibleArea from "./visible_area.ts";
export * as geometry from "./edit/geometry.ts";
