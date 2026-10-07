// The preview's Garmin rules (src/raster/garmin.ts) against the simulator
// captures they were fitted to (docs/research/probes/garmin-raster/): each
// family's off pixels on fr955 may not grow past what the fit reached.
import assert from "node:assert/strict";
import { test } from "node:test";
import { misses } from "../../docs/research/probes/garmin-raster/compare.ts";

const REACHED: Record<string, number> = {
  circles: 0, arcs: 27, lines: 0, polygons: 0, rects: 0, text: 1, ellipses: 0, lines2: 0, rects2: 0, rotated: 0,
  // Garmin's circle steps incrementally: from radius about 40 a few edge pixels differ from x² + y² <= r².
  big_circles: 144, big_fills: 12, big_ellipses: 20, big_lines: 0, big_rects: 0, big_arcs: 47,
};

test("every shape family is drawn as the simulator draws it, to the fit's own count", () => {
  for (const [family, reached] of Object.entries(REACHED)) assert.ok(misses(family, "fr955") <= reached, family);
});
