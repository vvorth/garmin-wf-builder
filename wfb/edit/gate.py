"""The gate every patch passes before it is accepted.

A patched text is accepted only when

1. it parses to exactly the data the patch intended, key order included,
   so a patch that touched anything else fails loudly; and
2. it loads through the whole front end (`wfb.build.load`: parse, schema,
   lowering, desugaring, the IR) with no error the text before it did not
   already have, and still loads if it loaded before.  A text that did not
   load (a font file not yet added, say) may be patched towards loading.

The text is loaded under the design's own path, so relative font paths
resolve as they do for the design and every diagnostic names the design.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..diagnostics import Bag, Diagnostic
from ..ir import Face
from .patch import Patch
from .spans import Refused, index_for, ordered


@dataclass(frozen=True)
class Loaded:
    """A text loaded under the design's path: the face (``None`` when it
    did not load) and every diagnostic."""

    text: str
    face: Face | None
    bag: Bag

    @property
    def errors(self) -> list[Diagnostic]:
        return self.bag.errors


def load_text(path: Path, text: str) -> Loaded:
    from ..build import load

    bag = Bag()
    face = load(path, bag, text, _composed(text))
    return Loaded(text, face, bag)


def _composed(text: str) -> Any:
    """``text``'s node tree from its shared index (`index_for`), which an
    edit has composed already, so the load does not scan the text again;
    ``None`` when the load must parse it itself: text that is not YAML,
    whose error the load reports, or text with a merge key, whose node the
    index's own construction has already merged away."""
    if "<<" in text:
        return None
    try:
        return index_for(text).root
    except Refused:
        return None


def _error_keys(loaded: Loaded) -> Counter[tuple[str, str]]:
    # Positions shift with every edit, so an error is known by what it says.
    return Counter((d.code, d.message) for d in loaded.errors)


class Gate:
    """Accepts or refuses patches to one text of one design."""

    def __init__(self, path: Path, text: str, before: Loaded | None = None) -> None:
        """``before`` is ``text`` already loaded, when the caller has it."""
        self.path = path
        self.before = before if before is not None and before.text == text else load_text(path, text)

    def check(self, patch: Patch, after: Loaded | None = None) -> Loaded:
        """The patched text, loaded; or `Refused`, saying why. ``after`` is
        that text already loaded, when the caller has it."""
        if ordered(index_for(patch.text).data) != ordered(patch.expected):
            raise Refused(f"{patch.what}: the edit would change more than intended")
        if after is None or after.text != patch.text:
            after = load_text(self.path, patch.text)
        new = _error_keys(after) - _error_keys(self.before)
        if new:
            first = next(d for d in after.errors if (d.code, d.message) in new)
            where = f" (line {first.span.line})" if first.span is not None else ""
            raise Refused(f"{patch.what}: {first.message}{where}")
        if after.face is None and self.before.face is not None:
            raise Refused(f"{patch.what}: the design no longer loads")
        return after
