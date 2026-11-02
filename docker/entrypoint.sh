#!/bin/sh
# Container entrypoint for garmin-wf-builder.
#
# Four things have to be arranged before `wfb` can run, and each of them is a
# trap that produces a confusing failure if it is left to chance (a fifth,
# Garmin's own fonts, is optional and only earns a notice -- see below):
#
#   1. The Connect IQ SDK is the user's own licensed copy, so it is not in the
#      image: it is mounted at /sdk (the SDK Manager's Sdks folder, or one SDK),
#      and a missing mount must be explained rather than surfacing as "no SDK".
#      `wfb` picks the SDK inside the mount and, since the mount is read-only
#      and `monkeyc` rewrites bin/default.jungle on every run, compiles from a
#      copy of the compiler's files in the cache (below).
#   2. The device definitions cannot be baked into the image either, so a
#      missing mount must be explained rather than surfacing as "Invalid device
#      id".
#   3. `monkeyc` finds those definitions through Java's `user.home`, which comes
#      from the *passwd entry* of the running uid -- not from $HOME.  Running
#      with `--user` therefore breaks device discovery unless user.home is set
#      explicitly, which is what JAVA_TOOL_OPTIONS does below.
#   4. The developer key signs the .prg.  Generating one silently into a
#      container layer would mean a different key on every run.
set -eu

# An escape hatch: anything that is obviously not a wfb subcommand runs directly,
# so `docker run IMAGE npm test` and `docker run IMAGE sh` behave as expected.
case "${1:-}" in
    sh|bash|java|node|npm)
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

# -------------------------------------------------------------- cache -------
# The compiler's copy and the device reference extracted from the SDK's pages
# live in $XDG_CACHE_HOME/wfb.  The image sets it to /cache; a volume there
# keeps both between runs (a second or so and 26 MB per run otherwise), and
# an unwritable /cache falls back to the home above.
if [ ! -w "${XDG_CACHE_HOME:-/cache}" ]; then
    export XDG_CACHE_HOME="${wfb_home}/.cache"
fi

# ------------------------------------------------------ what this needs -----
needs_devices=0
needs_sdk=0
needs_key=0
wants_fonts=0
case "${1:-}" in
    build)
        needs_devices=1
        needs_sdk=1
        needs_key=1
        wants_fonts=1
        for arg in "$@"; do
            [ "$arg" = "--no-compile" ] && needs_sdk=0 && needs_key=0
        done
        ;;
    export)
        needs_devices=1
        needs_sdk=1
        needs_key=1
        ;;
    preview|validate)
        needs_devices=1
        wants_fonts=1
        ;;
    studio)
        needs_devices=1
        wants_fonts=1
        # the editor's Build runs `wfb build`, which signs with this key
        needs_key=1
        # Inside the container the server must listen beyond its own
        # loopback for a published port to reach it, and it is reached by
        # whatever name the host, a proxy or an orchestrator gives it, which
        # the container cannot know. So it binds every address and answers
        # every name, and who can reach the port is up to how it is
        # published (docs/container.md, "The editor"). An explicit --host,
        # --allow-host or --allow-any-host replaces the matching default.
        has_host=0
        has_names=0
        for arg in "$@"; do
            case "$arg" in
                --host|--host=*) has_host=1 ;;
                --allow-host|--allow-host=*|--allow-any-host) has_names=1 ;;
            esac
        done
        if [ "$has_host" = 0 ]; then
            set -- "$@" --host 0.0.0.0
        fi
        if [ "$has_names" = 0 ]; then
            set -- "$@" --allow-any-host
        fi
        ;;
    devices|fonts)
        needs_devices=1
        ;;
    simulate)
        cat >&2 <<'EOF'
wfb: `simulate` is not available in this image.

The Connect IQ simulator is a GTK/WebKit GUI application. It is not installed
here, and it does not work headlessly in any case: on a base that supplies its
libraries natively it starts, then segfaults the moment a .prg is pushed to it,
and it does so with an unmodified SDK sample .prg -- so it is the environment,
not the built face.  See docs/limitations.md section 2.

Run `wfb simulate` on a desktop machine with the full SDK installed, or use

    wfb preview <design.yaml>

which renders from the same resolved geometry the generated code uses and needs
no display at all.
EOF
        exit 2
        ;;
esac

# The SDK Manager's folders, as a user mounts them (macOS paths; `wfb init`
# prints the Linux and Windows ones).
mounts() {
    cat <<EOF
  docker run --rm \\
    -v "\$PWD:/work" \\
    -v "\$HOME/Library/Application Support/Garmin/ConnectIQ/Sdks:${CIQ_SDK}:ro" \\
    -v "\$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:${WFB_DEVICES}:ro" \\
    -v "\$HOME/Library/Application Support/Garmin/ConnectIQ/Fonts:${WFB_FONTS}:ro" \\
    -v wfb-keys:/keys -v wfb-cache:/cache \\
    IMAGE ${1:-build} ...
EOF
}

# ---------------------------------------------------------------- sdk -------
# An SDK root has bin/monkeybrains.jar; the SDK Manager's Sdks folder holds
# one root per installed release.
has_sdk() {
    [ -f "${CIQ_SDK}/bin/monkeybrains.jar" ] && return 0
    for root in "${CIQ_SDK}"/*/; do
        [ -f "${root}bin/monkeybrains.jar" ] && return 0
    done
    return 1
}
if [ "${needs_sdk}" = "1" ] && ! has_sdk; then
    cat >&2 <<EOF
wfb: no Connect IQ SDK at ${CIQ_SDK}.

The SDK is licensed to you by Garmin's Connect IQ Developer Agreement, which
you accept by downloading it, so it is not in this image: mount the SDK
Manager's Sdks folder (or one SDK) from the computer that installed it.
\`docker run ... IMAGE init\` prints the steps for a computer that has not.

  macOS   ~/Library/Application Support/Garmin/ConnectIQ/Sdks
  Linux   ~/.Garmin/ConnectIQ/Sdks
  Windows %APPDATA%\\Garmin\\ConnectIQ\\Sdks

$(mounts "$1")

See docs/container.md.
EOF
    exit 2
fi

# ------------------------------------------------------------ devices -------
if [ "${needs_devices}" = "1" ]; then
    if [ ! -d "${WFB_DEVICES}" ] || [ -z "$(ls -A "${WFB_DEVICES}" 2>/dev/null)" ]; then
        cat >&2 <<EOF
wfb: no Connect IQ device definitions at ${WFB_DEVICES}.

They cannot be downloaded -- api.gcs.garmin.com returns HTTP 401 behind a Garmin
SSO login -- so they are not in this image and must be mounted from a machine
where the SDK Manager has installed them. \`docker run ... IMAGE init\` prints
the steps for a computer that has not.

  macOS   ~/Library/Application Support/Garmin/ConnectIQ/Devices
  Linux   ~/.Garmin/ConnectIQ/Devices
  Windows %APPDATA%\\Garmin\\ConnectIQ\\Devices

$(mounts "$1")

See docs/container.md.
EOF
        exit 2
    fi
fi

# --------------------------------------------------------------- fonts ------
# Optional, so a notice rather than an exit: without Garmin's own font files,
# text is measured and previewed with the registry's free stand-ins, and a
# preview quietly stops matching the device.  WFB_NO_GARMIN_FONTS=1 is the
# existing switch for choosing the stand-ins on purpose, and silences this.
if [ "${wants_fonts}" = "1" ] && [ "${WFB_NO_GARMIN_FONTS:-}" != "1" ] \
        && [ -z "$(ls -A "${WFB_FONTS}" 2>/dev/null)" ]; then
    cat >&2 <<EOF
wfb: no Garmin font files at ${WFB_FONTS}, so text is measured and previewed
     with free stand-ins that will not match the device exactly.  Mount the
     SDK Manager's Fonts directory to use the real ones:

  macOS   -v "\$HOME/Library/Application Support/Garmin/ConnectIQ/Fonts:${WFB_FONTS}:ro"
  Linux   -v "\$HOME/.Garmin/ConnectIQ/Fonts:${WFB_FONTS}:ro"

     or set WFB_NO_GARMIN_FONTS=1 to use the stand-ins without this notice.
     See docs/container.md.
EOF
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
    # Node's crypto, not openssl, which the slim Node image does not ship.
    node -e 'const { generateKeyPairSync } = require("node:crypto");
      const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 4096 });
      require("node:fs").writeFileSync(process.argv[1], privateKey.export({ type: "pkcs8", format: "der" }), { mode: 0o600 });' "${WFB_KEY}"
fi

exec wfb "$@"
