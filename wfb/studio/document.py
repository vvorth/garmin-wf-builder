"""The editor's open faces.

A `Document` is one face: its head in the history store (`store.py`) and a
temporary directory holding `face.yaml` and its files, which is what the
compiler reads, so relative font paths resolve exactly as they would on
disk.  The directory is disposable: it is rebuilt from the store whenever it
is missing, so the store alone is the document.

The pipeline runs once per version: the load, one resolve per target (font
sheets reused through a `BakeMemo` shared by every document), and the lint.
A frame -- one device, one set of switches -- is rendered on demand and kept
for that version.
"""

from __future__ import annotations

import base64
import io
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ..build import resolve_all, select_devices
from ..devices import DeviceDatabase
from ..diagnostics import Bag, Diagnostic
from ..edit import Gate, Refused, SpanIndex, set_value
from ..edit.gate import load_text
from ..edit.spans import ELEMENT_BLOCKS, Entry, is_element
from ..emit.resources import BakeMemo
from ..ir import Face
from ..layout import ResolvedFace
from .bundle import FACE, Bundle, asset_path, missing, references
from .store import REDO, UNDO, Change, Snapshot, Store, UnknownDocument


class StaleVersion(ValueError):
    """A change asked for against a version that is no longer the head."""


@dataclass(frozen=True)
class FrameKey:
    device: str
    style: str | None = None
    time: tuple[int, int, int] | None = None
    asleep: bool = False
    aod: bool = False
    scale: int = 2


@dataclass
class Analysis:
    """One version through the pipeline."""

    version: int
    face: Face | None
    bag: Bag
    resolved: dict[str, ResolvedFace] = field(default_factory=dict)


def _png(image: Any) -> str:
    out = io.BytesIO()
    # Loopback has bandwidth to spare; encoding time is what a frame waits on.
    image.save(out, format="PNG", compress_level=1)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


class Document:
    def __init__(self, studio: "Studio", doc_id: str) -> None:
        self.studio = studio
        self.id = doc_id
        store = studio.store
        meta = store.meta(doc_id)
        head = store.head(doc_id)
        if head is None:
            raise UnknownDocument(doc_id)
        self.name: str = meta["name"]
        self.head: Change = head
        self.text = store.text(doc_id, head)
        self.directory = studio.scratch / doc_id
        self._analysis: Analysis | None = None
        self._frames: OrderedDict[FrameKey, dict[str, Any]] = OrderedDict()
        #: What `materialise` last wrote, by path: the content it holds.
        self._written: dict[PurePosixPath, str] = {}
        snapshots = store.snapshots(doc_id)
        #: When the last snapshot was taken, and of which version; with none,
        #: the document's first change stands in, so the timer's first
        #: snapshot comes an interval after it.
        self.last_snapshot: tuple[float, int | None] = (
            (snapshots[-1].time, snapshots[-1].seq) if snapshots
            else (store.journal(doc_id)[0].time, None))
        self.materialise()

    @property
    def version(self) -> int:
        return self.head.seq

    @property
    def path(self) -> Path:
        return self.directory / FACE

    # -- the directory --------------------------------------------------------------

    def materialise(self) -> None:
        """Bring the directory to the head: `face.yaml` and exactly the files
        of its manifest.  A file already there with the right content is
        left alone, so its modification time -- part of the font-bake memo's
        key -- survives an edit that did not touch it."""
        store = self.studio.store
        self.directory.mkdir(parents=True, exist_ok=True)
        wanted = {PurePosixPath(rel): sha for rel, sha in self.head.assets.items()}
        for path in sorted(self.directory.rglob("*"), reverse=True):
            rel = PurePosixPath(path.relative_to(self.directory).as_posix())
            if path.is_dir():
                if not any(path.iterdir()):
                    path.rmdir()
            elif str(rel) != FACE and rel not in wanted:
                path.unlink()
        for rel, sha in wanted.items():
            target = self.directory / rel
            if self._written.get(rel) == sha and target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.get(self.id, sha))
            self._written[rel] = sha
        if not self.path.is_file() or self.path.read_text(encoding="utf-8") != self.text:
            self.path.write_text(self.text, encoding="utf-8")

    def ensure_directory(self) -> None:
        if not self.path.is_file():
            self._written.clear()
            self.materialise()

    # -- changes ----------------------------------------------------------------------

    def commit(self, text: str, assets: dict[str, bytes | str], label: str,
               expected: int) -> Change:
        """Record a change against version ``expected``; refused when that is
        no longer the head, so two tabs cannot overwrite each other."""
        self._check(expected)
        return self._moved(self.studio.store.append(self.id, label, text, assets))

    def _check(self, expected: int) -> None:
        if expected != self.version:
            raise StaleVersion(f"the face is at version {self.version}, not {expected}: "
                               "reload it to see the newer change")

    def _moved(self, change: Change) -> Change:
        """Make ``change``, just recorded, the head."""
        self.head = change
        self.text = self.studio.store.text(self.id, change)
        self._analysis = None
        self._frames.clear()
        self.materialise()
        return change

    # -- history ----------------------------------------------------------------------

    def undo(self, expected: int) -> Change:
        self._check(expected)
        line = self.studio.store.timeline(self.id)
        if not line.can_undo:
            raise Refused("there is nothing to undo")
        undone = line.states[line.cursor]
        return self._moved(self.studio.store.move(
            self.id, UNDO, f"undo {undone.label}", line.states[line.cursor - 1]))

    def redo(self, expected: int) -> Change:
        self._check(expected)
        line = self.studio.store.timeline(self.id)
        if not line.can_redo:
            raise Refused("there is nothing to redo")
        state = line.states[line.cursor + 1]
        return self._moved(self.studio.store.move(self.id, REDO, f"redo {state.label}", state))

    def snapshot(self, reason: str, now: float | None = None) -> Snapshot:
        snap = self.studio.store.snapshot(self.id, self.head, reason, now)
        self.last_snapshot = (snap.time, snap.seq)
        return snap

    def restore(self, name: str, expected: int) -> Change:
        """Make a snapshot the head, as one change: undoable like any other."""
        self._check(expected)
        store = self.studio.store
        snap = store.get_snapshot(self.id, name)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.time))
        return self.commit(store.text(self.id, snap), dict(snap.assets),
                           f"restore the snapshot of {when}", expected)

    def history(self) -> dict[str, Any]:
        store = self.studio.store
        line = store.timeline(self.id)
        return {
            "version": self.version,
            "can_undo": line.can_undo, "can_redo": line.can_redo,
            # newest first, the states past the cursor marked as redoable
            "states": [{"seq": c.seq, "time": c.time, "label": c.label,
                        "current": i == line.cursor, "redo": i > line.cursor}
                       for i, c in reversed(list(enumerate(line.states)))],
            "snapshots": [{"name": s.name, "time": s.time, "reason": s.reason,
                           "seq": s.seq, "label": s.label, "current": s.seq == self.version}
                          for s in reversed(store.snapshots(self.id))],
        }

    def add_asset(self, filename: str, data: bytes, reference: str | None,
                  expected: int) -> Change:
        """Store an uploaded file under `assets/` and point every font whose
        `source:` is written ``reference`` at it, as one change.  Each patch
        rewrites only that value's characters."""
        if expected != self.version:
            raise StaleVersion(f"the face is at version {self.version}, not {expected}: "
                               "reload it to see the newer change")
        assets: dict[str, bytes | str] = dict(self.head.assets)
        rel = asset_path(assets, filename)
        assets[rel] = data
        text = self.text
        if reference is not None:
            if not any(r.value == reference for r in missing(text, self.head.assets)):
                raise Refused(f"no missing font source is written {reference!r}")
            # The gate loads the patched text from the directory, so the
            # file has to be there first; a refusal rebuilds the directory.
            target = self.directory / PurePosixPath(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            try:
                text = self.repoint(text, {reference: rel})
            except Refused:
                self.materialise()
                raise
        label = f"add {rel}" + (f" for {reference}" if reference is not None else "")
        return self.commit(text, assets, label, expected)

    def repoint(self, text: str, moved: dict[str, str]) -> str:
        """``text`` with every font `source:` written as a key of ``moved``
        rewritten to its value, each patch through the gate."""
        for ref in [r for r in references(text)
                    if r.value in moved and moved[r.value] != r.value]:
            patch = set_value(SpanIndex(text), ref.path, moved[ref.value])
            Gate(self.path, text).check(patch)
            text = patch.text
        return text

    # -- the bundle -------------------------------------------------------------------

    def bundle(self) -> Bundle:
        store = self.studio.store
        return Bundle(self.name, self.text,
                      {rel: store.get(self.id, sha) for rel, sha in self.head.assets.items()})

    def missing(self) -> list[str]:
        return [r.value for r in missing(self.text, self.head.assets)]

    # -- the pipeline -----------------------------------------------------------------

    def analysis(self) -> Analysis:
        if self._analysis is not None and self._analysis.version == self.version:
            return self._analysis
        self.ensure_directory()
        loaded = load_text(self.path, self.text)
        bag = loaded.bag
        analysis = Analysis(self.version, loaded.face, bag)
        if loaded.face is not None:
            devices = select_devices(loaded.face, self.studio.db, bag)
            if devices:
                analysis.resolved, _ = resolve_all(loaded.face, devices, bag, self.studio.memo)
        self._analysis = analysis
        return analysis

    def diagnostics(self) -> list[dict[str, Any]]:
        return [self._diagnostic(d) for d in self.analysis().bag.items]

    def _diagnostic(self, d: Diagnostic) -> dict[str, Any]:
        out: dict[str, Any] = {"severity": d.severity.value, "code": d.code,
                               "message": self._shown(d.message),
                               "notes": [self._shown(n) for n in d.notes]}
        if d.span is not None:
            out.update(file=self.shown_path(d.span.path), line=d.span.line, col=d.span.col)
        return out

    def _shown(self, text: str) -> str:
        """``text`` with the temporary directory taken out of any path it
        quotes (a missing font's note names where it looked)."""
        for prefix in {str(self.directory), str(self.directory.resolve())}:
            text = text.replace(prefix + "/", "")
        return text

    def shown_path(self, path: Path) -> str:
        """A path as the author knows it: relative to the face's own
        directory, never the temporary one."""
        try:
            return Path(path).resolve().relative_to(self.directory.resolve()).as_posix()
        except ValueError:
            return Path(path).name

    def frame(self, key: FrameKey) -> dict[str, Any]:
        """One frame: the composed image, and each layer with its box."""
        from ..draw.layers import compose, layers
        from ..preview import PreviewOptions

        cached = self._frames.get(key)
        if cached is not None:
            self._frames.move_to_end(key)
            return cached
        analysis = self.analysis()
        resolved = analysis.resolved.get(key.device)
        if resolved is None:
            raise Refused(f"{key.device} is not drawn: the face does not load, "
                          "or does not target it")
        options = PreviewOptions(scale=key.scale, style=key.style, time=key.time,
                                 asleep=key.asleep, aod=key.aod)
        stack = layers(resolved, options)
        boxes = {item.id: item.box for item in resolved.items}
        out_layers = []
        for layer in stack:
            box = boxes.get(layer.id[len("ring:"):] if layer.kind == "ring" else layer.id)
            # Only the layer's ink travels: a full-frame, mostly clear RGBA
            # image per layer costs most of a frame's encoding time.
            ink = layer.image.getchannel("A").getbbox()
            out_layers.append({
                "id": layer.id, "kind": layer.kind,
                "line": layer.span.line if layer.span is not None else None,
                "box": [box.x, box.y, box.width, box.height] if box is not None else None,
                "origin": [ink[0], ink[1]] if ink else None,
                "image": _png(layer.image.crop(ink)) if ink else None,
            })
        device = resolved.device
        frame = {
            "version": self.version, "device": device.id, "scale": key.scale,
            "width": device.width, "height": device.height, "shape": device.shape,
            "frame": _png(compose(stack, resolved, options)),
            "layers": out_layers,
        }
        self._frames[key] = frame
        while len(self._frames) > 24:
            self._frames.popitem(last=False)
        return frame

    # -- what the editor shows ----------------------------------------------------------

    def tree(self) -> list[dict[str, Any]]:
        """The face's element blocks in draw order, each element with its
        children: shared `static:` then `elements:`, then each layout's own
        two."""
        try:
            index = SpanIndex(self.text)
        except Refused:
            return []
        blocks: list[dict[str, Any]] = []
        for path, label in _block_paths(index):
            entry = index.get(path)
            if entry is None:
                continue
            blocks.append({"kind": "block", "label": label, "path": list(path),
                           "line": entry.key.start_mark.line + 1,
                           "children": _children(index, entry)})
        return blocks

    def summary(self) -> dict[str, Any]:
        analysis = self.analysis()
        face = analysis.face
        styles: list[dict[str, str]] = []
        if face is not None and face.config_style is not None:
            styles = [{"name": e.name, "label": getattr(e, "label", None) or e.name}
                      for e in face.config_style.entries]
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "text": self.text, "missing": self.missing(),
            "loads": face is not None,
            "targets": list(analysis.resolved),
            "styles": styles,
            "tree": self.tree(),
            "diagnostics": self.diagnostics(),
            "assets": sorted(self.head.assets),
            "history": self.history(),
        }


def _block_paths(index: SpanIndex) -> list[tuple[tuple[str, ...], str]]:
    out: list[tuple[tuple[str, ...], str]] = [(("static",), "static"),
                                               (("elements",), "elements")]
    layouts = index.data.get("layouts") if isinstance(index.data, dict) else None
    if isinstance(layouts, dict):
        for name in layouts:
            out.append((("layouts", str(name), "static"), f"{name}: static"))
            out.append((("layouts", str(name), "elements"), f"{name}: elements"))
    return out


def _children(index: SpanIndex, block: Entry) -> list[dict[str, Any]]:
    out = []
    for entry in index.entries():
        if len(entry.path) != len(block.path) + 1 or entry.path[:-1] != block.path:
            continue
        if not is_element(index, entry):
            continue
        data = index.data
        for step in entry.path:
            data = data[step]
        node: dict[str, Any] = {"kind": "element", "id": entry.name, "type": data.get("type"),
                                "path": list(entry.path),
                                "line": entry.key.start_mark.line + 1, "children": []}
        for sub in ELEMENT_BLOCKS:
            child_block = index.get(entry.path + (sub,))
            if child_block is not None:
                node["children"].extend(_children(index, child_block))
        out.append(node)
    return out


#: `wfb studio --snapshot-minutes`'s default.
SNAPSHOT_MINUTES = 5.0


class Studio:
    """Every document this server has open, over one store and one device
    database.  One lock serialises the pipeline: it is CPU-bound, and the
    memo and caches are shared.

    ``on_event(name, data)`` is told what the server did on its own (a
    snapshot taken by the timer), for the event stream."""

    def __init__(self, store: Store, db: DeviceDatabase, scratch: Path | None = None, *,
                 snapshot_minutes: float = SNAPSHOT_MINUTES) -> None:
        self.store = store
        self.db = db
        self.memo = BakeMemo()
        self._own_scratch = scratch is None
        self.scratch = scratch or Path(tempfile.mkdtemp(prefix="wfb-studio-"))
        self.lock = threading.RLock()
        self._open: dict[str, Document] = {}
        self.snapshot_seconds = snapshot_minutes * 60
        self.on_event: Callable[[str, dict[str, Any]], None] = lambda name, data: None
        self._stop = threading.Event()
        self._timer: threading.Thread | None = None

    def close(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.join(timeout=5)
        if self._own_scratch:
            shutil.rmtree(self.scratch, ignore_errors=True)

    # -- snapshots on the timer ---------------------------------------------------------

    def tick(self, now: float | None = None) -> list[Snapshot]:
        """Snapshot every open document that changed since its last
        snapshot, once an interval has passed since that one."""
        now = time.time() if now is None else now
        taken = []
        with self.lock:
            for doc in list(self._open.values()):
                when, seq = doc.last_snapshot
                if seq != doc.version and now - when >= self.snapshot_seconds:
                    snap = doc.snapshot("timer", now)
                    taken.append(snap)
                    self.on_event("snapshot", {"id": doc.id, "name": snap.name,
                                               "version": doc.version})
        return taken

    def start_timer(self) -> None:
        """Run `tick` in the background until `close`."""
        period = max(1.0, min(30.0, self.snapshot_seconds / 4))

        def run() -> None:
            while not self._stop.wait(period):
                try:
                    self.tick()
                except Exception as exc:  # the timer must outlive one bad document
                    self.on_event("error", {"message": f"snapshot failed: {exc}"})

        self._timer = threading.Thread(target=run, name="wfb-studio-snapshots", daemon=True)
        self._timer.start()

    def document(self, doc_id: str) -> Document:
        doc = self._open.get(doc_id)
        if doc is None:
            doc = Document(self, doc_id)
            self._open[doc_id] = doc
        return doc

    def create(self, bundle: Bundle, label: str,
               moved: dict[str, str] | None = None) -> Document:
        """A new document from ``bundle``.  ``moved`` maps references to the
        paths their files were gathered to (`bundle.from_path`); each is
        patched as a second, recorded change."""
        doc_id = self.store.new_document(bundle.name)
        self.store.append(doc_id, label, bundle.text, dict(bundle.files))
        doc = self.document(doc_id)
        if moved:
            doc.commit(doc.repoint(doc.text, moved), dict(doc.head.assets),
                       "gather assets into the bundle", doc.version)
        return doc

    def fork(self, doc_id: str, name: str) -> Document:
        """A new document holding a snapshot of ``doc_id``: "open as a copy"."""
        store = self.store
        snap = store.get_snapshot(doc_id, name)
        source = self.document(doc_id)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.time))
        bundle = Bundle(f"{source.name} ({when})", store.text(doc_id, snap),
                        {rel: store.get(doc_id, sha) for rel, sha in snap.assets.items()})
        return self.create(bundle, f"copy of {source.name}'s snapshot of {when}")

    def delete(self, doc_id: str) -> None:
        self._open.pop(doc_id, None)
        shutil.rmtree(self.scratch / doc_id, ignore_errors=True)
        self.store.delete(doc_id)
