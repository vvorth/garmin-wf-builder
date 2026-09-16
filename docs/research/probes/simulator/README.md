# Simulator-in-a-container probe

Backs `docs/limitations.md` §2. **Not part of the compiler, not built by the
test suite** — it exists so "the simulator does not run headlessly" can be
re-checked against the real SDK rather than taken on trust, and so the next
person does not spend a session rediscovering the answer.

## The question

The shipping image leaves the simulator out. The stated reason was that it links
against `libwebkit2gtk-4.0` and `libsoup-2.4`, which current distributions no
longer package. Ubuntu 22.04 (jammy) still packages both, plus
`libjavascriptcoregtk-4.0`. So the obvious question: is the missing-library
problem the *whole* problem?

## The answer: no

Supplying every library natively gets further than before and still fails, in a
place that rules out the explanation the docs used to give.

1. **Every library resolves.** On bare jammy, `ldd bin/simulator` reports 27
   `not found`. After the `apt-get` line in the `Dockerfile` here, zero. The
   image asserts this at build time, so a base-image regression fails the build
   rather than silently changing what the probe measures.
2. **The simulator starts.** Under `Xvfb :99 -screen 0 1280x1024x24` it opens a
   446x700 window that `xwininfo` lists as `"CIQ Simulator": ("simulator"
   "Simulator")`, and it stays up indefinitely.
3. **It segfaults when a `.prg` is pushed.** `monkeydo <face>.prg
   fenix8solar47mm` kills it within seconds; the window disappears and the
   process dies of `SIGSEGV`. This is the "segfaults on app load" failure —
   loading the app is what `monkeydo` triggers.

## Why it is not an OpenGL problem

The docs used to attribute the crash to "software OpenGL". Under `gdb`:

```
Thread 34 "simulator" received signal SIGSEGV, Segmentation fault.
0x00005555558067ee in ?? ()
#0  0x00005555558067ee in ?? ()
...
#15 0x00005555568fa017 in ?? ()
#16 0x00007fffef178a83 in ?? () from /lib/x86_64-linux-gnu/libc.so.6
```

Every frame but the last two is in the `0x5555…` range — the simulator's own
stripped executable — and the last two are libc's thread entry. GTK, WebKit and
JavaScriptCore appear nowhere on the stack. More directly: `info sharedlibrary`
lists no `libGL` at all, so the simulator never loads OpenGL and software
rendering cannot be the mechanism.

## Ruled out

Each varied on its own, with the crash unchanged:

| Variable | Tried |
|---|---|
| `/dev/shm` size | 64 MB (Docker default) and 2 GB |
| seccomp | default profile and `--security-opt seccomp=unconfined` |
| uid | 1000 and root |
| device definitions | read-only bind mount, and copied in writable |
| WebKit escape hatches | `WEBKIT_DISABLE_COMPOSITING_MODE=1`, `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1` |

`SYS_PTRACE` is needed for the `gdb` run, and for nothing else.

**2026-09-16: retested outside Docker entirely, on a real Ubuntu 22.04 GUI
session (Xwayland via GNOME, not Xvfb, not a container).** The simulator
starts and renders its window correctly under `connectiq`, which is new —
the older, wrong "software OpenGL" and "container-only" theories both
predicted this would work. It still **segfaults the instant `monkeydo`
pushes an app**, at the identical crash: `SIGSEGV` at faulting address
`0x8`, same instruction (`mov rax, [0x8]` — an absolute, not
register-relative, operand — immediately preceding a `ud2`), and the same
`0x147ee` offset into the stripped binary run after run. Additionally ruled
out, each on its own, all with the crash unchanged: `GDK_BACKEND=x11`
(forcing Xwayland instead of whatever default), `JSC_useJIT=0` /
`WEBKIT_JAVASCRIPTCORE_USE_JIT=0` (in case it was WebKit's JIT — moot
anyway, since the backtrace never enters WebKit), two different devices
(`fenix8solar47mm`, `fr955`), and two different `.prg`s (`examples/graph`,
`examples/shapes`). The absolute-address load is consistent with a
compile-time-folded null-pointer field access baked into the simulator's
own optimized code, not an environment, display-server, or WebKit-ABI
problem — this SDK 9.2.0 build's `monkeydo`-triggered app load is broken
regardless of host. Nothing found in a search of `forums.garmin.com`
matches this exact signature. `wfb preview` remains the answer.

**2026-09-16, same day: tested the leading hypothesis (glibc's libpthread
merge) directly, and it's wrong.** Ubuntu 22.04 was the first LTS built on
glibc ≥2.34, which folded `libpthread` into `libc` itself — a well-known
source of segfaults in old prebuilt Linux binaries that assume the
pre-merge layout, and the crash's own instruction (an absolute-address
load, not register-relative — consistent with a stale hardcoded offset)
fit that story. So: built an Ubuntu 20.04 (`libc6 2.31-0ubuntu9.17`,
pre-merge) container with the same native dependency list, ran the *actual
host SDK's* `bin/simulator` inside it (bind-mounted, not re-downloaded)
with the host's X11 socket shared (`--network host`, `-v
/tmp/.X11-unix:/tmp/.X11-unix`, `xhost +local:` — Xauthority cookie
forwarding failed under this host's Xwayland setup, `xhost` was the
working substitute) so it could actually put a window on screen, and
pushed to it with the host's `monkeydo`. **Identical crash**: same
faulting address `0x8`, same instruction bytes, same `0x147ee` offset —
on a glibc three years and one major ABI generation older. glibc version
is not the variable. This closes off "try a different Ubuntu version" as
a productive direction entirely: nothing about the host — container or
not, glibc 2.31 or 2.35, X11 backend, WebKit flags, device, or example
face — changes this outcome. The defect is in the SDK 9.2.0 simulator
binary itself.

## Reproducing it

Build the probe image (it downloads the SDK unpruned, so it is large):

```sh
docker build -f docs/research/probes/simulator/Dockerfile \
             -t wfb-simprobe docs/research/probes/simulator/
```

Build a face to push, then run the simulator and push it:

```sh
./.venv/bin/python wfb.py build examples/slice/face.yaml -d fenix8solar47mm

docker run --rm -it --cap-add=SYS_PTRACE \
  -v "$HOME/.Garmin/ConnectIQ/Devices:/devices:ro" \
  -v "$PWD/build/slice:/probe:ro" \
  wfb-simprobe bash -c '
    export HOME=/tmp/h DISPLAY=:99
    mkdir -p $HOME/.Garmin/ConnectIQ
    ln -sfn /devices $HOME/.Garmin/ConnectIQ/Devices
    export JAVA_TOOL_OPTIONS="-Duser.home=$HOME"
    Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
    sleep 3
    /opt/ciq/bin/simulator & SIM=$!
    sleep 20
    xwininfo -root -tree | grep "CIQ Simulator"   # the window is there
    /opt/ciq/bin/monkeydo /probe/slice-fenix8solar47mm.prg fenix8solar47mm &
    sleep 45
    kill -0 $SIM 2>/dev/null && echo ALIVE || echo "DEAD -- segfaulted"
  '
```

Swap the `simulator &` line for `gdb -batch -ex run -ex "bt 40" \
-ex "info sharedlibrary" /opt/ciq/bin/simulator &` to re-take the backtrace.

Note that `docker exec` into a container running the simulator hangs; have the
script do its own observation, as above, rather than attaching from outside.

## What to do instead

`wfb preview`. It renders from the same resolved geometry the generated Monkey C
uses, so the two cannot disagree about position. It does not reproduce
system-font glyph rasterisation, arc cap shape, or the transflective panel's
real appearance — for those the simulator on a desktop machine is authoritative.
