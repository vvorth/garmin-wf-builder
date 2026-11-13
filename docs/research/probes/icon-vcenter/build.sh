#!/bin/sh
# Builds the probe for fenix8solar47mm, fenix8solar51mm and fr955.
#
# 1. `wfb build --no-compile` generates the project from face.yaml.
# 2. Each `old_*` icon (generated with `align: top`, so drawn at its row's
#    centre y with TEXT_JUSTIFY_CENTER) is patched to add TEXT_JUSTIFY_VCENTER:
#    the call the compiler made for every centred icon before it stopped
#    relying on VCENTER for baked fonts.
# 3. monkeyc compiles each device, warning-free under -l 3.
# 4. The `common` line and the drawn glyphs' `char` lines of every icon and
#    text font are printed per device: the lineHeight, base and yoffset the
#    measurements are compared against.
#
# Run from the repository root:  sh docs/research/probes/icon-vcenter/build.sh [OUT]
set -eu
OUT=${1:-build/icon-vcenter}
HERE=docs/research/probes/icon-vcenter
KEY=${CIQ_KEY:-$HOME/ciq/developer_key.der}
./wfb build "$HERE/face.yaml" --no-compile -o "$OUT"
PROJECT=$(dirname "$(ls "$OUT"/*/monkey.jungle)")
VIEW=$(ls "$PROJECT"/source/*View.mc)
perl -0pi -e 's/(function drawOld\w+\(dc as Dc\) as Void \{.*?Graphics\.TEXT_JUSTIFY_CENTER)\);/$1 | Graphics.TEXT_JUSTIFY_VCENTER);/sg' "$VIEW"
PATCHED=$(perl -0ne '$n = 0; while (/function drawOld\w+\(.*?\n    \}/sg) { $n++ if $& =~ /TEXT_JUSTIFY_VCENTER/ } print $n' "$VIEW")
test "$PATCHED" -eq 5 || { echo "patched $PATCHED of 5 old_* draws in $VIEW" >&2; exit 1; }
for d in fenix8solar47mm fenix8solar51mm fr955; do
  "$CIQ_SDK/bin/monkeyc" -f "$PROJECT/monkey.jungle" -d "$d" -o "$OUT/icon-vcenter-$d.prg" -y "$KEY" -w -l 3
  echo "== $d"
  for f in "$PROJECT/resources-$d"/fonts/*.fnt; do
    # an icon font holds the heart (U+F05F6) alone; the text font's H and 8 are ids 72 and 56
    echo "$(basename "$f"): $(grep '^common' "$f" | cut -d' ' -f2-3) | $(grep -E '^char id=(984566|72|56) ' "$f" | tr -s ' ' | cut -d' ' -f2,5-8 | tr '\n' ' ')"
  done
done
