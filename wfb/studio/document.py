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
import json
import re
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, cast

from ..build import resolve_all, select_devices
from ..devices import DeviceDatabase
from ..diagnostics import Bag, Diagnostic
from ..edit import (
    Gate, Refused, SpanIndex, remove, remove_slot, rename_key, rename_reference, rename_slot,
    set_value,
)
from ..edit.geometry import Part, Scope, target
from ..edit.gate import Loaded, load_text
from ..edit.spans import ELEMENT_BLOCKS, Entry, index_for, is_element
from ..emit.resources import BakeMemo
from ..ir import Face
from ..layout import ResolvedFace
from .inspect import GEOMETRY, globals_of, inspect
from .bundle import FACE, Bundle, asset_path, inside, missing, references
if TYPE_CHECKING:
    from .builder import Builder
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
        #: Frames, layers and thumbnails of this version, by what and key.
        self._frames: OrderedDict[tuple[str, FrameKey], Any] = OrderedDict()
        #: This version's load, with its own diagnostics only (`analysis`), and
        #: the gate's load of the text about to become the head.
        self._loaded: Loaded | None = None
        self._seed: Loaded | None = None
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
               expected: int, loaded: Loaded | None = None) -> Change:
        """Record a change against version ``expected``; refused when that is
        no longer the head, so two tabs cannot overwrite each other.
        ``loaded`` is ``text`` as the gate loaded it, reused by the analysis."""
        self._check(expected)
        change = self._moved(self.studio.store.append(self.id, label, text, assets))
        self._seed = loaded
        return change

    def _gate(self) -> Gate:
        """A gate over this version, reusing its load when the analysis ran."""
        before = self._loaded if self._loaded is not None and \
            self._loaded.text == self.text else None
        return Gate(self.path, self.text, before)

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
                  expected: int, font: tuple[str, str] | None = None) -> Change:
        """Store an uploaded file under `assets/`, as one change, and either
        point every font whose `source:` is written ``reference`` at it (a
        missing file added, or a font's file replaced), or declare it as a
        new font ``font`` = (name, size). A replaced file nothing else
        refers to leaves the bundle. Each patch passes the gate."""
        self._check(expected)
        assets: dict[str, bytes | str] = dict(self.head.assets)
        rel = asset_path(assets, filename)
        assets[rel] = data
        text = self.text
        # The gate loads the patched text from the directory, so the file has
        # to be there first; a refusal rebuilds the directory.
        target = self.directory / PurePosixPath(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            if reference is not None:
                if not any(r.value == reference for r in references(text)):
                    raise Refused(f"no font's source is written {reference!r}")
                text = self.repoint(text, {reference: rel})
                old = inside(reference)
                if old in assets and not any(r.inside == old for r in references(text)):
                    del assets[old]
                label = f"use {rel} for {reference}"
            elif font is not None:
                name, size = font
                index = index_for(text)
                if index.get(("resources", "fonts", name)) is not None:
                    raise Refused(f"there is already a font called {name}")
                patch = set_value(index, ("resources", "fonts", name),
                                  {"source": rel, "size": size})
                Gate(self.path, text).check(patch)
                text = patch.text
                label = f"add the font {name} from {rel}"
            else:
                label = f"add {rel}"
        except Refused:
            self.materialise()
            raise
        return self.commit(text, assets, label, expected)

    def edit(self, op: dict[str, Any], expected: int) -> Change:
        """One edit from the inspector or the global panel, gated and
        recorded:

        - `{"op": "set", "path": [...], "value": v}`;
        - `{"op": "remove", "path": [...]}`;
        - `{"op": "rename", "path": [...], "to": name, "prefix": "color."}`:
          a declared name and every reference to it; a `config: slots:`
          entry's references are the `slot:` keys naming it, and need no
          prefix; one is removed only while nothing draws it.

        A geometry key of an element (`element` and a `path` relative to it,
        such as `["at", "dy"]`) is written to the source ``scope`` names on
        ``device``: "all" (the element's own key), "device" or "shape" (its
        override, created when missing)."""
        self._check(expected)
        kind = op.get("op")
        if kind not in ("set", "remove", "rename"):
            raise Refused(f"unknown edit {kind!r}")
        index = index_for(self.text)
        path = _path(op.get("path"))
        if op.get("element") is not None:
            element = _path(op["element"])
            scope = op.get("scope", "all")
            if scope not in ("all", "device", "shape"):
                raise Refused(f"scope {scope!r} is not all, device or shape")
            if scope != "all" and (not path or path[0] not in GEOMETRY):
                raise Refused(f"{'.'.join(map(str, path))} cannot be overridden per "
                              "device; only at:, size:, radius: and align: can")
            device = self.studio.db.get(str(op.get("device"))) if scope != "all" else None
            path = (target(index, element, path, device, scope) if device is not None
                    else element + path)
        shown = ".".join(str(p) for p in path)
        if kind == "set":
            value = op.get("value")
            patch = set_value(index, path, value)
            label = f"set {shown} to {_shown_value(value)}"
        elif kind == "remove":
            if index.get(path) is None:
                raise Refused(f"{shown} is not set")
            patch = (remove_slot(index, str(path[2]))
                     if len(path) == 3 and path[:2] == ("config", "slots") else remove(index, path))
            label = f"remove {shown}"
        else:
            to = str(op.get("to", "")).strip()
            prefix = str(op.get("prefix", ""))
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", to):
                raise Refused(f"{to!r} is not a name: letters, digits and _, "
                              "not starting with a digit")
            if len(path) == 3 and path[:2] == ("config", "slots"):
                patch = rename_slot(index, str(path[2]), to)
            elif prefix:
                patch = rename_reference(index, path, to, prefix)
            else:
                patch = rename_key(index, path, to)
            label = f"rename {shown} to {to}"
        after = self._gate().check(patch)
        return self.commit(patch.text, dict(self.head.assets), label, expected, after)

    def replace_text(self, text: str, expected: int) -> Change:
        """The whole text as the author typed it in the YAML tab, against
        version ``expected``. Unlike a patch from the canvas, inspector or
        tree, it is not refused for an error the load reports: someone
        typing passes through broken states, and the YAML tab is where they
        are mended, with the diagnostics beside the text. Text that is not
        YAML at all is refused, not recorded, so the author keeps typing."""
        self._check(expected)
        if text == self.text:
            return self.head
        index_for(text)          # Refused when it is not YAML
        loaded = load_text(self.path, text)
        return self.commit(text, dict(self.head.assets), "edit the text", expected, loaded)

    def structure(self, op: dict[str, Any], expected: int) -> tuple[Change, str | None]:
        """One structural edit from the layer tree or the canvas, gated and
        recorded; also the id to select after it (a new element, a copy, a
        new group):

        - `{"op": "add", "type": t, "block": [...], "before": id, "choice": c}`;
        - `{"op": "delete" | "duplicate" | "ungroup", "path": [...]}`;
        - `{"op": "move", "path": [...], "block": [...], "before": id}`: within
          its own block a reorder, else into the other block;
        - `{"op": "group", "paths": [[...], ...]}`."""
        from ..edit import (
            add, delete_element, duplicate_element, group, move_element, move_to_block,
            ungroup,
        )

        self._check(expected)
        index = index_for(self.text)
        kind = op.get("op")
        select: str | None = None
        if kind == "add":
            block = _path(op.get("block") or ["elements"])
            before = op.get("before") or None
            patch = add(index, str(op.get("type")), block, before, choice=op.get("choice"))
            select = next(iter(set(index_for(patch.text).element_ids())
                               - index.element_ids()), None)
        elif kind in ("delete", "duplicate", "ungroup"):
            path = _path(op.get("path"))
            patch = {"delete": delete_element, "duplicate": duplicate_element,
                     "ungroup": ungroup}[kind](index, path)
            if kind == "duplicate":
                select = next(iter(set(index_for(patch.text).element_ids())
                                   - index.element_ids()), None)
        elif kind == "move":
            path = _path(op.get("path"))
            block = _path(op.get("block") or list(path[:-1]))
            before = op.get("before") or None
            if block == path[:-1]:
                siblings = [e.name for e in index.entries()
                            if e.path[:-1] == block and is_element(index, e)]
                if path[-1] not in siblings or (before is not None and before not in siblings):
                    raise Refused(f"{before} is not in {'.'.join(map(str, block))}")
                order = [n for n in siblings if n != path[-1]]
                to = order.index(before) if before is not None else len(order)
                patch = move_element(index, path, to)
            else:
                patch = move_to_block(index, path, block, before)
            select = str(path[-1])
        elif kind == "group":
            paths = op.get("paths")
            if not isinstance(paths, list):
                raise Refused("a group is made of a list of paths")
            patch = group(index, [_path(p) for p in paths])
            select = next(iter(set(index_for(patch.text).element_ids())
                               - index.element_ids()), None)
        else:
            raise Refused(f"unknown structural edit {kind!r}")
        after = self._gate().check(patch)
        change = self.commit(patch.text, dict(self.head.assets), patch.what, expected, after)
        return change, select

    def repoint(self, text: str, moved: dict[str, str]) -> str:
        """``text`` with every font `source:` written as a key of ``moved``
        rewritten to its value, each patch through the gate."""
        for ref in [r for r in references(text)
                    if r.value in moved and moved[r.value] != r.value]:
            patch = set_value(index_for(text), ref.path, moved[ref.value])
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
        # The gate's load of an accepted patch is this version's load.
        seed, self._seed = self._seed, None
        loaded = seed if seed is not None and seed.text == self.text else load_text(
            self.path, self.text)
        # what the gate compares against: the load's own diagnostics, before
        # the resolve and the lint add theirs to the bag
        copy = Bag()
        copy.items = list(loaded.bag.items)
        self._loaded = Loaded(loaded.text, loaded.face, copy)
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

    def _placed(self, key: FrameKey) -> tuple[ResolvedFace, Any]:
        """This version on ``key.device``, and the preview options for ``key``."""
        from ..preview import PreviewOptions

        resolved = self.analysis().resolved.get(key.device)
        if resolved is None:
            raise Refused(f"{key.device} is not drawn: the face does not load, "
                          "or does not target it")
        return resolved, PreviewOptions(scale=key.scale, style=key.style, time=key.time,
                                        asleep=key.asleep, aod=key.aod)

    def _cached(self, kind: str, key: FrameKey, make: Callable[[], Any]) -> Any:
        slot = (kind, key)
        if slot in self._frames:
            self._frames.move_to_end(slot)
            return self._frames[slot]
        value = make()
        self._frames[slot] = value
        while len(self._frames) > 48:
            self._frames.popitem(last=False)
        return value

    def frame(self, key: FrameKey) -> dict[str, Any]:
        """One frame, fast: the image `wfb.preview.render` draws, and every
        element the frame shows (and every group in its layout) with its
        box, centre and drag handles. The layer images are `layers`."""
        from ..draw.frames import in_layout
        from ..preview import _resolve_style_entry, frame_items, render
        from .drag import handles

        def make() -> dict[str, Any]:
            resolved, options = self._placed(key)
            entry = _resolve_style_entry(resolved.face, options.style)
            drawn = {p.id for p in frame_items(resolved, options, entry)}
            layout = entry.layout if entry is not None else None
            # a group the author wrote; the `static:` block's and a layout's
            # own groups are containers, not elements
            authored = index_for(self.text).element_ids()
            items = []
            for placed in resolved.items:
                if placed.id not in drawn and not (
                        placed.kind == "group" and placed.id in authored
                        and in_layout(placed, layout)):
                    continue
                box = placed.box
                span = placed.element.span
                items.append({
                    "id": placed.id, "kind": placed.kind, "drawn": placed.id in drawn,
                    "line": span.line if span is not None else None,
                    "box": [box.x, box.y, box.width, box.height],
                    "center": list(placed.center), "handles": handles(placed),
                })
            device = resolved.device
            return {
                "version": self.version, "device": device.id, "scale": key.scale,
                "width": device.width, "height": device.height, "shape": device.shape,
                "minor_radius": device.minor_radius,
                "frame": _png(render(resolved, options)),
                "items": items,
            }
        frame: dict[str, Any] = self._cached("frame", key, make)
        return frame

    def layers(self, key: FrameKey) -> dict[str, Any]:
        """The frame as layers (`wfb.draw.layers`), each cropped to its ink
        with its origin in frame pixels: what hit-testing by alpha and a
        drag's moving image read. Slower than `frame`: every element is
        painted twice."""
        from ..draw.layers import layers

        def make() -> dict[str, Any]:
            resolved, options = self._placed(key)
            out = []
            for layer in layers(resolved, options):
                ink = layer.image.getchannel("A").getbbox()
                out.append({
                    "id": layer.id, "kind": layer.kind,
                    "origin": [ink[0], ink[1]] if ink else None,
                    "image": _png(layer.image.crop(ink)) if ink else None,
                })
            return {"version": self.version, "device": key.device, "scale": key.scale,
                    "layers": out}
        result: dict[str, Any] = self._cached("layers", key, make)
        return result

    def thumbnail(self, key: FrameKey) -> bytes:
        """The frame as a PNG file, for the strip of targets."""
        from ..preview import render

        def make() -> bytes:
            resolved, options = self._placed(key)
            out = io.BytesIO()
            render(resolved, options).save(out, format="PNG", compress_level=1)
            return out.getvalue()
        data: bytes = self._cached("thumb", key, make)
        return data

    def drag(self, element_id: str, gesture: dict[str, Any], device_id: str, scope: str,
             expected: int) -> tuple[Change, bool]:
        """One gesture on the canvas, on ``device_id``: written in the author's
        units to the key that device reads ("auto"), or to the scope named,
        through the gate. Returns the change and whether the element landed
        on the dragged pixel."""
        from ..edit import View, move, resize, turn
        from .drag import describe

        self._check(expected)
        if scope not in ("auto", "all", "device", "shape"):
            raise Refused(f"scope {scope!r} is not auto, all, device or shape")
        device = self.studio.db.get(device_id)
        analysis = self.analysis()
        view = View(self.path, self.text, device, loaded=self._loaded,
                    resolved=analysis.resolved.get(device_id), memo=self.studio.memo)
        kind = gesture.get("kind")
        where = cast(Scope, scope)
        part = gesture.get("part", "both")
        if part not in ("both", "at", "to"):
            raise Refused(f"part {part!r} is not both, at or to")
        try:
            if kind == "move":
                converted = move(view, element_id, int(gesture["dx"]), int(gesture["dy"]),
                                 where, part=cast(Part, part))
            elif kind == "resize":
                converted = resize(view, element_id, tuple(gesture["key"]),
                                   int(gesture["delta"]), where)
            elif kind == "turn":
                converted = turn(view, element_id, str(gesture["key"]),
                                 float(gesture["degrees"]), where)
            else:
                raise Refused(f"unknown gesture {kind!r}")
        except Refused:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise Refused(f"a {kind} gesture needs its values: {exc}") from None
        after = self._gate().check(converted.patch, view.tried)
        change = self.commit(converted.patch.text, dict(self.head.assets),
                             describe(gesture, element_id, device_id), expected, after)
        return change, converted.landed

    # -- what the editor shows ----------------------------------------------------------

    def tree(self) -> list[dict[str, Any]]:
        """The face's element blocks in draw order, each element with its
        children: shared `static:` then `elements:`, then each layout's own
        two. A block the face does not have yet is listed empty (`line`
        null), as somewhere an element can be moved or added."""
        try:
            index = index_for(self.text)
        except Refused:
            return []
        blocks: list[dict[str, Any]] = []
        for path, label in _block_paths(index):
            entry = index.get(path)
            blocks.append({"kind": "block", "label": label, "path": list(path),
                           "line": entry.key.start_mark.line + 1 if entry else None,
                           "children": _children(index, entry) if entry else []})
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
            "globals": globals_of(self.text, self.studio.db),
        }

    def inspect(self, element: Any, device_id: str | None) -> dict[str, Any]:
        device = self.studio.db.get(device_id) if device_id else None
        return inspect(self.text, _path(element), device)


def _path(raw: Any) -> tuple[str | int, ...]:
    """An author path from JSON: a list of keys and list indices."""
    if not isinstance(raw, list) or not all(isinstance(s, (str, int)) for s in raw):
        raise Refused("a path is a list of keys and indices")
    return tuple(raw)


def _shown_value(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= 40 else text[:37] + "..."


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
                                "line": entry.key.start_mark.line + 1,
                                # its last line: the text range the YAML tab selects
                                "end": index.text.count("\n", 0, index.value_end(entry)),
                                "children": []}
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
                 snapshot_minutes: float = SNAPSHOT_MINUTES,
                 builder: "Builder | None" = None) -> None:
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
        from .builder import Builder
        self.builder = builder or Builder()

    def close(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.join(timeout=5)
        self.builder.close()
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
