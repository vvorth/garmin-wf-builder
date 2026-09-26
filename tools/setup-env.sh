#!/usr/bin/env bash
# Rebuild the Connect IQ build environment for garmin-wf-builder.
#
# Idempotent: safe to re-run. Runs on Linux and macOS. Installs
#   - Connect IQ SDK 9.2.0        -> ~/ciq/sdks/9.2.0   (Linux: downloaded;
#                                    macOS: found where the SDK Manager put it)
#   - a developer signing key     -> ~/ciq/developer_key.der (generated)
#   - device definitions          -> ~/.Garmin/ConnectIQ/Devices (Linux: copied;
#                                    macOS: read in place from the SDK Manager's
#                                    ~/Library/Application Support/Garmin/ConnectIQ)
#   - Garmin's own font files     -> ~/.Garmin/ConnectIQ/Fonts (Linux: copied
#                                    from vendor/fonts/, if present -- optional;
#                                    macOS: read in place, like the devices)
#   - the Nerd Fonts icon font    -> wfb/assets/icons/ (downloaded, hash-checked)
#   - the system fonts registry   -> wfb/assets/system-fonts/ (downloaded,
#                                    hash-checked; docs/plans/09-system-font-metrics.md)
#
# The SDK downloads unauthenticated. Device definitions CANNOT be downloaded
# (api.gcs.garmin.com returns HTTP 401, Garmin SSO); they must come from a host
# SDK Manager installation. See docs/guide/getting-started.md, "Step 1: get the device definitions".

set -euo pipefail

SDK_VERSION="9.2.0"
SDK_FILE="connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip"
SDK_URL="https://developer.garmin.com/downloads/connect-iq/sdks/${SDK_FILE}"
KEY_DER="${HOME}/ciq/developer_key.der"
# The Python the compiler needs: mypy.ini's python_version. macOS ships an
# older /usr/bin/python3, so a newer one is looked for by name as well.
PY_MIN="3.11"

# Where the SDK Manager keeps its downloads, and so where monkeyc looks for
# device definitions. On macOS the SDK Manager owns that tree, so this script
# reads it in place and never writes into it; on Linux it is the install
# target for a copy from vendor/devices/.
case "$(uname -s)" in
    Darwin)
        IS_MAC=true
        GARMIN_HOME="${HOME}/Library/Application Support/Garmin/ConnectIQ"
        ;;
    *)
        IS_MAC=false
        GARMIN_HOME="${HOME}/.Garmin/ConnectIQ"
        ;;
esac
SDK_ROOT="${HOME}/ciq/sdks/${SDK_VERSION}"
DEVICES_DEST="${GARMIN_HOME}/Devices"
FONTS_DEST="${GARMIN_HOME}/Fonts"
# Only the development sandbox has this file; everywhere else the exports are
# printed for the user's shell profile instead.
PERSIST="/etc/sandbox-persistent.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n=== %s ===\n' "$1"; }
# Entry count of a directory; BSD wc pads its output with spaces.
count() { ls "$1" 2>/dev/null | wc -l | tr -d ' '; }

# ------------------------------------------------------ prerequisites --------
say "prerequisites"
# curl and unzip only fetch the Linux SDK; on macOS the SDK Manager has it.
if [ "${IS_MAC}" = true ]; then
    tools=(openssl)
else
    tools=(curl unzip openssl)
fi
missing=()
for tool in "${tools[@]}"; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
done
# macOS has a /usr/bin/java stub even with no Java installed, so the check
# has to run it rather than find it.
java -version >/dev/null 2>&1 || missing+=("java")
PY=""
for cand in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "${cand}" >/dev/null 2>&1 &&
       "${cand}" -c "import sys; sys.exit(sys.version_info < tuple(map(int, '${PY_MIN}'.split('.'))))" 2>/dev/null; then
        PY="$(command -v "${cand}")"
        break
    fi
done
[ -n "${PY}" ] || missing+=("python${PY_MIN}+")
if [ "${#missing[@]}" -gt 0 ]; then
    if [ "${IS_MAC}" = true ]; then
        cat >&2 <<EOF
ERROR: missing required tools: ${missing[*]}

Install them with Homebrew (https://brew.sh) and re-run this script:

  brew install python@3.13
  brew install --cask temurin@21

java runs Garmin's compiler (monkeyc); Java 21 or newer is tested. The
python3 that ships with macOS is too old: wfb needs Python ${PY_MIN} or newer.
EOF
    else
        cat >&2 <<EOF
ERROR: missing required tools: ${missing[*]}

Install them with your package manager and re-run this script. On Debian/Ubuntu:

  sudo apt-get install -y curl unzip openssl python3 python3-venv openjdk-21-jre-headless

java runs Garmin's compiler (monkeyc); Java 21 or newer is tested. wfb needs
Python ${PY_MIN} or newer.
EOF
    fi
    exit 1
fi
echo "found: ${tools[*]} java ${PY}"

# ---------------------------------------------------------------- SDK --------
say "Connect IQ SDK ${SDK_VERSION}"
if [ "${IS_MAC}" = true ]; then
    # Garmin publishes no unauthenticated macOS SDK download this script has
    # checked, so on a Mac the SDK Manager's own install is used in place:
    # Sdks/connectiq-sdk-mac-<version>-<date>-<hash>/.
    SDK_ROOT=""
    for cand in "${GARMIN_HOME}/Sdks/connectiq-sdk-mac-${SDK_VERSION}-"*; do
        [ -x "${cand}/bin/monkeyc" ] && SDK_ROOT="${cand}"
    done
    if [ -z "${SDK_ROOT}" ]; then
        installed="$(ls "${GARMIN_HOME}/Sdks" 2>/dev/null | tr '\n' ' ' || true)"
        cat >&2 <<EOF
ERROR: Connect IQ SDK ${SDK_VERSION} is not installed.

Install it with Garmin's Connect IQ SDK Manager
(https://developer.garmin.com/connect-iq/sdk/): sign in, open the SDK tab and
download ${SDK_VERSION}. It lands in
  ${GARMIN_HOME}/Sdks/
where this script looks for it. Installed there now:
  ${installed:-(none)}
EOF
        exit 1
    fi
    echo "found at ${SDK_ROOT}"
elif [ -x "${SDK_ROOT}/bin/monkeyc" ]; then
    echo "already installed at ${SDK_ROOT}"
else
    mkdir -p "${SDK_ROOT}"
    tmp="$(mktemp -d)"
    echo "downloading ${SDK_FILE} (~204 MB)…"
    curl -fSL --retry 3 -o "${tmp}/sdk.zip" "${SDK_URL}"
    echo "extracting…"
    unzip -q -o "${tmp}/sdk.zip" -d "${SDK_ROOT}"
    rm -rf "${tmp}"
    chmod +x "${SDK_ROOT}"/bin/* 2>/dev/null || true
    echo "installed to ${SDK_ROOT}"
fi

# ------------------------------------------------------- developer key -------
say "developer key"
if [ -f "${KEY_DER}" ]; then
    echo "already present at ${KEY_DER}"
else
    mkdir -p "$(dirname "${KEY_DER}")"
    pem="${KEY_DER%.der}.pem"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "${pem}" 2>/dev/null
    openssl pkcs8 -topk8 -inform PEM -outform DER -in "${pem}" -out "${KEY_DER}" -nocrypt
    chmod 600 "${pem}" "${KEY_DER}"
    echo "generated ${KEY_DER}"
fi

# ---------------------------------------------------------- devices ---------
say "device definitions"
dest_had_devices=false
[ -d "${DEVICES_DEST}" ] && [ -n "$(ls -A "${DEVICES_DEST}" 2>/dev/null)" ] && dest_had_devices=true

src=""
# vendor/devices/ is the documented place. The two .devices-import paths are
# where the development sandbox receives a copy from its host.
for cand in \
    "${REPO_ROOT}/vendor/devices" \
    "${REPO_ROOT}/../.devices-import" \
    "${REPO_ROOT}/../garmin-watchface-protomolecule/.devices-import"
do
    if [ -d "${cand}" ] && [ -n "$(ls -A "${cand}" 2>/dev/null)" ]; then
        src="${cand}"; break
    fi
done

if [ "${IS_MAC}" = true ]; then
    # monkeyc and wfb both read the SDK Manager's folder directly, so nothing
    # is copied. A vendored device the SDK Manager lacks is only reported:
    # writing into the SDK Manager's own tree is not this script's business.
    if [ "${dest_had_devices}" = true ]; then
        echo "found $(count "${DEVICES_DEST}") devices in ${DEVICES_DEST}"
        if [ -n "${src}" ]; then
            absent=()
            for dev_path in "${src}"/*/; do
                name="$(basename "${dev_path%/}")"
                [ -d "${DEVICES_DEST}/${name}" ] || absent+=("${name}")
            done
            if [ "${#absent[@]}" -gt 0 ]; then
                echo "note: ${#absent[@]} device(s) in ${src} are not in the SDK Manager's folder,"
                echo "so monkeyc cannot build for them; download them with the SDK Manager: ${absent[*]}"
            fi
        fi
    else
        cat >&2 <<EOF
ERROR: no Garmin device definitions found in
  ${DEVICES_DEST}

The compiler needs them, and a script cannot download them: Garmin's server
requires you to sign in. Open Garmin's Connect IQ SDK Manager
(https://developer.garmin.com/connect-iq/sdk/), sign in, download the devices
you build for from its Devices tab, and re-run this script.

See docs/guide/getting-started.md, "Step 1: get the device definitions".
EOF
        exit 1
    fi
elif [ -z "${src}" ]; then
    if [ "${dest_had_devices}" = true ]; then
        echo "already installed: $(count "${DEVICES_DEST}") devices"
    else
        cat >&2 <<EOF
ERROR: no Garmin device definitions found.

The compiler needs them, and a script cannot download them: Garmin's server
requires you to sign in. Get them once by hand:

  1. Install Garmin's Connect IQ SDK Manager
     (https://developer.garmin.com/connect-iq/sdk/), sign in, and download
     the devices you build for.
  2. On this Linux machine, the SDK Manager saves them to
     ${DEVICES_DEST}
     and this script finds them there.
     If you downloaded them on another machine (macOS keeps them in
     ~/Library/Application Support/Garmin/ConnectIQ/Devices), copy that
     folder's contents into
     ${REPO_ROOT}/vendor/devices/
  3. Re-run this script.

See docs/guide/getting-started.md, "Step 1: get the device definitions".
EOF
        exit 1
    fi
else
    mkdir -p "${DEVICES_DEST}"
    # Copy each device directory from src that is not already present in the
    # destination. Never overwrite an existing device dir -- a newly vendored
    # device (e.g. fr255 added after the first setup run) is added on top of
    # whatever is already installed, incrementally, on every re-run.
    added=()
    for dev_path in "${src}"/*/; do
        dev_path="${dev_path%/}"
        name="$(basename "${dev_path}")"
        if [ ! -d "${DEVICES_DEST}/${name}" ]; then
            cp -R "${dev_path}" "${DEVICES_DEST}/"
            added+=("${name}")
        fi
    done

    if [ "${dest_had_devices}" = false ]; then
        echo "installed $(count "${DEVICES_DEST}") devices from ${src}"
    elif [ "${#added[@]}" -gt 0 ]; then
        echo "installed ${#added[@]} new device(s) from ${src}: ${added[*]}"
    else
        echo "already installed: $(count "${DEVICES_DEST}") devices"
    fi
fi

# ------------------------------------------------- Garmin's own fonts -------
say "Garmin font files (optional)"
VENDOR_FONTS="${REPO_ROOT}/vendor/fonts"
if [ "${IS_MAC}" = true ]; then
    # wfb reads vendor/fonts/ and the SDK Manager's Fonts folder in place
    # (wfb.fonts.fetch_system.garmin_font_root), so nothing is copied.
    echo "read in place: vendor/fonts/ first, then ${FONTS_DEST}"
elif [ -d "${VENDOR_FONTS}" ] && [ -n "$(ls -A "${VENDOR_FONTS}" 2>/dev/null)" ]; then
    mkdir -p "${FONTS_DEST}"
    # Same incremental shape as the device-definitions copy above: never
    # overwrite an existing entry, so a newly vendored font is added on top
    # of whatever is already installed on every re-run.
    added=()
    for src_path in "${VENDOR_FONTS}"/*; do
        [ -e "${src_path}" ] || continue
        name="$(basename "${src_path}")"
        if [ ! -e "${FONTS_DEST}/${name}" ]; then
            cp -R "${src_path}" "${FONTS_DEST}/"
            added+=("${name}")
        fi
    done
    if [ "${#added[@]}" -gt 0 ]; then
        echo "installed ${#added[@]} new font file(s)/dir(s) into ${FONTS_DEST}: ${added[*]}"
    else
        echo "already installed: $(count "${FONTS_DEST}") entries in ${FONTS_DEST}"
    fi
else
    # Quietly optional: most builds work fine on the registry's free
    # stand-ins alone (wfb doctor says so). See docs/container.md for how to
    # populate vendor/fonts/ from the SDK Manager's own Fonts directory.
    echo "no vendor/fonts/ found; skipping (optional -- see docs/container.md)"
fi

# One line stating what the absence of a Garmin font root actually *costs*
# (plan 12 R3.1) -- not just that it is optional. Mirrors garmin_font_root's
# own priority closely enough for a status line: vendor/fonts/ (just handled
# above) or FONTS_DEST (already installed from a previous run, or placed
# there by hand) either one means "found".
if [ -n "$(ls -A "${VENDOR_FONTS}" 2>/dev/null)" ] || [ -n "$(ls -A "${FONTS_DEST}" 2>/dev/null)" ]; then
    echo "preview fidelity: exact glyph shapes (Garmin font root found)"
else
    echo "preview fidelity: stand-in typefaces for any face the registry has no exact match for; see wfb doctor"
fi

# -------------------------------------------------------- icon font ---------
say "icon font"
"${PY}" "${REPO_ROOT}/tools/fetch-icon-font.py"

# ------------------------------------------------------ system fonts --------
say "system fonts"
"${PY}" "${REPO_ROOT}/tools/fetch-system-fonts.py"

# ------------------------------------------------------------- env ----------
say "environment"
if [ "${IS_MAC}" = false ] && [ -f "${PERSIST}" ] && [ -w "${PERSIST}" ]; then
    grep -qF "CIQ_SDK=${SDK_ROOT}" "${PERSIST}" 2>/dev/null || {
        echo "export CIQ_SDK=${SDK_ROOT}" >> "${PERSIST}"
        echo "export PATH=\$PATH:${SDK_ROOT}/bin" >> "${PERSIST}"
        echo "appended CIQ_SDK and PATH to ${PERSIST}"
    }
    echo "CIQ_SDK and PATH are set in ${PERSIST}"
else
    # Quoted: the macOS SDK path has a space in it.
    echo "Add these two lines to your shell profile (~/.zshrc or ~/.bashrc):"
    echo ""
    echo "  export CIQ_SDK=\"${SDK_ROOT}\""
    echo "  export PATH=\"\$PATH:${SDK_ROOT}/bin\""
fi

# --------------------------------------------------------- python -----------
say "python environment"
VENV="${REPO_ROOT}/.venv"
if [ -x "${VENV}/bin/python" ]; then
    echo "already present at ${VENV}"
else
    if command -v uv >/dev/null 2>&1; then
        uv venv --python "${PY}" "${VENV}" >/dev/null
    else
        # Debian/Ubuntu split ensurepip out of the stdlib package.
        "${PY}" -m venv "${VENV}" 2>/dev/null || {
            echo "could not create ${VENV} with ${PY}" >&2
            [ "${IS_MAC}" = true ] ||
                echo "python3-venv is probably missing; install it with: sudo apt-get install -y python3-venv" >&2
            exit 1
        }
    fi
    echo "created ${VENV}"
fi
if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="${VENV}" uv pip install -q -r "${REPO_ROOT}/requirements-dev.txt"
else
    "${VENV}/bin/pip" install -q --upgrade pip
    "${VENV}/bin/pip" install -q -r "${REPO_ROOT}/requirements-dev.txt"
fi
echo "installed host dependencies"

# ---------------------------------------------------------- verify ----------
say "verify"
"${SDK_ROOT}/bin/monkeyc" --version 2>&1 | grep -v JAVA_TOOL_OPTIONS || true
echo "devices: $(ls "${DEVICES_DEST}" | tr '\n' ' ')"

"${VENV}/bin/python" -c "import ruamel.yaml, jsonschema, PIL, fontTools; print('host deps ok')"

cat <<EOF

Setup complete. Build an example end to end:

  ./wfb.py build examples/features/graph/face.yaml

Expected: three signed .prg files and a measured memory figure per device, with
no warnings. Then:

  ./wfb.py preview examples/features/graph/face.yaml    # PNG in build/preview/, no toolchain
  ./wfb.py doctor                              # what is installed, and what is missing

To run \`wfb\` from any folder, add this alias to your shell profile:

  alias wfb="${REPO_ROOT}/wfb.py"
EOF
