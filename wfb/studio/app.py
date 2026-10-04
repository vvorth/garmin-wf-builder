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
import datetime
import json
import re
import threading
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import starters
from ..build import slug
from ..devices import DeviceError
from ..edit import Refused
from .bundle import MAX_UPLOAD_BYTES, Bundle, BundleError, read_upload, to_zip
from .document import Document, FrameKey, StaleVersion, Studio
from .sessions import CLAIM_SECONDS, COOKIE, Sessions
from .store import OWNER, StoreError, UnknownDocument, UnknownSnapshot

STATIC = Path(__file__).resolve().parent / "static"


class Events:
    """Server-sent events to every open stream.  `publish` is called from
    the thread pool; each subscriber is an asyncio queue on the loop that
    serves it.  A stream opened for a principal hears only of that
    principal's documents (``owner_of`` says whose an event's `id` is); one
    opened for nobody in particular hears everything."""

    def __init__(self, owner_of: Callable[[str], str | None] = lambda doc_id: None) -> None:
        self._lock = threading.Lock()
        self._owner_of = owner_of
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str],
                                      str | None]] = []

    def publish(self, event: str, data: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        owner = self._owner_of(str(data["id"])) if "id" in data else None
        for loop, queue, principal in subscribers:
            if principal is None or owner is None or principal == owner:
                loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream(self, principal: str | None = None) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        entry = (asyncio.get_running_loop(), queue, principal)
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


class NoSession(Exception):
    """The request carries no session: the editor's page gives one."""


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
        except NoSession:
            return _error(401, "no session: open the editor's page to start one")
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


def _date(raw: str | None) -> tuple[int, int, int] | None:
    if not raw:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    try:
        if m is None:
            raise ValueError
        datetime.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        raise Refused(f"date {raw!r} is not a day, YYYY-MM-DD") from None
    return int(m[1]), int(m[2]), int(m[3])


def _frame_key(request: Request, scale: int | None = None) -> FrameKey:
    """A frame's device and switches, from the query."""
    if scale is None:
        scale = _int(request, "scale") if "scale" in request.query_params else 2
    return FrameKey(
        device=request.query_params.get("device", ""),
        style=request.query_params.get("style") or None,
        time=_time(request.query_params.get("time")),
        date=_date(request.query_params.get("date")),
        asleep=_flag(request, "asleep"),
        aod=_flag(request, "aod"),
        scale=min(4, max(1, scale)),
        picks=_picks(request.query_params.get("picks")),
    )


def _picks(raw: str | None) -> tuple[tuple[str, str], ...]:
    """`picks=top:heart_rate,bottom:steps`: each slot and the type it is
    drawn showing, sorted so one choice is one cache key."""
    out = []
    for item in (raw or "").split(","):
        slot, _, type_ = item.partition(":")
        if slot.strip() and type_.strip():
            out.append((slot.strip(), type_.strip()))
    return tuple(sorted(out))


def create_app(studio: Studio, *, sessions: Sessions | None = None,
               allowed_hosts: list[str] | None = None) -> Starlette:
    """The app over ``studio``.

    With ``sessions``, each browser is a principal and sees only its own
    faces (`wfb.studio.sessions`); without, everyone is the owner, as with
    `--single-user`.  ``allowed_hosts`` are the only `Host` headers served:
    a page elsewhere that points its own name at this address
    (DNS rebinding) gets a 400, not the editor."""

    def owner_of(doc_id: str) -> str | None:
        try:
            return studio.store.owner(doc_id)
        except (UnknownDocument, OSError, ValueError):
            return None

    events = Events(owner_of)
    studio.on_event = events.publish
    #: Each finished build's document owner, so only they download it.
    build_owner: dict[str, str] = {}

    def principal(request: Request) -> str:
        if sessions is None:
            return OWNER
        found = sessions.principal_of(request.cookies.get(COOKIE))
        if found is None:
            raise NoSession()
        return found

    def doc(request: Request) -> Document:
        return studio.document(request.path_params["doc_id"], principal(request))

    def changed(document: Document) -> None:
        events.publish("changed", {"id": document.id, "version": document.version})

    def home(request: Request, data: bytes) -> Response:
        who = principal(request)
        with studio.lock:
            return JSONResponse({
                "templates": [{"name": n, "blurb": starters.TEMPLATE_BLURB.get(n, "")}
                              for n in starters.names()],
                "documents": studio.store.documents(owner=who),
                "store": str(studio.store.root),
                "shared": sessions is None or sessions.single_user,
            })

    def new(request: Request, data: bytes) -> Response:
        template = request.query_params.get("template", "minimal")
        name = request.query_params.get("name", "").strip() or "My Face"
        who = principal(request)
        with studio.lock:
            document = studio.create(Bundle(name, starters.instantiate(template, name)),
                                     f"new from the {template} template", owner=who)
            return JSONResponse(document.summary())

    def upload(request: Request, data: bytes) -> Response:
        filename = request.query_params.get("filename", "")
        who = principal(request)
        bundle = read_upload(filename, data)
        with studio.lock:
            document = studio.create(bundle, f"open {filename}", owner=who)
            return JSONResponse(document.summary())

    def summary(request: Request, data: bytes) -> Response:
        with studio.lock:
            return JSONResponse(doc(request).summary())

    def delete(request: Request, data: bytes) -> Response:
        with studio.lock:
            doc(request)
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

    def thumbnail(request: Request, data: bytes) -> Response:
        key = _frame_key(request, scale=1)
        with studio.lock:
            png = doc(request).thumbnail(key)
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    def hand_set(request: Request, data: bytes) -> Response:
        scale = _int(request, "scale") if "scale" in request.query_params else 1
        with studio.lock:
            png = doc(request).hand_set_image(request.query_params.get("name", ""),
                                             request.query_params.get("device", ""), scale)
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    def drag(request: Request, data: bytes) -> Response:
        try:
            body = json.loads(data or b"{}")
        except ValueError:
            raise Refused("the gesture is not JSON") from None
        if not isinstance(body, dict) or not isinstance(body.get("gesture"), dict):
            raise Refused("a drag is {element, gesture, device, scope}")
        elements = body.get("elements")
        gesture = body["gesture"]
        if elements is not None and (not isinstance(elements, list)
                                     or gesture.get("kind") != "move"
                                     or gesture.get("part", "both") != "both"):
            raise Refused("several elements can only be moved together")
        with studio.lock:
            document = doc(request)
            if elements is not None:
                try:
                    dx, dy = int(gesture["dx"]), int(gesture["dy"])
                except (KeyError, TypeError, ValueError):
                    raise Refused("a move needs its dx and dy") from None
                change, landed = document.move_all([str(e) for e in elements], dx, dy,
                                                   str(body.get("device", "")),
                                                   str(body.get("scope", "auto")),
                                                   _int(request, "version"))
            else:
                change, landed = document.drag(str(body.get("element", "")), gesture,
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

    async def icon_font(request: Request) -> Response:
        """The icon font, so the browser draws a catalogue icon's glyph."""
        from ..icons import FONT_PATH
        if not FONT_PATH.is_file():
            return _error(404, "the icon font is not installed: run ./tools/setup-env.sh")
        return FileResponse(FONT_PATH, media_type="font/ttf")

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
            who = document.owner
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
        build_owner[done.id] = who
        return JSONResponse({
            "ok": done.ok, "device": done.device, "version": done.version, "log": done.log,
            "memory": done.memory, "seconds": round(done.seconds, 1),
            "download": f"/api/builds/{done.id}" if done.ok else None,
        })

    async def download_build(request: Request) -> Response:
        try:
            who = principal(request)
        except NoSession:
            return _error(401, "no session: open the editor's page to start one")
        build_id = request.path_params["build_id"]
        done = studio.builder.get(build_id)
        if done is None or done.prg is None or not done.prg.is_file() \
                or build_owner.get(build_id) != who:
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
            doc(request)
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
        try:
            who = principal(request)
        except NoSession:
            return _error(401, "no session: open the editor's page to start one")
        return StreamingResponse(events.stream(who), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    def with_session(request: Request, response: Response, token: str) -> Response:
        """``response`` setting the session cookie: the browser keeps it as
        long as the faces it reaches are kept, renewed on each visit, and
        sends it only with this site's own requests."""
        assert sessions is not None
        response.set_cookie(COOKIE, token, max_age=int(sessions.keep_seconds), path="/",
                            httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    async def index(request: Request) -> Response:
        page = FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
        if sessions is None or sessions.single_user:
            return page
        code = request.query_params.get("claim")
        if code:
            return await claim(request)
        token = request.cookies.get(COOKIE)
        if sessions.principal_of(token) is None:
            _, token = await run_in_threadpool(sessions.new_browser)
        assert token is not None
        return with_session(request, page, token)

    async def claim(request: Request) -> Response:
        """A claim link: this browser joins the link's principal and sees
        its faces. A link works once."""
        assert sessions is not None
        code = request.path_params.get("code") or request.query_params.get("claim", "")
        token = await run_in_threadpool(sessions.redeem, code)
        if token is None:
            return HTMLResponse(
                "<!doctype html><meta charset=utf-8><title>wfb studio</title>"
                "<p>This link has been used, or has expired. Ask for a new one from the "
                "browser that has the faces: <b>Use my faces in another browser</b>.</p>",
                status_code=410)
        return with_session(request, RedirectResponse("/", status_code=303), token)

    def new_claim(request: Request, data: bytes) -> Response:
        who = principal(request)
        if sessions is None or sessions.single_user:
            raise Refused("every browser sees the same faces here: there is nothing to join")
        code = sessions.claim_for(who)
        return JSONResponse({"url": f"/claim/{code}", "seconds": int(CLAIM_SECONDS)})

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/home", _endpoint(home)),
            Route("/api/documents/new", _endpoint(new), methods=["POST"]),
            Route("/api/documents/upload", _endpoint(upload, body=True), methods=["POST"]),
            Route("/api/documents/{doc_id}", _endpoint(summary)),
            Route("/api/documents/{doc_id}", _endpoint(delete), methods=["DELETE"]),
            Route("/api/documents/{doc_id}/frame", _endpoint(frame)),
            Route("/api/documents/{doc_id}/thumbnail", _endpoint(thumbnail)),
            Route("/api/documents/{doc_id}/handset", _endpoint(hand_set)),
            Route("/api/documents/{doc_id}/drag", _endpoint(drag, body=True), methods=["POST"]),
            Route("/api/documents/{doc_id}/assets", _endpoint(add_asset, body=True),
                  methods=["POST"]),
            Route("/api/documents/{doc_id}/download", _endpoint(download)),
            Route("/api/vocabulary", _endpoint(vocabulary)),
            Route("/api/schema", face_schema),
            Route("/api/icon-font", icon_font),
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
            Route("/api/claims", _endpoint(new_claim), methods=["POST"]),
            Route("/claim/{code}", claim),
            Mount("/static", StaticFiles(directory=STATIC), name="static"),
        ],
    )
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.state.events = events
    return app
