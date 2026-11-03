#!/usr/bin/env bash
# Smoke-test a built container image, with no Garmin device file anywhere.
#
#   ./tools/image-smoke-test.sh IMAGE
#
# CI runs it on every image before anything is published
# (.github/workflows/docker.yml). The fixture device `wfbtest`
# (ts/test/fixtures/devices/) stands in for the device definitions a user
# mounts at /vendor/Devices, and a pruned SDK -- Garmin's free download, fetched
# once by the image's own ts/tools/fetch-sdk.ts into .cache/smoke-sdk/ (or
# WFB_SMOKE_SDK) -- for the one a user mounts at /vendor/Sdks (both at once by
# mounting the SDK Manager's folder at /vendor). The test covers what runs
# on the fixture alone: the toolchain starts (Node, the JRE), `wfb` finds the
# read-only SDK and compiles from a copy of it, extracts the device reference
# from the SDK's pages into the cache (and not again when the cache is kept),
# the slice fixture generates a project and renders a preview, a missing SDK
# is refused with the mount hint unless WFB_ACCEPT_LICENSE=1 lets the image
# download one (into /cache here), the editor starts with no SDK and says so
# over its API, and the default command serves the editor to a request
# addressed by any host name. `monkeyc` does not know `wfbtest`,
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
        -v "$sdk:/vendor/Sdks:ro" \
        -v "$fixtures/devices:/vendor/Devices:ro" \
        -v "$fixtures/devices/reference:/reference:ro" \
        -e WFB_DEVICE_REFERENCE=/reference \
        -e WFB_NO_GARMIN_FONTS=1 \
        "$image" "$@"
}
# The same without the fixture's reference pages: wfb extracts the fleet's from the SDK, into /cache.
run_extracting() {
    docker run --rm \
        -v "$work:/work" \
        -v "$sdk:/vendor/Sdks:ro" \
        -v "$cache:/cache" \
        -v "$fixtures/devices:/vendor/Devices:ro" \
        -e WFB_NO_GARMIN_FONTS=1 \
        "$image" "$@"
}

# `expect PATTERN cmd...`: the command's output (both streams) kept whole and
# shown, then searched. Never `cmd | grep -q`: grep stops at the first match,
# the writer gets a broken pipe, and pipefail fails the line.
expect() {
    local pattern=$1
    shift
    "$@" >"$work/out.txt" 2>&1 || true
    cat "$work/out.txt" >&2
    grep -q -- "$pattern" "$work/out.txt"
}
# The same for a command that must succeed as well.
expect_ok() {
    local pattern=$1
    shift
    "$@" >"$work/out.txt" 2>&1
    cat "$work/out.txt" >&2
    grep -q -- "$pattern" "$work/out.txt"
}

set -x
run --version
run java -version
expect_ok '^ready' run init
expect_ok 'read-only, so the compiler runs from a copy' run doctor
expect_ok '^ready' run doctor
run build --no-compile face.yaml
test -f "$work/build/slice/manifest.xml"
run preview face.yaml -o build/preview
test -s "$work/build/preview/wfbtest.png"

# The device reference: extracted from the mounted SDK's pages the first time, kept in /cache after.
expect_ok 'extracting the device reference from SDK' run_extracting devices
test -d "$cache/wfb/device-reference/devices"
test -n "$(ls "$cache/wfb/device-reference/devices")"
run_extracting devices >"$work/out.txt" 2>&1
if grep -q 'extracting the device reference' "$work/out.txt"; then
    echo "the cached device reference was extracted again" >&2
    exit 1
fi
# The compiler's copy sits in the same cache, made by the first command that compiles (doctor discovers the toolchain).
expect_ok 'runs from a copy at /cache/wfb/sdk/' run_extracting doctor
test -f "$cache"/wfb/sdk/*/bin/monkeybrains.jar

# No SDK mounted and no say-so: a build is refused with the mount and the switch, not a stack trace.
if docker run --rm -v "$work:/work" -v "$fixtures/devices:/vendor/Devices:ro" -e WFB_NO_GARMIN_FONTS=1 "$image" build face.yaml 2>"$work/no-sdk.txt"; then
    echo "a build with no SDK mounted succeeded" >&2
    exit 1
fi
grep -q 'no Connect IQ SDK at /vendor/Sdks' "$work/no-sdk.txt"
grep -q 'ConnectIQ:/vendor:ro' "$work/no-sdk.txt"
grep -q 'WFB_ACCEPT_LICENSE=1' "$work/no-sdk.txt"
# With the say-so, the image downloads Garmin's newest SDK into /cache before compiling (which then fails: monkeyc does not know wfbtest).
docker run --rm -v "$work:/work" -v "$cache:/cache" -v "$fixtures/devices:/vendor/Devices:ro" -v "$fixtures/devices/reference:/reference:ro" \
    -e WFB_DEVICE_REFERENCE=/reference -e WFB_NO_GARMIN_FONTS=1 -e WFB_ACCEPT_LICENSE=1 "$image" build face.yaml >"$work/auto.txt" 2>&1 || true
grep -q 'WFB_ACCEPT_LICENSE=1, so downloading' "$work/auto.txt"
grep -q '^installed SDK' "$work/auto.txt"
test -f "$cache"/wfb/sdks/connectiq-sdk-lin-*/bin/monkeybrains.jar
# and finds it there on the next run, without the mount.
expect_ok 'Connect IQ SDK   9.*/cache/wfb/sdks/' docker run --rm -v "$cache:/cache" -v "$fixtures/devices:/vendor/Devices:ro" -v "$fixtures/devices/reference:/reference:ro" \
    -e WFB_DEVICE_REFERENCE=/reference -e WFB_NO_GARMIN_FONTS=1 "$image" doctor

# `init` in the container names the host's steps and the mounts (and exits 1: nothing is mounted).
init_out=$(docker run --rm "$image" init || true)
grep -q 'connectiq-sdk-manager.dmg' <<<"$init_out"
grep -q 'ConnectIQ:/vendor:ro' <<<"$init_out"
grep -q 'init --download-sdk --accept-license' <<<"$init_out"
# A download without the agreement accepted fetches nothing.
if docker run --rm -v "$cache:/vendor/Sdks" "$image" init --download-sdk 2>"$work/gate.txt"; then
    echo "init --download-sdk ran without --accept-license" >&2
    exit 1
fi
grep -q 'accept-license' "$work/gate.txt"

# One mount of the SDK Manager's folder brings the SDK, the devices and the fonts at once.
garmin="$(mktemp -d)"
mkdir -p "$garmin/Fonts"
cp -R "$fixtures/devices" "$garmin/Devices"
rm -rf "$garmin/Devices/reference" "$garmin/Devices/README.md"
mkdir -p "$garmin/Sdks"
cp -R "$sdk" "$garmin/Sdks/connectiq-sdk-lin-smoke"
chmod -R a+rX "$garmin"
expect_ok '^ready' docker run --rm -v "$garmin:/vendor:ro" -v "$fixtures/devices/reference:/reference:ro" -e WFB_DEVICE_REFERENCE=/reference -e WFB_NO_GARMIN_FONTS=1 "$image" doctor
grep -q 'Connect IQ SDK   9.*/vendor/Sdks/connectiq-sdk-lin-smoke' "$work/out.txt"
grep -q '/vendor/Devices' "$work/out.txt"
rm -rf "$garmin"
# The paths an image before 2026-11 took still work.
expect_ok '^ready' docker run --rm -v "$sdk:/sdk:ro" -v "$fixtures/devices:/devices:ro" -v "$fixtures/devices/reference:/reference:ro" -e WFB_DEVICE_REFERENCE=/reference -e WFB_NO_GARMIN_FONTS=1 "$image" doctor
grep -q 'Connect IQ SDK   9.*(/sdk)' "$work/out.txt"

# The editor starts with nothing mounted at all (an empty folder at /vendor hides the image's own): its page's dialog
# installs the SDK and points at the SDK Manager for the watches, so the server only reports that neither is there.
mkdir -p "$work/empty-vendor"
bare=$(docker run -d -p 127.0.0.1::8765 -v "$work/empty-vendor:/vendor" -e WFB_NO_GARMIN_FONTS=1 -e WFB_NO_UPDATE_CHECK=1 "$image")
bare_port=$(docker port "$bare" 8765/tcp | head -1 | sed 's/.*://')
for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:$bare_port/api/sdk" && break
    sleep 1
done
curl -fsS "http://127.0.0.1:$bare_port/api/sdk" >"$work/sdk.json"
grep -q '"sdk":null' "$work/sdk.json"
grep -q '"canDownload":true' "$work/sdk.json"
grep -q '"devices":{"root":"/vendor/Devices","count":0}' "$work/sdk.json"
curl -fsS "http://127.0.0.1:$bare_port/api/doctor" >"$work/doctor.json"
grep -q '"verdict":' "$work/doctor.json"
docker rm -f "$bare" >/dev/null

# No arguments: the editor, on every address and answering any name.
studio=$(docker run -d -p 127.0.0.1::8765 \
    -v "$sdk:/vendor/Sdks:ro" \
    -v "$fixtures/devices:/vendor/Devices:ro" \
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
docker logs "$studio" >"$work/studio.txt" 2>&1
grep -q 'wfb studio on' "$work/studio.txt"
