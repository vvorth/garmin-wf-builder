"""Generated-symbol derivation: how a data source path, an element id or a
`config:` axis name becomes a Monkey C local, field, method or resource id.
Kept apart from :mod:`wfb.ir.model` so a symbol can be derived without
depending on the dataclasses it names -- the only exception is
`config_data_ids`, whose `face` parameter is typed for readability only, under
`TYPE_CHECKING`, and is never imported at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Face

# --------------------------------------------------------------------------
# helpers


def local_name(source_path: str) -> str:
    """The generated local variable holding one source's value.

    ``activity.step_goal`` -> ``activityStepGoal``.  Stable and derived, so the
    generated code reads the same way the YAML does.
    """
    parts = source_path.replace(".", "_").split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def config_field(name: str) -> str:
    """The view field a `config:` axis is cached in (``_configAccentColor``).

    Module-level rather than only a `ConfigColor` property because
    `Builder._build_scope` has to name the field for an axis that was
    *rejected* -- there is no `ConfigColor` for one of those, and deriving it
    a second time inline would be the same kind of duplicated symbol
    derivation `element_const_prefix`/`element_method_name` were moved here to
    stop (a mismatch between two copies is a `Redefinition` from `monkeyc`
    pointing at a generated line number).
    """
    return "_config" + _pascal(name)


def config_data_ids(face: "Face") -> dict[str, int]:
    """`config: data:` slot name -> the `<complication id="N">` this slot is
    emitted under, 1-based in declaration order (`docs/research/probes/
    config-axes/watchface.xml` numbers from 1, following the SDK's own
    sample).  Module-level, and derived from `face.config_data` rather than
    stored on `ConfigDataSlot` itself, so `wfb.emit.resources.config_resource`
    (writing the ids into the resource) and `wfb.emit.monkeyc._emit_apply_config`
    (matching `ComplicationRef.uniqueIdentifier` back against them) cannot
    silently number the same design's slots two different ways.
    """
    return {name: index for index, name in enumerate(face.config_data, start=1)}


def element_const_prefix(element_id: str) -> str:
    """The layout-constant prefix codegen derives from an element id.

    ``temp_low`` and ``tempLow`` both become ``TEMP_LOW``: separators are
    folded to ``_`` and a case boundary is treated as an implicit one, so
    that a design read either camelCase or snake_case still produces the
    Monkey C convention (`SCREAMING_SNAKE_CASE` constants).  That folding is
    exactly why two distinct ids can collide -- see
    :meth:`Builder._check_symbol_collision`, the one place this is checked.
    """
    out = []
    for index, char in enumerate(element_id):
        if char.isupper() and index and not element_id[index - 1].isupper():
            out.append("_")
        out.append(char.upper() if char.isalnum() else "_")
    return "".join(out)


def element_method_name(element_id: str) -> str:
    """The private draw method codegen derives from an element id (``drawTempLow``)."""
    return "draw" + _element_suffix(element_id)


def static_group_method(element_id: str) -> str:
    """The method that paints one static subtree (``drawStaticTicks``).

    A root already called ``static`` -- which is the id the top-level
    ``static:`` block is desugared under -- gives ``drawStatic``, not
    ``drawStaticStatic``: the prefix says what the method *is*, and repeating a
    word the id already carries is not something a person would write
    (ADR 0003).  Only a `group` root gets one of these; a static leaf is drawn
    by its own `draw<Id>` straight from `renderStatic`, because a wrapper around
    a single call is noise.

    Derived here rather than in the emitter for the same reason every other
    generated symbol is: :meth:`Builder._check_symbol_collision` has to see, in
    one place, every symbol an id can produce.
    """
    suffix = _element_suffix(element_id)
    return "drawStatic" if suffix == "Static" else "drawStatic" + suffix


def complication_slot_icon_method(element_id: str) -> str:
    """The private method that resolves one `complication_slot`'s icon glyph
    from a `Complications.Type` (``iconForTopReading``).

    A generated method, not an inline mutable local, because Monkey C locals
    cannot be given an explicit ``as String?`` type (verified: "Invalid
    explicit typing of a local variable" from a real build) -- there is no
    way to declare a local that starts `null` and is later assigned a
    `String` without one. Returning through a function whose own signature
    declares `String?` sidesteps that entirely: the call site's local infers
    its type from the function's declared return type instead.  Only emitted
    for a slot that actually draws an icon (`icon_size:` set); reserved here
    regardless, the same way `static_group_method` is reserved for every
    `group` whether or not it ends up static, so a later edit adding
    `icon_size:` cannot make an existing id collide with itself.
    """
    return "iconFor" + _element_suffix(element_id)


def complication_slot_hold_method(element_id: str) -> str:
    """The public method `on_hold: auto` on a `complication_slot` compiles to
    (``holdTargetForTopReading``), returning this slot's own current
    `Complications.Id` so the delegate can hand it straight to
    `Complications.exitTo` without baking in a fixed type at build time.

    Public, unlike every draw method, because the delegate is a different
    class and Monkey C's `private` genuinely blocks a cross-class call
    (verified by building both ways -- "Cannot find symbol" without the
    modifier dropped).  Only emitted for a slot that actually declares
    `on_hold: auto`, but derived here regardless of that, for the same "an
    unrelated later edit must not introduce a collision" reasoning
    `complication_slot_icon_method` already gives.
    """
    return "holdTargetFor" + _element_suffix(element_id)


def graph_series_field(element_id: str) -> str:
    """The view field holding a graph's cached series (``hrGraphSeries``)."""
    return _lower_first(_element_suffix(element_id)) + "Series"


def graph_min_field(element_id: str) -> str:
    """The view field holding a graph's auto-computed minimum, when
    `min_auto` is set -- unused, and not emitted, otherwise."""
    return _lower_first(_element_suffix(element_id)) + "Min"


def graph_max_field(element_id: str) -> str:
    return _lower_first(_element_suffix(element_id)) + "Max"


def graph_built_field(element_id: str) -> str:
    """The minute-of-last-rebuild field a graph checks every frame
    (``hrGraphBuiltAt``) -- see `runtime-lib/WfbSeries.mc`'s module docstring
    for why this is not the TTL cache this project deleted."""
    return _lower_first(_element_suffix(element_id)) + "BuiltAt"


def graph_rebuild_method(element_id: str) -> str:
    """The private method that recomputes one graph's series (``rebuildHrGraph``)."""
    return "rebuild" + _element_suffix(element_id)


def _element_suffix(element_id: str) -> str:
    parts = [p for p in element_id.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _pascal(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else " " for c in text)
    return "".join(word[:1].upper() + word[1:] for word in cleaned.split())


def font_resource_id(name: str) -> str:
    """The Monkey C resource id a font named ``name`` is emitted under.

    Shared between author-declared custom fonts (:class:`FontSpec`) and the
    synthetic per-size icon fonts (:mod:`wfb.icons`), so both are addressed the
    same way in generated code without either needing to know the other exists.
    """
    return f"Font{_pascal(name)}"


def config_label_id(axis: str, index: int) -> str:
    """The `<string>` resource id a labelled `config:` choice is emitted
    under (`ConfigDataColor0`), referenced from `<color label="@Strings...">`.

    Keyed by axis and position rather than by the label text itself: two
    choices could share a label (unlikely, but nothing forbids it), and a
    position-derived id is what every other generated symbol in this project
    already does (`element_const_prefix` and friends) rather than hashing
    author text.
    """
    return f"Config{_pascal(axis)}{index}"


def config_style_label_id(index: int) -> str:
    """The `<string>` resource id a labelled `color_scheme:` entry's Styles
    label is emitted under (`ConfigStyle0`), referenced from `<style
    label="@Strings...">`.

    Keyed by position, the same reasoning `config_label_id` already gives:
    two schemes could share a label, and a position-derived id matches every
    other generated symbol in this project rather than hashing author text.
    """
    return f"ConfigStyle{index}"
