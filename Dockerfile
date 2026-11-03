# syntax=docker/dockerfile:1
#
# garmin-wf-builder -- the generator, as a container.
#
# Builds a YAML design into a signed, sideloadable Connect IQ .prg.  See
# docs/container.md for the full story; three things are worth knowing up front:
#
#   * The **Connect IQ SDK is not in the image.**  Garmin licenses it to the
#     developer who downloads it (the Connect IQ Developer Agreement, accepted
#     by downloading, forbids hosting or redistributing it), so it is mounted
#     at run time: the SDK Manager's whole folder at /vendor (its Sdks,
#     Devices and Fonts inside), or its Sdks folder, or one SDK, at
#     /vendor/Sdks.  The
#     image holds everything else a build needs: Node, a headless JRE, `wfb`,
#     the Nerd Fonts icon font and the free stand-ins for Garmin's system fonts
#     (downloaded in the build by ts/tools/fetch-icon-font.ts and
#     ts/tools/fetch-system-fonts.ts; neither is part of the repository).
#   * The **device definitions cannot be downloaded** -- api.gcs.garmin.com
#     returns HTTP 401 behind Garmin SSO -- and are the user's licensed copy too,
#     so they are mounted at run time, at /vendor/Devices.  Garmin's own font
#     files (optional, rank above the registry) mount the same way, at
#     /vendor/Fonts.  The one /vendor mount of the SDK Manager's folder covers
#     all three; the entrypoint also takes the older /sdk, /devices and /fonts.
#   * The **simulator is not included**.  It is a GTK/WebKit GUI application that
#     segfaults on app load under Xvfb even with its libraries supplied, and does
#     so with an unmodified SDK sample.  `wfb preview` renders from the same
#     resolved geometry the generated code uses and needs no display.
#
# Build:
#   docker build -t garmin-wf-builder .
#
# Run (macOS path; `docker run --rm garmin-wf-builder init` prints the others):
#   docker run --rm \
#     -v "$PWD:/work" \
#     -v "$HOME/Library/Application Support/Garmin/ConnectIQ:/vendor:ro" \
#     -v wfb-keys:/keys -v wfb-cache:/cache \
#     garmin-wf-builder build examples/features/graph/face.yaml
#
#   The /cache mount is optional -- see docs/container.md.

ARG NODE_VERSION=24.22.1
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
# Stage 2 -- fetch the icon font and the registry's system-font stand-ins
# with the tools in ts/tools/, each checked against its pinned hash.  There
# are no device definitions and no SDK at image build time, so every font the
# registry knows is fetched (`--registry`) rather than the ones installed
# devices need.
# ---------------------------------------------------------------------------
FROM ts AS fonts

# Node's fetch honours https_proxy and no_proxy only when asked to.
ENV NODE_USE_ENV_PROXY=1

ARG WFB_NERD_FONTS_BASE_URL=https://github.com/ryanoasis/nerd-fonts/releases/download
ARG WFB_FONTS_MIRROR=""
ARG EXTRA_CA_CERT_B64

RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
        export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt; \
    fi; \
    WFB_NERD_FONTS_BASE_URL="${WFB_NERD_FONTS_BASE_URL}" node tools/fetch-icon-font.ts /opt/icons; \
    WFB_FONTS_MIRROR="${WFB_FONTS_MIRROR}" node tools/fetch-system-fonts.ts --registry /opt/system-fonts; \
    test -n "$(ls -A /opt/system-fonts)"


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

# /vendor is the SDK Manager's folder as mounted, with its Sdks, Devices and
# Fonts inside: CIQ_SDK is where `wfb` looks for the SDK (that folder, or one
# SDK root), WFB_DEVICES and WFB_FONTS for the device definitions and Garmin's
# fonts; XDG_CACHE_HOME is where it keeps the compiler's writable copy and the
# device reference it extracts from the SDK's pages.
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    WFB_VENDOR=/vendor \
    CIQ_SDK=/vendor/Sdks \
    XDG_CACHE_HOME=/cache \
    WFB_DEVICES=/vendor/Devices \
    WFB_FONTS=/vendor/Fonts \
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
COPY --from=fonts /opt/icons/ ./ts/assets/icons/
COPY --from=fonts /opt/system-fonts/ ./ts/assets/system-fonts/
COPY runtime-lib/ ./runtime-lib/
COPY schema/ ./schema/
COPY examples/ ./examples/
# The Help popup in `wfb studio` serves these (docs/research/ is left out: 60 MB of records).
COPY docs/ ./docs/
COPY wfb README.md LICENSE ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN set -eux; \
    chmod +x /usr/local/bin/entrypoint.sh /opt/wfb/wfb; \
    ln -s /opt/wfb/wfb /usr/local/bin/wfb; \
    mkdir -p /vendor/Sdks /vendor/Devices /vendor/Fonts /sdk /devices /fonts /keys /cache /work; \
    chmod 1777 /keys /cache /work

# The image writes only to the mounted project directory, the cache, a
# temporary home and /keys, so it runs as any uid.  1000 (the Node image's
# own `node` user) matches the common single-user host; override with
# `--user "$(id -u):$(id -g)"` when it does not.
USER 1000
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# With no arguments the image serves the editor (docs/container.md, "The editor");
# any other arguments are a `wfb` command line instead.
CMD ["studio"]
