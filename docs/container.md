# Running garmin-wf-builder as a container

A container image that turns a YAML design into a signed, sideloadable Connect IQ
`.prg` — with no Garmin SDK, no Java and no Node set up on the host.

```sh
docker build -t garmin-wf-builder .

docker run --rm \
  -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  garmin-wf-builder build examples/features/graph/face.yaml
```

(a `-v "<Fonts dir>:/fonts:ro"` mount is also accepted, and optional — see
"Garmin's own font files" below.)

```
generated  /work/build/graph
built      graph-fenix8solar47mm.prg  3,417 B / 131,072 B (2.6%)
built      graph-fenix8solar51mm.prg  3,418 B / 131,072 B (2.6%)
built      graph-fr955.prg  3,417 B / 131,072 B (2.6%)
```

The generated Monkey C is byte-identical to a host build of the same design.

---

## Requirements

| | |
|---|---|
| **Docker** | any recent version, or Podman with `podman` in place of `docker`. On macOS it is tested with [OrbStack](https://orbstack.dev) |
| **Disk** | ~600 MB for the image; the build downloads the 204 MB SDK once |
| **Device definitions** | **required, and must come from you** — see below |
| **Garmin's own font files** | optional — see below |
| **Network** | only at image build time, for the SDK, the icon and system fonts, and the npm packages |
| **Architecture** | verified on `linux/amd64`. The pruned SDK contains **no native binaries** — only shell scripts and JVM bytecode — so `linux/arm64` should work, but has not been tested |

### The one thing you have to supply: device definitions

The image cannot contain them, for two independent reasons.

**They cannot be downloaded.** The SDK Manager fetches them from
`api.gcs.garmin.com/ciq-product-onboarding/devices`, which returns **HTTP 401** —
it needs a Garmin SSO login that cannot be completed non-interactively. Without
them every device-targeted build fails with `Invalid device id specified`.

**They are your licensed copy of Garmin's files.** Baking them into a
distributable image would be redistributing them, which is a question this
project has not cleared.

So install the SDK Manager once on a desktop machine, let it download the devices
you target, and mount that directory read-only:

| Host | Path |
|---|---|
| macOS | `~/Library/Application Support/Garmin/ConnectIQ/Devices` |
| Linux | `~/.Garmin/ConnectIQ/Devices` |
| Windows | `%APPDATA%\Garmin\ConnectIQ\Devices` |

```sh
-v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro"
```

If the mount is missing, the container says so and points here rather than
failing deep inside a build.

### Garmin's own font files (optional)

Text measurement and previews use free stand-ins for Garmin's system fonts
by default (`ts/src/data/font-registry.json`). If the same SDK Manager
install
that provided the device definitions also has Garmin's own font files —
under its `Fonts` directory, next to `Devices` — mounting it at `/fonts`
makes the container prefer the device's real file over the registry's
stand-in, the same `garmin` > registry precedence `wfb doctor` reports on
the host:

| Host | Path |
|---|---|
| macOS | `~/Library/Application Support/Garmin/ConnectIQ/Fonts` |
| Linux | `~/.Garmin/ConnectIQ/Fonts` |
| Windows | `%APPDATA%\Garmin\ConnectIQ\Fonts` |

```sh
-v "$HOME/Library/Application Support/Garmin/ConnectIQ/Fonts:/fonts:ro"
```

`WFB_FONTS=/fonts` is already set in the image; nothing to configure beyond
the mount itself. Unlike the device definitions, this one is **optional** —
without it, builds and previews fall back to the registry's fonts, which
`ts/tools/fetch-system-fonts.ts` prefetched into the image at build time.

**Not baked in, by design:** `.dockerignore` keeps all of `vendor/` out of
the build context, `vendor/fonts/` included, because like the device
definitions they are your licensed copy and the image is meant to be
distributable; a macOS SDK Manager install is outside the build context
anyway. So a populated `vendor/fonts/` on the host does nothing for the
container until it is mounted (`-v "$PWD/vendor/fonts:/fonts:ro"` works as
well as the SDK Manager's directory). Since a preview without them quietly
stops matching the device, `build`, `preview` and `validate` print a notice
to stderr when `/fonts` is empty; set `WFB_NO_GARMIN_FONTS=1` to use the
stand-ins on purpose without it. `wfb doctor` in the container gives the same
mount hint (the image sets `WFB_CONTAINER=1` so it knows to).

### The developer key

The key signs the `.prg`. The container generates a 4096-bit RSA key the first
time one is needed, at `/keys/developer_key.der`.

**Mount a volume at `/keys`** so the same key is reused:

```sh
docker volume create wfb-keys
# ... -v wfb-keys:/keys ...
```

Without that volume the key is regenerated on every run and thrown away. That
still produces a valid `.prg`, which is fine for `--no-compile` and for throwaway
checks — but treat a signing key the way you would outside a container: keep one,
keep it private, and back it up.

To use a key you already have:

```sh
-v "$HOME/ciq/developer_key.der:/keys/developer_key.der:ro"
```

---

## Commands

The image's entrypoint is `wfb`, so the arguments are the CLI's:

```sh
docker run ... garmin-wf-builder build     design.yaml [-d DEVICE] [--no-compile]
docker run ... garmin-wf-builder validate  design.yaml [-d DEVICE]
docker run ... garmin-wf-builder preview   design.yaml [-d DEVICE] [--scale N]
docker run ... garmin-wf-builder devices
docker run ... garmin-wf-builder sources
```

Anything that is obviously not a subcommand runs directly instead, so the image
doubles as a development shell:

```sh
docker run --rm -it garmin-wf-builder sh
docker run --rm ... garmin-wf-builder node --version
```

What each command needs mounted:

| Command | `/work` | `/devices` | `/fonts` | `/keys` |
|---|:--:|:--:|:--:|:--:|
| `build` | ✔ | ✔ | optional | ✔ |
| `build --no-compile` | ✔ | ✔ | optional | |
| `preview` | ✔ | ✔ | optional | |
| `validate` | ✔ | ✔ | | |
| `devices`, `sources` | | ✔ | | |
| `doctor` | | | optional | |
| `studio` | | ✔ | optional | ✔ (for Build) |

### The editor

`wfb studio` serves the visual editor. Inside the container it listens on
all of the container's interfaces (the entrypoint adds `--host 0.0.0.0`), so
**publish the port to the host's loopback only**:

```sh
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  garmin-wf-builder studio
```

Then open `http://127.0.0.1:8765/` in a browser on the host. The faces and
their history are kept in that browser ([where the faces
are](guide/studio.md#where-the-faces-are)), and go in by upload and come out
by download, so the editor needs no `/work` mount. Its Build signs with the
key at `/keys`, as `build` does. Whoever reaches the port can run builds, so
never publish it beyond `127.0.0.1`.

---

## File ownership

The image runs as **uid 1000**, which matches the usual single-user Linux host,
so build output in `/work` lands owned by you. On Docker Desktop for macOS and
Windows ownership is mapped for you and this does not arise.

If your uid is not 1000:

```sh
docker run --user "$(id -u):$(id -g)" ...
```

That works, at the cost of about a quarter-second on the first run: `monkeyc`
regenerates `default.jungle` inside the SDK on every invocation, so the SDK tree
has to be writable, and for a uid that does not own `/opt/ciq` the entrypoint
copies the 26 MB tree into the container's temporary home first. It says so when
it does.

A build directory left over from a run as a *different* uid cannot be replaced;
remove it and re-run. The tool reports that as a diagnostic rather than a
traceback.

---

## The simulator is not in this image

`wfb simulate` is unavailable in the container, and the entrypoint says so
plainly rather than letting you discover it mid-build.

The Connect IQ simulator is a GTK/WebKit GUI application. On current Linux it
links against `libwebkit2gtk-4.0`, `libsoup-2.4` and `libjavascriptcoregtk-4.0`,
which distributions no longer ship — and supplying those libraries is not
enough. On an `ubuntu:22.04` base, which still packages all three natively, the
simulator starts and opens its window under Xvfb, then **segfaults the moment a
`.prg` is pushed to it** with `monkeydo`. That was reproduced with an unmodified
SDK sample `.prg`, so it is a property of the environment, not of generated
faces. The crash is on a worker thread inside the simulator's own stripped
binary, with no GL library loaded at all; `docs/limitations.md` §2 records the
backtrace and everything that was ruled out. Rebasing this image on jammy to get
the libraries would therefore buy nothing but ~800 MB.

Use `wfb preview` instead:

```sh
docker run --rm -v "$PWD:/work" -v "$DEVICES:/devices:ro" \
  garmin-wf-builder preview examples/features/graph/face.yaml --scale 3
```

It renders from the **same resolved geometry the generated Monkey C uses**, so
the two cannot disagree about position — that is the anti-drift mechanism ADR
0004 specifies, not a second implementation. It does not reproduce system-font
glyph rasterisation, arc cap shape, or the transflective panel's real appearance;
for those, run the simulator on a desktop machine with the full SDK.

---

## How the image is built

Three stages, and **no system package manager runs in any of them** — the
image is composed from official bases rather than installed on top of one. That keeps builds
reproducible and working on networks where the distribution mirrors are not
reachable.

**Stage 1** installs `ts/`'s npm dependencies from its lock file
(`npm ci`) on the official `node:24-trixie-slim` image and copies in `ts/`.
Node runs its `.ts` sources directly, so nothing is compiled.

**Stage 2** builds on stage 1 and runs its tools. `ts/tools/fetch-sdk.ts`
downloads the SDK and strips it to the compiler: the full SDK is 309 MB;
`doc/`, `resources/` and `samples/` are documentation, and `share/` plus the
simulator, ERA, MonkeyMotion, the language server and the FIT graph tool are
GUI and analysis programs the container does not run. What is left is
**24 MB** and builds every target correctly; pruned files are skipped before
they are unzipped. It keeps `doc/docs/Device_Reference/`, the one part of
`doc/` that is data, aside: `ts/tools/extract-device-reference.ts` turns it
into the device reference stage 3 copies into `.cache/device-reference/`.
It also downloads the Nerd Fonts icon font with `ts/tools/fetch-icon-font.ts`
and the registry's system-font stand-ins (free substitutes previews and
width estimates use for Garmin's own system fonts) with
`ts/tools/fetch-system-fonts.ts --all` for every device in the device
reference (no device definitions exist at image build time), each checked
against pinned SHA-256 hashes; stage 3 copies both into `ts/assets/icons/`
and `ts/assets/system-fonts/`. Neither is in the repository, and
`.dockerignore` keeps a host copy out of the build context.

**Stage 3** copies a headless JRE from `eclipse-temurin:21-jre-noble` onto
the same `node:24-trixie-slim` base, then the pruned SDK, `ts/` with its
`node_modules`, `runtime-lib/`, `schema/`, `examples/` and the `wfb`
launcher. The Debian base provides `bash`, which the SDK's `monkeyc`
launcher needs; the developer key is generated with Node's own `crypto`, so
no `openssl` is needed.

Roughly 400 MB total: 159 MB JRE, the Node base, 24 MB SDK and about 54 MB
of `node_modules`, development tools included, so the image can run `ts/`'s
tests and type check. Those are estimates, not the rebuilt image's
measurement.

### Build arguments

| Argument | Default | Purpose |
|---|---|---|
| `SDK_VERSION` | `9.2.0` | recorded in the image at `/opt/ciq/SDK_VERSION` |
| `SDK_FILE` | the 9.2.0 Linux zip | the archive to download |
| `SDK_BASE_URL` | Garmin's download host | override for an internal mirror |
| `WFB_NERD_FONTS_BASE_URL` | the Nerd Fonts GitHub releases | override for a mirror of the icon font |
| `WFB_FONTS_MIRROR` | empty | override the host of every registry system-font URL, for a mirror that reproduces the same paths |
| `NODE_VERSION` | `24.21.0` | the `node` image tag for every stage |
| `EXTRA_CA_CERT_B64` | empty | a base64 PEM certificate to trust |

Behind a TLS-inspecting proxy:

```sh
docker build \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg EXTRA_CA_CERT_B64="$(base64 -w0 corp-ca.pem)" \
  -t garmin-wf-builder .
```

The certificate is appended to the system trust store in every stage and
handed to Node (`NODE_EXTRA_CA_CERTS`), whose `fetch` honours `HTTPS_PROXY`
there (`NODE_USE_ENV_PROXY=1`), so the SDK and font downloads and the npm
install all go through the proxy.

### Upgrading the SDK

Point the build at a newer archive:

```sh
docker build \
  --build-arg SDK_VERSION=9.3.0 \
  --build-arg SDK_FILE=connectiq-sdk-lin-9.3.0-<date>-<hash>.zip \
  -t garmin-wf-builder:9.3.0 .
```

Then re-run the test suite in the image before trusting it — the generated code
is pinned by golden files, so an SDK change that alters behaviour will show up as
a readable diff rather than as a surprise on the wrist.

---

## Two things that will bite you if you change the image

Both were found the hard way and are commented in the Dockerfile and entrypoint.

**`monkeyc` finds device definitions through Java's `user.home`, not `$HOME`.**
Java reads `user.home` from the *passwd entry* of the running uid, so exporting
`HOME` has no effect and running with `--user` silently breaks device discovery —
the symptom is `Invalid device id specified`, which looks like a missing mount.
The entrypoint sets `-Duser.home=...` through `JAVA_TOOL_OPTIONS` and symlinks
`<home>/.Garmin/ConnectIQ/Devices` at the mount.

**`monkeyc` regenerates `$CIQ_SDK/bin/default.jungle` on every invocation**, and
it replaces the file rather than truncating it — so the *directory* must be
writable, not just the file. A read-only SDK mount fails with
`Unable to generate default.jungle: Permission denied`.

---

## Continuous integration

Everything up to and including code generation needs no Garmin toolchain, which
is deliberate (ADR 0003): the device files are the scarce resource. In CI where
they are unavailable, the schema, semantic, layout, lint, font and golden-file
tests still run — only the slow suite, which invokes `monkeyc`, needs them.

```sh
docker run --rm --workdir /opt/wfb/ts garmin-wf-builder npm test
```

To build for real in CI, the device definitions have to reach the runner
somehow — a private artefact store or a self-hosted runner that has them. They
cannot be fetched from Garmin.
