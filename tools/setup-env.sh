#!/usr/bin/env bash
# Rebuild the Connect IQ build environment for garmin-wf-builder.
#
# Idempotent: safe to re-run. Runs on Linux and macOS. Installs
#   - the newest Connect IQ SDK   -> ~/ciq/sdks/<version> (Linux: downloaded,
#     (SDK_VERSION=x.y.z pins one)   newest per Garmin's sdks.json; macOS: the
#                                    newest the SDK Manager installed)
#   - a developer signing key     -> ~/ciq/developer_key.der (generated)
#   - device definitions          -> ~/.Garmin/ConnectIQ/Devices (Linux: copied;
#                                    macOS: read in place from the SDK Manager's
#                                    ~/Library/Application Support/Garmin/ConnectIQ)
#   - Garmin's own font files     -> ~/.Garmin/ConnectIQ/Fonts (Linux: copied
#                                    from vendor/fonts/, if present -- optional;
#                                    macOS: read in place, like the devices)
#   - Node 24 (if no Node on PATH -> ~/.local/share/wfb/node-v<version>
#     strips TypeScript types)       (downloaded, checked against SHASUMS256),
#                                    and ts/'s npm dependencies
#   - the SDK device reference    -> .cache/device-reference/ (extracted from
#                                    the SDK's own pages)
#   - the Nerd Fonts icon font    -> ts/assets/icons/ (downloaded, hash-checked)
#   - the system fonts registry   -> ts/assets/system-fonts/ (downloaded,
#                                    hash-checked; docs/lore/toolchain.md)
#
# The SDK downloads unauthenticated. Device definitions CANNOT be downloaded
# (api.gcs.garmin.com returns HTTP 401, Garmin SSO); they must come from a host
# SDK Manager installation. See docs/guide/getting-started.md, "Step 1: get the device definitions".

set -euo pipefail

# Unset, the newest SDK; SDK_VERSION=x.y.z in the environment pins one.
SDK_VERSION="${SDK_VERSION:-}"
SDK_BASE_URL="https://developer.garmin.com/downloads/connect-iq/sdks"
KEY_DER="${HOME}/ciq/developer_key.der"

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
if [ "${#missing[@]}" -gt 0 ]; then
    if [ "${IS_MAC}" = true ]; then
        cat >&2 <<EOF
ERROR: missing required tools: ${missing[*]}

Install them with Homebrew (https://brew.sh) and re-run this script:

  brew install --cask temurin@21

java runs Garmin's compiler (monkeyc); Java 21 or newer is tested.
EOF
    else
        cat >&2 <<EOF
ERROR: missing required tools: ${missing[*]}

Install them with your package manager and re-run this script. On Debian/Ubuntu:

  sudo apt-get install -y curl unzip openssl openjdk-21-jre-headless

java runs Garmin's compiler (monkeyc); Java 21 or newer is tested.
EOF
    fi
    exit 1
fi
echo "found: ${tools[*]} java"

# ---------------------------------------------------------------- SDK --------
say "Connect IQ SDK ${SDK_VERSION:-(newest)}"
# The newest of a list of names that differ only from a version on: sort -V.
newest() { sort -V | tail -n 1; }
if [ "${IS_MAC}" = true ]; then
    # Garmin publishes no unauthenticated macOS SDK download this script has
    # checked, so on a Mac the SDK Manager's own install is used in place:
    # Sdks/connectiq-sdk-mac-<version>-<date>-<hash>/.
    SDK_ROOT=""
    cand="$(ls "${GARMIN_HOME}/Sdks" 2>/dev/null | grep "^connectiq-sdk-mac-${SDK_VERSION:+${SDK_VERSION}-}" | newest || true)"
    [ -n "${cand}" ] && [ -x "${GARMIN_HOME}/Sdks/${cand}/bin/monkeyc" ] && SDK_ROOT="${GARMIN_HOME}/Sdks/${cand}"
    if [ -z "${SDK_ROOT}" ]; then
        installed="$(ls "${GARMIN_HOME}/Sdks" 2>/dev/null | tr '\n' ' ' || true)"
        cat >&2 <<EOF
ERROR: Connect IQ SDK ${SDK_VERSION:-(any version)} is not installed.

Install it with Garmin's Connect IQ SDK Manager
(https://developer.garmin.com/connect-iq/sdk/): sign in, open the SDK tab and
download ${SDK_VERSION:-the newest}. It lands in
  ${GARMIN_HOME}/Sdks/
where this script looks for it. Installed there now:
  ${installed:-(none)}
EOF
        exit 1
    fi
    echo "found at ${SDK_ROOT}"
else
    # Garmin's catalogue of releases; offline, the newest SDK already here.
    SDK_FILE="$(curl -fsSL --retry 3 "${SDK_BASE_URL}/sdks.json" 2>/dev/null \
        | grep -o "connectiq-sdk-lin-${SDK_VERSION:+${SDK_VERSION}-}[^\"]*\.zip" | newest || true)"
    if [ -n "${SDK_FILE}" ]; then
        SDK_VERSION="$(echo "${SDK_FILE}" | sed 's/^connectiq-sdk-lin-\([0-9.]*\)-.*/\1/')"
    elif [ -z "${SDK_VERSION}" ]; then
        SDK_VERSION="$(ls "${HOME}/ciq/sdks" 2>/dev/null | newest || true)"
        [ -n "${SDK_VERSION}" ] && echo "note: ${SDK_BASE_URL}/sdks.json unreachable; using the newest installed SDK"
    fi
    if [ -z "${SDK_VERSION}" ]; then
        echo "ERROR: ${SDK_BASE_URL}/sdks.json is unreachable and no SDK is installed in ~/ciq/sdks." >&2
        exit 1
    fi
    SDK_ROOT="${HOME}/ciq/sdks/${SDK_VERSION}"
    if [ -x "${SDK_ROOT}/bin/monkeyc" ]; then
        echo "already installed at ${SDK_ROOT}"
    elif [ -z "${SDK_FILE}" ]; then
        echo "ERROR: SDK ${SDK_VERSION} is not installed and ${SDK_BASE_URL}/sdks.json lists no Linux SDK for it." >&2
        exit 1
    else
        mkdir -p "${SDK_ROOT}"
        tmp="$(mktemp -d)"
        echo "downloading ${SDK_FILE} (~204 MB)…"
        curl -fSL --retry 3 -o "${tmp}/sdk.zip" "${SDK_BASE_URL}/${SDK_FILE}"
        echo "extracting…"
        unzip -q -o "${tmp}/sdk.zip" -d "${SDK_ROOT}"
        rm -rf "${tmp}"
        chmod +x "${SDK_ROOT}"/bin/* 2>/dev/null || true
        echo "installed to ${SDK_ROOT}"
    fi
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
    # (ts/src/fonts/node.ts's garminFontRoot), so nothing is copied.
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
# -- not just that it is optional. Mirrors garmin_font_root's
# own priority closely enough for a status line: vendor/fonts/ (just handled
# above) or FONTS_DEST (already installed from a previous run, or placed
# there by hand) either one means "found".
if [ -n "$(ls -A "${VENDOR_FONTS}" 2>/dev/null)" ] || [ -n "$(ls -A "${FONTS_DEST}" 2>/dev/null)" ]; then
    echo "preview fidelity: exact glyph shapes (Garmin font root found)"
else
    echo "preview fidelity: stand-in typefaces for any face the registry has no exact match for; see wfb doctor"
fi

# ----------------------------------------------------------- node -----------
say "node"
# The TypeScript compiler in ts/ runs its .ts sources directly, which needs a
# Node that strips types: an official build of 22.18+ or 24. A distribution
# build may lack it (Ubuntu's 22.22 fails with ERR_NO_TYPESCRIPT), so the
# check runs a .ts file rather than reading the version.
NODE_VERSION="24.21.0"
NODE_HOME="${HOME}/.local/share/wfb/node-v${NODE_VERSION}"
strips_types() {
    local probe
    probe="$(mktemp -d)"
    printf 'const n: number = 1;\nprocess.exit(n - 1);\n' > "${probe}/probe.ts"
    "$1" "${probe}/probe.ts" >/dev/null 2>&1
    local ok=$?
    rm -rf "${probe}"
    return ${ok}
}
NODE=""
for cand in "${NODE_HOME}/bin/node" "$(command -v node 2>/dev/null || true)"; do
    if [ -n "${cand}" ] && [ -x "${cand}" ] && strips_types "${cand}"; then
        NODE="${cand}"
        break
    fi
done
if [ -z "${NODE}" ]; then
    case "$(uname -s)-$(uname -m)" in
        Linux-x86_64)  node_platform="linux-x64" ;;
        Linux-aarch64) node_platform="linux-arm64" ;;
        Darwin-arm64)  node_platform="darwin-arm64" ;;
        Darwin-x86_64) node_platform="darwin-x64" ;;
        *) echo "ERROR: no Node ${NODE_VERSION} build for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
    esac
    node_file="node-v${NODE_VERSION}-${node_platform}.tar.gz"
    node_url="https://nodejs.org/dist/v${NODE_VERSION}"
    work="$(mktemp -d)"
    curl -fsSL -o "${work}/${node_file}" "${node_url}/${node_file}"
    curl -fsSL -o "${work}/SHASUMS256.txt" "${node_url}/SHASUMS256.txt"
    expected="$(grep " ${node_file}\$" "${work}/SHASUMS256.txt" | cut -d' ' -f1)"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "${work}/${node_file}" | cut -d' ' -f1)"
    else
        actual="$(shasum -a 256 "${work}/${node_file}" | cut -d' ' -f1)"
    fi
    if [ -z "${expected}" ] || [ "${expected}" != "${actual}" ]; then
        echo "ERROR: ${node_file} does not match nodejs.org's SHASUMS256.txt" >&2
        exit 1
    fi
    mkdir -p "${NODE_HOME}"
    tar -xzf "${work}/${node_file}" -C "${NODE_HOME}" --strip-components=1
    rm -rf "${work}"
    NODE="${NODE_HOME}/bin/node"
    echo "installed Node ${NODE_VERSION} at ${NODE_HOME}"
fi
NODE_BIN="$(dirname "${NODE}")"
echo "node $("${NODE}" --version) at ${NODE}: strips types"
if [ "${NODE_BIN}" = "${NODE_HOME}/bin" ]; then
    if [ "${IS_MAC}" = false ] && [ -f "${PERSIST}" ] && [ -w "${PERSIST}" ]; then
        grep -qF "${NODE_HOME}/bin" "${PERSIST}" 2>/dev/null || {
            # Prepended: it must win over a distribution node on PATH.
            echo "export PATH=${NODE_HOME}/bin:\$PATH" >> "${PERSIST}"
            echo "prepended ${NODE_HOME}/bin to PATH in ${PERSIST}"
        }
    else
        echo "Add this line to your shell profile (~/.zshrc or ~/.bashrc):"
        echo ""
        echo "  export PATH=\"${NODE_HOME}/bin:\$PATH\""
    fi
fi
(cd "${REPO_ROOT}/ts" && PATH="${NODE_BIN}:${PATH}" npm ci --silent --no-audit --no-fund)
echo "installed ts/ dependencies"

# --------------------------------------------- SDK device reference ---------
# Derived data, never committed: extracted from the SDK's own
# doc/docs/Device_Reference pages into .cache/device-reference/. wfb reads each
# panel's palette size and per-font pixel metrics from it, and the system-fonts
# step below reads which font names each device needs. Regenerated only when
# missing or extracted from a different SDK (source.txt names the one it came
# from, sdk-version.txt its release, which wfb build compares).
say "SDK device reference"
REF_DEST="${REPO_ROOT}/.cache/device-reference"
REF_SRC="$(cd "${SDK_ROOT}/doc/docs/Device_Reference" 2>/dev/null && pwd -P || true)"
if [ -z "${REF_SRC}" ]; then
    echo "ERROR: no doc/docs/Device_Reference in ${SDK_ROOT}; the device reference is extracted from it." >&2
    exit 1
fi
if [ -f "${REF_DEST}/source.txt" ] && [ "$(cat "${REF_DEST}/source.txt")" = "${REF_SRC}" ] \
        && [ -f "${REF_DEST}/sdk-version.txt" ]; then
    echo "up to date: $(count "${REF_DEST}/devices") devices, from ${REF_SRC}"
else
    "${NODE}" "${REPO_ROOT}/ts/tools/extract-device-reference.ts" --sdk "${SDK_ROOT}"
fi

# -------------------------------------------------------- icon font ---------
say "icon font"
"${NODE}" "${REPO_ROOT}/ts/tools/fetch-icon-font.ts"

# ------------------------------------------------------ system fonts --------
say "system fonts"
"${NODE}" "${REPO_ROOT}/ts/tools/fetch-system-fonts.ts"

# ------------------------------------------------------------- env ----------
say "environment"
if [ "${IS_MAC}" = false ] && [ -f "${PERSIST}" ] && [ -w "${PERSIST}" ]; then
    grep -qF "CIQ_SDK=${SDK_ROOT}" "${PERSIST}" 2>/dev/null || {
        # A newer SDK replaces the old one's lines, so PATH finds one monkeyc.
        sed -i '/^export CIQ_SDK=/d; \#^export PATH=.*/ciq/sdks/[^/]*/bin$#d' "${PERSIST}"
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

# ---------------------------------------------------------- verify ----------
say "verify"
"${SDK_ROOT}/bin/monkeyc" --version 2>&1 | grep -v JAVA_TOOL_OPTIONS || true
echo "devices: $(ls "${DEVICES_DEST}" | tr '\n' ' ')"

(cd "${REPO_ROOT}/ts" && PATH="${NODE_BIN}:${PATH}" npm run --silent typecheck) && echo "ts/ typechecks"

cat <<EOF

Setup complete. Build an example end to end:

  ./wfb build examples/features/graph/face.yaml

Expected: three signed .prg files and a measured memory figure per device, with
no warnings. Then:

  ./wfb preview examples/features/graph/face.yaml    # PNG in build/preview/, no toolchain
  ./wfb doctor                              # what is installed, and what is missing

To run \`wfb\` from any folder, add this alias to your shell profile:

  alias wfb="${REPO_ROOT}/wfb"
EOF
