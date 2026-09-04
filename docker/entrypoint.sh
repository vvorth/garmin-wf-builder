#!/bin/sh
# Container entrypoint for garmin-wf-builder.
#
# Three things have to be arranged before `wfb` can run, and each of them is a
# trap that produces a confusing failure if it is left to chance:
#
#   1. The device definitions cannot be baked into the image, so a missing mount
#      must be explained rather than surfacing as "Invalid device id".
#   2. `monkeyc` finds those definitions through Java's `user.home`, which comes
#      from the *passwd entry* of the running uid -- not from $HOME.  Running
#      with `--user` therefore breaks device discovery unless user.home is set
#      explicitly, which is what JAVA_TOOL_OPTIONS does below.
#   3. The developer key signs the .prg.  Generating one silently into a
#      container layer would mean a different key on every run.
set -eu

# An escape hatch: anything that is obviously not a wfb subcommand runs directly,
# so `docker run IMAGE pytest` and `docker run IMAGE sh` behave as expected.
case "${1:-}" in
    sh|bash|python|python3|pytest|pip|java|monkeyc)
        exec "$@"
        ;;
esac

# --------------------------------------------------------------- home -------
# Pick a writable home, and point the JVM at it.  `monkeyc` looks for device
# definitions under <user.home>/.Garmin/ConnectIQ/Devices, so this is what makes
# the -v ...:/devices mount visible to the compiler.
wfb_home="${HOME:-}"
if [ -z "${wfb_home}" ] || [ ! -w "${wfb_home}" ]; then
    wfb_home=/tmp/wfb-home
fi
mkdir -p "${wfb_home}/.Garmin/ConnectIQ"
if [ ! -e "${wfb_home}/.Garmin/ConnectIQ/Devices" ]; then
    ln -s "${WFB_DEVICES}" "${wfb_home}/.Garmin/ConnectIQ/Devices"
fi
export HOME="${wfb_home}"
# Appended, not replaced, so a caller can still pass JVM options of their own.
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Duser.home=${wfb_home}"

# ----------------------------------------------------------------- sdk -----
# `monkeyc` regenerates $CIQ_SDK/bin/default.jungle from the installed device
# list on every invocation, replacing the file, so the directory must be
# writable.  The image hands /opt/ciq to uid 1000; anything else gets a private
# copy.  It is ~26 MB, so this costs a fraction of a second and only happens when
# the container is run as a different user.
if [ ! -w "${CIQ_SDK}/bin" ]; then
    private_sdk="${HOME}/ciq"
    if [ ! -x "${private_sdk}/bin/monkeyc" ]; then
        echo "wfb: ${CIQ_SDK} is not writable by uid $(id -u); copying it to ${private_sdk}" >&2
        mkdir -p "${private_sdk}"
        cp -a "${CIQ_SDK}/." "${private_sdk}/"
    fi
    CIQ_SDK="${private_sdk}"
    export CIQ_SDK
    PATH="${private_sdk}/bin:${PATH}"
    export PATH
fi

# ------------------------------------------------------ what this needs -----
needs_devices=0
needs_key=0
case "${1:-}" in
    build)
        needs_devices=1
        needs_key=1
        for arg in "$@"; do
            [ "$arg" = "--no-compile" ] && needs_key=0
        done
        ;;
    preview|validate|devices)
        needs_devices=1
        ;;
    simulate)
        cat >&2 <<'EOF'
wfb: `simulate` is not available in this image.

The Connect IQ simulator is a GTK/WebKit GUI application. It is not installed
here, and it does not work headlessly in any case: with its libraries supplied it
still segfaults on app load under Xvfb with software OpenGL, and it does so with
an unmodified SDK sample .prg -- so it is the environment, not the built face.

Run `wfb simulate` on a desktop machine with the full SDK installed, or use

    wfb preview <design.yaml>

which renders from the same resolved geometry the generated code uses and needs
no display at all.
EOF
        exit 2
        ;;
esac

# ------------------------------------------------------------ devices -------
if [ "${needs_devices}" = "1" ]; then
    if [ ! -d "${WFB_DEVICES}" ] || [ -z "$(ls -A "${WFB_DEVICES}" 2>/dev/null)" ]; then
        cat >&2 <<EOF
wfb: no Connect IQ device definitions at ${WFB_DEVICES}.

They cannot be downloaded -- api.gcs.garmin.com returns HTTP 401 behind a Garmin
SSO login -- so they are not in this image and must be mounted from a machine
where the SDK Manager has installed them:

  macOS   ~/Library/Application Support/Garmin/ConnectIQ/Devices
  Linux   ~/.Garmin/ConnectIQ/Devices

  docker run --rm \\
    -v "\$PWD:/work" \\
    -v "\$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \\
    IMAGE ${1:-build} ...

See docs/container.md.
EOF
        exit 2
    fi
fi

# ---------------------------------------------------------------- key -------
if [ "${needs_key}" = "1" ] && [ ! -f "${WFB_KEY}" ]; then
    key_dir=$(dirname "${WFB_KEY}")
    if ! mkdir -p "${key_dir}" 2>/dev/null || [ ! -w "${key_dir}" ]; then
        WFB_KEY="${HOME}/developer_key.der"
        key_dir="${HOME}"
        export WFB_KEY
        echo "wfb: /keys is not writable; using a throwaway key at ${WFB_KEY}" >&2
        echo "     mount a volume at /keys to keep one key across builds." >&2
    fi
    echo "wfb: generating a 4096-bit developer signing key at ${WFB_KEY}" >&2
    pem="${key_dir}/developer_key.pem"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "${pem}" 2>/dev/null
    openssl pkcs8 -topk8 -inform PEM -outform DER -in "${pem}" -out "${WFB_KEY}" -nocrypt
    chmod 600 "${pem}" "${WFB_KEY}" 2>/dev/null || true
fi

exec wfb "$@"
