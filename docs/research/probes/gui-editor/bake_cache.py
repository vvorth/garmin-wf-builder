"""How much of an edit's re-run does a font-bake cache save?

Backs docs/research/28-editor-open-questions.md §5. Host-side only.

    ./.venv/bin/python docs/research/probes/gui-editor/bake_cache.py

Times the in-process pipeline (load, resolve with font baking, render) on
fenix8solar47mm at 2x, warm, with `wfb.emit.resources.bake`/`dilate` as
they are and then memoised on their arguments plus the font file's mtime --
what a long-lived editor server would do, since a drag changes none of a
bake's inputs. The memoised render is checked pixel-identical to the plain
one.
"""

from __future__ import annotations

import functools
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from PIL import ImageChops  # noqa: E402

from wfb import preview  # noqa: E402
from wfb.build import load, resolve_all, select_devices  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402
from wfb.emit import resources  # noqa: E402

DEVICE = "fenix8solar47mm"
FACES = ["examples/features/progress/face.yaml", "examples/features/styles/face.yaml",
         "examples/features/vector-text/face.yaml", "examples/showcase/face.yaml"]
OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def run(db, path):
    bag = Bag()
    a = time.perf_counter()
    face = load(Path(path), bag)
    b = time.perf_counter()
    resolved, _ = resolve_all(face, select_devices(face, db, bag, [DEVICE]), bag)
    c = time.perf_counter()
    image = preview.render(resolved[DEVICE], preview.PreviewOptions(scale=2))
    d = time.perf_counter()
    return (b - a, c - b, d - c, d - a), image


def best(db, path, n=4):
    runs = [run(db, path) for _ in range(n)]
    times = min((r[0] for r in runs[1:]), key=lambda t: t[3])
    return times, runs[-1][1]


def memoised(fn):
    @functools.lru_cache(maxsize=None)
    def cached(source, mtime, kwargs):
        return fn(source, **dict(kwargs))

    @functools.wraps(fn)
    def wrapper(source, **kwargs):
        mtime = os.stat(source).st_mtime_ns if isinstance(source, (str, os.PathLike)) else None
        return cached(source, mtime, tuple(sorted(kwargs.items())))
    return wrapper


def main() -> None:
    db = DeviceDatabase.discover()
    run(db, FACES[0])
    say(f"## pipeline per edit, warm, {DEVICE}, 2x, ms: load / resolve / render / total")
    plain = {}
    for path in FACES:
        plain[path] = best(db, path)
    original_bake, original_dilate = resources.bake, resources.dilate
    resources.bake = memoised(original_bake)
    dil_cache: dict = {}

    def dilate(base, **kw):
        key = (id(base), tuple(sorted(kw.items())))
        if key not in dil_cache:
            dil_cache[key] = original_dilate(base, **kw)
        return dil_cache[key]
    resources.dilate = dilate
    for path in FACES:
        (t0, img0), (t1, img1) = plain[path], best(db, path)
        same = ImageChops.difference(img0.convert("RGB"), img1.convert("RGB")).getbbox() is None
        fmt = lambda t: " / ".join(f"{x * 1e3:.0f}" for x in t)  # noqa: E731
        say(f"{path:<42} plain {fmt(t0):>22}   cached {fmt(t1):>20}   pixels identical {same}")
    Path(__file__).with_name("bake_cache_results.txt").write_text("\n".join(OUT) + "\n",
                                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
