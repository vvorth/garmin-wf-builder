"""The named top-level blocks other than `fonts:` and `config:`:
`layouts:`, `palette:` and `color_scheme:`, and the expression scope every
block binds."""

from __future__ import annotations

from typing import Any

from ... import catalog, expr
from ...catalog import Type
from ...desugar import layout_ids
from ...diagnostics import Span
from ...palette import Color, ColorError

from ..model import ColorScheme, ComplicationSlot, Element, LayoutDecl, walk_elements
from ..naming import config_field, local_name
from .state import _lint_suppression
from .fonts import FontBlock


class TopLevelBlocks(FontBlock):
    """Builds `layouts:`, `palette:` and `color_scheme:` into their
`NamedRegistry`s, then the scope the element tree's expressions resolve
against."""

    # -- layouts, palette, config, fonts, scope -----------------------------

    def _build_layouts(self, raw: dict[str, Any]) -> None:
        """`layouts:` -- named widget sets, form A only.

        Post-desugar each body is just `{}` or `{lint: ...}`: `wfb.desugar`
        has already folded its `static:`/`elements:` into synthetic
        top-level groups (`layout_ids`), which `_assign_layouts` walks
        later.  So this records only the names, in declaration order, and
        each layout's own `lint:` (for `unreachable-layout`).  Nothing can
        reject a layout today, but it is a `NamedRegistry` like every other
        named block, so a future rejection cascades correctly.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.layouts.declare(name, span)
            self.layouts[name] = LayoutDecl(
                name=name,
                **_lint_suppression(spec),
                span=span,
            )

    def _assign_layouts(self, elements: list[Element]) -> None:
        """Stamp `Element.layout` on each layout's synthetic groups and their
        descendants, by the reserved id `wfb.desugar.layout_ids` defines,
        then apply the slot rule.

        Runs right after `build_elements`, before `_apply_static` -- see
        `build()`'s own comment for why the ordering matters.  Only the
        *top-level* synthetic groups are looked up by id: `layout_ids`
        always mints a top-level id (the desugar rewrite appends both groups
        straight onto the top-level `elements:`, never nested), so a linear
        scan of `elements` is enough; :func:`walk_elements` then reaches
        every descendant from there.
        """
        if self.layouts:
            by_id = {e.id: e for e in elements}
            for decl in self.layouts.values():
                for generated_id in layout_ids(decl.name):
                    group = by_id.get(generated_id)
                    if group is None:
                        continue  # this layout declared no static:/elements: of that kind
                    for element in walk_elements([group]):
                        element.layout = decl.name

        for element in walk_elements(elements):
            if isinstance(element, ComplicationSlot) and element.layout is not None:
                self.bag.error(
                    "layouts",
                    f"{element.id!r}: a complication_slot may not be inside "
                    f"layout {element.layout!r} content",
                    element.span,
                    notes=[
                        "the Data axis is face-wide -- one <complication "
                        "id=...> however many layouts read it -- so a slot "
                        "belongs in the shared top-level 'elements:', not "
                        "inside a 'layouts:' body",
                        "docs/guide/styles-and-layouts.md",
                    ],
                )

    def _check_layouts_reachable(self, data: dict[str, Any]) -> None:
        """`layouts:` declared with no `config: style:` entry ever naming one
        as its `layout:` is an error -- nothing lets the wearer pick it.

        Called after `_build_config`, once `self.config_style`/
        `self.rejected_config` are both known.  A `config: style:` that was
        declared and then rejected gives no second error here: the real
        mistake already has its own error pointing at `config:` -- the usual
        cascade discipline.
        """
        if not self.layouts:
            return
        if self.config_style is not None or "style" in self.rejected_config:
            return
        self.bag.error(
            "layouts",
            "layouts: is declared, but no 'config: style:' entry ever names "
            "one as its 'layout:' -- nothing lets the wearer pick it",
            self.doc.span(data, "layouts", of="key"),
            notes=["declared layouts: " + ", ".join(self.layouts),
                   "add a 'config: style:' block with an entry naming one, "
                   "or remove 'layouts:'"],
        )

    def _build_palette(self, raw: dict[str, Any]) -> None:
        """`palette:` -- named colours, in either of two spellings.

        The short form, `name: "#RRGGBB"`, is unchanged.  The long form,
        `name: {value: "#RRGGBB", label: "..."}`, adds a label with no other
        effect here -- it only matters once a `config:` entry references this
        entry as `palette.<name>` (`_palette_reference`), which is where the
        label becomes a generated `<string>`, exactly as an inline `label:`
        on a `config:` choice already does.
        """
        for name, value in raw.items():
            span = self.doc.span(raw, name)
            self.palette.declare(name, span)
            if isinstance(value, dict):
                raw_value = value.get("value")
                value_span = self.doc.span(value, "value") or span
                label = value.get("label")
            else:
                raw_value = value
                value_span = span
                label = None
            if isinstance(raw_value, str) and raw_value.startswith(("palette.", "config.")):
                self.bag.error(
                    "palette",
                    f"palette entry {name!r} refers to {raw_value!r}",
                    value_span,
                    notes=[
                        "palette entries must be literal colours in this format version",
                        "reference a config entry directly from 'color:'/'track_color:' "
                        "instead -- e.g. 'color: config.accent_color' -- rather than "
                        "through a palette entry",
                    ],
                )
                self.palette.reject(name)
                continue
            try:
                self.palette[name] = Color.parse(raw_value, what=f"palette.{name}")
            except ColorError as exc:
                self.bag.error("palette", str(exc), value_span)
                self.palette.reject(name)
                continue
            if label is not None:
                self.palette_labels[name] = label

    def _palette_reference(self, name: str, span: Span | None) -> Color | None:
        """Resolve a `palette.<name>` reference used where a build-time literal
        colour is required -- a `config:` entry's own `default:`/`choices:`.

        Returns ``None`` when the name does not resolve, either because it was
        never declared or because it *was* declared and then rejected by
        `_build_palette` (an out-of-range colour, a `config.*` reference).  In
        the rejected case this stays quiet: the real mistake already has its
        own error pointing at the `palette:` block, and the same cascade fix
        every `NamedRegistry` applies here -- one error at the real mistake,
        not one more per reference blaming the wrong line.
        """
        key = name[len("palette."):]
        return self.palette.resolve(
            self.bag, key, span, code="config",
            message=f"unknown palette entry {name!r}",
            note="declared palette entries", prefix="palette.",
        )

    def _resolve_config_color(self, raw: object, what: str, span: Span | None) -> Color | None:
        """A `config:` `default:`/`choices:` colour: a literal hex, or a
        `palette.<name>` reference resolved through `_palette_reference`."""
        if isinstance(raw, str) and raw.startswith("palette."):
            return self._palette_reference(raw, span)
        try:
            return Color.parse(raw, what=what)
        except ColorError as exc:
            self.bag.error("config", str(exc), span)
            return None

    def _build_color_scheme(self, raw: dict[str, Any]) -> None:
        """`color_scheme:` -- named role -> colour sets, picked on-device via
        a `config: style:` entry's own `colors:` (docs/research/09 §3,
        ADR 0006 1's second amendment).

        A role's colour is resolved exactly like a `config:` axis's own
        `default:`/`choices:` colour (`_resolve_config_color`): a literal
        hex, or a `palette.<name>` reference, with the identical
        declared/rejected cascade behaviour a bad palette reference already
        has everywhere else.

        Every accepted scheme must declare the identical role set, checked
        here against the union of every scheme's own roles -- a scheme
        missing one that another has would leave `config.colors.<role>`
        undefined whenever the wearer picks the one that lacks it.  Checked
        with the union rather than an arbitrary "first" scheme so the report
        does not depend on declaration order: whichever scheme(s) fall short
        of what the others collectively declare are the ones named.
        """
        role_sets: dict[str, dict[str, Color]] = {}
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.color_scheme.declare(name, span)
            label = spec.get("label")
            raw_colors = spec["colors"]
            colors: dict[str, Color] = {}
            ok = True
            for role in raw_colors:
                role_span = self.doc.span(raw_colors, role)
                color = self._resolve_config_color(
                    raw_colors[role], f"color_scheme.{name}.colors.{role}", role_span)
                if color is None:
                    ok = False
                    continue
                colors[role] = color
            if not ok:
                self.color_scheme.reject(name)
                continue
            self.color_scheme[name] = ColorScheme(name=name, label=label, colors=colors, span=span)
            role_sets[name] = colors

        if len(role_sets) < 2:
            return
        union: set[str] = set()
        for colors in role_sets.values():
            union |= set(colors)
        for name, colors in role_sets.items():
            missing = union - set(colors)
            if not missing:
                continue
            self.bag.error(
                "color-scheme",
                f"color_scheme.{name}: missing role(s) "
                f"{', '.join(sorted(missing))} -- every color_scheme entry "
                "must declare the same roles",
                self.color_scheme[name].span,
                notes=[
                    f"color_scheme.{name} declares: "
                    + (", ".join(sorted(colors)) or "(none)"),
                    "otherwise 'config.colors.<role>' would be undefined "
                    "whenever the wearer picks the scheme that lacks it",
                ],
            )
            self.color_scheme.reject(name)
            del self.color_scheme[name]

    def _scheme_reference(self, name: str, span: Span | None) -> str | None:
        """Resolve a bare `color_scheme:` name used from a `config: style:`
        entry's own `colors:`.

        Bare, not `color_scheme.<name>` -- that qualifying form is for
        expressions (`color: color_scheme.dark` is not even legal there
        either; it is `config.colors.<role>`), and there is exactly one thing
        `colors:` can name here, so a prefix buys nothing.  The schema's own
        `$defs/identifier` already rejects a non-identifier value before this
        ever runs, so this only ever sees a plausible name.

        Same declared/rejected cascade `_palette_reference` already has: a
        name that was declared and then rejected (a bad role colour, a
        role-set mismatch) gets no second error here, because the real
        mistake already has its own error pointing at the `color_scheme:`
        block.
        """
        scheme = self.color_scheme.resolve(
            self.bag, name, span, code="config",
            message=f"unknown color scheme {name!r}",
            note="declared color_scheme entries",
        )
        return name if scheme is not None else None

    def _layout_reference(self, name: str, span: Span | None) -> str | None:
        """Resolve a bare `layouts:` name used from a `config: style:`
        entry's own `layout:`.

        Same declared/rejected cascade `_scheme_reference` already has for
        `colors:` -- there is currently little that can reject a *declared*
        layout (`_build_layouts`), but the cascade exists anyway so a future
        rejection needs no change here.
        """
        decl = self.layouts.resolve(
            self.bag, name, span, code="config",
            message=f"unknown layout {name!r}", note="declared layouts",
        )
        return name if decl is not None else None

    def _define_palette_color(self, name: str, constant: int) -> None:
        """Bind `palette.<name>` to its Monkey C constant -- shared by an
        accepted palette entry (`constant` is its real value) and a
        declared-then-rejected one (`constant=0`, a placeholder: nothing is
        emitted from a design that has an error, so it is never reached --
        see the two call sites in `_build_scope` for the cascade this binds
        into scope for).
        """
        self.scope.define(
            f"palette.{name}",
            expr.Binding(
                expr.Value(Type.COLOR),
                code=f"Palette.{name.upper()}",
                constant=constant,
            ),
        )

    def _define_config_color(self, path: str, code: str) -> None:
        """Bind `path` (`config.<name>` or `config.colors.<role>`) to the
        view field `code` reads back from -- shared by every accepted or
        declared-then-rejected config colour binding in `_build_scope`.

        `constant=None` is deliberate, unlike a palette entry: the view
        field this reads is user-editable at runtime (on a device with the
        native editor), so `fold` must never inline it as the declared
        default -- `expr.fold`'s Ref branch only substitutes when
        `binding.constant` is set.
        """
        self.scope.define(
            path,
            expr.Binding(expr.Value(Type.COLOR), code=code, constant=None),
        )

    def _build_scope(self) -> None:
        """Populate the expression scope: catalogue sources, palette, config.

        Nullable sources bind to a *guarded local* named after the source, not
        to the raw API read.  The generator declares that local behind a null
        check, so the emitted expression never dereferences a null.
        """
        for path, source in catalog.CATALOG.items():
            self.scope.define(
                path,
                expr.Binding(
                    expr.Value(source.type, source.guard_needed),
                    code=local_name(path),
                ),
            )
        for name, color in self.palette.items():
            self._define_palette_color(name, color.value)
        # Declared-then-rejected palette entries and `config:` axes are bound
        # too, so a reference to one gets only the real error already
        # reported against its block, not a second "unknown data source"
        # (the `NamedRegistry` cascade).  A design with an error emits
        # nothing, so the placeholder constant/field is never reached.
        for name in sorted(self.palette.rejected):
            self._define_palette_color(name, 0)
        for name, entry in self.config.items():
            self._define_config_color(f"config.{name}", entry.field)
        for name in sorted(self.rejected_config - {"style"}):
            # (`style` is not a single colour; its roles are bound below.)
            self._define_config_color(f"config.{name}", config_field(name))

        # `config.colors.<role>` -- one binding per role of the default
        # style entry's scheme, and none for the bare `config.colors` (a
        # scheme is not a colour; `expression` gives both mistakes a
        # dedicated error).  A layout-only default entry binds no roles.
        if self.config_style is not None and self.config_style.default_entry.colors is not None:
            default_scheme = self.color_scheme[self.config_style.default_entry.colors]
            self._config_colors_roles = tuple(sorted(default_scheme.colors))
            for role in default_scheme.colors:
                self._define_config_color(f"config.colors.{role}", config_field(f"colors_{role}"))
        elif "style" in self.rejected_config:
            # The same cascade for a rejected Styles axis: bind every role a
            # surviving `color_scheme:` entry declares.
            roles: set[str] = set()
            for scheme in self.color_scheme.values():
                roles |= set(scheme.colors)
            if roles:
                self._config_colors_roles = tuple(sorted(roles))
                for role in self._config_colors_roles:
                    self._define_config_color(f"config.colors.{role}", config_field(f"colors_{role}"))
        self.scope.used.clear()
