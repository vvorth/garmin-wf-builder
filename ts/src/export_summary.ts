// The text of `wfb export`'s phone-settings summary line. A Store install is
// the one place Garmin Connect edits an app's settings, so the export says
// which devices carry the `config:` axes there (docs/guide/configuration.md).
import { usesSettingsMenu } from "./availability.ts";
import type { Device } from "./devices/device.ts";
import { menuAxes } from "./emit/monkeyc/config_menu.ts";
import type { Face } from "./ir/model.ts";

/** `phone settings: <n> axes on <ids>`, or why there are none. */
export function phoneSettingsLine(face: Face, devices: readonly Device[]): string {
  if (!face.hasConfig) return "phone settings: none (no config:)";
  const carrying = devices.filter(usesSettingsMenu);
  if (carrying.length === 0) return "phone settings: none (every device has the native editor)";
  const n = menuAxes(face).length;
  return `phone settings: ${n} ${n === 1 ? "axis" : "axes"} on ${carrying.map((d) => d.id).join(", ")}`;
}
