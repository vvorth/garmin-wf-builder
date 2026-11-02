#!/usr/bin/env bash
# Smoke-test a built container image, with no Garmin device file anywhere.
#
#   ./tools/image-smoke-test.sh IMAGE
#
# CI runs it on every image before anything is published
# (.github/workflows/docker.yml). The fixture device `wfbtest`
# (ts/test/fixtures/devices/) stands in for the device definitions a user
# mounts at /devices, and a pruned SDK -- Garmin's free download, fetched once
# by the image's own ts/tools/fetch-sdk.ts into .cache/smoke-sdk/ (or
# WFB_SMOKE_SDK) -- for the one a user mounts at /sdk. The test covers what runs
# on the fixture alone: the toolchain starts (Node, the JRE), `wfb` finds the
# read-only SDK and compiles from a copy of it, extracts the device reference
# from the SDK's pages into the cache (and not again when the cache is kept),
# the slice fixture generates a project and renders a preview, a missing /sdk
# is refused with the mount hint, and the default command serves the editor
# to a request addressed by any host name. `monkeyc` does not know `wfbtest`,
# so a compiled .prg needs real devices and is not tested here.
set -euo pipefail

image=${1:?usage: $0 IMAGE}
root="$(cd "$(dirname "$0")/.." && pwd)"
fixtures="$root/ts/test/fixtures"
sdk="${WFB_SMOKE_SDK:-$root/.cache/smoke-sdk}"

work="$(mktemp -d)"
cache="$(mktemp -d)"
# What the container writes belongs to its uid (1000), not necessarily the caller's.
studio=""
cleanup() {
    [ -z "$studio" ] || docker rm -f "$studio" >/dev/null 2>&1 || true
    docker run --rm -v "$work:/work" -v "$cache:/cache" --entrypoint sh "$image" -c 'rm -rf /work/build /cache/*' >/dev/null 2>&1 || true
    rm -rf "$work" "$cache"
}
trap cleanup EXIT
cp -R "$fixtures/slice/." "$work/"
# The slice targets the verification devices; the fixture device is the only one mounted.
sed -i -e '/^  targets:$/,/^[^ ]/{/^    - /d}' -e 's/^  targets:$/  targets:\n    - wfbtest/' "$work/face.yaml"
grep -q '^    - wfbtest$' "$work/face.yaml"
chmod -R a+rwX "$work" "$cache"

# The SDK, once: the newest Linux release, pruned to the compiler, its device
# pages and its licences, by the tool the image carries.
if [ ! -f "$sdk/bin/monkeybrains.jar" ]; then
    mkdir -p "$sdk"
    chmod a+rwX "$sdk"
    docker run --rm -v "$sdk:/out" "$image" node /opt/wfb/ts/tools/fetch-sdk.ts --newest /out
fi
test -f "$sdk/bin/monkeybrains.jar"
test -d "$sdk/doc/docs/Device_Reference"

# As a user runs it: the SDK, the devices and their reference pages mounted read-only.
run() {
    docker run --rm \
        -v "$work:/work" \
        -v "$sdk:/sdk:ro" \
        -v "$fixtures/devices:/devices:ro" \
        -v "$fixtures/devices/reference:/reference:ro" \
        -e WFB_DEVICE_REFERENCE=/reference \
        -e WFB_NO_GARMIN_FONTS=1 \
        "$image" "$@"
}
# The same without the fixture's reference pages: wfb extracts the fleet's from the SDK, into /cache.
run_extracting() {
    docker run --rm \
        -v "$work:/work" \
        -v "$sdk:/sdk:ro" \
        -v "$cache:/cache" \
        -v "$fixtures/devices:/devices:ro" \
        -e WFB_NO_GARMIN_FONTS=1 \
        "$image" "$@"
}

set -x
run --version
run java -version
run init | tee /dev/stderr | grep -q '^ready'
run doctor | tee /dev/stderr | grep -q 'read-only, so the compiler runs from a copy'
run doctor | grep -q '^ready'
run build --no-compile face.yaml
test -f "$work/build/slice/manifest.xml"
run preview face.yaml -o build/preview
test -s "$work/build/preview/wfbtest.png"

# The device reference: extracted from the mounted SDK's pages the first time, kept in /cache after.
run_extracting devices 2>&1 | tee /dev/stderr | grep -q 'extracting the device reference from SDK'
test -d "$cache/wfb/device-reference/devices"
test -n "$(ls "$cache/wfb/device-reference/devices")"
if run_extracting devices 2>&1 | grep -q 'extracting the device reference'; then
    echo "the cached device reference was extracted again" >&2
    exit 1
fi
# The compiler's copy sits in the same cache, made by the first command that compiles (doctor discovers the toolchain).
run_extracting doctor | grep -q 'runs from a copy at /cache/wfb/sdk/'
test -f "$cache"/wfb/sdk/*/bin/monkeybrains.jar

# No SDK mounted: a build is refused with the mount, not a stack trace.
if docker run --rm -v "$work:/work" -v "$fixtures/devices:/devices:ro" -e WFB_NO_GARMIN_FONTS=1 "$image" build face.yaml 2>"$work/no-sdk.txt"; then
    echo "a build with no SDK mounted succeeded" >&2
    exit 1
fi
grep -q 'no Connect IQ SDK at /sdk' "$work/no-sdk.txt"
grep -q 'Sdks:/sdk:ro' "$work/no-sdk.txt"
# `init` in the container names the host's steps and the mounts (and exits 1: nothing is mounted).
init_out=$(docker run --rm "$image" init || true)
grep -q 'connectiq-sdk-manager.dmg' <<<"$init_out"
grep -q 'Sdks:/sdk:ro' <<<"$init_out"
grep -q 'init --download-sdk --accept-license' <<<"$init_out"
# A download without the agreement accepted fetches nothing.
if docker run --rm -v "$cache:/sdk" "$image" init --download-sdk 2>"$work/gate.txt"; then
    echo "init --download-sdk ran without --accept-license" >&2
    exit 1
fi
grep -q 'accept-license' "$work/gate.txt"

# No arguments: the editor, on every address and answering any name.
studio=$(docker run -d -p 127.0.0.1::8765 \
    -v "$sdk:/sdk:ro" \
    -v "$fixtures/devices:/devices:ro" \
    -v "$fixtures/devices/reference:/reference:ro" \
    -e WFB_DEVICE_REFERENCE=/reference \
    -e WFB_NO_GARMIN_FONTS=1 \
    "$image")
port=$(docker port "$studio" 8765/tcp | head -1 | sed 's/.*://')
for _ in $(seq 1 30); do
    curl -fsS -o /dev/null -H 'Host: studio.example' "http://127.0.0.1:$port/" && break
    sleep 1
done
curl -fsS -o /dev/null -H 'Host: studio.example' "http://127.0.0.1:$port/"
docker logs "$studio" 2>&1 | grep -q 'wfb studio on'
