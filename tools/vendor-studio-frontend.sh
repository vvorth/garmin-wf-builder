#!/usr/bin/env bash
# Vendor the `wfb studio` front end's libraries into ts/app/vendor/.
#
# A maintainer step, run deliberately when a pinned version changes: it needs
# npm and the network. Contributors and users never run it; the vendored
# files are committed with their versions and licences.
#
#   ./tools/vendor-studio-frontend.sh
#
# - htm's `preact/standalone.module.js`: Preact (with hooks) and htm in one
#   ES module, as htm publishes it. No bundler involved.
# - `codemirror.module.js`: CodeMirror 6, its YAML mode and
#   codemirror-json-schema's YAML schema support, bundled by esbuild from
#   tools/studio-frontend/ (pinned by its package-lock.json, `npm ci`), with
#   schema descriptions rendered as plain text instead of markdown-it and
#   Shiki. Every bundled package's licence goes into LICENSES-codemirror.
set -euo pipefail

HTM_VERSION=3.1.1

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/ts/app/vendor"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$work"
npm pack --silent "htm@$HTM_VERSION" >/dev/null
tar xzf "htm-$HTM_VERSION.tgz"
preact_range="$(node -e "console.log(require('./package/package.json').devDependencies.preact)")"

mkdir -p "$out"
cp package/preact/standalone.module.js "$out/preact-htm.module.js"
cp package/LICENSE "$out/LICENSE-htm"
# The standalone module bundles Preact; its licence travels with it.
npm pack --silent "preact@$preact_range" >/dev/null
mkdir preact && tar xzf preact-*.tgz -C preact
cp preact/package/LICENSE "$out/LICENSE-preact"

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
preact-htm.module.js  htm@$HTM_VERSION preact/standalone.module.js (Preact $preact_range bundled by htm)
LICENSE-htm           htm (Apache-2.0)
LICENSE-preact        Preact (MIT)
codemirror.module.js  $cm_versions (tools/studio-frontend, esbuild, markdown as plain text)
LICENSES-codemirror   every package in codemirror.module.js, with its version
EOF
echo "vendored into $out:"
cat "$out/VERSIONS"
