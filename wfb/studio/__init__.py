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
from .bundle import from_path
from .document import SNAPSHOT_MINUTES, Studio
from .store import Store

LOOPBACK = ("127.0.0.1", "localhost", "::1")


#: `--keep-days` and `--keep-snapshots`' defaults.
KEEP_DAYS = 30.0
KEEP_SNAPSHOTS = 50


def serve(*, host: str, port: int, state_dir: Path, db: DeviceDatabase,
          design: Path | None = None, snapshot_minutes: float = SNAPSHOT_MINUTES,
          keep_days: float = KEEP_DAYS, keep_snapshots: int = KEEP_SNAPSHOTS) -> None:
    """Run the editor until interrupted."""
    import uvicorn

    from .app import create_app

    store = Store(state_dir)
    for line in store.prune(keep_days=keep_days, keep_snapshots=keep_snapshots):
        print(f"pruned {line}", flush=True)
    studio = Studio(store, db, snapshot_minutes=snapshot_minutes)
    initial = None
    try:
        if design is not None:
            bundle, moved = from_path(design)
            initial = studio.create(bundle, f"open {design.name}", moved).id
        app = create_app(studio, initial=initial)
        shown = f"[{host}]" if ":" in host else host
        print(f"wfb studio on http://{shown}:{port}/  (history: {store.root})", flush=True)
        if host not in LOOPBACK and os.environ.get("WFB_CONTAINER") == "1":
            print(f"in a container: publish the port to the host's loopback only, "
                  f"-p 127.0.0.1:{port}:{port}, and open http://127.0.0.1:{port}/ there",
                  flush=True)
        elif host not in LOOPBACK:
            print(f"warning: listening on {host}, not loopback: anyone who can reach this "
                  "port can read and write the faces in the editor", file=sys.stderr, flush=True)
        studio.start_timer()
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        studio.close()
