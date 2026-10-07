// The page's `/dist/raster.js`, which the studio server bundles, resolved
// to its source when the page's modules run in Node.
import { registerHooks } from "node:module";

const RASTER = new URL("../src/raster/canvas.ts", import.meta.url).href;

registerHooks({
  resolve: (specifier, context, next) => next(specifier === "/dist/raster.js" ? RASTER : specifier, context),
});
