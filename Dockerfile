# syntax=docker/dockerfile:1
#
# garmin-wf-builder -- the generator, as a container.
#
# Builds a YAML design into a signed, sideloadable Connect IQ .prg.  See
# docs/container.md for the full story; three things are worth knowing up front:
#
#   * The Connect IQ SDK downloads freely and is baked in, pruned to the ~24 MB
#     the compiler actually needs.  The Nerd Fonts icon font and the
#     registry's system-font stand-ins are downloaded the same way
#     (ts/tools/fetch-icon-font.ts, ts/tools/fetch-system-fonts.ts); neither
#     is part of the repository.
#   * The **device definitions cannot be downloaded** -- api.gcs.garmin.com
#     returns HTTP 401 behind Garmin SSO -- so they are mounted at run time.
#     They are also the user's own licensed copy of Garmin's files, which is a
#     second reason not to bake them into a distributable image.  Garmin's own
#     font files (optional, rank above the registry) mount the same way, at
#     `/fonts` -- see docs/container.md.
#   * The **simulator is not included**.  It is a GTK/WebKit GUI application that
#     segfaults on app load under Xvfb even with its libraries supplied, and does
#     so with an unmodified SDK sample.  `wfb preview` renders from the same
#     resolved geometry the generated code uses and needs no display.
#
# Build:
#   docker build -t garmin-wf-builder .
#
# Run:
#   docker run --rm \
#     -v "$PWD:/work" \
#     -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
#     -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Fonts:/fonts:ro" \
#     -v wfb-keys:/keys \
#     garmin-wf-builder build examples/features/graph/face.yaml
#
#   The /fonts mount is optional -- see docs/container.md.

ARG NODE_VERSION=24.21.0
ARG DEBIAN_SUITE=trixie

# Optional: a base64-encoded PEM certificate to trust, for networks behind a
# TLS-inspecting proxy.  Empty by default, in which case nothing changes.
#   docker build --build-arg EXTRA_CA_CERT_B64="$(base64 -w0 corp-ca.pem)" .
ARG EXTRA_CA_CERT_B64=""


# ---------------------------------------------------------------------------
# Stage 1 -- the TypeScript package in ts/, with its npm dependencies
# installed from the lock file.  Node runs the .ts sources directly (type
# stripping), so nothing is compiled.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-${DEBIAN_SUITE}-slim AS ts

ARG EXTRA_CA_CERT_B64

WORKDIR /opt/wfb/ts
COPY ts/package.json ts/package-lock.json ./
RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
        export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt; \
    fi; \
    npm ci --no-audit --no-fund
COPY ts/ ./


# ---------------------------------------------------------------------------
# Stage 2 -- fetch the SDK and strip it to what `monkeyc` needs, extract the
# SDK device reference from its pages, and fetch the icon font and the
# registry's system-font stand-ins, with the tools in ts/tools/.  The device
# definitions are not here (they mount at run time), so the needed font
# names come from the device reference: `--all` fetches for every device in
# it.
# ---------------------------------------------------------------------------
FROM ts AS sdk

# Node's fetch honours https_proxy and no_proxy only when asked to.
ENV NODE_USE_ENV_PROXY=1

ARG SDK_VERSION=9.2.0
ARG SDK_FILE=connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip
ARG SDK_BASE_URL=https://developer.garmin.com/downloads/connect-iq/sdks
ARG WFB_NERD_FONTS_BASE_URL=https://github.com/ryanoasis/nerd-fonts/releases/download
ARG WFB_FONTS_MIRROR=""
ARG EXTRA_CA_CERT_B64

RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
        export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt; \
    fi; \
    node tools/fetch-sdk.ts "${SDK_BASE_URL}/${SDK_FILE}" /opt/ciq --device-reference /tmp/sdk-doc; \
    echo "${SDK_VERSION}" > /opt/ciq/SDK_VERSION; \
    test -x /opt/ciq/bin/monkeyc; \
    WFB_NERD_FONTS_BASE_URL="${WFB_NERD_FONTS_BASE_URL}" node tools/fetch-icon-font.ts /opt/icons; \
    node tools/extract-device-reference.ts --sdk /tmp/sdk-doc \
        --sdk-version "$(cat /opt/ciq/bin/version.txt)" --out /opt/wfb/.cache/device-reference; \
    test -n "$(ls -A /opt/wfb/.cache/device-reference/devices)"; \
    WFB_FONTS_MIRROR="${WFB_FONTS_MIRROR}" node tools/fetch-system-fonts.ts --all /opt/system-fonts; \
    test -n "$(ls -A /opt/system-fonts)"; \
    rm -rf /tmp/sdk-doc


# ---------------------------------------------------------------------------
# Stage 3 -- the runtime image.
#
# Composed rather than installed: the JRE is copied from an official Temurin
# image onto the Node base, so no package manager runs here.  That keeps the
# build reproducible and working on networks where the distribution mirrors
# are not reachable.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-${DEBIAN_SUITE}-slim

ARG EXTRA_CA_CERT_B64

LABEL org.opencontainers.image.title="garmin-wf-builder" \
      org.opencontainers.image.description="Build a Garmin Connect IQ watch face from a YAML design" \
      org.opencontainers.image.source="https://github.com/vvorth/garmin-wf-builder"

# `monkeyc` is a Java program.  A headless JRE is enough: there is no GUI here
# and nothing is compiled from Java source.
COPY --from=eclipse-temurin:21-jre-noble /opt/java/openjdk /opt/java/openjdk
COPY --from=sdk /opt/ciq /opt/ciq

ENV JAVA_HOME=/opt/java/openjdk \
    CIQ_SDK=/opt/ciq \
    PATH=/opt/java/openjdk/bin:/opt/ciq/bin:$PATH \
    WFB_DEVICES=/devices \
    WFB_FONTS=/fonts \
    WFB_KEY=/keys/developer_key.der \
    WFB_CONTAINER=1

RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
    fi; \
    java -version; \
    node --version

WORKDIR /opt/wfb

COPY --from=ts /opt/wfb/ts/ ./ts/
COPY --from=sdk /opt/icons/ ./ts/assets/icons/
COPY --from=sdk /opt/system-fonts/ ./ts/assets/system-fonts/
COPY runtime-lib/ ./runtime-lib/
COPY schema/ ./schema/
COPY examples/ ./examples/
# The SDK device reference: the only source for each panel's real palette size
# (64 colours, not the 256 that bitsPerPixel implies) and for per-device
# system-font pixel metrics.  Extracted from the SDK in the stage above; wfb
# refuses to load devices without it.
COPY --from=sdk /opt/wfb/.cache/device-reference/ ./.cache/device-reference/
COPY wfb README.md ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN set -eux; \
    chmod +x /usr/local/bin/entrypoint.sh /opt/wfb/wfb; \
    ln -s /opt/wfb/wfb /usr/local/bin/wfb; \
    mkdir -p /devices /fonts /keys /work; \
    chmod 1777 /keys /work; \
    # The Node image's own uid 1000 is `node`; the image runs as uid 1000.
    # `monkeyc` regenerates bin/default.jungle on every run, so the SDK tree has
    # to be writable by whoever runs the container.  Giving the default uid
    # ownership covers the common case without making anything world-writable;
    # the entrypoint copies the tree for any other uid.
    chown -R 1000:1000 /opt/ciq

# The image writes only to the mounted project directory, a temporary home and
# /keys, so it runs as any uid.  1000 matches the common single-user host;
# override with `--user "$(id -u):$(id -g)"` when it does not.
USER 1000
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
