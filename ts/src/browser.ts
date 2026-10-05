// The browser bundle's entry (`npm run bundle` → `dist/wfb.js`): what the
// editor's worker imports. It grows as stages are ported.
export { MemoryDeviceFiles, readJson } from "./devices/files.ts";
export type { DeviceFiles } from "./devices/files.ts";
