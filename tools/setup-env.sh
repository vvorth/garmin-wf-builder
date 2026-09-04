#!/usr/bin/env bash
# Rebuild the Connect IQ build environment for garmin-wf-builder.
#
# Idempotent: safe to re-run. Installs
#   - Connect IQ SDK 9.2.0        -> ~/ciq/sdks/9.2.0   (downloaded)
#   - a developer signing key     -> ~/ciq/developer_key.der (generated)
#   - device definitions          -> ~/.Garmin/ConnectIQ/Devices (copied)
#
# The SDK downloads unauthenticated. Device definitions CANNOT be downloaded
# (api.gcs.garmin.com returns HTTP 401, Garmin SSO); they must come from a host
# SDK Manager installation. See CLAUDE.md section 2.

set -euo pipefail

SDK_VERSION="9.2.0"
SDK_FILE="connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip"
SDK_URL="https://developer.garmin.com/downloads/connect-iq/sdks/${SDK_FILE}"
SDK_ROOT="${HOME}/ciq/sdks/${SDK_VERSION}"
KEY_DER="${HOME}/ciq/developer_key.der"
DEVICES_DEST="${HOME}/.Garmin/ConnectIQ/Devices"
PERSIST="/etc/sandbox-persistent.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n=== %s ===\n' "$1"; }

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
if [ -d "${DEVICES_DEST}" ] && [ -n "$(ls -A "${DEVICES_DEST}" 2>/dev/null)" ]; then
    echo "already installed: $(ls "${DEVICES_DEST}" | wc -l) devices"
else
    src=""
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
        cat >&2 <<'EOF'
ERROR: no device definitions found.

They cannot be downloaded -- api.gcs.garmin.com returns HTTP 401 (Garmin SSO).
Ask the user to run this on their macOS host, then re-run this script:

  cp -R ~/Library/Application\ Support/Garmin/ConnectIQ/Devices \
        ~/claude/garmin-watchface-protomolecule/.devices-import
EOF
        exit 1
    fi

    mkdir -p "${DEVICES_DEST}"
    cp -R "${src}"/* "${DEVICES_DEST}/"
    echo "installed $(ls "${DEVICES_DEST}" | wc -l) devices from ${src}"
fi

# ------------------------------------------------------------- env ----------
say "environment"
if [ -w "${PERSIST}" ] || [ -w "$(dirname "${PERSIST}")" ]; then
    grep -q "CIQ_SDK=${SDK_ROOT}" "${PERSIST}" 2>/dev/null || {
        echo "export CIQ_SDK=${SDK_ROOT}" >> "${PERSIST}"
        echo "export PATH=\$PATH:${SDK_ROOT}/bin" >> "${PERSIST}"
        echo "appended CIQ_SDK and PATH to ${PERSIST}"
    }
else
    echo "note: ${PERSIST} not writable; export these yourself:"
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

Setup complete. Build the Phase 2 slice end to end:

  ./.venv/bin/python wfb.py build examples/slice/face.yaml

Expected: three signed .prg files and a measured memory figure per device, with
no warnings. Then:

  ./.venv/bin/python wfb.py preview examples/slice/face.yaml   # PNG, no toolchain
  ./.venv/bin/python -m pytest                                 # the test suite
EOF
