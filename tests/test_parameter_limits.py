"""Guards Connect IQ 3.x's 9-parameter ceiling on every Monkey C function.

Found 2026-09-18: `WfbGeom.drawTextRotated` grew a 10th parameter
(`justify`) in plan 06 and built fine on every target this project's tests
happened to exercise -- CIQ 5.x/6.x devices don't enforce a lower bound, so
nothing caught it until a real `monkeyc` run against fenix6/fenix6xpro/fr245
(API 3.4.5/3.4.5/3.3.6) produced "Too many arguments passed to method
'drawTextRotated'. Only 9 arguments are allowed." Fixed by splitting the
rotate-the-point step out of the draw call (`WfbGeom.rotatedX`/`rotatedY`,
`docs/lore/monkeyc.md`, `docs/limitations.md` §2). This scans every
hand-written barrel function so a future helper cannot repeat the mistake
silently, plus every function the emitter generates for a representative
sample of examples (hands, patterns, a `shape: text` pattern part), all with
no toolchain needed -- the limit is on the *declaration*, checkable from the
generated text alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.build import build
from wfb.diagnostics import Bag

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_LIB = ROOT / "runtime-lib"
MAX_PARAMETERS = 9

_OPEN, _CLOSE = "([{", ")]}"


def _signatures(text: str):
    """Yield `(name, params_text)` for every `function name(...)` declaration.

    The closing paren is found by bracket depth, not the first literal `)`,
    so a Dictionary-literal parameter type's own commas (e.g.
    `wfb/emit/monkeyc/delegate.py`'s `onWatchFaceConfigEdited(options as
    {:configId as ..., :type as ..., :committed as ...})`) are not mistaken
    for parameter separators. Only `()`/`[]`/`{}` are tracked -- no
    signature in this project uses a comma-bearing `<...>` generic
    (`Array<Graphics.Point2D>`, `Array<Float?>` and friends carry no
    top-level comma), so `<`/`>` need no tracking here.
    """
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\(", text):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            c = text[i]
            if c in _OPEN:
                depth += 1
            elif c in _CLOSE:
                depth -= 1
            i += 1
        yield name, text[start:i - 1]


def _param_count(params_text: str) -> int:
    """Top-level comma count, depth-aware for the same reason as
    :func:`_signatures`; a zero-argument signature is 0, not 1."""
    params_text = params_text.strip()
    if not params_text:
        return 0
    depth = 0
    count = 1
    for c in params_text:
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
        elif c == "," and depth == 0:
            count += 1
    return count


def _too_wide(text: str) -> list[tuple[str, int]]:
    return [(name, _param_count(params)) for name, params in _signatures(text)
            if _param_count(params) > MAX_PARAMETERS]


def test_no_runtime_lib_function_declares_more_than_9_parameters():
    """CIQ 3.x (fenix6, fenix6xpro, fr245 among this project's own targets)
    rejects a 10th argument outright; every hand-written barrel function
    must fit."""
    offenders = []
    for path in sorted(RUNTIME_LIB.glob("*.mc")):
        for name, count in _too_wide(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}:{name} ({count} parameters)")
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize(
    "example", ["features/patterns", "features/analog", "showcase"])
def test_no_generated_function_declares_more_than_9_parameters(example, tmp_path, db):
    """The barrel is not the only place a >9-parameter function could grow --
    a generated per-element `drawX` method could too. Builds three examples
    that between them exercise hands, patterns and a `shape: text` pattern
    part, then scans every `.mc` file the pipeline writes (runtime-lib copy
    included) for the same ceiling. `compile_prg=False` needs no toolchain,
    since the limit is checkable from the generated text alone.
    """
    design = ROOT / "examples" / example / "face.yaml"
    bag = Bag()
    result = build(design, output=tmp_path, bag=bag, db=db, compile_prg=False)
    assert result is not None, bag.render()
    offenders = []
    for path in sorted(result.output_dir.rglob("*.mc")):
        for name, count in _too_wide(path.read_text(encoding="utf-8")):
            offenders.append(
                f"{path.relative_to(result.output_dir)}:{name} ({count} parameters)")
    assert not offenders, "\n".join(offenders)
