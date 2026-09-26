#!/bin/sh
# Build the three variants on each device; print warnings and --build-stats.
#   A  no settings at all                    (excludes :settings, :menu)
#   B  properties.xml + settings.xml + read  (excludes :nosettings, :menu)
#   C  B plus a getSettingsView Menu2        (excludes :nosettings)
# Usage: build.sh OUTDIR [device ...]
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=$1; shift
devices=${*:-"fenix8solar47mm fenix8solar51mm fr955"}
for variant in A B C; do
    d=$out/$variant
    rm -rf "$d"; mkdir -p "$d/source" "$d/resources/strings" "$d/resources/settings"
    cp "$here"/*.mc "$d/source/"
    cp "$here/strings.xml" "$d/resources/strings/"
    case $variant in
        A) exclude="settings;menu" ;;
        B) exclude="nosettings;menu"
           cp "$here/properties.xml" "$here/settings.xml" "$d/resources/settings/" ;;
        C) exclude="nosettings"
           cp "$here/properties.xml" "$here/settings.xml" "$d/resources/settings/" ;;
    esac
    for dev in $devices; do
        # A launcher icon is mandatory, at the size the device asks for.
        mkdir -p "$d/resources-$dev/drawables"
        "$here/../../../../.venv/bin/python" - "$dev" "$d/resources-$dev/drawables" <<'PY'
import json, os, sys
from PIL import Image
dev, out = sys.argv[1], sys.argv[2]
cfg = json.load(open(os.path.expanduser(f"~/.Garmin/ConnectIQ/Devices/{dev}/compiler.json")))
size = cfg.get("launcherIcon") or {"width": 40, "height": 40}
Image.new("RGB", (size["width"], size["height"]), "white").save(f"{out}/launcher_icon.png")
open(f"{out}/drawables.xml", "w").write(
    '<drawables><bitmap id="LauncherIcon" filename="launcher_icon.png" /></drawables>\n')
PY
    done
    products=""
    for dev in $devices; do products="$products<iq:product id=\"$dev\"/>"; done
    cat > "$d/manifest.xml" <<MANIFEST
<?xml version="1.0"?>
<iq:manifest version="3" xmlns:iq="http://www.garmin.com/xml/connectiq">
    <iq:application id="0f3c6a1e9b2d4c7e8a5b1d2c3e4f5a6b" type="watchface"
                    name="@Strings.AppName" entry="ProbeApp" minApiLevel="3.1.0"
                    launcherIcon="@Drawables.LauncherIcon">
        <iq:products>$products</iq:products>
        <iq:permissions/>
        <iq:languages><iq:language>eng</iq:language></iq:languages>
        <iq:barrels/>
    </iq:application>
</iq:manifest>
MANIFEST
    cat > "$d/monkey.jungle" <<JUNGLE
project.manifest = manifest.xml
project.typecheck = strict
project.optimization = 3z
base.excludeAnnotations = $exclude
JUNGLE
    for dev in $devices; do
        echo "== $variant $dev"
        "$CIQ_SDK/bin/monkeyc" -f "$d/monkey.jungle" -d "$dev" -o "$d/$dev.prg" \
            -y "$HOME/ciq/developer_key.der" -w -l 3 --build-stats 0 2>&1 \
            | grep -v '^$' | grep -v '^Picked up JAVA_TOOL_OPTIONS' || true
    done
done
