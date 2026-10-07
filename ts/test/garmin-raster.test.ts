// The preview's Garmin rules (src/raster/garmin.ts) against the simulator
// captures they were fitted to (docs/research/probes/garmin-raster/): each
// family's off pixels on fr955 may not grow past what the fit reached.
import assert from "node:assert/strict";
import { test } from "node:test";
import { misses } from "../../docs/research/probes/garmin-raster/compare.ts";

const REACHED: Record<string, number> = { circles: 0, arcs: 27, lines: 224, polygons: 1, rects: 0, text: 1 };

test("every shape family is drawn as the simulator draws it, to the fit's own count", () => {
  for (const [family, reached] of Object.entries(REACHED)) assert.ok(misses(family, "fr955") <= reached, family);
});
