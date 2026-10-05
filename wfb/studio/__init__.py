"""`wfb studio`: the visual editor, a local web app.

The browser drives it: it creates a face from a template or uploads one, and
downloads it to save.  The server holds each open face's text (ADR 0002:
the text is the design) and runs the compiler over it:

- `bundle`: a face in and out, a `.zip` with `face.yaml` and `assets/` or a
  plain `.yaml`, every path checked before anything is unpacked;
- `store`: the durable history of every document, outside the temporary
  directories the compiler reads;
- `document`: an open face, its directory, its pipeline and its frames;
- `app`: the HTTP endpoints and the event stream;
- `static/`: the front end, vendored ES modules with no build step.

The patch engine every edit goes through is `wfb.edit`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..devices import DeviceDatabase
from .document import SNAPSHOT_MINUTES, Studio
from .sessions import Sessions
from .store import Store

LOOPBACK = ("127.0.0.1", "localhost", "::1")


#: `--keep-snapshots`' default.
KEEP_SNAPSHOTS = 50


#: The names a request may address the editor by, always.
LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"]


def allowed_hosts(host: str, extra: list[str]) -> list[str]:
    """The `Host` names the editor answers: loopback's, the address it
    listens on (unless that is every address), and ``extra``."""
    out = list(LOOPBACK_HOSTS)
    shown = f"[{host}]" if ":" in host else host
    if host not in ("0.0.0.0", "::") and shown not in out:
        out.append(shown)
    return out + [h for h in extra if h not in out]


def serve(*, host: str, port: int, state_dir: Path, db: DeviceDatabase,
          snapshot_minutes: float = SNAPSHOT_MINUTES,
          keep_snapshots: int = KEEP_SNAPSHOTS,
          single_user: bool = False, allow_hosts: list[str] | None = None) -> None:
    """Run the editor until interrupted."""
    import uvicorn

    from .app import create_app

    store = Store(state_dir)
    for line in store.prune(keep_snapshots=keep_snapshots):
        print(f"pruned {line}", flush=True)
    sessions = Sessions(state_dir, single_user=single_user)
    for line in sessions.prune({store.owner(d["id"]) for d in store.documents()}):
        print(f"pruned {line}", flush=True)
    studio = Studio(store, db, snapshot_minutes=snapshot_minutes)
    try:
        app = create_app(studio, sessions=sessions,
                         allowed_hosts=allowed_hosts(host, allow_hosts or []))
        shown = f"[{host}]" if ":" in host else host
        if host in ("0.0.0.0", "::"):
            shown = "127.0.0.1"
        claim = "" if single_user else f"?claim={sessions.startup_claim()}"
        print(f"wfb studio on http://{shown}:{port}/{claim}  (history: {store.root})", flush=True)
        if claim:
            print("  open that address once to have this server's faces in your browser; "
                  "it works once", flush=True)
        if host not in LOOPBACK and os.environ.get("WFB_CONTAINER") == "1":
            print(f"in a container: publish the port to the host's loopback only, "
                  f"-p 127.0.0.1:{port}:{port}, and open the address above there",
                  flush=True)
        elif host not in LOOPBACK:
            print(f"warning: listening on {host}, not loopback: anyone who can reach this "
                  "port can make faces here and run builds on this computer"
                  + (", and, with --single-user, read and write every face" if single_user
                     else ""), file=sys.stderr, flush=True)
        studio.start_timer()
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        studio.close()
