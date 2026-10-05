"""The editor's durable state: every document's history, outside the
volatile directories the compiler reads.

One directory per document under the store's root:

- `meta.json`: the display name, when the document was created, and its
  `owner`, the principal it belongs to (`wfb.studio.sessions`; a document
  from before owners belongs to the owner principal);
- `blobs/<sha256>`: every text version and every asset file, content
  addressed by the hash of the content, so a long history of a small face
  costs little and an asset is stored once. A text version is stored
  zlib-compressed, as `<sha256>.z` (a third of its size, measured on the
  example faces, for 0.2 ms): every drag on the canvas is a version;
- `journal.jsonl`: one JSON line per action, appended and flushed to disk
  before the action is acknowledged.  Every line names the text and asset
  manifest the document has after it, by hash, so the last line *is* the
  document.  A crash mid-append can leave a line cut short; it was never
  acknowledged, so before the next append the file is cut back to its last
  whole line, and what was cut is kept beside it as
  `journal.jsonl.torn-<ms>` rather than destroyed;
- `snapshots/<name>.json`: a point in time to go back to, naming its text
  and assets by hash the same way.

**Undo and redo are journal lines too.** A `change` line adds a state; an
`undo` or `redo` line moves to an earlier or later one, naming it by its
sequence number (`target`).  Replaying the journal (`timeline`) gives the
states on the current line of history and where the document is among
them, so undo survives a restart.  A change after an undo drops the states
past the cursor from the line, as every editor does; their blobs stay, so
a snapshot taken in that branch still restores.  A `change` line marked
`merge` takes the place of the state before it instead of following it,
so a burst of typing is one step to undo.

The store keeps each journal it has read in memory, checked against the
file's size and modification time, so a document's head and timeline cost
nothing to ask for again.

A document's directory is the whole of it: deleting the directory deletes
the document.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The principal a document belongs to when its `meta.json` names none: one
#: made before documents had owners (`wfb.studio.sessions.OWNER`).
OWNER = "owner"

#: A document id: what `new_document` mints, and all a path may be built from.
_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT = re.compile(r"^[0-9]{8}-[0-9]+$")

#: What a journal line does.
CHANGE, UNDO, REDO = "change", "undo", "redo"


class StoreError(OSError):
    """The store could not be read or written; the change is not applied."""


class UnknownDocument(KeyError):
    """No document with that id is in the store."""


class UnknownSnapshot(KeyError):
    """No snapshot with that name is in the document."""


@dataclass(frozen=True)
class Change:
    """One journal line: the action, and the document after it."""

    seq: int
    time: float
    label: str
    text: str
    assets: dict[str, str]
    kind: str = CHANGE
    #: For `undo`/`redo`: the `seq` of the `change` line it moved to.
    target: int | None = None
    #: For a `change`: it replaces the state before it on the line.
    merge: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seq": self.seq, "time": self.time, "label": self.label,
                               "text": self.text, "assets": self.assets, "kind": self.kind}
        if self.target is not None:
            out["target"] = self.target
        if self.merge:
            out["merge"] = True
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Change":
        target = data.get("target")
        return cls(int(data["seq"]), float(data["time"]), str(data["label"]),
                   str(data["text"]), {str(k): str(v) for k, v in data["assets"].items()},
                   str(data.get("kind", CHANGE)), int(target) if target is not None else None,
                   bool(data.get("merge", False)))


@dataclass
class Timeline:
    """The states on the current line of history, oldest first, and the
    index of the one the document is in."""

    states: list[Change] = field(default_factory=list)
    cursor: int = -1

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.states) - 1


@dataclass
class _Journal:
    """A journal as read: the file's size and modification time when it
    was read, its readable lines, how many bytes they take (the rest is a
    line cut short), and their timeline once asked for."""

    size: int
    mtime: int
    changes: list[Change]
    valid: int
    timeline: Timeline | None = None


@dataclass(frozen=True)
class Snapshot:
    name: str
    time: float
    #: Why it was taken: `timer`, `download`, `manual`.
    reason: str
    #: The journal position it was taken at, and that state's label.
    seq: int
    label: str
    text: str
    assets: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "time": self.time, "reason": self.reason, "seq": self.seq,
                "label": self.label, "text": self.text, "assets": self.assets}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(str(data["name"]), float(data["time"]), str(data["reason"]),
                   int(data["seq"]), str(data["label"]), str(data["text"]),
                   {str(k): str(v) for k, v in data["assets"].items()})


def default_root() -> Path:
    """`$XDG_STATE_HOME/wfb/studio`, `~/.local/state/wfb/studio` without it."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "wfb" / "studio"


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def replay(journal: list[Change]) -> Timeline:
    """The timeline a journal leaves."""
    line = Timeline()
    by_seq: dict[int, int] = {}
    for entry in journal:
        if entry.kind == CHANGE:
            for gone in line.states[line.cursor + 1:]:
                del by_seq[gone.seq]
            del line.states[line.cursor + 1:]
            if entry.merge and line.states:
                del by_seq[line.states[-1].seq]
                line.states[-1] = entry
            else:
                line.states.append(entry)
            line.cursor = len(line.states) - 1
            by_seq[entry.seq] = line.cursor
        elif entry.target in by_seq:
            line.cursor = by_seq[entry.target]
    return line


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._journals: dict[str, _Journal] = {}
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"cannot create the history store at {root}: {exc}") from exc

    def _dir(self, doc_id: str) -> Path:
        if not _ID.match(doc_id):
            raise UnknownDocument(doc_id)
        path = self.root / doc_id
        if not (path / "meta.json").is_file():
            raise UnknownDocument(doc_id)
        return path

    # -- documents ------------------------------------------------------------------

    def new_document(self, name: str, owner: str = OWNER) -> str:
        doc_id = uuid.uuid4().hex
        path = self.root / doc_id
        try:
            (path / "blobs").mkdir(parents=True)
            _write_atomic(path / "meta.json",
                          json.dumps({"name": name, "created": time.time(),
                                      "owner": owner}).encode())
        except OSError as exc:
            shutil.rmtree(path, ignore_errors=True)
            raise StoreError(f"cannot write to the history store: {exc}") from exc
        return doc_id

    def meta(self, doc_id: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self._dir(doc_id) / "meta.json").read_text())
        return data

    def owner(self, doc_id: str) -> str:
        """The principal ``doc_id`` belongs to."""
        return str(self.meta(doc_id).get("owner") or OWNER)

    def documents(self, owner: str | None = None) -> list[dict[str, Any]]:
        """Every document with a recorded change (``owner``'s only, when
        given), most recently changed first."""
        out = []
        for path in self.root.iterdir():
            if not _ID.match(path.name):
                continue
            try:
                meta = self.meta(path.name)
                head = self.head(path.name)
                snapshots = len(self._snapshot_files(path.name))
            except (UnknownDocument, OSError, ValueError):
                continue
            if head is None or (owner is not None and (meta.get("owner") or OWNER) != owner):
                continue
            out.append({"id": path.name, "name": meta["name"], "created": meta["created"],
                        "changed": head.time, "version": head.seq, "snapshots": snapshots})
        return sorted(out, key=lambda d: d["changed"], reverse=True)

    def delete(self, doc_id: str) -> None:
        shutil.rmtree(self._dir(doc_id))
        self._journals.pop(doc_id, None)

    # -- blobs ------------------------------------------------------------------------

    def put(self, doc_id: str, data: bytes, compress: bool = False) -> str:
        """Store ``data`` once, by its hash; ``compress`` keeps it deflated."""
        sha = hashlib.sha256(data).hexdigest()
        blobs = self._dir(doc_id) / "blobs"
        if not (blobs / sha).exists() and not (blobs / f"{sha}.z").exists():
            try:
                if compress:
                    _write_atomic(blobs / f"{sha}.z", zlib.compress(data, 6))
                else:
                    _write_atomic(blobs / sha, data)
            except OSError as exc:
                raise StoreError(f"cannot write to the history store: {exc}") from exc
        return sha

    def get(self, doc_id: str, sha: str) -> bytes:
        if not _SHA.match(sha):
            raise StoreError(f"not a blob id: {sha!r}")
        blobs = self._dir(doc_id) / "blobs"
        packed = blobs / f"{sha}.z"
        if packed.exists():
            return zlib.decompress(packed.read_bytes())
        return (blobs / sha).read_bytes()

    def text(self, doc_id: str, state: Change | Snapshot) -> str:
        return self.get(doc_id, state.text).decode("utf-8")

    # -- the journal --------------------------------------------------------------------

    def append(self, doc_id: str, label: str, text: str, assets: dict[str, bytes | str],
               merge: bool = False) -> Change:
        """Record a change: ``text`` and ``assets`` (bytes to store, or the
        hash of a blob already stored) become the document's head.  With
        ``merge`` it takes the place of the state before it on the line."""
        manifest = {path: (self.put(doc_id, v) if isinstance(v, bytes) else v)
                    for path, v in sorted(assets.items())}
        return self._write(doc_id, label, self.put(doc_id, text.encode("utf-8"), compress=True),
                           manifest, CHANGE, None, merge)

    def move(self, doc_id: str, kind: str, label: str, state: Change) -> Change:
        """Record an undo or redo to ``state``, a `change` line."""
        return self._write(doc_id, label, state.text, dict(state.assets), kind, state.seq)

    def _write(self, doc_id: str, label: str, text: str, manifest: dict[str, str], kind: str,
               target: int | None, merge: bool = False) -> Change:
        read = self._read(doc_id)
        head = read.changes[-1] if read.changes else None
        change = Change((head.seq + 1) if head else 1, time.time(), label, text, manifest,
                        kind, target, merge)
        path = self._dir(doc_id) / "journal.jsonl"
        if read.size != read.valid:
            self._set_aside(path, read.valid)
        try:
            with open(path, "a", encoding="utf-8") as out:
                out.write(json.dumps(change.to_json()) + "\n")
                out.flush()
                os.fsync(out.fileno())
        except OSError as exc:
            # The line may be in the file already: a change reported refused
            # must not come back as applied after a restart.
            self._journals.pop(doc_id, None)
            try:
                with open(path, "r+b") as out:
                    out.truncate(read.valid)
            except OSError:
                pass
            raise StoreError(f"cannot write to the history store: {exc}") from exc
        stat = path.stat()
        self._journals[doc_id] = _Journal(stat.st_size, stat.st_mtime_ns,
                                          [*read.changes, change], stat.st_size)
        return change

    def _set_aside(self, path: Path, valid: int) -> None:
        """Cut ``path`` back to its first ``valid`` bytes, its whole lines,
        keeping what follows in a `.torn-<ms>` file beside it."""
        try:
            with open(path, "r+b") as journal:
                journal.seek(valid)
                torn = journal.read()
                _write_atomic(path.with_name(f"{path.name}.torn-{int(time.time() * 1000)}"),
                              torn)
                journal.truncate(valid)
                journal.flush()
                os.fsync(journal.fileno())
        except OSError as exc:
            raise StoreError(f"cannot repair the history store's journal: {exc}") from exc

    def _read(self, doc_id: str) -> _Journal:
        """The journal, from memory while the file is as it was read."""
        path = self._dir(doc_id) / "journal.jsonl"
        try:
            stat = path.stat()
        except FileNotFoundError:
            return _Journal(0, 0, [], 0)
        cached = self._journals.get(doc_id)
        if cached is not None and (cached.size, cached.mtime) == (stat.st_size,
                                                                   stat.st_mtime_ns):
            return cached
        data = path.read_bytes()
        changes: list[Change] = []
        valid = 0
        for line in data.splitlines(keepends=True):
            # A line cut short by a crash mid-append, or one with no end:
            # everything before it was acknowledged, it was not.
            if not line.endswith(b"\n"):
                break
            try:
                changes.append(Change.from_json(json.loads(line)))
            except (ValueError, KeyError, TypeError, AttributeError):
                break
            valid += len(line)
        read = _Journal(len(data), stat.st_mtime_ns, changes, valid)
        self._journals[doc_id] = read
        return read

    def journal(self, doc_id: str) -> list[Change]:
        return list(self._read(doc_id).changes)

    def head(self, doc_id: str) -> Change | None:
        changes = self._read(doc_id).changes
        return changes[-1] if changes else None

    def timeline(self, doc_id: str) -> Timeline:
        read = self._read(doc_id)
        if read.timeline is None:
            read.timeline = replay(read.changes)
        return read.timeline

    # -- snapshots ---------------------------------------------------------------------

    def _snapshot_files(self, doc_id: str) -> list[Path]:
        folder = self._dir(doc_id) / "snapshots"
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.glob("*.json") if _SNAPSHOT.match(p.stem))

    def snapshot(self, doc_id: str, state: Change, reason: str,
                 now: float | None = None) -> Snapshot:
        """Keep ``state`` (the document's head) as a point in time."""
        now = time.time() if now is None else now
        snap = Snapshot(f"{state.seq:08d}-{int(now * 1000)}", now, reason, state.seq,
                        state.label, state.text, dict(state.assets))
        folder = self._dir(doc_id) / "snapshots"
        try:
            folder.mkdir(exist_ok=True)
            _write_atomic(folder / f"{snap.name}.json", json.dumps(snap.to_json()).encode())
        except OSError as exc:
            raise StoreError(f"cannot write to the history store: {exc}") from exc
        return snap

    def snapshots(self, doc_id: str) -> list[Snapshot]:
        """Oldest first."""
        out = []
        for path in self._snapshot_files(doc_id):
            try:
                out.append(Snapshot.from_json(json.loads(path.read_text())))
            except (ValueError, KeyError):
                continue
        return sorted(out, key=lambda s: s.time)

    def get_snapshot(self, doc_id: str, name: str) -> Snapshot:
        if not _SNAPSHOT.match(name):
            raise UnknownSnapshot(name)
        path = self._dir(doc_id) / "snapshots" / f"{name}.json"
        if not path.is_file():
            raise UnknownSnapshot(name)
        return Snapshot.from_json(json.loads(path.read_text()))

    # -- pruning -----------------------------------------------------------------------

    def prune(self, *, keep_snapshots: int) -> list[str]:
        """Remove every snapshot past a document's newest ``keep_snapshots``.
        A document itself is never removed but by its owner.  Returns one
        line per removal, for the log."""
        removed: list[str] = []
        for doc in self.documents():
            snaps = self.snapshots(doc["id"])
            folder = self._dir(doc["id"]) / "snapshots"
            for snap in snaps[:max(0, len(snaps) - keep_snapshots)]:
                (folder / f"{snap.name}.json").unlink()
                removed.append(f"{doc['name']}: snapshot {snap.name}")
        return removed
