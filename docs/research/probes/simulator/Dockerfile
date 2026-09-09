# syntax=docker/dockerfile:1
#
# Simulator-in-a-container probe.  **Not the shipping image** -- see the
# Dockerfile at the repo root for that, and README.md here for what this one
# proved.
#
# The question: the shipping image leaves the Connect IQ simulator out because
# it links against libwebkit2gtk-4.0, libsoup-2.4 and libjavascriptcoregtk-4.0,
# which current distributions no longer package.  Ubuntu 22.04 (jammy) still
# does.  So: does supplying them natively make the simulator work headlessly?
#
# The answer is no, and the failure is not the one the docs used to describe.
# The simulator starts and opens its window under Xvfb, then segfaults the
# moment a .prg is pushed to it with monkeydo -- on a worker thread inside its
# own stripped binary, with libGL never loaded at all.
#
# Two differences from the shipping image are what make this a probe rather
# than a variant of it:
#
#   * the SDK is unzipped whole rather than pruned by docker/fetch-sdk.py,
#     because the pruning deliberately drops bin/simulator;
#   * the base is jammy rather than the shipping image's Python/Debian, purely
#     for the three libraries above.
#
# Build and run:  see README.md.

FROM ubuntu:22.04 AS sdk

ARG SDK_FILE=connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip
ARG SDK_BASE_URL=https://developer.garmin.com/downloads/connect-iq/sdks

RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends unzip curl ca-certificates; \
    curl -fsSL "${SDK_BASE_URL}/${SDK_FILE}" -o /tmp/sdk.zip; \
    unzip -q -o /tmp/sdk.zip -d /opt/ciq; \
    rm /tmp/sdk.zip; \
    test -x /opt/ciq/bin/monkeyc; \
    test -x /opt/ciq/bin/simulator


FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# libwebkit2gtk-4.0-37 pulls libjavascriptcoregtk-4.0-18 with it.  x11-utils,
# x11-apps and gdb are the observation tools: without them a crash is
# indistinguishable from a window that never appeared.
RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends \
        libwebkit2gtk-4.0-37 libsoup2.4-1 libgtk-3-0 libsecret-1-0 libusb-1.0-0 \
        libxxf86vm1 libsm6 libatk1.0-0 libxkbcommon0 libgl1-mesa-dri \
        xvfb x11-utils x11-apps gdb ca-certificates fonts-dejavu-core; \
    rm -rf /var/lib/apt/lists/*

COPY --from=eclipse-temurin:21-jre-jammy /opt/java/openjdk /opt/java/openjdk
COPY --from=sdk /opt/ciq /opt/ciq

ENV JAVA_HOME=/opt/java/openjdk \
    CIQ_SDK=/opt/ciq \
    PATH=/opt/java/openjdk/bin:/opt/ciq/bin:$PATH

# Every one of the simulator's shared libraries must resolve, or the probe is
# testing the wrong thing.  This fails the build if a base image ever regresses.
RUN set -eux; \
    ! ldd /opt/ciq/bin/simulator 2>&1 | grep 'not found'

WORKDIR /probe
