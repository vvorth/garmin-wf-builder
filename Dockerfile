# syntax=docker/dockerfile:1
#
# garmin-wf-builder -- the generator, as a container.
#
# Builds a YAML design into a signed, sideloadable Connect IQ .prg.  See
# docs/container.md for the full story; three things are worth knowing up front:
#
#   * The Connect IQ SDK downloads freely and is baked in, pruned to the ~26 MB
#     the compiler actually needs.
#   * The **device definitions cannot be downloaded** -- api.gcs.garmin.com
#     returns HTTP 401 behind Garmin SSO -- so they are mounted at run time.
#     They are also the user's own licensed copy of Garmin's files, which is a
#     second reason not to bake them into a distributable image.
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
#     -v wfb-keys:/keys \
#     garmin-wf-builder build examples/slice/face.yaml

ARG PYTHON_VERSION=3.13
ARG DEBIAN_SUITE=trixie

# Optional: a base64-encoded PEM certificate to trust, for networks behind a
# TLS-inspecting proxy.  Empty by default, in which case nothing changes.
#   docker build --build-arg EXTRA_CA_CERT_B64="$(base64 -w0 corp-ca.pem)" .
ARG EXTRA_CA_CERT_B64=""


# ---------------------------------------------------------------------------
# Stage 1 -- fetch the SDK and strip it to what `monkeyc` actually needs.
#
# docker/fetch-sdk.py does the work and explains the pruning.  It runs on the
# same Python base as the runtime stage, so this stage installs no packages at
# all and proxy settings are picked up from the standard environment variables.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE} AS sdk

ARG SDK_VERSION=9.2.0
ARG SDK_FILE=connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip
ARG SDK_BASE_URL=https://developer.garmin.com/downloads/connect-iq/sdks
ARG EXTRA_CA_CERT_B64

COPY docker/fetch-sdk.py /tmp/fetch-sdk.py

RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
    fi; \
    python /tmp/fetch-sdk.py "${SDK_BASE_URL}/${SDK_FILE}" /opt/ciq; \
    rm /tmp/fetch-sdk.py; \
    echo "${SDK_VERSION}" > /opt/ciq/SDK_VERSION; \
    test -x /opt/ciq/bin/monkeyc


# ---------------------------------------------------------------------------
# Stage 2 -- the runtime image.
#
# Composed rather than installed: the JRE is copied from an official Temurin
# image and Python comes from the base, so no package manager runs here.  That
# keeps the build reproducible and working on networks where the distribution
# mirrors are not reachable.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE}

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
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    WFB_DEVICES=/devices \
    WFB_KEY=/keys/developer_key.der

RUN set -eux; \
    if [ -n "${EXTRA_CA_CERT_B64}" ]; then \
        echo "${EXTRA_CA_CERT_B64}" | base64 -d >> /etc/ssl/certs/ca-certificates.crt; \
    fi; \
    java -version; \
    openssl version

WORKDIR /opt/wfb

# Dependencies first, so editing a source file does not re-resolve them.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY wfb/ ./wfb/
COPY runtime-lib/ ./runtime-lib/
COPY schema/ ./schema/
COPY examples/ ./examples/
COPY tests/ ./tests/
# The device-reference scrape: the only source for each panel's real palette size
# (64 colours, not the 256 that bitsPerPixel implies) and for per-device
# system-font pixel metrics.  Without it the palette and text-overflow lints
# degrade to "not checked" -- correct, but weaker than they need to be.
COPY docs/research/data/devices/ ./docs/research/data/devices/
COPY pytest.ini wfb.py README.md ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN set -eux; \
    chmod +x /usr/local/bin/entrypoint.sh; \
    printf '#!/bin/sh\nexec python /opt/wfb/wfb.py "$@"\n' > /usr/local/bin/wfb; \
    chmod +x /usr/local/bin/wfb; \
    mkdir -p /devices /keys /work; \
    chmod 1777 /keys /work; \
    useradd --uid 1000 --create-home --shell /bin/bash wfb; \
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
