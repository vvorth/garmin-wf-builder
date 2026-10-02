// Bundles entry.js into one minified ES module: `node build.mjs <out.js>`.
// Prints the bundled packages, one per line, for their licences.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const stub = fileURLToPath(new URL("./markdown-stub.js", import.meta.url));
const result = await build({
  entryPoints: [fileURLToPath(new URL("./entry.js", import.meta.url))],
  bundle: true, format: "esm", minify: true, legalComments: "none",
  outfile: process.argv[2], metafile: true,
  plugins: [{
    // schema descriptions as plain text: no markdown-it, no Shiki
    name: "plain-markdown",
    setup(b) { b.onResolve({ filter: /utils\/markdown(\.js)?$/ }, () => ({ path: stub })); },
  }],
});
const packages = new Set();
for (const input of Object.keys(result.metafile.inputs)) {
  const m = input.match(/node_modules\/((@[^/]+\/)?[^/]+)/);
  if (m) packages.add(m[1]);
}
console.log([...packages].sort().join("\n"));
