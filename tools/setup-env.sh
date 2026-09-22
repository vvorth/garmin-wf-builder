#!/usr/bin/env bash
# Rebuild the Connect IQ build environment for garmin-wf-builder.
#
# Idempotent: safe to re-run. Installs
#   - Connect IQ SDK 9.2.0        -> ~/ciq/sdks/9.2.0   (downloaded)
#   - a developer signing key     -> ~/ciq/developer_key.der (generated)
#   - device definitions          -> ~/.Garmin/ConnectIQ/Devices (copied)
#   - Garmin's own font files     -> ~/.Garmin/ConnectIQ/Fonts (copied from
#                                    vendor/fonts/, if present -- optional)
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
SDK_ROOT="${HOME}/ciq/sdks/${SDK_VERSION}"
KEY_DER="${HOME}/ciq/developer_key.der"
DEVICES_DEST="${HOME}/.Garmin/ConnectIQ/Devices"
FONTS_DEST="${HOME}/.Garmin/ConnectIQ/Fonts"
# Only the development sandbox has this file; everywhere else the exports are
# printed for the user's shell profile instead.
PERSIST="/etc/sandbox-persistent.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n=== %s ===\n' "$1"; }

# ------------------------------------------------------ prerequisites --------
say "prerequisites"
missing=()
for tool in curl unzip openssl python3 java; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
done
if [ "${#missing[@]}" -gt 0 ]; then
    cat >&2 <<EOF
ERROR: missing required tools: ${missing[*]}

Install them with your package manager and re-run this script. On Debian/Ubuntu:

  sudo apt-get install -y curl unzip openssl python3 python3-venv openjdk-21-jre-headless

java runs Garmin's compiler (monkeyc); Java 21 or newer is tested.
EOF
    exit 1
fi
echo "found: curl unzip openssl python3 java"

# ---------------------------------------------------------------- SDK --------
say "Connect IQ SDK ${SDK_VERSION}"
if [ -x "${SDK_ROOT}/bin/monkeyc" ]; then
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
    "${REPO_ROOT}/../garmin-watchface-protomolecule/.devices-import" \
    "${HOME}/Library/Application Support/Garmin/ConnectIQ/Devices"
do
    if [ -d "${cand}" ] && [ -n "$(ls -A "${cand}" 2>/dev/null)" ]; then
        src="${cand}"; break
    fi
done

if [ -z "${src}" ]; then
    if [ "${dest_had_devices}" = true ]; then
        echo "already installed: $(ls "${DEVICES_DEST}" | wc -l) devices"
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
        echo "installed $(ls "${DEVICES_DEST}" | wc -l) devices from ${src}"
    elif [ "${#added[@]}" -gt 0 ]; then
        echo "installed ${#added[@]} new device(s) from ${src}: ${added[*]}"
    else
        echo "already installed: $(ls "${DEVICES_DEST}" | wc -l) devices"
    fi
fi

# ------------------------------------------------- Garmin's own fonts -------
say "Garmin font files (optional)"
VENDOR_FONTS="${REPO_ROOT}/vendor/fonts"
if [ -d "${VENDOR_FONTS}" ] && [ -n "$(ls -A "${VENDOR_FONTS}" 2>/dev/null)" ]; then
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
        echo "already installed: $(ls "${FONTS_DEST}" | wc -l) entries in ${FONTS_DEST}"
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
python3 "${REPO_ROOT}/tools/fetch-icon-font.py"

# ------------------------------------------------------ system fonts --------
say "system fonts"
python3 "${REPO_ROOT}/tools/fetch-system-fonts.py"

# ------------------------------------------------------------- env ----------
say "environment"
if [ -f "${PERSIST}" ] && [ -w "${PERSIST}" ]; then
    grep -q "CIQ_SDK=${SDK_ROOT}" "${PERSIST}" 2>/dev/null || {
        echo "export CIQ_SDK=${SDK_ROOT}" >> "${PERSIST}"
        echo "export PATH=\$PATH:${SDK_ROOT}/bin" >> "${PERSIST}"
        echo "appended CIQ_SDK and PATH to ${PERSIST}"
    }
    echo "CIQ_SDK and PATH are set in ${PERSIST}"
else
    echo "Add these two lines to your shell profile (~/.bashrc or ~/.zshrc):"
    echo ""
    echo "  export CIQ_SDK=${SDK_ROOT}"
    echo "  export PATH=\$PATH:${SDK_ROOT}/bin"
fi

# --------------------------------------------------------- python -----------
say "python environment"
VENV="${REPO_ROOT}/.venv"
if [ -x "${VENV}/bin/python" ]; then
    echo "already present at ${VENV}"
else
    if command -v uv >/dev/null 2>&1; then
        uv venv "${VENV}" >/dev/null
    else
        # Debian/Ubuntu split ensurepip out of the stdlib package.
        python3 -m venv "${VENV}" 2>/dev/null || {
            echo "python3-venv is missing; install it with:" >&2
            echo "  sudo apt-get install -y python3-venv" >&2
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
