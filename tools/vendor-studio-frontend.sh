#!/usr/bin/env bash
# Vendor the `wfb studio` front end's libraries into wfb/studio/static/vendor/.
#
# A maintainer step, run deliberately when a pinned version changes: it needs
# npm and the network. Contributors and users never run it; the vendored
# files are committed with their versions and licences.
#
#   ./tools/vendor-studio-frontend.sh
#
# - htm's `preact/standalone.module.js`: Preact (with hooks) and htm in one
#   ES module, as htm publishes it. No bundler involved.
set -euo pipefail

HTM_VERSION=3.1.1

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/wfb/studio/static/vendor"
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

cat > "$out/VERSIONS" <<EOF
preact-htm.module.js  htm@$HTM_VERSION preact/standalone.module.js (Preact $preact_range bundled by htm)
LICENSE-htm           htm (Apache-2.0)
LICENSE-preact        Preact (MIT)
EOF
echo "vendored into $out:"
cat "$out/VERSIONS"
