"""The semantic pass's shared state and the small helpers every layer of
it uses: `NamedRegistry` (the declared/accepted/rejected bookkeeping a named
top-level block keeps), `dedup_append`, `and_paths` and a node's own `lint:`
suppression."""

from __future__ import annotations

from typing import Any, Generic, TypedDict, TypeVar

from ... import expr
from ...diagnostics import Bag, Span
from ...palette import Color
from ...yamlsrc import YamlDocument

from ..model import (
    ColorScheme, ConfigColor, ConfigDataSlot,
    ConfigStyle, Expression, FontSpec, HandSet, LayoutDecl,
)

T = TypeVar("T")


class NamedRegistry(dict[str, T], Generic[T]):
    """A named top-level block -- `fonts:`, `palette:`, `layouts:`,
    `color_scheme:`, `config: data:` or `hands:` -- as it parses: a dict of
    the *accepted* entries, in declaration order, plus the bookkeeping for
    references to the rest.

    `declared` is every name the block saw, whether or not it survived; a
    rejected entry is still a *declared* one, so a reference to a name that
    was declared and then rejected can be told apart from one that was never
    declared at all.  `rejected` is the subset that failed the block's own
    check.  :meth:`resolve` is the one lookup: the accepted value, or the
    shared "one error, not N" cascade tail -- a name that was declared and
    then rejected stays quiet, because the real mistake already has its own
    error against this block, and anything else is `unknown X`, with a note
    listing every declared name (`docs/lore/codegen.md`).
    """

    def __init__(self) -> None:
        super().__init__()
        self.declared: dict[str, Span | None] = {}
        self.rejected: set[str] = set()

    def declare(self, name: str, span: Span | None) -> None:
        self.declared[name] = span

    def reject(self, name: str) -> None:
        self.rejected.add(name)

    def resolve(
        self, bag: Bag, name: str, span: Span | None, *,
        code: str, message: str, note: str, prefix: str = "",
    ) -> T | None:
        """The accepted entry `name`, or `None` after reporting it.
        `message` is the error's full text; `note` is the fixed lead-in for
        the one note ("declared palette entries", "declared fonts", ...),
        followed by the declared names, sorted and `prefix`-qualified
        (`"palette."`, `"font."`, `"config.data."`, or `""`), or "(none
        declared)".  Nothing is reported for a declared-then-rejected name.
        """
        if name in self:
            return self[name]
        if name in self.rejected:
            return None
        known = ", ".join(f"{prefix}{n}" for n in sorted(self.declared)) or "(none declared)"
        bag.error(code, message, span, notes=[f"{note}: {known}"])
        return None


def dedup_append(colors: list[Expression], color: Expression | None) -> None:
    """Append `color` to `colors` in first-use order, unless it is `None` or
    already present -- the "every effective colour, deduplicated" accumulation
    `HandsElement.colors`/`PatternElement.colors` each build."""
    if color is not None and color not in colors:
        colors.append(color)


class LintSuppression(TypedDict):
    lint_allow: frozenset[str]
    lint_reason: str | None


def _lint_suppression(node: dict[str, Any]) -> LintSuppression:
    """A node's own `lint: {allow, reason}`, as the `lint_allow`/
    `lint_reason` keyword arguments every carrier of one takes."""
    lint = node.get("lint") or {}
    return {"lint_allow": frozenset(lint.get("allow", ())), "lint_reason": lint.get("reason")}


def and_paths(paths: tuple[str, ...]) -> str:
    """``'a'``, ``'a' and 'b'``, ``'a', 'b' and 'c'`` -- for a diagnostic."""
    quoted = [repr(path) for path in paths]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


class BuilderState:
    """Everything the semantic pass accumulates while it walks a document:
the named top-level blocks, the face-wide defaults and the expression
scope.  Every other layer of `Builder` reads and writes these."""

    def __init__(self, doc: YamlDocument, bag: Bag) -> None:
        self.doc = doc
        self.bag = bag
        # Named top-level blocks: each is a `NamedRegistry` of its accepted
        # values plus every declared name, so a reference to a
        # declared-then-rejected entry stays quiet ("one error, not N",
        # `docs/lore/codegen.md`).
        self.palette: NamedRegistry[Color] = NamedRegistry()
        #: Accepted long-form `palette:` entries' labels, keyed by name --
        #: read when a `config:` choice names `palette.<name>`.
        self.palette_labels: dict[str, str] = {}
        self.fonts: NamedRegistry[FontSpec] = NamedRegistry()
        #: `layouts:` entries in declaration order; built before `config:`
        #: so a style entry's `layout:` resolves in the same pass.
        self.layouts: NamedRegistry[LayoutDecl] = NamedRegistry()
        self.color_scheme: NamedRegistry[ColorScheme] = NamedRegistry()
        self.config_data: NamedRegistry[ConfigDataSlot] = NamedRegistry()
        self.hand_sets: NamedRegistry[HandSet] = NamedRegistry()
        #: `accent_color`/`data_color` axes.  A rejected axis (or `"style"`)
        #: goes in `rejected_config` instead, and is still bound into scope
        #: by `_build_scope` for the same cascade reason.
        self.config: dict[str, ConfigColor] = {}
        self.rejected_config: set[str] = set()
        #: The `config: style:` axis; `None` if undeclared or rejected.
        self.config_style: ConfigStyle | None = None
        #: The roles `config.colors.<role>` may name, set by `_build_scope`
        #: for `expression`'s dedicated error; `None` means no Styles
        #: colours at all, not zero roles.
        self._config_colors_roles: tuple[str, ...] | None = None
        self.scope = expr.Scope()
        self.seen_ids: dict[str, Span | None] = {}
        #: Derived Monkey C symbol -> the element id and span that claimed it
        #: first (`_check_symbol_collision`).
        self.seen_symbols: dict[str, tuple[str, Span | None]] = {}
        # Face-wide defaults, read first in `build()`: `_build_fonts` needs
        # `face_antialias`; the tree passes need the rest.
        self.face_antialias = False
        self.face_min_1px = False
        self.face_aod_default_hide = True
        self.face_aod_lint_allow: frozenset[str] = frozenset()
        self.face_aod_lint_reason: str | None = None
        #: `None` for both an absent `aod: dim:` and `dim: 1` (`Face.aod_dim`).
        self.face_aod_dim: float | None = None
        self.face_aod_mask: bool = True
