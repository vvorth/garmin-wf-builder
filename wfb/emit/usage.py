"""What generated Monkey C actually calls: runtime-lib barrel modules, and
`Toybox` modules -- read straight off the emitted source text (plan 19 A3).

The alternative the plan itself proposed -- have each emitter *record* a
barrel helper or a `Toybox` module as it writes one, e.g. at `Writer.call`
sites -- misses most uses: a barrel call is just as often built inline as a
string (`WfbMath.percent(...)` inside a compiled expression, from
`wfb.expr`; `WfbTime.hour12(...)` from a strftime code, from
`wfb.formatting`; `WfbComplications.valueOf(...)` from a reader's own
`call`, from `wfb.catalog`), and a `Toybox` module shows up the same way, in
a reader's declared type (`Gregorian.Info`) as readily as in a call. The
generated source text is the one complete record of what the code calls, so
this module reads it directly instead of re-deriving the same decision a
second time from the IR -- the "inspect what was actually emitted, don't
re-derive it" move `docs/lore/codegen.md` already credits for `WfbColor.dim`
and `WfbAodMask.apply` before this, generalised to every barrel module and
every `Toybox` import.
"""

from __future__ import annotations

import re
from pathlib import Path

RUNTIME_LIB = Path(__file__).resolve().parent.parent.parent / "runtime-lib"


class UnknownBarrelModule(RuntimeError):
    """Generated code calls into a `Wfb<Name>` module with no matching
    `runtime-lib/Wfb<Name>.mc` file -- a compiler bug (the emitter wrote a
    call to a barrel helper that was never written), never an author
    mistake, so this is raised rather than turned into a diagnostic."""


# --------------------------------------------------------------------------
# stripping comments and string literals


#: A `//` line comment (doc comments -- `//!` -- included, since they start
#: the same way) to end of line, or a `"..."` string literal with backslash
#: escapes.  Whichever starts first at a given position wins, which is what
#: keeps a `//` inside a string, or a `"` inside a comment, from being
#: mistaken for the other (`re.sub` always takes the leftmost match).  Monkey
#: C also has `/* */` comments and `'x'` char literals, but this project's
#: own emitters never write either, so there is nothing to strip them for.
_STRIP_RE = re.compile(r'//[^\n]*' r'|"(?:\\.|[^"\\])*"')


def strip_comments_and_strings(text: str) -> str:
    """``text`` with every line comment and string literal blanked out, so a
    `Wfb<Name>.` or a `Toybox` module name mentioned only in prose or in a
    quoted string is never mistaken for a real reference."""
    return _STRIP_RE.sub(" ", text)


# --------------------------------------------------------------------------
# barrel modules


_BARREL_CALL_RE = re.compile(r"\bWfb[A-Za-z0-9]+(?=\.)")


def _direct_barrel_files(text: str) -> set[str]:
    stripped = strip_comments_and_strings(text)
    names = {m.group(0) for m in _BARREL_CALL_RE.finditer(stripped)}
    files = set()
    for name in names:
        path = RUNTIME_LIB / f"{name}.mc"
        if not path.exists():
            raise UnknownBarrelModule(
                f"generated code calls {name}.<member>, but {path} does not exist -- "
                "a generated program cannot call into a barrel module that was never "
                "written"
            )
        files.add(f"{name}.mc")
    return files


def barrel_modules(texts) -> set[str]:
    """The `runtime-lib/*.mc` files generated code actually calls into,
    closed over the barrel files themselves.

    ``texts`` is one source string or an iterable of them -- every generated
    Monkey C source in the project (`wfb.emit.project.generate` passes every
    `project.sources` text). Every `Wfb<Name>` identifier immediately
    followed by `.` is a module member reference; each is mapped to
    `runtime-lib/Wfb<Name>.mc`, raising :class:`UnknownBarrelModule` if that
    file does not exist -- a generated call into a module that was never
    written is a compiler bug, not something a build should silently ignore.

    The result is then closed over the runtime-lib files themselves: no
    barrel file references another one today, but nothing here assumes that
    stays true, so a copied-in file that starts calling a second one would
    still get that second file copied too.
    """
    if isinstance(texts, str):
        texts = (texts,)
    files = set()
    for text in texts:
        files |= _direct_barrel_files(text)
    pending = list(files)
    while pending:
        name = pending.pop()
        content = (RUNTIME_LIB / name).read_text(encoding="utf-8")
        for found in _direct_barrel_files(content):
            if found not in files:
                files.add(found)
                pending.append(found)
    return files


# --------------------------------------------------------------------------
# Toybox modules


#: Every `Toybox` module this compiler's generated view code can reference,
#: by the bare top-level identifier the generated text actually uses --
#: derived from `_BASE_IMPORTS`, every `wfb.catalog.READERS` entry's own
#: `module`/`monkeyc_type`, `wfb.series.ACQUISITION`, `wfb.expr.CALL_MODULES`
#: and the view's own config/complications/hands/pattern machinery. Two
#: entries are not a plain `Toybox.<name>`: `Gregorian` (a
#: `Toybox.Time.Gregorian` reference, e.g. `Gregorian.info(...)`) and
#: `WatchFaceConfig` (`Toybox.Application.WatchFaceConfig`, e.g.
#: `WatchFaceConfig.getSettings(...)`).
TOYBOX_MODULES: dict[str, str] = {
    "Graphics": "Toybox.Graphics",
    "Lang": "Toybox.Lang",
    "WatchUi": "Toybox.WatchUi",
    "System": "Toybox.System",
    "Time": "Toybox.Time",
    "Gregorian": "Toybox.Time.Gregorian",
    "ActivityMonitor": "Toybox.ActivityMonitor",
    "Activity": "Toybox.Activity",
    "Weather": "Toybox.Weather",
    "UserProfile": "Toybox.UserProfile",
    "Complications": "Toybox.Complications",
    "Math": "Toybox.Math",
    "Application": "Toybox.Application",
    "WatchFaceConfig": "Toybox.Application.WatchFaceConfig",
}


def _module_pattern(name: str) -> re.Pattern[str]:
    escaped = re.escape(name)
    return re.compile(rf"\b{escaped}\.|\b{escaped}\s+has\b")


_TOYBOX_PATTERNS = {name: _module_pattern(name) for name in TOYBOX_MODULES}


def toybox_modules(text: str) -> set[str]:
    """The `Toybox.*` imports ``text`` needs: every :data:`TOYBOX_MODULES`
    name that appears as an identifier followed by `.` (a member reference,
    e.g. `Weather.CurrentConditions?`) or by `` has `` (a bare module-
    existence check, e.g. `Application has :WatchFaceConfig`) -- the two
    shapes generated code actually uses a module name in, per
    `$CIQ_SDK/doc/docs/Monkey_C/Functions.html`'s own `Toybox has
    :Magnetometer` idiom for the second.
    """
    stripped = strip_comments_and_strings(text)
    return {module for name, module in TOYBOX_MODULES.items()
            if _TOYBOX_PATTERNS[name].search(stripped)}
