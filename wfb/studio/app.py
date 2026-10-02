"""The editor's HTTP surface: plain requests for everything the browser
asks, and one server-sent event stream for what the server announces.
Every message is JSON a `curl` can read.

Each endpoint's work is a plain function run in Starlette's thread pool
(`_endpoint`), with `Studio.lock` serialising the pipeline behind them.  An
upload is the request's raw body, read on the event loop first, with the
file name in the query: no multipart parser.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import starters
from ..build import slug
from ..devices import DeviceError
from ..edit import Refused
from .bundle import MAX_UPLOAD_BYTES, Bundle, BundleError, read_upload, to_zip
from .document import Document, FrameKey, StaleVersion, Studio
from .store import StoreError, UnknownDocument, UnknownSnapshot

STATIC = Path(__file__).resolve().parent / "static"


class Events:
    """Server-sent events to every open stream.  `publish` is called from
    the thread pool; each subscriber is an asyncio queue on the loop that
    serves it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]] = []

    def publish(self, event: str, data: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        entry = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._subscribers.append(entry)
        try:
            yield ": connected\n\n"
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subscribers.remove(entry)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


Handler = Callable[[Request, bytes], Response]


def _endpoint(handler: Handler, *, body: bool = False
              ) -> Callable[[Request], Awaitable[Response]]:
    """``handler`` as an endpoint: the body read first when it takes one,
    the work in the thread pool, and every refusal as JSON with its status,
    never a stack trace."""
    async def run(request: Request) -> Response:
        try:
            data = await _read_body(request) if body else b""
            return await run_in_threadpool(handler, request, data)
        except UnknownDocument:
            return _error(404, "there is no such face; it may have been deleted")
        except UnknownSnapshot:
            return _error(404, "there is no such snapshot; it may have been pruned")
        except StaleVersion as exc:
            return _error(409, str(exc))
        except (BundleError, Refused, starters.UnknownTemplate, DeviceError) as exc:
            return _error(400, str(exc))
        except StoreError as exc:
            return _error(507, str(exc))
    run.__name__ = handler.__name__
    return run


async def _read_body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise BundleError(f"the upload is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return bytes(data)


def _int(request: Request, name: str) -> int:
    raw = request.query_params.get(name)
    if raw is None or not re.fullmatch(r"-?\d+", raw):
        raise Refused(f"{name} must be a whole number")
    return int(raw)


def _flag(request: Request, name: str) -> bool:
    return request.query_params.get(name, "") in ("1", "true", "yes")


def _time(raw: str | None) -> tuple[int, int, int] | None:
    if not raw:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if m is None or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3] or 0) > 59:
        raise Refused(f"time {raw!r} is not HH:MM or HH:MM:SS")
    return int(m[1]), int(m[2]), int(m[3] or 0)


def _frame_key(request: Request, scale: int | None = None) -> FrameKey:
    """A frame's device and switches, from the query."""
    if scale is None:
        scale = _int(request, "scale") if "scale" in request.query_params else 2
    return FrameKey(
        device=request.query_params.get("device", ""),
        style=request.query_params.get("style") or None,
        time=_time(request.query_params.get("time")),
        asleep=_flag(request, "asleep"),
        aod=_flag(request, "aod"),
        scale=min(4, max(1, scale)),
    )


def create_app(studio: Studio, *, initial: str | None = None) -> Starlette:
    """The app over ``studio``.  ``initial`` is a document id the home
    screen opens straight away (`wfb studio face.yaml`)."""
    events = Events()
    studio.on_event = events.publish

    def doc(request: Request) -> Document:
        return studio.document(request.path_params["doc_id"])

    def changed(document: Document) -> None:
        events.publish("changed", {"id": document.id, "version": document.version})

    def home(request: Request, data: bytes) -> Response:
        with studio.lock:
            return JSONResponse({
                "templates": [{"name": n, "blurb": starters.TEMPLATE_BLURB.get(n, "")}
                              for n in starters.names()],
                "documents": studio.store.documents(),
                "store": str(studio.store.root),
                "initial": initial,
            })

    def new(request: Request, data: bytes) -> Response:
        template = request.query_params.get("template", "minimal")
        name = request.query_params.get("name", "").strip() or "My Face"
        with studio.lock:
            document = studio.create(Bundle(name, starters.instantiate(template, name)),
                                     f"new from the {template} template")
            return JSONResponse(document.summary())

    def upload(request: Request, data: bytes) -> Response:
        filename = request.query_params.get("filename", "")
        bundle = read_upload(filename, data)
        with studio.lock:
            document = studio.create(bundle, f"open {filename}")
            return JSONResponse(document.summary())

    def summary(request: Request, data: bytes) -> Response:
        with studio.lock:
            return JSONResponse(doc(request).summary())

    def delete(request: Request, data: bytes) -> Response:
        with studio.lock:
            studio.delete(request.path_params["doc_id"])
        return JSONResponse({"deleted": request.path_params["doc_id"]})

    def frame(request: Request, data: bytes) -> Response:
        key = _frame_key(request)
        with studio.lock:
            document = doc(request)
            shown = document.frame(key)
            events.publish("rendered", {"id": document.id, "version": document.version,
                                        "device": key.device})
            return JSONResponse(shown)

    def layers(request: Request, data: bytes) -> Response:
        key = _frame_key(request)
        with studio.lock:
            return JSONResponse(doc(request).layers(key))

    def thumbnail(request: Request, data: bytes) -> Response:
        key = _frame_key(request, scale=1)
        with studio.lock:
            png = doc(request).thumbnail(key)
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    def drag(request: Request, data: bytes) -> Response:
        try:
            body = json.loads(data or b"{}")
        except ValueError:
            raise Refused("the gesture is not JSON") from None
        if not isinstance(body, dict) or not isinstance(body.get("gesture"), dict):
            raise Refused("a drag is {element, gesture, device, scope}")
        with studio.lock:
            document = doc(request)
            change, landed = document.drag(str(body.get("element", "")), body["gesture"],
                                           str(body.get("device", "")),
                                           str(body.get("scope", "auto")),
                                           _int(request, "version"))
            changed(document)
            return JSONResponse({**document.summary(), "landed": landed, "what": change.label})

    def add_asset(request: Request, data: bytes) -> Response:
        filename = request.query_params.get("filename", "")
        reference = request.query_params.get("reference") or None
        font_name = request.query_params.get("font") or None
        font = (font_name, request.query_params.get("size") or "10%r") if font_name else None
        expected = _int(request, "version")
        with studio.lock:
            document = doc(request)
            document.add_asset(filename, data, reference, expected, font)
            changed(document)
            return JSONResponse(document.summary())

    def edit(request: Request, data: bytes) -> Response:
        try:
            op = json.loads(data or b"{}")
        except ValueError:
            raise Refused("the edit is not JSON") from None
        if not isinstance(op, dict):
            raise Refused("the edit is a JSON object")
        with studio.lock:
            document = doc(request)
            document.edit(op, _int(request, "version"))
            changed(document)
            return JSONResponse(document.summary())

    def structure(request: Request, data: bytes) -> Response:
        try:
            op = json.loads(data or b"{}")
        except ValueError:
            raise Refused("the edit is not JSON") from None
        if not isinstance(op, dict):
            raise Refused("the edit is a JSON object")
        with studio.lock:
            document = doc(request)
            _, select = document.structure(op, _int(request, "version"))
            changed(document)
            return JSONResponse({**document.summary(), "select": select})

    def replace_text(request: Request, data: bytes) -> Response:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise Refused("the text is not UTF-8") from None
        with studio.lock:
            document = doc(request)
            document.replace_text(text, _int(request, "version"))
            changed(document)
            return JSONResponse(document.summary())

    async def face_schema(request: Request) -> Response:
        from .inspect import SCHEMA
        return FileResponse(SCHEMA, media_type="application/schema+json")

    def inspector(request: Request, data: bytes) -> Response:
        try:
            element = json.loads(request.query_params.get("element", "null"))
        except ValueError:
            raise Refused("element is a JSON list") from None
        with studio.lock:
            return JSONResponse(doc(request).inspect(
                element, request.query_params.get("device") or None))

    installed: list[dict[str, Any]] = []

    def vocabulary(request: Request, data: bytes) -> Response:
        from .inspect import devices, vocabulary as words
        with studio.lock:
            if not installed:
                installed.extend(devices(studio.db))
            return JSONResponse({**words(), "devices": installed})

    skins: dict[tuple[str, int], dict[str, Any]] = {}

    def skin(request: Request, data: bytes) -> Response:
        """A watch's simulator skin at a scale, and where its screen sits
        in it: drawn over the face, transparent where the screen shows."""
        from ..preview import _skin_for
        from .document import _png

        device_id = request.query_params.get("device", "")
        scale = min(4, max(1, _int(request, "scale") if "scale" in request.query_params else 2))
        key = (device_id, scale)
        if key not in skins:
            found = _skin_for(studio.db.get(device_id), scale)
            if found is None:
                return _error(404, f"{device_id}'s files have no skin")
            image, (x, y) = found
            skins[key] = {"device": device_id, "scale": scale, "image": _png(image),
                          "width": image.width, "height": image.height, "x": x, "y": y}
        return JSONResponse(skins[key])

    def build(request: Request, data: bytes) -> Response:
        from .builder import BuildBusy

        device_id = request.query_params.get("device", "")
        with studio.lock:
            document = doc(request)
            document._check(_int(request, "version"))
            device = studio.db.get(device_id)
            if not device.supports_watchface:
                raise Refused(f"{device_id} cannot run a watch face")
            if document.analysis().face is None:
                raise Refused("the face does not load: mend the errors in Diagnostics first")
            document.ensure_directory()
            work = studio.builder.stage(document.directory)
            version, stem = document.version, slug(document.name)
        try:
            done = studio.builder.run(work, device_id, version, stem)
        except BuildBusy as exc:
            return _error(409, str(exc))
        return JSONResponse({
            "ok": done.ok, "device": done.device, "version": done.version, "log": done.log,
            "memory": done.memory, "seconds": round(done.seconds, 1),
            "download": f"/api/builds/{done.id}" if done.ok else None,
        })

    async def download_build(request: Request) -> Response:
        done = studio.builder.get(request.path_params["build_id"])
        if done is None or done.prg is None or not done.prg.is_file():
            return _error(404, "there is no such build; builds last until the editor stops")
        return FileResponse(done.prg, media_type="application/octet-stream",
                            filename=done.name, headers={"Cache-Control": "no-store"})

    def undo(request: Request, data: bytes) -> Response:
        with studio.lock:
            document = doc(request)
            document.undo(_int(request, "version"))
            changed(document)
            return JSONResponse(document.summary())

    def redo(request: Request, data: bytes) -> Response:
        with studio.lock:
            document = doc(request)
            document.redo(_int(request, "version"))
            changed(document)
            return JSONResponse(document.summary())

    def snapshot(request: Request, data: bytes) -> Response:
        with studio.lock:
            document = doc(request)
            snap = document.snapshot("manual")
            events.publish("snapshot", {"id": document.id, "name": snap.name,
                                        "version": document.version})
            return JSONResponse(document.history())

    def restore(request: Request, data: bytes) -> Response:
        with studio.lock:
            document = doc(request)
            document.restore(request.path_params["name"], _int(request, "version"))
            changed(document)
            return JSONResponse(document.summary())

    def fork(request: Request, data: bytes) -> Response:
        with studio.lock:
            copy = studio.fork(request.path_params["doc_id"], request.path_params["name"])
            return JSONResponse(copy.summary())

    def download(request: Request, data: bytes) -> Response:
        form = request.query_params.get("form", "auto")
        with studio.lock:
            document = doc(request)
            bundle = document.bundle()
            # Every download is a point in time worth going back to, unless
            # that version already has a snapshot.
            if document.last_snapshot[1] != document.version:
                snap = document.snapshot("download")
                events.publish("snapshot", {"id": document.id, "name": snap.name,
                                            "version": document.version})
        if form == "auto":
            form = "zip" if bundle.files else "yaml"
        stem = slug(bundle.name)
        if form == "yaml":
            body, media, name = bundle.text.encode("utf-8"), "application/yaml", f"{stem}.yaml"
        elif form == "zip":
            body, media, name = to_zip(bundle), "application/zip", f"{stem}.zip"
        else:
            raise Refused(f"form {form!r} is neither zip nor yaml")
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def stream(request: Request) -> Response:
        return StreamingResponse(events.stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    async def index(request: Request) -> Response:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/home", _endpoint(home)),
            Route("/api/documents/new", _endpoint(new), methods=["POST"]),
            Route("/api/documents/upload", _endpoint(upload, body=True), methods=["POST"]),
            Route("/api/documents/{doc_id}", _endpoint(summary)),
            Route("/api/documents/{doc_id}", _endpoint(delete), methods=["DELETE"]),
            Route("/api/documents/{doc_id}/frame", _endpoint(frame)),
            Route("/api/documents/{doc_id}/layers", _endpoint(layers)),
            Route("/api/documents/{doc_id}/thumbnail", _endpoint(thumbnail)),
            Route("/api/documents/{doc_id}/drag", _endpoint(drag, body=True), methods=["POST"]),
            Route("/api/documents/{doc_id}/assets", _endpoint(add_asset, body=True),
                  methods=["POST"]),
            Route("/api/documents/{doc_id}/download", _endpoint(download)),
            Route("/api/vocabulary", _endpoint(vocabulary)),
            Route("/api/schema", face_schema),
            Route("/api/skin", _endpoint(skin)),
            Route("/api/builds/{build_id}", download_build),
            Route("/api/documents/{doc_id}/build", _endpoint(build), methods=["POST"]),
            Route("/api/documents/{doc_id}/text", _endpoint(replace_text, body=True),
                  methods=["POST"]),
            Route("/api/documents/{doc_id}/edit", _endpoint(edit, body=True), methods=["POST"]),
            Route("/api/documents/{doc_id}/inspect", _endpoint(inspector)),
            Route("/api/documents/{doc_id}/structure", _endpoint(structure, body=True),
                  methods=["POST"]),
            Route("/api/documents/{doc_id}/undo", _endpoint(undo), methods=["POST"]),
            Route("/api/documents/{doc_id}/redo", _endpoint(redo), methods=["POST"]),
            Route("/api/documents/{doc_id}/snapshots", _endpoint(snapshot), methods=["POST"]),
            Route("/api/documents/{doc_id}/snapshots/{name}/restore", _endpoint(restore),
                  methods=["POST"]),
            Route("/api/documents/{doc_id}/snapshots/{name}/copy", _endpoint(fork),
                  methods=["POST"]),
            Route("/api/events", stream),
            Mount("/static", StaticFiles(directory=STATIC), name="static"),
        ],
    )
    app.state.events = events
    return app
