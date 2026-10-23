# garmin-wf-builder

A visual editor and compiler for Garmin Connect IQ watch faces: design on the
watch's own screen, see it on every watch you target, and build a signed
`.prg` to sideload, without writing Monkey C.

![wfb studio, the visual editor](https://raw.githubusercontent.com/vvorth/garmin-wf-builder/main/docs/screenshots/studio.png)

This image is built from [`vvorth/garmin-wf-builder`](https://github.com/vvorth/garmin-wf-builder).
It holds the `wfb` command line and editor with everything a build needs:
Node, a headless Java runtime, and the Connect IQ SDK's compiler. You need
nothing on the host but Docker and **your own copy of Garmin's device
definitions** (see below).

## What is included

- `wfb studio`: the visual editor in your browser. Drag and resize on the
  face, preview every target watch at once, edit colours, styles,
  complication slots, fonts and hands, with a YAML editor beside it.
- `wfb build`: YAML design to signed, sideloadable `.prg` files, one per
  watch, each with its memory use against that watch's limit.
- `wfb preview`: renders the face to PNG with no simulator, from the same
  geometry the generated code uses.
- `wfb validate`, `wfb devices`, `wfb sources`, `wfb doctor`.
- The Connect IQ SDK (pruned to the compiler), the Nerd Fonts icon font and
  free stand-ins for Garmin's system fonts.

Not included: the Connect IQ simulator (it cannot run headless; use
`wfb preview`, or the simulator on a desktop machine), and Garmin's device
definitions (below).

## Tags

| Tag | Purpose |
| --- | --- |
| `latest` | Newest release. Releases are versioned by date: `26.10.0`, `26.10.1`, … (year, month, release number within the month). |
| `<version>` | One release; pin it for reproducible builds. Its notes are on [GitHub Releases](https://github.com/vvorth/garmin-wf-builder/releases). |
| `dev`, `dev-<commit>` | Development build, published on every push to `main` after the tests pass. Unstable: for trying what is coming. |

Every tag is multi-arch: `linux/amd64` and `linux/arm64`; Docker pulls the
one for your host.

## You supply the device definitions

Garmin's device definitions cannot be downloaded without a Garmin SSO login,
and they are your licensed copy, so they are not in the image. Install the
[Connect IQ SDK Manager](https://developer.garmin.com/connect-iq/sdk/) once on
a desktop machine, let it download the watches you target, and mount its
`Devices` directory read-only at `/devices`:

| Host | Path |
| --- | --- |
| macOS | `~/Library/Application Support/Garmin/ConnectIQ/Devices` |
| Linux | `~/.Garmin/ConnectIQ/Devices` |
| Windows | `%APPDATA%\Garmin\ConnectIQ\Devices` |

If the mount is missing, the container says so instead of failing deep in a
build.

## Quick start

Build a face in the current directory (macOS paths shown):

```sh
docker volume create wfb-keys

docker run --rm \
  -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  vvorth/garmin-wf-builder:latest build my-face.yaml
```

The `.prg` files land in `./build/`. As a shell alias:

```sh
alias wfb='docker run --rm -v "$PWD:/work" -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" -v wfb-keys:/keys vvorth/garmin-wf-builder:latest'
wfb new "My Face"        # writes my-face.yaml from a template
wfb preview my-face.yaml # build/preview/<watch>.png
wfb build my-face.yaml   # build/my-face/*.prg
```

The container sees only the directory mounted at `/work`, so run it from the
folder that holds your face.

## The editor

With no command, the image serves the editor on port `8765`:

```sh
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  vvorth/garmin-wf-builder:latest
```

Open <http://127.0.0.1:8765/>. Faces are kept in your browser and come in and
out by upload and download, so the editor needs no `/work` mount.

In the container the editor listens on every address and answers requests
addressed by any host name, so it works behind whatever name a proxy or your
network gives it. **Securing it is up to how you publish the port**: anyone
who reaches it can run builds. Publish it on `127.0.0.1`, or behind a reverse
proxy with authentication. To change the defaults, pass `studio` with your
own options: `--port N`, `--host ADDRESS`, or `--allow-host NAME` to answer
only that name.

## Docker Compose

```yaml
services:
  garmin-wf-builder:
    image: vvorth/garmin-wf-builder:latest
    container_name: garmin-wf-builder
    restart: unless-stopped
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - /path/to/ConnectIQ/Devices:/devices:ro
      - /path/to/ConnectIQ/Fonts:/fonts:ro   # optional
      - wfb-keys:/keys

volumes:
  wfb-keys:
```

## Mounts

| Path | What | Needed by |
| --- | --- | --- |
| `/work` | your project directory; the working directory | `build`, `preview`, `validate` |
| `/devices` | Garmin's device definitions, read-only | everything but `doctor` |
| `/keys` | the developer signing key, `developer_key.der` | `build`, and Build in `studio` |
| `/fonts` | optional: Garmin's own font files (the SDK Manager's `Fonts` directory, next to `Devices`) | `build`, `preview`, `studio` |

**The signing key.** The first build generates a 4096-bit key at
`/keys/developer_key.der`. Keep `/keys` on a volume so every build signs with
the same key, and back it up. To use a key you already have, mount it:
`-v "$HOME/ciq/developer_key.der:/keys/developer_key.der:ro"`.

**Fonts.** Without `/fonts`, text is measured and previewed with free
stand-ins that will not match the watch exactly, and the container prints a
notice. Set `WFB_NO_GARMIN_FONTS=1` to use the stand-ins without it.

## User and file ownership

The image runs as uid `1000`, so on a typical single-user Linux host the build
output is yours. Otherwise run with `--user "$(id -u):$(id -g)"`. On Docker
Desktop for macOS and Windows ownership is mapped for you.

Anything that is not a `wfb` subcommand (`sh`, `node`, `npm`, `java`,
`monkeyc`) runs directly, so the image doubles as a shell:
`docker run --rm -it vvorth/garmin-wf-builder sh`.

## Links

- GitHub: <https://github.com/vvorth/garmin-wf-builder>
- The container in full: <https://github.com/vvorth/garmin-wf-builder/blob/main/docs/container.md>
- The design format: <https://github.com/vvorth/garmin-wf-builder/blob/main/docs/README.md>
- Releases: <https://github.com/vvorth/garmin-wf-builder/releases>
- Issues: <https://github.com/vvorth/garmin-wf-builder/issues>

For personal sideloading. Garmin, Connect IQ and the device names are
trademarks of Garmin Ltd.; this project is not affiliated with Garmin.
