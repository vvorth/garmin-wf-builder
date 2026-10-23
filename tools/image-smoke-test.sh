#!/usr/bin/env bash
# Smoke-test a built container image, with no Garmin file anywhere.
#
#   ./tools/image-smoke-test.sh IMAGE
#
# CI runs it on every image before anything is published
# (.github/workflows/docker.yml). The fixture device `wfbtest`
# (ts/test/fixtures/devices/) stands in for the device definitions a user
# mounts at /devices, so the test covers what runs on the fixture alone: the
# toolchain starts (Node, the JRE, `monkeyc`), and the slice fixture
# generates a project and renders a preview. `monkeyc` does not know
# `wfbtest`, so a compiled .prg needs real devices and is not tested here.
set -euo pipefail

image=${1:?usage: $0 IMAGE}
root="$(cd "$(dirname "$0")/.." && pwd)"
fixtures="$root/ts/test/fixtures"

work="$(mktemp -d)"
# What the container writes belongs to its uid (1000), not necessarily the caller's.
cleanup() {
    docker run --rm -v "$work:/work" --entrypoint sh "$image" -c 'rm -rf /work/build' >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
cp -R "$fixtures/slice/." "$work/"
# The slice targets the verification devices; the fixture device is the only one mounted.
sed -i -e '/^  targets:$/,/^[^ ]/{/^    - /d}' -e 's/^  targets:$/  targets:\n    - wfbtest/' "$work/face.yaml"
grep -q '^    - wfbtest$' "$work/face.yaml"
chmod -R a+rwX "$work"

run() {
    docker run --rm \
        -v "$work:/work" \
        -v "$fixtures/devices:/devices:ro" \
        -v "$fixtures/devices/reference:/reference:ro" \
        -e WFB_DEVICE_REFERENCE=/reference \
        -e WFB_NO_GARMIN_FONTS=1 \
        "$image" "$@"
}

set -x
run --version
run java -version
run monkeyc --version
run build --no-compile face.yaml
test -f "$work/build/slice/manifest.xml"
run preview face.yaml -o build/preview
test -s "$work/build/preview/wfbtest.png"
