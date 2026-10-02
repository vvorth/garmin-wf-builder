"""The editor's durable state: every document's history, outside the
volatile directories the compiler reads.

One directory per document under the store's root:

- `meta.json`: the display name and when the document was created;
- `blobs/<sha256>`: every text version and every asset file, content
  addressed, so a long history of a small face costs little and an asset
  is stored once;
- `journal.jsonl`: one JSON line per change, appended and flushed to disk
  before the change is acknowledged.  Each line names the resulting text
  and asset manifest by hash, so the last line *is* the document.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: A document id: what `new_document` mints, and all a path may be built from.
_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class StoreError(OSError):
    """The store could not be read or written; the change is not applied."""


class UnknownDocument(KeyError):
    """No document with that id is in the store."""


@dataclass(frozen=True)
class Change:
    """One journal line."""

    seq: int
    time: float
    label: str
    text: str
    assets: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "time": self.time, "label": self.label,
                "text": self.text, "assets": self.assets}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Change":
        return cls(int(data["seq"]), float(data["time"]), str(data["label"]),
                   str(data["text"]), {str(k): str(v) for k, v in data["assets"].items()})


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


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
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

    def new_document(self, name: str) -> str:
        doc_id = uuid.uuid4().hex
        path = self.root / doc_id
        try:
            (path / "blobs").mkdir(parents=True)
            _write_atomic(path / "meta.json",
                          json.dumps({"name": name, "created": time.time()}).encode())
        except OSError as exc:
            shutil.rmtree(path, ignore_errors=True)
            raise StoreError(f"cannot write to the history store: {exc}") from exc
        return doc_id

    def meta(self, doc_id: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self._dir(doc_id) / "meta.json").read_text())
        return data

    def documents(self) -> list[dict[str, Any]]:
        """Every document with a recorded change, most recently changed first."""
        out = []
        for path in self.root.iterdir():
            if not _ID.match(path.name):
                continue
            try:
                meta = self.meta(path.name)
                head = self.head(path.name)
            except (UnknownDocument, OSError, ValueError):
                continue
            if head is None:
                continue
            out.append({"id": path.name, "name": meta["name"], "created": meta["created"],
                        "changed": head.time, "version": head.seq})
        return sorted(out, key=lambda d: d["changed"], reverse=True)

    def delete(self, doc_id: str) -> None:
        shutil.rmtree(self._dir(doc_id))

    # -- blobs ------------------------------------------------------------------------

    def put(self, doc_id: str, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self._dir(doc_id) / "blobs" / sha
        if not path.exists():
            try:
                _write_atomic(path, data)
            except OSError as exc:
                raise StoreError(f"cannot write to the history store: {exc}") from exc
        return sha

    def get(self, doc_id: str, sha: str) -> bytes:
        if not _SHA.match(sha):
            raise StoreError(f"not a blob id: {sha!r}")
        return (self._dir(doc_id) / "blobs" / sha).read_bytes()

    # -- the journal --------------------------------------------------------------------

    def append(self, doc_id: str, label: str, text: str, assets: dict[str, bytes | str]
               ) -> Change:
        """Record a change: ``text`` and ``assets`` (bytes to store, or the
        hash of a blob already stored) become the document's head."""
        manifest = {path: (self.put(doc_id, v) if isinstance(v, bytes) else v)
                    for path, v in sorted(assets.items())}
        head = self.head(doc_id)
        change = Change((head.seq + 1) if head else 1, time.time(), label,
                        self.put(doc_id, text.encode("utf-8")), manifest)
        try:
            with open(self._dir(doc_id) / "journal.jsonl", "a", encoding="utf-8") as out:
                out.write(json.dumps(change.to_json()) + "\n")
                out.flush()
                os.fsync(out.fileno())
        except OSError as exc:
            raise StoreError(f"cannot write to the history store: {exc}") from exc
        return change

    def journal(self, doc_id: str) -> list[Change]:
        path = self._dir(doc_id) / "journal.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(Change.from_json(json.loads(line)))
            except (ValueError, KeyError):
                # A line cut short by a crash mid-append: everything before
                # it was acknowledged, it was not.
                break
        return out

    def head(self, doc_id: str) -> Change | None:
        journal = self.journal(doc_id)
        return journal[-1] if journal else None

    def text(self, doc_id: str, change: Change) -> str:
        return self.get(doc_id, change.text).decode("utf-8")
