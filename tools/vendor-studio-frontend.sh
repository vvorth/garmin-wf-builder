#!/usr/bin/env bash
# Vendor the `wfb studio` front end's libraries into ts/app/vendor/.
#
# A maintainer step, run deliberately when a pinned version changes: it needs
# npm and the network. Contributors and users never run it; the vendored
# files are committed with their versions and licences.
#
#   ./tools/vendor-studio-frontend.sh
#
# Preact and htm are not vendored: they are npm dependencies of ts/ (its
# package.json), bundled into the page with these files by esbuild.
#
# - `codemirror.module.js`: CodeMirror 6, its YAML mode and
#   codemirror-json-schema's YAML schema support, bundled by esbuild from
#   tools/studio-frontend/ (pinned by its package-lock.json, `npm ci`), with
#   schema descriptions rendered as plain text instead of markdown-it and
#   Shiki. Every bundled package's licence goes into LICENSES-codemirror.
# - marked's `lib/marked.esm.js`: the Help popup's markdown, as published.
set -euo pipefail

MARKED_VERSION=18.1.0

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/ts/app/vendor"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$work"
mkdir -p "$out"
npm pack --silent "marked@$MARKED_VERSION" >/dev/null
mkdir marked && tar xzf "marked-$MARKED_VERSION.tgz" -C marked
cp marked/package/lib/marked.esm.js "$out/marked.esm.js"
cp marked/package/LICENSE "$out/LICENSE-marked"

# CodeMirror: one bundle from the pinned packages
cp -R "$root/tools/studio-frontend" "$work/cm"
(cd "$work/cm" && npm ci --silent >/dev/null)
packages="$(cd "$work/cm" && node build.mjs "$out/codemirror.module.js")"
: > "$out/LICENSES-codemirror"
for p in $packages; do
  dir="$work/cm/node_modules/$p"
  version="$(node -e "console.log(require('$dir/package.json').version)")"
  licence="$(ls "$dir" | grep -i -m1 -E '^(licen[cs]e|copying)' || true)"
  {
    echo "=== $p@$version"
    if [ -n "$licence" ]; then cat "$dir/$licence"
    else node -e "console.log('licence: ' + require('$dir/package.json').license)"; fi
    echo
  } >> "$out/LICENSES-codemirror"
done
cm_versions="$(cd "$work/cm" && node -e "
const p = require('./package.json').dependencies;
console.log(Object.entries(p).filter(([k]) => k !== 'esbuild').map(([k, v]) => k + '@' + v).join(', '))")"

cat > "$out/VERSIONS" <<EOF
codemirror.module.js  $cm_versions (tools/studio-frontend, esbuild, markdown as plain text)
LICENSES-codemirror   every package in codemirror.module.js, with its version
LICENSES-pillow       Pillow 12.3.0 (MIT-CMU): ts/src/raster/pillow.ts (bundled as /dist/raster.js) follows its ImageDraw.py and libImaging/Draw.c
marked.esm.js         marked@$MARKED_VERSION lib/marked.esm.js (the Help popup's markdown)
LICENSE-marked        marked (MIT)
EOF
echo "vendored into $out:"
cat "$out/VERSIONS"
