#!/usr/bin/env bash
# Capture every garmin-raster probe face in the Connect IQ simulator, on the
# user's Mac: one window capture per face and device, into captures/.
#
#   ./docs/research/probes/garmin-raster/capture.sh [FAMILY ...]
#
# Each face is captured on the devices its own `targets:` names. Each face is built and pushed with `wfb simulate`, which then captures the
# simulator's window (macOS needs the terminal to have Screen Recording).
# Keep the simulator's zoom at 100% throughout, so a watch pixel is the same
# number of screen pixels in every capture.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../../.." && pwd)"
families=("$@")
[ ${#families[@]} -gt 0 ] || families=(circles arcs lines polygons rects text swatches ellipses lines2 rects2 rotated
  big_circles big_fills big_ellipses big_lines big_rects big_arcs)
mkdir -p "$here/captures"
for family in "${families[@]}"; do
  # The devices the face itself targets.
  devices=$(sed -n 's/^  targets: \[\(.*\)\]$/\1/p' "$here/faces/$family/face.yaml" | tr -d ' ' | tr ',' ' ')
  for device in $devices; do
    echo "== $family on $device"
    node "$root/ts/src/cli.ts" simulate "$here/faces/$family/face.yaml" -d "$device" \
      -o "$here/build" --screenshot "$here/captures/$family-$device.png"
    sleep 2
  done
done
echo "captures in $here/captures"
