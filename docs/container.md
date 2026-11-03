# Running garmin-wf-builder as a container

A container image that turns a YAML design into a signed, sideloadable Connect IQ
`.prg` — with no Java and no Node set up on the host. Garmin's own files, the
Connect IQ SDK and your watches' device definitions, come from you: the
Connect IQ SDK Manager puts them on your computer, and the container mounts
its folders (macOS paths shown):

```sh
docker run --rm \
  -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ:/vendor:ro" \
  -v wfb-keys:/keys -v wfb-cache:/cache \
  vvorth/garmin-wf-builder build examples/features/graph/face.yaml
```

The image is published on Docker Hub ("Published images" below); `docker
build -t garmin-wf-builder .` in a checkout builds the same image, and the
rest of this page uses that local name.

(The one `/vendor` mount brings the SDK Manager's `Sdks`, `Devices` and
`Fonts` folders together; `/cache` is optional — below.)

```
generated  /work/build/graph
built      graph-1.0.0-fenix8solar47mm.prg  3,417 B / 131,072 B (2.6%)
built      graph-1.0.0-fenix8solar51mm.prg  3,418 B / 131,072 B (2.6%)
built      graph-1.0.0-fr955.prg  3,417 B / 131,072 B (2.6%)
```

The generated Monkey C is byte-identical to a host build of the same design.
Not sure what you have? `docker run --rm garmin-wf-builder init` prints the
steps for the computer running Docker, from the SDK Manager's download to
the mounts.

---

## Requirements

| | |
|---|---|
| **Docker** | any recent version, or Podman with `podman` in place of `docker`. On macOS it is tested with [OrbStack](https://orbstack.dev) |
| **Disk** | ~400 MB for the image |
| **The Connect IQ SDK** | **required, and must come from you** — see below |
| **Device definitions** | **required, and must come from you** — see below |
| **Garmin's own font files** | optional — see below |
| **Network** | only at image build time, for the icon and system fonts and the npm packages |
| **Architecture** | `linux/amd64` and `linux/arm64`. The compiler is JVM bytecode, so the SDK Manager's SDK from any OS runs in either. CI builds each on its own architecture and smoke-tests it with the fixture device, which generates and previews but cannot compile, so a real `.prg` build is verified by hand |

### The two things you have to supply: the SDK and the device definitions

Both come from Garmin's [Connect IQ SDK
Manager](https://developer.garmin.com/connect-iq/sdk/): install it once on
a desktop machine, sign in with a Garmin account, download the newest SDK on
its SDK tab and the watches you build for on its Devices tab. It keeps them,
with Garmin's font files beside them, under one folder:

| Host | Folder |
|---|---|
| macOS | `~/Library/Application Support/Garmin/ConnectIQ` |
| Linux | `~/.Garmin/ConnectIQ` |
| Windows | `%APPDATA%\Garmin\ConnectIQ` |

with `Sdks/`, `Devices/` and `Fonts/` inside. Mount that folder read-only
at `/vendor`:

```sh
-v "$HOME/Library/Application Support/Garmin/ConnectIQ:/vendor:ro"
```

The image reads the SDK at `/vendor/Sdks` (the SDK the SDK Manager marks
current is used, else the newest; one SDK's own folder mounted there works
too), the device definitions at `/vendor/Devices` and Garmin's fonts at
`/vendor/Fonts`, so the three can also be mounted one by one, from
wherever they are (`-v "<dir>:/vendor/Devices:ro"`); an image from before
November 2026 took `/sdk`, `/devices` and `/fonts`, which still work. If
the SDK or the devices are missing, the container says so and points here
rather than failing deep inside a build, and `docker run --rm
garmin-wf-builder init` prints every step.

**No SDK Manager on the Docker host?** The SDK itself downloads without a
sign-in, and the image fetches Garmin's newest once you say so, since
downloading it accepts Garmin's agreement as the download button on its
page would. **The editor** starts without an SDK and, on every load that
finds none, shows a dialog with the agreement to read and accept and a
**Download and install** button; a reload then shows what the SDK knows
about the watches (`docs/guide/studio.md`, "Doctor, and the SDK"). A
command that compiles (`build`, `export`) asks at the terminal (`docker run
-it ...`), or downloads at once with `-e WFB_ACCEPT_LICENSE=1`, which also
has the editor fetch the SDK as it starts; Compose users set it once. It
lands in `/vendor/Sdks` when that is writable (mount the SDK Manager's
folder read-write for that, and the SDK Manager sees it too), else in
`/cache` (so a cache volume keeps it), as
`connectiq-sdk-lin-<version>-<date>-<hash>/`, the layout the SDK Manager
uses, so a later SDK Manager install sees it too, and every later run finds
it there. The same download by hand, into a folder of your choosing:

```sh
mkdir -p "$HOME/.Garmin/ConnectIQ/Sdks"
docker run --rm -v "$HOME/.Garmin/ConnectIQ/Sdks:/vendor/Sdks" garmin-wf-builder init --download-sdk --accept-license
```

The device definitions have no such download: only the SDK Manager,
signed in, provides them.

**A newer SDK.** The commands that compile, and `init` and `doctor`, print
one line on stderr when Garmin lists a newer SDK than the one found, and
the editor's Doctor names it with an **Install SDK x.y.z…** button. The
release list is fetched at most once a day (the copy sits in `/cache`),
with a short timeout, and nothing is said offline; `-e
WFB_NO_UPDATE_CHECK=1` turns the check off. To take the newer one, download
it in the SDK Manager, install it from Doctor, or run once with
`WFB_ACCEPT_LICENSE=1` and the old SDK not mounted.

The image cannot contain them, for two independent reasons.

**They are licensed to you, not to this project.** Downloading the SDK
accepts Garmin's Connect IQ Developer Agreement, which grants a "personal,
revocable, non-assignable, non-sublicensable and non-transferable license to
use the Program Materials for the sole purpose of developing and testing
Applications" and forbids to "upload to or host on any website or server,
sell, redistribute, or sublicense the Program Materials in whole or in
part". A published image is both hosting and redistribution, so the SDK —
the compiler, its API database, the device reference pages — stays out of
it, and so do the device files and Garmin's fonts, which the same agreement
covers. `docs/lore/toolchain.md`, "The Developer Agreement", has the
citations.

**The device definitions cannot be downloaded at all.** The SDK Manager
fetches them from `api.gcs.garmin.com/ciq-product-onboarding/devices`, which
returns **HTTP 401** — it needs a Garmin SSO login that cannot be completed
non-interactively. Without them every device-targeted build fails with
`Invalid device id specified`. (The SDK itself downloads freely, which is
how `tools/setup-env.sh` installs one on a Linux host: that is the
developer's own download, under the same agreement.)

### Garmin's own font files (optional)

Text measurement and previews use free stand-ins for Garmin's system fonts
by default (`ts/src/data/font-registry.json`). If the same SDK Manager
install that provided the device definitions also has Garmin's own font files
— under its `Fonts` directory, next to `Devices` — the `/vendor` mount
brings them along, and the container prefers the device's real file over
the registry's stand-in, the same `garmin` > registry precedence `wfb
doctor` reports on the host. Mounted on their own:

```sh
-v "$HOME/Library/Application Support/Garmin/ConnectIQ/Fonts:/vendor/Fonts:ro"
```

`WFB_FONTS=/vendor/Fonts` is already set in the image; nothing to configure
beyond the mount itself. Unlike the SDK and the device definitions, this one is
**optional** — without it, builds and previews fall back to the registry's
fonts, which `ts/tools/fetch-system-fonts.ts --registry` prefetched into the
image at build time, every font the registry knows.

**Not baked in, by design:** `.dockerignore` keeps all of `vendor/` out of
the build context, `vendor/fonts/` included, because like the device
definitions they are your licensed copy and the image is meant to be
distributable; a macOS SDK Manager install is outside the build context
anyway. So a populated `vendor/fonts/` on the host does nothing for the
container until it is mounted (`-v "$PWD/vendor/fonts:/vendor/Fonts:ro"`
works as well as the SDK Manager's directory). Since a preview without them
quietly stops matching the device, `build`, `preview` and `validate` print
a notice to stderr when `/vendor/Fonts` is empty; set `WFB_NO_GARMIN_FONTS=1` to use the
stand-ins on purpose without it. `wfb doctor` in the container gives the same
mount hint (the image sets `WFB_CONTAINER=1` so it knows to).

### The cache (optional)

Two things are made from the mounted SDK at run time, and `/cache` keeps
them between runs:

- **A writable copy of the compiler.** `monkeyc` rewrites
  `bin/default.jungle` on every run, and `/vendor` is mounted read-only, so
  `wfb` copies the compiler's files (about 26 MB, nothing of the simulator
  or the docs) to `/cache/wfb/sdk/<version>/` and compiles from there,
  once per SDK release.
- **The device reference**, the facts a device's own files omit (its real
  palette size, its system fonts' pixel metrics), which `wfb` extracts from
  the SDK's own device pages into `/cache/wfb/device-reference/` the first
  time it is needed, and again when the SDK's release changes (about a
  second for the whole fleet; `wfb` says so on stderr when it does).

Without the mount both are remade on every run, into the container's
temporary home: correct, a second or so slower.

```sh
-v wfb-cache:/cache
```

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

The image's entrypoint is `wfb`, so the arguments are the CLI's. With no
arguments it runs `studio` (below):

```sh
docker run ... garmin-wf-builder init
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

| Command | `/work` | `/vendor/Sdks` | `/vendor/Devices` | `/vendor/Fonts` | `/keys` |
|---|:--:|:--:|:--:|:--:|:--:|
| `build` | ✔ | ✔ | ✔ | optional | ✔ |
| `build --no-compile` | ✔ | | ✔ | optional | |
| `export` | ✔ | ✔ | ✔ | | ✔ |
| `preview` | ✔ | | ✔ | optional | |
| `validate` | ✔ | | ✔ | | |
| `devices`, `sources` | | | ✔ | | |
| `init`, `doctor` | | optional (`init --download-sdk` writes into it) | optional | optional | |
| `studio` | | for Build (or its dialog installs one) | ✔ | optional | ✔ (for Build) |

(One `/vendor` mount of the SDK Manager's folder fills the three middle
columns at once.) `/cache` is optional everywhere. `preview` and `validate` need no SDK to
run, but with none mounted the device reference cannot be extracted either,
so they read whatever reference the cache holds; mount the SDK once with
`/cache` kept, or keep mounting it.

### The editor

`wfb studio` serves the visual editor, and is what the image runs with no
arguments:

```sh
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ:/vendor:ro" \
  -v wfb-keys:/keys -v wfb-cache:/cache \
  garmin-wf-builder
```

Then open `http://127.0.0.1:8765/` in a browser on the host. The faces and
their history are kept in that browser ([where the faces
are](guide/studio.md#where-the-faces-are)), and go in by upload and come out
by download, so the editor needs no `/work` mount. Its Build signs with the
key at `/keys`, as `build` does. It starts with no SDK and no devices
mounted (an empty folder at `/vendor` included): its dialog then installs
the SDK from Garmin into `/vendor/Sdks` or `/cache` and says how to get
the devices, and its
**Doctor** shows what the container has (the SDK, the watches, the fonts).

Inside the container the server cannot know the address or the name it is
reached by: the host, a reverse proxy or an orchestrator decides both. So the
entrypoint adds `--host 0.0.0.0` (every address) and `--allow-any-host`
(answer any `Host` name) to `studio`, and the published port is the boundary.
**Whoever reaches the port can run builds**, so publish it to the host's
loopback (`-p 127.0.0.1:8765:8765`) or behind a reverse proxy that
authenticates. The server says so when it starts, instead of the
`--allow-any-host` warning it prints on a host.

Each default gives way to an option of your own: `docker run ...
garmin-wf-builder studio --port 9000`, `--host ADDRESS`, or `--allow-host
NAME` to answer only that name (and IP addresses and `localhost`), which
drops `--allow-any-host`. The options are in [the editor's
guide](guide/studio.md).

---

## File ownership

The image runs as **uid 1000**, which matches the usual single-user Linux host,
so build output in `/work` lands owned by you. On Docker Desktop for macOS and
Windows ownership is mapped for you and this does not arise.

If your uid is not 1000:

```sh
docker run --user "$(id -u):$(id -g)" ...
```

`/work`, `/keys` and `/cache` are world-writable in the image, so any uid
can write its output, its key and its cache there; the SDK's copy and the
device reference land in the cache whoever runs the container.

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
docker run --rm -v "$PWD:/work" -v "$GARMIN:/vendor:ro" \
  garmin-wf-builder preview examples/features/graph/face.yaml --scale 3
```

It renders from the **same resolved geometry the generated Monkey C uses**, so
the two cannot disagree about position — that is the anti-drift mechanism ADR
0004 specifies, not a second implementation. It does not reproduce system-font
glyph rasterisation, arc cap shape, or the transflective panel's real appearance;
for those, run the simulator on a desktop machine with the full SDK.

---

## Published images

`vvorth/garmin-wf-builder` on Docker Hub, multi-arch (`linux/amd64`,
`linux/arm64`):

| Tag | What |
|---|---|
| `latest` | the newest release |
| `<version>`, e.g. `26.10.0` | a release: `YY.M.N`, `N` counting the month's releases, the same as the git tag `v<version>` and the GitHub release |
| `dev` | the newest commit on `main`, the development branch, that passed CI |
| `dev-<commit>` | one `main` commit; the newest ten are kept |

The version is in the image's `org.opencontainers.image.version` label
(`dev+<commit>` on a dev image); `wfb --version` prints the compiler's own
version, which is not the release number. How the images are made is in
`docs/development.md`, "Continuous integration".
The Docker Hub page's overview is `DOCKERHUB.md` at the repository root;
each release uploads it.

## How the image is built

Three stages, and **no system package manager runs in any of them** — the
image is composed from official bases rather than installed on top of one. That keeps builds
reproducible and working on networks where the distribution mirrors are not
reachable.

**Stage 1** installs `ts/`'s npm dependencies from its lock file
(`npm ci`) on the official `node:24-trixie-slim` image and copies in `ts/`.
Node runs its `.ts` sources directly, so nothing is compiled.

**Stage 2** builds on stage 1 and runs two of its tools: `ts/tools/fetch-icon-font.ts`
downloads the Nerd Fonts icon font, and `ts/tools/fetch-system-fonts.ts
--registry` the registry's system-font stand-ins (free substitutes previews
and width estimates use for Garmin's own system fonts), every font the
registry knows, since there are no device definitions and no SDK at image
build time to say which a device needs. Each is checked against a pinned
SHA-256 hash; stage 3 copies both into `ts/assets/icons/` and
`ts/assets/system-fonts/`. Neither is in the repository, and
`.dockerignore` keeps a host copy out of the build context.

**Stage 3** copies a headless JRE from `eclipse-temurin:21-jre-noble` onto
the same `node:24-trixie-slim` base, then `ts/` with its `node_modules`,
`runtime-lib/`, `schema/`, `examples/`, `docs/` (without `docs/research/`),
`README.md`, `LICENSE` and the `wfb` launcher; the docs are there for `wfb
studio`'s Help popup. `wfb` runs the compiler as the JVM on the SDK's
`monkeybrains.jar` directly, so the SDK's own `bash` launcher is not needed;
the developer key is generated with Node's own `crypto`, so no `openssl` is
needed either. Nothing of Garmin's is in any stage.

About 400 MB as built: the JRE (159 MB), the Node base, the fonts and
`node_modules` with its development tools, so the image can run `ts/`'s
tests and type check.

### Build arguments

| Argument | Default | Purpose |
|---|---|---|
| `WFB_NERD_FONTS_BASE_URL` | the Nerd Fonts GitHub releases | override for a mirror of the icon font |
| `WFB_FONTS_MIRROR` | empty | override the host of every registry system-font URL, for a mirror that reproduces the same paths |
| `NODE_VERSION` | `24.22.1` | the `node` image tag for every stage; earlier than 22.23.4, 24.22.1 or 26.12.1 is vulnerable, and `wfb` refuses it |
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
there (`NODE_USE_ENV_PROXY=1`), so the font downloads and the npm install
all go through the proxy.

### Upgrading the SDK

The SDK is yours, not the image's: download the newer release in the SDK
Manager and the next run picks it up (the current one, else the newest, in
the mounted `Sdks` folder), copies its compiler into the cache and extracts
its device reference. `wfb build` records the release in `build-info.json`.
Then re-run the test suite before trusting it — the generated code is pinned
by golden files, so an SDK change that alters behaviour will show up as a
readable diff rather than as a surprise on the wrist.

---

## Two things that will bite you if you change the image

Both were found the hard way and are commented in the Dockerfile and entrypoint.

**`monkeyc` finds device definitions through Java's `user.home`, not `$HOME`.**
Java reads `user.home` from the *passwd entry* of the running uid, so exporting
`HOME` has no effect and running with `--user` silently breaks device discovery —
the symptom is `Invalid device id specified`, which looks like a missing mount.
The entrypoint sets `-Duser.home=...` through `JAVA_TOOL_OPTIONS` and symlinks
`<home>/.Garmin/ConnectIQ/Devices` at the mount.

**`monkeyc` regenerates `<sdk>/bin/default.jungle` on every invocation**, and
it replaces the file rather than truncating it — so the *directory* must be
writable, not just the file. A read-only SDK fails with `Unable to generate
default.jungle: Permission denied`, which is why `wfb` compiles from a copy
of the compiler's files when the SDK's `bin/` is not writable (`compilerRoot`
in `ts/src/sdk.ts`).

---

## Continuous integration

Everything up to and including code generation needs no Garmin toolchain, which
is deliberate (ADR 0003): the device files are the scarce resource. In CI where
they are unavailable, the schema, semantic, layout, lint, font and golden-file
tests still run — only the slow suite, which invokes `monkeyc`, needs them.

```sh
docker run --rm --workdir /opt/wfb/ts garmin-wf-builder npm test
```

This project's own CI tests each image with `tools/image-smoke-test.sh`,
which fetches a pruned SDK once (Garmin's free download, by
`ts/tools/fetch-sdk.ts --newest` in the image, into `.cache/smoke-sdk/`; it
is the runner's own download and is never published), mounts it read-only
at `/vendor/Sdks` and the fixture device `wfbtest` at `/vendor/Devices` (and
both at once under one `/vendor`, and at the older `/sdk` and `/devices`),
and checks that
the toolchain starts, `wfb` compiles from a copy of the read-only SDK,
extracts the device reference into the cache once, generates and previews a
face, refuses a build with no SDK and no `WFB_ACCEPT_LICENSE` with the
mount hint, downloads the SDK into `/cache` with it, starts the editor with
no SDK at all, and serves the editor. It compiles nothing.

To build for real in CI, the device definitions have to reach the runner
somehow — a private artefact store or a self-hosted runner that has them. They
cannot be fetched from Garmin.
