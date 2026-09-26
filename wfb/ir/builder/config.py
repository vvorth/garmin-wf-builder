"""`config:`: the four on-device configuration axes -- Styles
(`style:`), Data (`data:`, complication slots) and the two colours
(`accent_color`, `data_color`)."""

from __future__ import annotations

from typing import Any

from ... import complications, icons
from ...diagnostics import Span
from ...palette import Color, ColorError

from ..model import ConfigChoice, ConfigColor, ConfigDataSlot, ConfigStyle, StyleEntry
from .state import _lint_suppression
from .glyphs import _NO_ICON_OVERRIDE, _ICON_OVERRIDE_ERROR
from .blocks import TopLevelBlocks


class ConfigAxes(TopLevelBlocks):
    """Builds the `config:` axes."""

    def _build_config_style(self, spec: dict[str, Any], span: Span | None) -> None:
        """`config: style:` -- an author-named, ordered set of entries riding
        Styles, the one axis Garmin gives no meaning to at all
        (docs/research/09 §3).  `config: colors:` is not a key; the schema
        rejects it.

        Unlike `accent_color`/`data_color`, entries are named by the
        *author* -- `choices:` is an ordered mapping, not a list -- so
        `default:` names an entry and "default must be one of choices" is an
        identity comparison on the entry name, not a scheme-name or
        colour-value one.

        Three uniform-shape passes, each rejecting the whole block at its
        first violation -- one error, not N (CLAUDE.md, docs/lore/codegen.md):

        1. every entry needs at least one of `layout:`/`colors:`;
        2. `layout:` is required on every entry once this design declares
           `layouts:`, and rejected when it does not -- an entry showing
           only shared content in a design that has layouts would be a
           silent blank-looking face;
        3. `colors:` is all-or-none across entries, independent of
           `layout:` -- a role must never be undefined for the entry the
           wearer picked.
        """
        raw_choices = spec["choices"]
        has_layouts = bool(self.layouts)

        for name, item in raw_choices.items():
            if "layout" in item or "colors" in item:
                continue
            self.bag.error(
                "config",
                f"config.style.choices.{name}: needs at least one of "
                "'layout:'/'colors:'",
                self.doc.span(raw_choices, name),
            )
            self.rejected_config.add("style")
            return

        for name, item in raw_choices.items():
            item_span = self.doc.span(raw_choices, name)
            has_layout = "layout" in item
            if has_layouts and not has_layout:
                self.bag.error(
                    "config",
                    f"config.style.choices.{name}: needs 'layout:' -- this "
                    "design declares 'layouts:', so every entry must pick one",
                    item_span,
                    notes=["declared layouts: "
                           + ", ".join(self.layouts)],
                )
                self.rejected_config.add("style")
                return
            if not has_layouts and has_layout:
                self.bag.error(
                    "config",
                    f"config.style.choices.{name}: 'layout:' is set, but "
                    "this design declares no 'layouts:' at all",
                    self.doc.span(item, "layout") or item_span,
                    notes=["remove 'layout:', or add a 'layouts:' block"],
                )
                self.rejected_config.add("style")
                return

        baseline_name = next(iter(raw_choices))
        baseline_has_colors = "colors" in raw_choices[baseline_name]
        for name, item in raw_choices.items():
            has_colors = "colors" in item
            if has_colors == baseline_has_colors:
                continue
            item_span = self.doc.span(raw_choices, name)
            if has_colors:
                message = (f"config.style.choices.{name}: declares "
                           f"'colors:', but 'choices.{baseline_name}' does not")
            else:
                message = (f"config.style.choices.{name}: needs 'colors:' "
                           f"-- 'choices.{baseline_name}' declares one")
            self.bag.error(
                "config", message, item_span,
                notes=["'colors:' must be declared on every entry, or none"],
            )
            self.rejected_config.add("style")
            return

        entries: list[StyleEntry] = []
        ok = True
        for name, item in raw_choices.items():
            item_span = self.doc.span(raw_choices, name)
            entry_ok = True
            colors_name: str | None = None
            if "colors" in item:
                color_span = self.doc.span(item, "colors") or item_span
                colors_name = self._scheme_reference(item["colors"], color_span)
                if colors_name is None:
                    entry_ok = False
            layout_name: str | None = None
            if "layout" in item:
                layout_span = self.doc.span(item, "layout") or item_span
                layout_name = self._layout_reference(item["layout"], layout_span)
                if layout_name is None:
                    entry_ok = False
            if not entry_ok:
                ok = False
                continue
            entries.append(StyleEntry(
                name=name,
                label=item.get("label"),
                colors=colors_name,
                layout=layout_name,
                **_lint_suppression(item),
                span=item_span,
            ))
        if not ok:
            self.rejected_config.add("style")
            return

        default_name = spec["default"]
        by_name = {e.name: e for e in entries}
        if default_name not in by_name:
            self._default_not_in_choices(
                "config.style", default_name, self.doc.span(spec, "default"),
                noun="entry", tag="style", listed="declared entries: " + ", ".join(by_name))
            self.rejected_config.add("style")
            return

        self.config_style = ConfigStyle(
            default=default_name, entries=tuple(entries), span=span)

    def _default_not_in_choices(
        self, where: str, default: object, span: Span | None, *,
        noun: str, tag: str, listed: str,
    ) -> None:
        """The shared "default is not one of 'choices:'" error every
        `config:` axis gives (`accent_color`/`data_color`, `style`, a `data`
        slot).  `tag` is the generated resource element the editor reads
        the default from; `listed` the closing note naming what is there."""
        article = "an" if noun[0] in "aeiou" else "a"
        self.bag.error(
            "config",
            f"{where}: default {default!r} is not one of 'choices:'",
            span,
            notes=[
                f"the on-device editor marks one listed {noun} as the user's "
                f"default (the generated <{tag} default=\"true\">) -- Garmin "
                "defines no behaviour for a default that is not in the list",
                f"add it to 'choices:', or change 'default:' to match {article} "
                f"{noun} already there",
                listed,
            ],
        )

    @staticmethod
    def _complication_suggestion_notes(name: str, noun: str) -> list[str]:
        """The shared "unknown complication" notes: a "did you mean: ...?"
        when `wfb.complications.TYPES.suggest` finds a near match, then
        "run `wfb complications` for the full list of N <noun>" -- built
        identically by `_complication_reference` (`noun="types"`) and
        `_hold_target` (`noun="launch targets"`), which name the same table
        for two different reasons.
        """
        notes = complications.TYPES.did_you_mean_notes(name)
        notes.append(f"run `wfb complications` for the full list of "
                     f"{len(complications.TYPES)} {noun}")
        return notes

    def _complication_reference(self, raw: object, what: str, span: Span | None) -> str | None:
        """Resolve a `complication.<name>` reference used from `config: data:`'s
        own `default:`/`choices:`, against :mod:`wfb.complications` -- the same
        table `on_hold:` and `catalog`'s `complication.*` sources already
        resolve against, not a second one (docs/research/09 §4).
        """
        if not (isinstance(raw, str) and raw.startswith("complication.")):
            self.bag.error("config", f"{what}: expected a 'complication.<name>' "
                                     f"reference, got {raw!r}", span)
            return None
        name = raw[len("complication."):]
        if complications.get(name) is not None:
            return name
        notes = self._complication_suggestion_notes(name, "types")
        self.bag.error("config", f"{what}: unknown complication type {raw!r}", span, notes=notes)
        return None

    def _build_config_data(self, raw: dict[str, Any], block_span: Span | None) -> None:
        """`config: data:` -- named native complication slots
        (docs/research/09-data-library-and-config-axes.md §4).

        Shaped like `_build_config`'s colour-axis loop: a compiled-in
        `default:` plus either `"any"` (the editor's own unrestricted
        complication picker) or an explicit, orderable `choices:` list --
        except every name here is a `complication.<name>` reference into
        :mod:`wfb.complications` rather than a colour.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.config_data.declare(name, span)
            default_span = self.doc.span(spec, "default")
            default = self._complication_reference(
                spec["default"], f"config.data.{name}.default", default_span)
            if default is None:
                self.config_data.reject(name)
                continue

            raw_choices = spec["choices"]
            if raw_choices == "any":
                self.config_data[name] = ConfigDataSlot(
                    name=name, default=default, choices="any", span=span)
                continue

            choices: list[str] = []
            icon_overrides: dict[str, icons.SlotIcon | None] = {}
            seen: dict[str, int] = {}
            ok = True
            for index, item in enumerate(raw_choices):
                item_span = self.doc.span(raw_choices, index)
                if isinstance(item, dict):
                    # `{type: complication.<name>, icon:/glyph: ...}` --
                    # carries more than the bare form, so it is not sugar.
                    type_span = self.doc.span(item, "type") if "type" in item else item_span
                    resolved = self._complication_reference(
                        item.get("type"), f"config.data.{name}.choices[{index}].type",
                        type_span)
                    if resolved is None:
                        ok = False
                        continue
                    override = self._resolve_choice_icon_override(
                        item, f"config.data.{name}.choices[{index}]", item_span)
                    if override is _ICON_OVERRIDE_ERROR:
                        ok = False
                        continue
                    if override is not _NO_ICON_OVERRIDE:
                        icon_overrides[resolved] = override
                else:
                    resolved = self._complication_reference(
                        item, f"config.data.{name}.choices[{index}]", item_span)
                    if resolved is None:
                        ok = False
                        continue
                if resolved in seen:
                    self.bag.error(
                        "config",
                        f"config.data.{name}.choices: complication.{resolved} is "
                        "listed more than once",
                        item_span,
                        notes=[
                            f"already listed at choices[{seen[resolved]}]",
                            "a type can appear at most once in 'choices:', "
                            "regardless of which shape (a bare reference or "
                            "{type, icon}/{type, glyph}) each appearance uses -- "
                            "the schema's own 'uniqueItems' cannot see through "
                            "the two different shapes",
                        ],
                    )
                    ok = False
                    continue
                seen[resolved] = index
                choices.append(resolved)
            if not ok:
                self.config_data.reject(name)
                continue

            if default not in choices:
                self._default_not_in_choices(
                    f"config.data.{name}", spec["default"], default_span,
                    noun="type", tag="type",
                    listed="listed types: " + ", ".join(f"complication.{n}" for n in choices))
                self.config_data.reject(name)
                continue

            self.config_data[name] = ConfigDataSlot(
                name=name, default=default, choices=tuple(choices),
                icon_overrides=icon_overrides, span=span)

    def _build_config(self, raw: dict[str, Any]) -> None:
        """`config:` -- the native editor's colour axes, the Styles axis, and
        the Data axis (ADR 0006 1, twice amended; docs/research/09 §4).

        `accent_color`/`data_color` read back as a single `Color`; `style`
        picks author-named entries, each naming a declared `color_scheme:`
        entry (`_build_config_style`) -- a different enough shape that it
        does not fit `ConfigAxis`/`ConfigColor` at all; `data` is a mapping
        of named slots, each built by `_build_config_data`.  Only these four
        keys reach here: the schema's `additionalProperties: false` on
        `config:` rejects anything else before the IR ever sees it, the same
        division of labour `_build_fonts` and `_build_palette` already rely
        on for their own blocks.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            if name == "style":
                self._build_config_style(spec, span)
                continue
            if name == "data":
                self._build_config_data(spec, span)
                continue
            default_span = self.doc.span(spec, "default")
            default = self._resolve_config_color(
                spec["default"], f"config.{name}.default", default_span)
            if default is None:
                self.rejected_config.add(name)
                continue

            raw_choices = spec["choices"]
            if raw_choices == "any":
                self.config[name] = ConfigColor(name=name, default=default, choices="any",
                                                span=span)
                continue

            choices: list[ConfigChoice] = []
            ok = True
            for index, item in enumerate(raw_choices):
                item_span = self.doc.span(raw_choices, index)
                if isinstance(item, str):
                    # A bare `palette.<name>` reference -- the schema accepts
                    # nothing else as a plain string here.  Contributes the
                    # entry's colour and, if it has one, its label.
                    color = self._palette_reference(item, item_span)
                    if color is None:
                        ok = False
                        continue
                    choices.append(ConfigChoice(
                        color=color,
                        label=self.palette_labels.get(item[len("palette."):]),
                    ))
                    continue
                try:
                    color = Color.parse(item["color"], what=f"config.{name}.choices[{index}]")
                except ColorError as exc:
                    self.bag.error("config", str(exc), self.doc.span(item, "color"))
                    ok = False
                    continue
                choices.append(ConfigChoice(color=color, label=item.get("label")))
            if not ok:
                self.rejected_config.add(name)
                continue

            if not any(choice.color == default for choice in choices):
                self._default_not_in_choices(
                    f"config.{name}", spec["default"], default_span,
                    noun="colour", tag="color",
                    listed="listed colours: " + ", ".join(str(c.color) for c in choices))
                self.rejected_config.add(name)
                continue

            self.config[name] = ConfigColor(name=name, default=default,
                                            choices=tuple(choices), span=span)
