"""Build-time checks, with explicit confidence (ADR 0008).

The linter is this framework's main claim to being better than hand-writing, so
its credibility matters more than its coverage.  Every check here states what it
rests on, and the two that cannot be exact -- memory and the partial-update
power budget -- say so in their own message rather than borrowing the authority
of the exact ones.

Checks that need no Garmin toolchain run in stages 1-3 and therefore work in CI.
Only :func:`check_memory` needs a real build.
"""

from __future__ import annotations

import difflib
import re

from . import availability, catalog, complications
from .devices import Device, version_key
from .diagnostics import Bag, Diagnostic, Severity, Span
from .fonts import BakedFont
from .ir import (
    CONFIG_SYMBOL, ComplicationSlot, Element, Face, FontSpec, HandsElement,
    PatternElement, StyleEntry, Text, authored_draw_order, never_together,
)
from .layout import (
    ANTIALIASED_PRIMITIVES, BEZEL_MARGIN, PlacedPattern, PlacedText, ResolvedFace,
    inside_screen, inside_visible_area_for, is_full_bleed, visible_reach,
)
from .palette import Color
from .units import IntBox

#: Checks an author may silence with ``lint: {allow: [...], reason: "..."}``.
#: The hard-platform-limit errors are deliberately absent: suppressing one
#: produces a face that does not work.
SUPPRESSIBLE = frozenset({
    "palette-dither", "safe-area", "text-overflow", "contrast", "partial-update-budget",
    "hold-unsupported", "hold-overlap", "api-gated",
    "dead-element", "graphics-pool", "antialias-dither", "static-overlap",
    "config-unsupported", "duplicate-style", "unreachable-layout",
    "sub-pixel-length", "font-unavailable", "off-screen", "text-outline-interior",
    "aod-unreachable", "aod-empty",
})
#: `api-gated-unguardable` is deliberately absent here -- see
#: `check_api_gated`'s case 5: it means the generator would emit an unguarded
#: call that crashes on a device that lacks it, the same "silencing this
#: ships a broken face" reasoning the hard-platform-limit errors above it
#: already follow.

#: Every diagnostic code emitted anywhere in this compiler -- not just the
#: checks in this file.  This is what lets :func:`check_lint_allow` tell a
#: misspelled code (not here at all) apart from a real one that is simply not
#: suppressible (here, but not in ``SUPPRESSIBLE``).  Derived by hand from a
#: grep of every ``bag.error/warning/note`` and ``Diagnostic(...)`` call across
#: ``wfb/`` -- ``tests/test_lint.py`` re-runs that grep and fails the build the
#: day this set drifts from what the compiler actually emits, so it cannot rot
#: silently.
ALL_CODES = frozenset({
    "antialias-dither",
    "aod", "aod-unreachable", "aod-empty",
    "api-gated", "api-gated-unguardable",
    "color", "color-scheme", "complication-slot",
    "config", "config-unsupported",
    "contrast", "dead-element",
    "element-mapping",
    "devices", "duplicate-id", "duplicate-style", "element", "expression",
    "font", "font-unavailable", "format", "format-version", "graph", "graphics-pool", "hands",
    "icon", "io",
    "layouts", "lint-allow", "memory",
    "metrics", "missing-glyph", "monkeyc", "off-screen", "palette",
    "hold-overlap", "hold-unsupported",
    "hold-auto-ambiguous", "hold-auto-unresolved",
    "palette-dither", "partial-update", "partial-update-budget", "pattern",
    "pattern-step", "permission",
    "on-hold", "overrides", "raw-color", "safe-area", "schema", "source-renamed",
    "sub-pixel-length", "target",
    "static", "static-overlap", "string-label",
    "text-antialias", "text-curve", "text-outline", "text-outline-interior",
    "unreachable-layout",
    "text-overflow", "toolchain", "type", "units", "when-absent", "yaml",
})


def run(resolved: ResolvedFace, bag: Bag) -> None:
    """Stage 3: everything computable from resolved geometry on one device."""
    check_palette(resolved, bag)
    check_antialias_palette(resolved, bag)
    check_config_palette(resolved, bag)
    check_color_scheme_palette(resolved, bag)
    check_config_support(resolved, bag)
    check_geometry(resolved, bag)
    check_sub_pixel_length(resolved, bag)
    check_text_fit(resolved, bag)
    check_glyphs(resolved, bag)
    check_contrast(resolved, bag)
    check_partial_update_budget(resolved, bag)
    check_hold_targets(resolved, bag)
    check_dead_element(resolved, bag)
    check_aod_unreachable(resolved, bag)
    check_aod_empty(resolved, bag)
    check_api_gated(resolved, bag)
    check_graphics_pool(resolved, bag)
    check_static_overlap(resolved, bag)
    check_text_outline_interior(resolved, bag)
    check_pattern_step(resolved, bag)
    for warning in resolved.warnings:
        bag.note("metrics", warning, confidence="not checked -- no metrics available")


def _suppressed_element(element: Element, code: str) -> bool:
    """The one place that knows what "suppressed" means: the code names a
    real suppressible diagnostic, and this exact element accepted it."""
    return code in element.lint_allow and code in SUPPRESSIBLE


def _suppressed(placed, code: str) -> bool:
    return _suppressed_element(placed.element, code)


def _emit(bag: Bag, placed, diag: Diagnostic) -> None:
    if _suppressed(placed, diag.code):
        return
    bag.add(diag)


def _suppressed_by_any(users: list[Element], code: str) -> bool:
    """For a diagnostic about a shared declaration (a `palette:` entry, a
    `config:` axis, a colour-scheme role) rather than one placed element:
    there is no element of its own to hang `lint: {allow: [...]}` on, so
    suppression is honoured on whichever element(s) actually reference the
    declaration -- a dithered colour dithers everywhere it is drawn, so
    acknowledging it once, on any one use, is acknowledging the colour
    itself.
    """
    return any(_suppressed_element(user, code) for user in users)


def _emit_for_element(bag: Bag, users: list[Element], diag: Diagnostic) -> None:
    """Like `_emit`, but for a declaration with several (or zero) candidate
    users instead of one placed element -- see `_suppressed_by_any`."""
    if _suppressed_by_any(users, diag.code):
        return
    bag.add(diag)


# -- permissions ------------------------------------------------------------


def check_permissions(face: Face, bag: Bag) -> None:
    """Every permission a binding implies must be legal for a watch face.

    Device-independent, so this runs once rather than per target.  ``monkeyc``
    would reject the manifest anyway, but it reports the permission without
    naming the binding that produced it -- and since this compiler *derives* the
    permission set, the author has no line to look at.  Here the diagnostic can
    point straight at the source responsible.
    """
    for element in face.walk():
        for expression in element.expressions():
            for path in expression.sources:
                source = catalog.get(path)
                if source is None:
                    continue
                for permission in source.permissions:
                    if permission in catalog.WATCHFACE_PERMISSIONS:
                        continue
                    bag.error(
                        "permission",
                        f"{element.id}: {path!r} needs the {permission!r} permission, "
                        f"which a watch face may not declare",
                        expression.span or element.span,
                        notes=[
                            "the SDK's permission table leaves the Watch Face column "
                            "blank for this one (Core_Topics/Manifest_and_Permissions)",
                            "legal for a watch face: "
                            + ", ".join(sorted(catalog.WATCHFACE_PERMISSIONS)),
                        ],
                        confidence="exact -- the SDK's own permission table",
                    )


def check_duplicate_style(face: Face, bag: Bag) -> None:
    """Two `config: style:` entries with the same `(layout, colors)` pair are
    indistinguishable on the wrist: the editor lists two entries that look,
    and behave, identically.  In a design with no `layouts:`, `layout` is
    `None` on every entry, and this reduces to "two entries name the same
    `colors:` scheme"; the pair test checks both fields regardless, so a
    layout-carrying design is covered the same way with no change here.

    A designer may still want this deliberately (two labels while iterating,
    say), so it is a warning, not an error, and suppressible -- on the
    *second* entry of the pair, since that is the one that makes the
    combination a duplicate; the first establishes it and needs no
    acknowledgement of its own.

    Device-independent (an entry's `layout`/`colors` never varies by
    target), so -- like :func:`check_permissions` -- this runs once per
    design, in `resolve_all`, rather than once per target.
    """
    axis = face.config_style
    if axis is None:
        return
    seen: dict[tuple[str | None, str | None], StyleEntry] = {}
    for entry in axis.entries:
        key = (entry.layout, entry.colors)
        first = seen.setdefault(key, entry)
        if first is entry:
            continue
        if "duplicate-style" in entry.lint_allow:
            continue
        bag.warning(
            "duplicate-style",
            f"config.style.choices.{entry.name}: the same combination as "
            f"'{first.name}' -- indistinguishable on the wrist",
            entry.span,
            notes=[
                f"both resolve to colors: {entry.colors!r}"
                + (f", layout: {entry.layout!r}" if entry.layout is not None else ""),
                "set 'lint: {allow: [duplicate-style], reason: ...}' on "
                f"'{entry.name}' to accept it -- e.g. two labels while "
                "iterating on the same look",
            ],
        )


def check_unreachable_layout(face: Face, bag: Bag) -> None:
    """A declared `layouts:` entry no `config: style:` entry ever names as
    its `layout:` -- its content ships in the `.prg` (every layout's
    elements, fonts and code are in the build together) but can never be
    drawn, because nothing lets the wearer switch to it.

    A warning, not an error -- an author may be mid-iteration, with a layout
    built but not yet wired to an entry -- and suppressible, on the layout's
    own `lint:`: a layout has no element of its own to hang `lint:` on, the
    same reasoning a `config: style:` entry's own `lint:` follows for
    `duplicate-style`.

    Design-level, not per-target (a layout's reachability never varies by
    device), so -- like :func:`check_permissions`/:func:`check_duplicate_style`
    -- this runs once per design, in `resolve_all`, rather than once per
    target.
    """
    if not face.layouts:
        return
    referenced: set[str] = set()
    if face.config_style is not None:
        referenced = {e.layout for e in face.config_style.entries if e.layout is not None}
    for name in face.layouts:
        if name in referenced:
            continue
        decl = face.layout_decls[name]
        if "unreachable-layout" in decl.lint_allow:
            continue
        bag.warning(
            "unreachable-layout",
            f"layouts.{name}: no 'config: style:' entry names it as its "
            f"'layout:' -- it can never be drawn",
            decl.span,
            notes=[
                "its elements, fonts and code still ship in the .prg -- "
                "content is not free even though a style entry is",
                "name it from a 'config: style:' entry's 'layout:', or "
                "delete the layout",
                "set 'lint: {allow: [unreachable-layout], reason: ...}' on "
                f"'layouts.{name}' to accept it",
            ],
        )


def check_vector_font_availability(
    face: Face, resolved: dict[str, ResolvedFace], bag: Bag,
) -> None:
    """`if_unavailable:` (plan 11 §2.4) -- `error`/`hide` are inherently
    cross-device questions ("did gates 1-3 fail on ANY target?"), unlike
    every check in this module that reads a single device's own
    `ResolvedFace` (`run`'s per-device loop): so this is not part of `run`,
    and does not take one `ResolvedFace` -- `wfb.build.resolve_all` calls
    it once, after every target device in this build has been resolved.
    `wfb.layout.Resolver._resolve_vector_face` has already decided, per
    device, whether gates 1-3 passed (`PlacedText.font_available`); this
    only turns "failed on device X" into a diagnostic, and is therefore
    also the one place that can see "failed on *every* device this build
    actually targets", which is what `error` means.

    **`error` (the default) is a hard build failure, never suppressible**
    -- the same "silencing this ships a broken face" reasoning
    `_check_one_lint_allow` gives the hard-platform-limit checks, even
    though `font-unavailable` is in `SUPPRESSIBLE` for the `hide` case
    below: an author in `error` mode who wants leniency switches the font
    or the element to `hide` outright, rather than suppressing the failure
    while leaving the design still asking for a face that will never draw.
    Names the element, every failing device, and *why* each one fails:
    gate 1 (`Graphics.getVectorFont`, or under `curve:` the matching
    `drawAngledText`/`drawRadialText`, missing entirely) is a categorically
    different failure from gates 2/3 (the symbol exists, but none of the
    requested faces is in this device's own catalogue) -- plan 11 §1's own
    instruction is that the author needs to know which, so the message
    never collapses them into one "unavailable".

    **`hide` draws nothing there and is not a build error** -- a
    suppressible warning instead, naming every device the element will not
    draw on.

    **Covers a `Text` element's own `font:` and a pattern's `shape: text`
    part's own `font:` alike** (plan 11 slice 2) -- the same gates, the
    same `if_unavailable:` precedence (the part's own value wins over the
    font's), reported through the shared `_report_vector_font_unavailable`
    so the two cannot drift into different wording for the same failure. A
    pattern part is named `<pattern id>.parts[<i>]`, and suppression
    (`hide` mode's warning only) reads the *pattern's* own `lint: {allow:
    [...]}` -- a `HandPart` carries no `lint:` of its own to hang it on.
    """
    placed_by_device: dict[str, dict[str, PlacedText]] = {
        device_id: {p.id: p for p in rf.items if isinstance(p, PlacedText)}
        for device_id, rf in resolved.items()
    }
    #: The pattern counterpart, keyed the same way (plan 11 slice 2): a
    #: `PlacedPattern`'s own `parts` line up 1:1 with `PatternElement.parts`
    #: (`Resolver._resolve_pattern` builds one `ResolvedHandPart` per
    #: `HandPart`), so a part's availability is `pp.parts[part_index].
    #: font_available`, the same shape `placed_by_device` gives a `Text`
    #: element's own `PlacedText.font_available`.
    pattern_by_device: dict[str, dict[str, PlacedPattern]] = {
        device_id: {p.id: p for p in rf.items if isinstance(p, PlacedPattern)}
        for device_id, rf in resolved.items()
    }
    for element in face.walk():
        if isinstance(element, Text) and element.font_is_custom:
            spec = face.fonts.get(element.font)
            if spec is None or not spec.is_vector:
                continue
            failing = sorted(
                device_id
                for device_id, placed in placed_by_device.items()
                if (item := placed.get(element.id)) is not None and not item.font_available
            )
            if not failing:
                continue
            effective = element.if_unavailable or spec.if_unavailable or "error"
            _report_vector_font_unavailable(
                bag, resolved, what=element.id, font_name=element.font, spec=spec,
                curve=element.curve, span=element.span, effective=effective,
                lint_allow=element.lint_allow, failing=failing,
                fix_note=(
                    f"set 'if_unavailable: hide' on 'font.{element.font}' or on "
                    f"'{element.id}' to let it disappear on a target that cannot "
                    "draw it, drop the device from 'targets:', or add a face it "
                    "actually publishes"
                ),
            )
        elif isinstance(element, PatternElement):
            for part_index, part in enumerate(element.parts):
                if part.shape != "text" or not part.font_is_custom:
                    continue
                spec = face.fonts.get(part.font)
                if spec is None or not spec.is_vector:
                    continue
                failing = sorted(
                    device_id
                    for device_id, placed in pattern_by_device.items()
                    if (pp := placed.get(element.id)) is not None
                    and part_index < len(pp.parts)
                    and not pp.parts[part_index].font_available
                )
                if not failing:
                    continue
                part_where = f"{element.id}.parts[{part_index}]"
                effective = part.if_unavailable or spec.if_unavailable or "error"
                _report_vector_font_unavailable(
                    bag, resolved, what=part_where, font_name=part.font, spec=spec,
                    curve=part.curve, span=part.span, effective=effective,
                    lint_allow=element.lint_allow, failing=failing,
                    fix_note=(
                        f"set 'if_unavailable: hide' on 'font.{part.font}' or on "
                        f"'{part_where}' to let it disappear on a target that cannot "
                        "draw it, drop the device from 'targets:', or add a face it "
                        "actually publishes"
                    ),
                )


def _report_vector_font_unavailable(
    bag: Bag, resolved: dict[str, ResolvedFace], *, what: str, font_name: str,
    spec: FontSpec, curve, span: Span | None, effective: str, lint_allow: frozenset[str],
    failing: list[str], fix_note: str,
) -> None:
    """The shared error/warning body :func:`check_vector_font_availability`
    reports for either a `Text` element or a pattern's own `shape: text`
    part -- identical wording either way (`what` is the element id or
    `<pattern id>.parts[<i>]`), so the two cannot silently drift into
    different messages for the same underlying gate failure.
    """
    requested = ", ".join(spec.face)
    if effective == "error":
        reasons = [
            _vector_font_failure_reason(resolved[device_id].device, spec, curve)
            for device_id in failing
        ]
        bag.error(
            "font-unavailable",
            f"{what}: 'font: font.{font_name}' has no usable face on " + ", ".join(failing),
            span,
            notes=[
                f"requested face(s), in author order: {requested}",
                *reasons,
                fix_note,
            ],
            confidence="exact -- resolved per-device gates 1-3",
        )
        return
    if "font-unavailable" in lint_allow:
        return
    bag.warning(
        "font-unavailable",
        f"{what}: will not draw on " + ", ".join(failing)
        + f" -- 'font: font.{font_name}' has no usable face there",
        span,
        notes=[
            f"requested face(s), in author order: {requested}",
            "set 'lint: {allow: [font-unavailable], reason: ...}' on "
            f"'{what}' to accept it",
        ],
        confidence="exact -- resolved per-device gates 1-3",
    )


def _vector_font_failure_reason(device: Device, spec: FontSpec, curve) -> str:
    """One line naming *why* `spec.face` failed to resolve on `device` --
    gate 1 (the symbol itself is absent) and gates 2/3 (the symbol exists,
    but the device's own catalogue has none of the requested faces) are
    different failures with different fixes, so
    :func:`check_vector_font_availability` never collapses them into one
    "unavailable" (plan 11 §1's own instruction).
    """
    if not device.has_symbol(Device.VECTOR_FONT_SYMBOL):
        return (f"{device.id}: has no {Device.VECTOR_FONT_SYMBOL!r} at all (gate 1) "
                "-- no device-resident face, of any name, can ever be drawn here")
    if curve is not None:
        symbol = (Device.DRAW_ANGLED_TEXT_SYMBOL if curve.style == "angled"
                 else Device.DRAW_RADIAL_TEXT_SYMBOL)
        if not device.has_symbol(symbol):
            return (f"{device.id}: has {Device.VECTOR_FONT_SYMBOL!r} but not "
                    f"{symbol!r} (gate 1) -- 'curve: {{style: {curve.style}}}' "
                    "cannot draw here even though a plain, upright 'face:' text could")
    published = ", ".join(device.scalable_faces) if device.scalable_faces else "none"
    return (f"{device.id}: publishes {published} (gates 2/3) -- none of the "
            "requested face(s) is in that list")


def _check_one_lint_allow(bag: Bag, what: str, span, code: str) -> None:
    """The body of :func:`check_lint_allow`, for one `lint: {allow: [...]}`
    code on one owner -- an element (`what` is its id) or a `config: style:`
    entry (`what` is `config.style.choices.<name>`).  Factored out so both
    owners get byte-identical error text and the same registry lookups.
    """
    if code in SUPPRESSIBLE:
        return
    if code in ALL_CODES:
        bag.error(
            "lint-allow",
            f"{what}: {code!r} is a real diagnostic code, but it is "
            f"deliberately not suppressible",
            span,
            notes=[
                "the hard-platform-limit checks stay unsuppressible on purpose: "
                "silencing one would produce a face that does not work",
                "suppressible codes: " + ", ".join(sorted(SUPPRESSIBLE)),
            ],
            confidence="exact -- SUPPRESSIBLE is this file's own registry",
        )
        return
    near = difflib.get_close_matches(code, ALL_CODES, n=1, cutoff=0.6)
    notes = ["suppressible codes: " + ", ".join(sorted(SUPPRESSIBLE))]
    if near:
        notes.insert(0, f"did you mean {near[0]!r}?")
    bag.error(
        "lint-allow",
        f"{what}: {code!r} is not a diagnostic code this compiler emits",
        span,
        notes=notes,
        confidence="exact -- SUPPRESSIBLE is this file's own registry",
    )


def check_lint_allow(face: Face, bag: Bag) -> None:
    """A ``lint: {allow: [...]}`` entry must name a code this compiler can
    actually suppress.

    Before this check existed, an unknown code (a typo) and a real-but-hard
    check (naming one of the errors ``SUPPRESSIBLE`` deliberately excludes)
    both failed the exact same way: silently.  The warning the author was
    trying to silence just kept firing, with nothing to say whether they
    misspelled the code or the check itself refuses suppression on purpose.

    An element's ``lint_allow`` is fixed once the IR is built, before any
    device is resolved, so -- like :func:`check_permissions` -- this runs once
    per build rather than once per device.  A `config: style:` entry's own
    ``lint:`` (the suppression site for `duplicate-style`) and a `layouts:`
    entry's own ``lint:`` (the suppression site for `unreachable-layout`)
    are both validated the same way, through the same helper -- there is no
    per-target device dependency at either site either.
    """
    for element in face.walk():
        for code in sorted(element.lint_allow):
            _check_one_lint_allow(bag, element.id, element.span, code)
    if face.config_style is not None:
        for entry in face.config_style.entries:
            for code in sorted(entry.lint_allow):
                _check_one_lint_allow(
                    bag, f"config.style.choices.{entry.name}", entry.span, code)
    for name in face.layouts:
        decl = face.layout_decls[name]
        for code in sorted(decl.lint_allow):
            _check_one_lint_allow(bag, f"layouts.{name}", decl.span, code)


# -- check 3: palette legality ---------------------------------------------


#: Element fields that can carry a bare ``palette.<name>`` reference.  Not
#: every element kind has all three -- ``Text``/``Shape``/``IconElement``
#: have only ``color``, ``Progress`` also has ``track_color``,
#: ``ComplicationSlot`` also has ``icon_color`` -- ``getattr`` covers the
#: gap without needing an isinstance check per kind here.
_PALETTE_REFERENCING_FIELDS = ("color", "track_color", "icon_color")


def _users_of(face: Face, token: str) -> list[Element]:
    """Elements whose ``color:``/``track_color:`` is exactly ``token``.

    This is deliberately an exact textual match on the author's own expression
    text, not a search through folded constants -- a conditional expression
    that merely *mentions* the reference (``hr.current > 100 ? palette.fg :
    ...``) does not count, because the dithering these checks are about is a
    property of the named colour itself, not of any one place it is used, and
    claiming to trace it through arbitrary expressions would overclaim what
    this check can actually verify.  Shared by :func:`_palette_users`,
    :func:`_config_users` and :func:`_config_colors_role_users`, which differ
    only in which token they build.

    A `HandsElement` has no `color:` field of its own -- its colours live on
    the `hour:`/`minute:`/`second:` hands its `hands:` names, already folded
    into `HandsElement.colors` at build time (`Builder._build_hands_element`)
    -- so it is matched by exact text there instead: every check that reads
    a shape's `.color` must also read the part colours.  A `PatternElement`
    *does* have its own `color:` (the default every part without one
    inherits), but a part may override it -- so it is matched the same way,
    through its own `.colors`, checked first so its `color:` field is never
    read through the generic branch below and short-circuit a part's
    override out of the match.
    """
    out = []
    for element in face.walk():
        if isinstance(element, (HandsElement, PatternElement)):
            if any(color.text == token for color in element.colors):
                out.append(element)
        elif any(
            (expression := getattr(element, field, None)) is not None
            and expression.text == token
            for field in _PALETTE_REFERENCING_FIELDS
        ):
            out.append(element)
    return out


def _palette_users(face: Face, name: str) -> list[Element]:
    """Elements whose ``color:``/``track_color:`` is exactly ``palette.<name>``."""
    return _users_of(face, f"palette.{name}")


def _dither_suppress_note(users: list[Element], token: str) -> str:
    """The two variants of "how to accept this dithered colour" note, shared
    by every dither check below: point at an existing user if one exists, or
    say honestly that there is nowhere yet to put the suppression -- the
    note must never claim a suppression mechanism that does not exist.
    """
    if users:
        return (
            f"set 'lint: {{allow: [palette-dither], reason: ...}}' on the element "
            f"whose 'color:' or 'track_color:' is '{token}' to keep it"
        )
    return (
        f"no element's 'color:' or 'track_color:' is exactly '{token}', "
        f"so there is nowhere to put 'lint: {{allow: [palette-dither]}}' for it"
    )


def _emit_dither(
    bag: Bag, users: list[Element], message: str, nearest_note: str, token: str,
) -> None:
    """The common back half of `check_palette`/`check_config_palette`/
    `check_color_scheme_palette`: build the notes every dither warning shares
    and emit through :func:`_emit_for_element`, since none of the three has a
    single element of its own to hang `lint:` on -- suppression is honoured
    on whichever element(s) actually reference the declaration via `color:`
    or `track_color:`. That is the right scope: a dithered colour dithers
    every place it is drawn, so acknowledging it once, on any one use, is
    acknowledging the colour itself.
    """
    _emit_for_element(bag, users, Diagnostic(
        Severity.WARNING,
        "palette-dither",
        message,
        notes=[
            nearest_note,
            "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is "
            "dithered by the firmware and looks grainy",
            _dither_suppress_note(users, token),
        ],
        confidence="exact -- device display_colors",
    ))


def check_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Each channel must be 0x00/0x55/0xAA/0xFF on a 64-colour panel.

    The warning is about a *palette entry*, not an element -- ``palette:`` is
    a flat mapping with nowhere of its own to hang a ``lint:`` block (and
    schema/IR changes are out of scope here) -- so suppression is honoured on
    whichever element(s) actually reference the entry via ``color:`` or
    ``track_color:``.  That is the right scope: a dithered colour dithers
    every place it is drawn, so acknowledging it once, on any one use, is
    acknowledging the colour itself.
    """
    colors = resolved.device.display_colors
    if colors is None:
        bag.note(
            "palette-dither",
            f"{resolved.device.id}: palette size is unknown, so colour legality is not checked",
            confidence="not checked",
        )
        return
    for name, color in resolved.face.palette.items():
        if color.is_palette_legal(colors):
            continue
        users = _palette_users(resolved.face, name)
        nearest = color.nearest_legal(colors)
        _emit_dither(
            bag, users,
            f"palette.{name} = {color} is not one of {resolved.device.id}'s "
            f"{colors} colours and will be dithered",
            f"nearest legal colour: {nearest}",
            f"palette.{name}",
        )


def check_antialias_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Anti-aliasing manufactures the exact intermediate values a 64-colour
    panel cannot show cleanly.

    Constraint 13 (CLAUDE.md) is what :func:`check_palette` is about: each
    channel must land on 0x00/0x55/0xAA/0xFF or the firmware dithers it.  A
    soft edge is, by construction, a blend between the shape's colour and
    whatever is behind it -- every intermediate pixel it produces is an
    intermediate value, deliberately, the entire point of asking for one.  So
    the same rule fires here for the same reason, just without a specific
    off-grid colour to name: the colours at both ends can each be perfectly
    legal and the blend between them still is not.

    Once per **device**, not once per element: unlike a `palette:` entry,
    which is one colour that either is or is not legal, "is anti-aliasing
    used anywhere on this device" is the only fact this check can state --
    exactly how many edges are soft and how visible each one is depends on
    geometry and colour this check does not (and should not) try to model.
    Reported against the first element that actually draws anti-aliased, the
    same "one representative, not one diagnostic per user" shape
    :func:`check_graphics_pool` already uses, so `lint: {allow: [...]}` on
    that one element silences the device-wide note.

    **Severity: WARNING, matching `palette-dither` rather than
    `graphics-pool`'s informational half.** The two checks reach the same
    firmware behaviour (channel quantization) from two different directions,
    and `palette-dither` already treats it as something the author should
    hear about, not just a number to log. The one thing worth weighing
    explicitly: all three of this project's current targets are 64-colour, so
    this warning fires on *every* face that turns primitive anti-aliasing on
    at all, with no way to satisfy it short of turning the feature back off
    (there is no "legal" soft edge on a 64-colour panel the way there is a
    legal palette colour) -- unlike `palette-dither`, where picking a
    different colour is a real fix. That is a real cost to this check's
    signal-to-noise, but not a reason to go quiet about it: an author who has
    already made this tradeoff on purpose acknowledges it once, on the one
    element that triggered it, with `lint: {allow: [antialias-dither],
    reason: ...}` -- the same one-line acceptance `palette-dither` and
    `graphics-pool` already ask for.
    """
    colors = resolved.device.display_colors
    if colors != 64:
        return
    users = [
        placed for placed in resolved.items
        if isinstance(placed, ANTIALIASED_PRIMITIVES)
        and placed.element.resolved_antialias
    ]
    if not users:
        return
    _emit(bag, users[0], Diagnostic(
        Severity.WARNING,
        "antialias-dither",
        f"{resolved.device.id}: anti-aliased primitive drawing is enabled, and this "
        f"device's panel shows only {colors} colours -- every soft edge it draws "
        f"will be dithered",
        users[0].element.span,
        notes=[
            "each channel must be 0x00, 0x55, 0xAA or 0xFF; anti-aliasing blends "
            "toward values in between by construction, so this is not avoidable "
            "while antialias: stays true here",
            f"{len(users)} element(s) draw anti-aliased on {resolved.device.id}: "
            + ", ".join(sorted(p.id for p in users)),
            "set 'lint: {allow: [antialias-dither], reason: ...}' on "
            f"'{users[0].id}' to accept it",
        ],
        confidence="exact -- device display_colors",
    ))


def _config_users(face: Face, name: str) -> list[Element]:
    """Elements whose `color:`/`track_color:` is exactly `config.<name>`.

    Same exact-textual-match rule as :func:`_palette_users`, for the same
    reason: the colour is either legal or it is not, independent of any one
    conditional expression that merely mentions it.
    """
    return _users_of(face, f"config.{name}")


def _config_colors_role_users(face: Face, role: str) -> list[Element]:
    """Elements whose `color:`/`track_color:` is exactly `config.colors.<role>`.

    Same exact-textual-match rule as :func:`_config_users`/`_palette_users`.
    """
    return _users_of(face, f"config.colors.{role}")


def _slot_users(face: Face, name: str) -> list[Element]:
    """`complication_slot` elements whose `slot:` is exactly `config.data.<name>`."""
    return [element for element in face.walk()
            if isinstance(element, ComplicationSlot) and element.slot == name]


def check_config_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """A declared `config:` colour is checked the same way a `palette:` entry
    is -- each channel must be 0x00/0x55/0xAA/0xFF on a 64-colour panel, or
    the firmware dithers it.

    Every colour a design can ever show through this axis is checked: the
    compiled-in `default:` always (it is the only value a device with no
    native editor -- fr955 -- ever shows), and -- when `choices:` is an
    explicit list -- every listed choice too, since the wearer can pick any
    of them on a device with the native editor.  `choices: any` skips only
    the list half: it hands the wearer the editor's own unrestricted picker,
    which this compiler has no list to check.

    Reported the same way :func:`check_palette` reports a palette entry:
    against whichever element's `color:`/`track_color:` is exactly
    `config.<name>`, so `lint: {allow: [palette-dither], reason: ...}` there
    silences it -- the same code, because it is the same firmware behaviour
    reached from a different declaration.
    """
    colors = resolved.device.display_colors
    if colors is None:
        return  # check_palette already emits the one "not checked" note per device
    for name, entry in resolved.face.config.items():
        # `default:` is checked unconditionally: it is compiled in and is the
        # only value a device with no native editor (fr955) ever shows, no
        # matter what `choices:` says. `choices: any` skips only the *list*
        # half -- there is no list to check when the wearer gets the
        # editor's own unrestricted picker instead.
        offenders = [entry.default] if entry.allow_any else (
            [entry.default] + [c.color for c in entry.choices]
        )
        bad = [c for c in offenders if not c.is_palette_legal(colors)]
        if not bad:
            continue
        users = _config_users(resolved.face, name)
        nearest = ", ".join(f"{c} -> {c.nearest_legal(colors)}" for c in bad)
        _emit_dither(
            bag, users,
            f"config.{name}: {len(bad)} declared colour(s) are not one of "
            f"{resolved.device.id}'s {colors} colours and will be dithered",
            f"off-grid -> nearest legal: {nearest}",
            f"config.{name}",
        )


def check_color_scheme_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Every colour a `config: style:` entry's `colors:` can ever put on
    screen, checked the same way a `config:` colour axis is.

    A `color_scheme:` entry has no `choices: any` equivalent -- Styles has no
    unrestricted picker -- so every role of every scheme some entry actually
    references is checked, the same "every listed choice, not only the
    default" scope :func:`check_config_palette` gives an explicit list.  Two
    entries may reference the same scheme (that is exactly what makes them
    `duplicate-style` candidates), so the schemes checked here are
    deduplicated, in first-reference order.  A scheme declared but never
    referenced by any entry is unreachable on any device (`resolveStyle`
    only ever assigns for a referenced scheme), so it is not checked here --
    there is nothing on the wrist for the warning to be about.
    """
    colors = resolved.device.display_colors
    if colors is None:
        return  # check_palette already emits the one "not checked" note per device
    axis = resolved.face.config_style
    if axis is None:
        return
    default_entry = axis.default_entry
    if default_entry.colors is None:
        return  # a layout-only default entry has no scheme role to check
    roles = sorted(resolved.face.color_scheme[default_entry.colors].colors)
    scheme_names = list(dict.fromkeys(
        e.colors for e in axis.entries if e.colors is not None))
    for role in roles:
        offenders = [
            (name, resolved.face.color_scheme[name].colors[role])
            for name in scheme_names
        ]
        bad = [(name, c) for name, c in offenders if not c.is_palette_legal(colors)]
        if not bad:
            continue
        users = _config_colors_role_users(resolved.face, role)
        nearest = ", ".join(
            f"color_scheme.{name}.colors.{role}={c} -> {c.nearest_legal(colors)}"
            for name, c in bad
        )
        _emit_dither(
            bag, users,
            f"config.colors.{role}: {len(bad)} declared colour(s) are not one of "
            f"{resolved.device.id}'s {colors} colours and will be dithered",
            f"off-grid -> nearest legal: {nearest}",
            f"config.colors.{role}",
        )


def check_config_support(resolved: ResolvedFace, bag: Bag) -> None:
    """Does this device actually have the native on-device editor?

    Resolved against the device's own symbol table, not an API-level compare
    -- constraint 6 again: fr955 reports 5.2.0, above the editor's documented
    5.1.0, and still has no editor at all
    (`docs/research/probes/watchface-config/`).  A device without it still
    compiles and runs every line `config:` generates; it just keeps the
    declared `default:` forever, which is a real, user-facing consequence of
    ADR 0006 2's chosen scope, not a bug -- and must not be silent.

    **Except a `config.data.*` slot on a device that also lacks
    `Toybox.Complications`** (fenix6, fenix6xpro, fr245 today): a slot's
    `default:` is not a plain compiled constant the way
    `accent_color`/`data_color`/`colors.<role>` are -- it is read through
    `WfbComplications.valueOf` the same as any other choice, so a device
    missing the module cannot resolve it either, and the slot shows its
    absent state instead of "keeping" anything. That case is reported
    separately below, with accurate wording, and is *not* the same fact as
    `check_api_gated`'s own `api-gated` warning about the same slot -- see
    that function's case 4 for why both fire together rather than one
    deduping the other.
    """
    face = resolved.face
    if not face.has_config:
        return
    config = face.config
    device = resolved.device
    try:
        available = device.has_symbol(CONFIG_SYMBOL)
    except Exception:
        bag.note(
            "config-unsupported",
            f"{device.id}: no symbol table, so on-device config support is not checked",
            confidence="not checked -- the device's api.debug.xml is unavailable",
        )
        return
    if available:
        return

    names_list = [f"config.{name}" for name in sorted(config)]
    role_tokens: list[str] = []
    non_default_entries: list[str] = []
    if face.config_style is not None:
        default_entry = face.config_style.default_entry
        if default_entry.colors is not None:
            # A layout-only default entry names no role at all -- there is no
            # scheme to read one from.
            default_scheme = face.color_scheme[default_entry.colors]
            role_tokens = [f"config.colors.{role}" for role in sorted(default_scheme.colors)]
            names_list += role_tokens
        non_default_entries = [
            e.name for e in face.config_style.entries if e.name != face.config_style.default
        ]
    slot_tokens = [f"config.data.{name}" for name in sorted(face.config_data)]
    names_list += slot_tokens
    if not names_list and not non_default_entries:
        # Nothing the wearer could ever observe differently: no colour axis,
        # no role, no slot, and (a single-entry `config: style:`) no
        # unreachable entry either -- a design this trivial has nothing for
        # `config-unsupported` to be about.
        return
    names = ", ".join(names_list)

    # A config.data.* slot's own 'default:' is itself read through
    # Toybox.Complications (WfbComplications.valueOf), not compiled in as a
    # plain constant the way config.accent_color/data_color/colors.<role>
    # are -- so on a device that *also* lacks that module (fenix6,
    # fenix6xpro, fr245 today), "keeps its declared default forever" is
    # false for a slot specifically: the default cannot resolve there
    # either, and the slot shows its absent state instead. This is a
    # genuinely different device population than "lacks the editor" (a
    # fēnix 7-family device has the module but not the editor, and the
    # claim below is correct there), so it is checked directly rather than
    # assumed -- see check_api_gated's own case 4, which fires
    # independently of this warning for exactly this reason.
    has_complications = True
    if slot_tokens:
        has_complications = device.has_module("Complications")
    kept_names_list = [n for n in names_list if n not in slot_tokens] + (
        slot_tokens if has_complications else []
    )
    absent_slot_tokens: list[str] = [] if has_complications else slot_tokens

    # `_config_users`/`_config_colors_role_users`/`_slot_users` return raw IR
    # Elements, from `Face.walk()`, not the `resolved.items` layout wrappers
    # `_emit` expects -- so this routes through `_emit_for_element` instead,
    # which takes that same list of candidate elements directly and suppresses
    # if any of them accepts the code.
    users: list[Element] = []
    for name in config:
        users.extend(_config_users(resolved.face, name))
    for role in [t.split(".", 2)[2] for t in role_tokens]:
        users.extend(_config_colors_role_users(resolved.face, role))
    for name in face.config_data:
        users.extend(_slot_users(resolved.face, name))
    notes = []
    if kept_names_list:
        if slot_tokens and has_complications:
            notes.append(
                "the face still works: every element bound to a config.* colour, or "
                "drawing a config.data.* slot, simply keeps its declared default "
                "forever on this device"
            )
        else:
            notes.append(
                "the face still works: every element bound to a config.* colour "
                "simply keeps its declared default forever on this device"
            )
    if absent_slot_tokens:
        notes.append(
            "a config.data.* slot's own declared default is itself read through "
            "Toybox.Complications, which this device also lacks -- so "
            + ", ".join(absent_slot_tokens) + " show their absent state here instead of "
            "any declared default (see the 'api-gated' warning for the same fact)"
        )
    notes.append(
        "this follows from ADR 0006 2's chosen scope -- the native editor is "
        "fēnix 8 and newer only -- not from a missing feature in this compiler"
    )
    if len(non_default_entries) >= 1:
        notes.append(
            "with no editor to switch styles, every 'config: style:' entry but "
            f"the default ({face.config_style.default!r}) is unreachable here: "
            + ", ".join(non_default_entries)
        )
    if users:
        suppress_note = (
            "set 'lint: {allow: [config-unsupported], reason: ...}' on the "
            f"element whose 'color:'/'track_color:' or 'slot:' is one of {names} "
            "to accept it"
        )
    elif names:
        suppress_note = (
            f"no element's 'color:'/'track_color:'/'slot:' is exactly one of "
            f"{names}, so there is nowhere to put "
            "'lint: {allow: [config-unsupported]}' for it"
        )
    else:
        # `names` is empty exactly when every `config: style:` entry is
        # layout-only (no `colors:` anywhere) and there is no other config
        # axis or slot either -- `non_default_entries` alone is why this
        # fired at all, so there is no element-level `color:`/`track_color:`/
        # `slot:` to point the suppress note at in the first place.
        suppress_note = (
            "nothing here binds a 'color:'/'track_color:'/'slot:' at all -- "
            "this is purely about the unreachable style entries named above"
        )
    if kept_names_list and absent_slot_tokens:
        message = (
            f"{device.id}: has no on-device watch face editor, so "
            f"{', '.join(kept_names_list)} keep their declared defaults here; it also "
            f"lacks Toybox.Complications, so {', '.join(absent_slot_tokens)} show as "
            f"absent here instead"
        )
    elif kept_names_list:
        message = (f"{device.id}: has no on-device watch face editor, so "
                   f"{', '.join(kept_names_list)} keep their declared defaults here")
    elif absent_slot_tokens:
        message = (
            f"{device.id}: has no on-device watch face editor, and also lacks "
            f"Toybox.Complications, so {', '.join(absent_slot_tokens)} show as absent "
            f"here rather than their declared defaults"
        )
    else:
        message = (f"{device.id}: has no on-device watch face editor, so "
                   f"every 'config: style:' entry but the default is stuck there")
    _emit_for_element(bag, users, Diagnostic(
        Severity.WARNING,
        "config-unsupported",
        message,
        notes=notes + [suppress_note],
        confidence="exact -- the device's own api.debug.xml",
    ))


# -- check 4: geometry ------------------------------------------------------


def check_geometry(resolved: ResolvedFace, bag: Bag) -> None:
    """Off the framebuffer and outside the visible disc are both warnings.

    SDK 9.2.0's `Toybox.Graphics.Dc` documents no exception for out-of-range
    draw coordinates on any draw call (only `drawBitmap2` throws, and that is
    for a *source* rect inside the bitmap, not a destination point) -- `Dc`
    clips the same way `setClip` does: "Pixels outside of the region will not
    be affected by any operations." An off-screen element is therefore a
    cropped design, not a broken one -- the same class of thing as
    `safe-area`, so `off-screen` is in `SUPPRESSIBLE` too.

    **Suppressing `off-screen` also skips `safe-area` for that element.** The
    `continue` below runs whether or not `_emit` actually added a diagnostic
    (suppressed or not) -- a box outside the rectangular framebuffer is
    necessarily also outside the visible disc it contains, so `safe-area`
    would only repeat the same finding under a different name. An author who
    has already acknowledged the crop has nothing further to acknowledge.
    """
    device = resolved.device
    unchecked_shape = False
    for placed in resolved.items:
        if placed.kind == "group":
            continue
        box = placed.box
        if not inside_screen(box, device):
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "off-screen",
                f"{placed.id}: {box.width}x{box.height} at ({box.x}, {box.y}) falls outside "
                f"the {device.width}x{device.height} framebuffer",
                placed.element.span,
                notes=["the device clips silently (Dc, like setClip: pixels outside the "
                       "region are simply not drawn), so this is a cropped design, not a "
                       "broken one -- acknowledge it with 'lint: {allow: [off-screen], "
                       "reason: ...}' if it is deliberate"],
                confidence="exact -- resolved geometry",
            ))
            continue
        if is_full_bleed(box, device):
            continue  # a background is meant to run under the bezel
        visible = inside_visible_area_for(placed, device)
        if visible is None:
            unchecked_shape = True
        elif not visible:
            notes = ["the framebuffer is rectangular but the panel is not; the outer "
                     "edge is cropped by the bezel"]
            if device.shape == "round":
                # A shape-aware reach (`visible_reach`) is what actually
                # decided this for a round screen whenever one applies (an
                # arc/circle/hands/radial-pattern disc, or a curved text
                # element's own real ink) -- name the two numbers the
                # comparison came down to, rather than leaving the author to
                # re-derive them from `box` alone, which for any of those
                # kinds is no longer the shape this check tested against.
                screen_cx, screen_cy = device.width / 2, device.height / 2
                reach = visible_reach(placed, screen_cx, screen_cy)
                limit = device.minor_radius * (1.0 - BEZEL_MARGIN)
                if reach is not None:
                    notes.append(
                        f"this element's own ink reaches {reach:.1f}px from {device.id}'s "
                        f"screen centre; the visible disc's own limit is {limit:.1f}px")
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "safe-area",
                f"{placed.id} reaches outside the visible area of {device.id}'s "
                f"{device.shape} screen",
                placed.element.span,
                notes=notes,
                confidence="exact for round and rectangle screens",
            ))
    if unchecked_shape:
        bag.note(
            "safe-area",
            f"{device.id}: no visible-area geometry is defined for a "
            f"{device.shape!r} screen, so element placement is not checked",
            confidence="not checked -- see ADR 0004",
        )


# -- check 4b: sub-pixel relative lengths ------------------------------------


def check_sub_pixel_length(resolved: ResolvedFace, bag: Bag) -> None:
    """`min_1px:` is opt-in, so a nonzero `%`/`%r` length that
    resolves under 1px with the switch off is legal -- the resolver clamps
    nothing and rounds it away exactly as it always has. This is the case
    the switch exists for, though: the same hairline draws on a device with
    a larger screen and silently vanishes on this one, which an author
    almost never means on purpose. `Resolver` has already done the one thing
    this check cannot -- notice the condition while it still has the
    authored `Length` and the unclamped value in hand -- and left one
    `wfb.layout.SubPixelLength` per occurrence in `resolved.sub_pixel`
    (`wfb.layout.Resolver._extent`/`._hand_extent`); this only turns each
    one into a diagnostic.

    **One diagnostic per record, not one per device-wide representative.**
    `check_antialias_palette` collapses every anti-aliased primitive into a
    single device-wide note, because "is anti-aliasing on anywhere" is the
    only fact that check can responsibly state -- exactly how visible any
    one soft edge is depends on geometry it deliberately does not model, so
    a second offender adds no new information. This check is the opposite
    case: every `SubPixelLength` names a *different* authored line (a
    different `key`, a different `length`, sometimes a different element or
    part entirely), and each one has its own fix -- turning `min_1px:` on
    at a different level, or accepting that one specific line. Collapsing
    them into "device X has N sub-pixel lengths, see the first" would hide
    every fix but one; so, unlike `antialias-dither`, this fires once per
    record.

    **A part is suppressed through its owning element, not itself.** A hand
    or pattern part has no `lint:` key of its own -- only an element does --
    so `SubPixelLength.element` always names the `hands`/`pattern` element
    that owns the offending part (never the part, which is not an
    `Element` at all), and suppression is checked against that element via
    `_emit`. One consequence worth stating plainly: `lint: {allow:
    [sub-pixel-length], reason: ...}` on a `hands`/`pattern` element
    silences *every* sub-pixel finding on *any* of its parts, not just the
    one an author had in mind -- there is nowhere finer to hang the
    acknowledgement. The note below says so, so an author who only meant to
    accept one part is not surprised later by a second, silently-suppressed
    one.

    **Severity: WARNING, matching `antialias-dither`** for the same reason:
    this is a legal, occasionally deliberate thing to write (a hairline that
    is only ever meant to show on the larger targets in `targets:`), so it
    is suppressible rather than an error -- but silent disappearance on a
    real device is exactly the kind of thing an author needs to hear about
    by default.

    **Confidence: exact.** Unlike the memory and partial-update-budget
    checks, this rests on nothing estimated: `resolved.sub_pixel` already
    *is* this device's real resolved geometry, computed the same way the
    device's own draw call would be were the switch on.
    """
    if not resolved.sub_pixel:
        return
    # One `Placed` per element (`Resolver._resolve_list` appends exactly one
    # per element, including a `hands`/`pattern` element itself -- never per
    # part), so a plain id lookup is enough to hand `_emit` something with a
    # `.element` to check `lint: {allow: [...]}` against.
    placed_by_id = {placed.id: placed for placed in resolved.items}
    for sp in resolved.sub_pixel:
        placed = placed_by_id[sp.element.id]
        is_part = sp.owner != sp.element.id
        # The element is the last level worth naming when the finding is the
        # element's own; a part's finding has one more level below it, and
        # naming both is the whole point there ("on the element, or on just
        # the one part").  Naming the element twice when there is no part
        # would read as two different places to put the key.
        levels = (
            f"the face, a containing group, '{sp.element.id}' itself, or just this part"
            if is_part else
            f"the face, a containing group, or '{sp.element.id}' itself"
        )
        notes = [
            f"turn on 'min_1px: true' at whichever level actually needs it -- "
            f"{levels} -- to floor it at 1px on every device",
            f"or accept it deliberately with 'lint: {{allow: [sub-pixel-length], "
            f"reason: ...}}' on '{sp.element.id}'",
        ]
        if is_part:
            notes.append(
                "a hand or pattern part has no 'lint:' key of its own, so that "
                f"acknowledgement suppresses every sub-pixel-length finding on "
                f"any part of '{sp.element.id}', not just this one"
            )
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "sub-pixel-length",
            f"{sp.owner}: {sp.key} = {sp.length} resolves to {sp.value:.2f}px "
            f"on {resolved.device.id} -- a nonzero relative length this thin "
            f"rounds away to nothing and vanishes here, though it may draw "
            f"fine on a target with a bigger screen",
            sp.span,
            notes=notes,
            confidence="exact -- resolved device geometry",
        ))


# -- check 5: text overflow -------------------------------------------------


def check_text_fit(resolved: ResolvedFace, bag: Bag) -> None:
    """Does the widest plausible rendering still fit on this screen?"""
    device = resolved.device
    for placed in resolved.items:
        if not isinstance(placed, PlacedText):
            continue
        if placed.font_px == 0:
            continue
        if placed.curve_style is not None:
            # `placed.box` is already the *rotated*/radial bounding box
            # (plan 11 §4, `Resolver._resolve_text`), and `check_geometry`'s
            # off-screen/safe-area checks already run against it -- exactly
            # the thing worth catching here. This check's own message
            # ("does not fit its position", `x=..box.right..`) is plain
            # horizontal framing that reads as nonsense once the box is
            # rotated or a full circle, so a curved element skips it rather
            # than repeat the same finding under a message that does not
            # describe what actually happened.
            continue
        confidence = (
            "approximate -- the device's own typeface is not available, so the extent "
            "is measured from a stand-in scaled to the published pixel height"
            if placed.width_is_estimated
            else "exact -- measured from the baked font's own glyph advances"
        )
        fits = inside_visible_area_for(placed, device)
        if placed.box.width > device.width or fits is False:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "text-overflow",
                f"{placed.id}: the widest rendering {placed.widest!r} is "
                f"{placed.measured_width}px and does not fit its position on {device.id}",
                placed.element.span,
                notes=[f"screen is {device.width}px wide; the text box spans "
                       f"x={placed.box.x}..{placed.box.right}"],
                confidence=confidence,
            ))


# -- check 6: missing glyphs ------------------------------------------------


def check_glyphs(resolved: ResolvedFace, bag: Bag) -> None:
    """A subsetted font must contain every character the design can render."""
    for placed in resolved.items:
        if isinstance(placed, PlacedPattern):
            # A `shape: text` template part: every *drawn* copy's string is
            # already known
            # (`HandPart.texts`/`ResolvedHandPart.texts`), so this checks
            # them directly rather than a "widest" estimate -- there is
            # nothing to estimate, the whole set is exact.  Every drawn
            # copy's missing characters are collected into **one** error per
            # part ("one error, not N", docs/lore/codegen.md), not one per
            # copy that happens to repeat the same missing glyph.
            for index, part in enumerate(placed.parts):
                if part.shape != "text" or not part.font_is_custom:
                    continue
                font = resolved.fonts.get(part.font_reference)
                if font is None:
                    continue
                missing: set[str] = set()
                for copy_index in placed.copies:
                    missing |= font.missing(part.texts[copy_index])
                if not missing:
                    continue
                characters = ", ".join(repr(c) for c in sorted(missing))
                bag.error(
                    "missing-glyph",
                    f"{placed.id}.parts[{index}]: font "
                    f"{part.font_reference!r} has no glyph for {characters}",
                    placed.element.parts[index].span,
                    notes=["widen the font's 'glyphs:' set, or remove it to let "
                           "the compiler derive the set from the design"],
                    confidence="exact -- the baked font's own character map",
                )
            continue
        if not isinstance(placed, PlacedText) or not placed.font_is_custom:
            continue
        font: BakedFont | None = resolved.fonts.get(placed.font_reference)
        if font is None:
            continue
        missing = font.missing(placed.widest)
        if missing:
            characters = ", ".join(repr(c) for c in sorted(missing))
            bag.error(
                "missing-glyph",
                f"{placed.id}: font {placed.font_reference!r} has no glyph for {characters}",
                placed.element.span,
                notes=[f"the widest rendering of this element is {placed.widest!r}",
                       "widen the font's 'glyphs:' set, or remove it to let the compiler "
                       "derive the set from the design"],
                confidence="exact -- the baked font's own character map",
            )


# -- check 10: contrast -----------------------------------------------------


def check_contrast(resolved: ResolvedFace, bag: Bag) -> None:
    """WCAG-style ratio between each element and the backdrop behind it.

    The arithmetic is exact; the 3.0 threshold is a judgement call, which is why
    this is a warning and is suppressible.

    **An `outline:`-bearing element (plan 15) is judged on its ring colour,
    never its interior `color:`.** The interior is *supposed* to match
    whatever is underneath it -- that is the entire hollow-text idiom
    `outline:` exists for (`docs/guide/text.md`) -- so running the ordinary
    interior-vs-backdrop check on it would flag the idiom itself as a
    defect every time an author uses it correctly (this is exactly the
    false positive `text-outline-interior` above independently proves is
    *safe* when it can show the interior colour equals a fully-covering
    earlier element's own colour). For a hollow design the ring is the
    *only* ink that actually reads, so `_check_outline_contrast` below
    judges it in the ring's place, against two different neighbours,
    because a poor ring can fail either one independently:

    * **ring vs. backdrop.** If this fails, the whole character can vanish
      into the page: with a hollow interior, the ring is the only mark
      drawn at all, so "the ring blends into the backdrop" *is* "the text
      is unreadable," not a milder version of it. This is what an author
      sees: the glyph looks like it was never drawn.
    * **ring vs. interior.** If this fails (independently of the check
      above -- a design can pass one and fail the other), the ring's
      *outer* edge may read fine against the backdrop while its *inner*
      edge, against the fill, does not: the glyph reads as one soft-edged
      blob in the fill colour rather than a crisp ring-plus-fill shape.
      This is what an author sees: the outline looks like it never
      rendered, even though the text itself is perfectly legible.

    A design with no `outline:` is entirely unaffected -- the branch below
    is the only new code path, and every pre-existing call/message for a
    plain `color:` element is untouched.
    """
    backdrop = _backdrop(resolved)
    if backdrop is None:
        return
    for placed in resolved.items:
        outline = getattr(placed.element, "outline", None)
        if outline is not None:
            _check_outline_contrast(bag, placed, outline, backdrop)
            continue
        color_expression = getattr(placed.element, "color", None)
        if color_expression is None or color_expression.constant is None:
            continue
        color = Color.parse(int(color_expression.constant))
        if color.value == backdrop.value and placed.kind == "shape":
            continue
        ratio = color.contrast_ratio(backdrop)
        if ratio < 3.0:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "contrast",
                f"{placed.id}: {color} on {backdrop} has a contrast ratio of {ratio:.1f}",
                placed.element.span,
                notes=["below 3.0 this is hard to read on a transflective display in "
                       "low light"],
                confidence="exact arithmetic; the 3.0 threshold is a judgement call",
            ))


def _check_outline_contrast(bag: Bag, placed, outline, backdrop: Color) -> None:
    """The two ring-based comparisons `check_contrast` uses in place of the
    ordinary interior-vs-backdrop check, for one `outline:`-bearing element.

    Both comparisons are independent and either, both, or neither may fire --
    see `check_contrast`'s own docstring for what each failure looks like to
    an author. Silent (like the plain check) whenever a colour involved is
    not a build-time constant (`config.*`, or a data-conditional that never
    folded): there is nothing to compute a ratio from.
    """
    ring_expression = outline.color  # required in the schema -- never None itself
    ring = None
    if ring_expression.constant is not None:
        ring = Color.parse(int(ring_expression.constant))
        ratio = ring.contrast_ratio(backdrop)
        if ratio < 3.0:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "contrast",
                f"{placed.id}: outline ring {ring} on {backdrop} has a contrast "
                f"ratio of {ratio:.1f}",
                placed.element.span,
                notes=["with a hollow interior the ring is the only ink drawn -- "
                       "below 3.0 the whole character can disappear into the page"],
                confidence="exact arithmetic; the 3.0 threshold is a judgement call",
            ))
    interior_expression = getattr(placed.element, "color", None)
    if ring is None or interior_expression is None or interior_expression.constant is None:
        return
    interior = Color.parse(int(interior_expression.constant))
    inner_ratio = ring.contrast_ratio(interior)
    if inner_ratio < 3.0:
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "contrast",
            f"{placed.id}: outline ring {ring} on its own interior {interior} has a "
            f"contrast ratio of {inner_ratio:.1f}",
            placed.element.span,
            notes=["the ring's inner edge is invisible against its own fill -- the "
                   "glyph reads as one soft-edged blob in the fill colour instead of "
                   "a crisp outline"],
            confidence="exact arithmetic; the 3.0 threshold is a judgement call",
        ))


#: Shapes whose *ink* fills their bounding box closely enough to be the thing
#: behind everything else.  An `arc` or a `polygon` can easily have a
#: screen-sized bounding box while painting a sliver of it, and an outlined
#: shape of any kind paints only its edge -- neither is a backdrop.
_BACKDROP_SHAPES = ("rectangle", "rounded_rectangle", "circle", "ellipse")


def _backdrop(resolved: ResolvedFace) -> Color | None:
    """The colour behind everything: the first full-screen shape, or palette.bg."""
    for placed in resolved.items:
        element = placed.element
        if placed.kind != "shape" or getattr(element, "color", None) is None:
            continue
        if element.shape not in _BACKDROP_SHAPES or not element.filled:
            continue
        if placed.box.area >= resolved.screen.area * 0.9 and element.color.constant is not None:
            return Color.parse(int(element.color.constant))
    return resolved.face.palette.get("bg")


# -- check 9: partial-update budget (heuristic) -----------------------------


def _expensive_low_power_reader(element: Element) -> str | None:
    """The first ``weather.*``/``complication.*`` path this element binds, if any.

    Both readers are genuinely expensive to call every second: a
    ``complication.*`` path goes through ``Complications.getComplication``, and
    ``weather.*`` goes through ``Weather.getCurrentConditions``/
    ``getDailyForecast`` -- real API calls, not a local field read. Identified
    by ``catalog.Reader``, not by string-matching the path, so a future reader
    sharing the same cost (another 42-entry generated family, say) is caught by
    construction rather than by remembering to update a prefix list here.
    """
    for expression in element.expressions():
        for path in expression.sources:
            source = catalog.get(path)
            if source is None:
                continue
            reader = catalog.READERS.get(source.reader)
            if reader is not None and (
                reader.complication_type is not None
                or source.reader in ("weather_current", "weather_daily")
            ):
                return path
    return None


def check_partial_update_budget(resolved: ResolvedFace, bag: Bag) -> None:
    """Warn on relative grounds -- the numeric budget is not published.

    What *is* known: the clip is charged by region area, every pixel inside it
    counts as modified whenever any does, and exceeding the budget disables
    partial updates permanently.  So a large clip is worth flagging even without
    an exact threshold -- but the message must not pretend to one.

    Two independent triggers, checked in order, **at most one of which fires
    for a given face** -- a small clip that happens to read
    ``Weather.getCurrentConditions()`` every second is exactly the case a pure
    clip-area check misses, so it needs its own trigger rather than being
    folded into the area threshold, but the two must not both fire and
    describe the same underlying cost twice:

    1. **Clip-area, face-wide** (as before). Like :func:`check_palette`, this is
       about the whole face's clip rectangle rather than one element, so there
       is no single natural place to hang ``lint: {allow: ...}`` -- the
       candidates that *do* exist are the elements the clip was actually built
       from, so suppression is honoured there.
    2. **Known-expensive reads, per element.** A ``weather.*``/``complication.*``
       binding, or a ``graph`` element, drawn in ``low_power`` is expensive
       regardless of how tight its own clip is -- reported against that
       specific element, so ``lint: {allow: [partial-update-budget]}`` on it
       silences just that one.

    ``resolved.clip_for("low_power")`` unions low-power elements across
    *every* layout, deliberately -- conservative rather than wrong, since a
    per-layout clip is not something this stage can compute (see that
    method's own docstring, ``wfb/layout.py``).  A design with two layouts,
    each with its own small low-power reading, is measured here as if both
    were on screen together.
    """
    clip = resolved.clip_for("low_power")
    if clip is None:
        return
    device = resolved.device
    if not device.supports_partial_update:
        bag.error(
            "partial-update",
            f"{device.id} is an {device.display_type.upper()} device and does not support "
            f"onPartialUpdate, but this design has low-power elements",
            notes=["MIP and AMOLED are structurally different low-power paths, not a "
                   "styling difference; on an AMOLED target the sleep frame is 'aod:', "
                   "not 'modes: [low_power]'"],
            confidence="exact -- device displayType",
        )
        return
    low_power = resolved.drawn_in_mode("low_power")
    fraction = clip.area / (device.width * device.height)
    operations = len(low_power)
    if fraction > 0.25:
        _emit_for_element(bag, [p.element for p in low_power], Diagnostic(
            Severity.WARNING,
            "partial-update-budget",
            f"low-power updates clip {fraction * 100:.0f}% of the screen "
            f"({clip.width}x{clip.height}px) and draw {operations} element(s) each second",
            notes=["setClip is charged by region area, so a wide clip is expensive even "
                   "when little inside it changes",
                   "exceeding the budget calls onPowerBudgetExceeded and disables partial "
                   "updates PERMANENTLY for the rest of the app's lifecycle -- not just "
                   "for the frame that overran",
                   "since the per-source refresh-cadence check was removed, this warning is now the "
                   "ONLY thing standing between an author and reading "
                   "Weather.getCurrentConditions() or a Complications lookup inside "
                   "onPartialUpdate -- a 'weather.*' or 'complication.*' binding, or a "
                   "'graph' element (its own series is recomputed on-device every "
                   "minute, not read fresh, but the drawing itself still runs every "
                   "partial update), on a low_power element is the expensive case to "
                   "look at first",
                   "position the low-power elements physically close together to tighten "
                   "the clip -- wrapping them in a 'group' does not: a group paints "
                   "nothing and, with no explicit 'size:', resolves to its entire parent "
                   "box, so grouping can make the clip bigger, never smaller",
                   "set 'lint: {allow: [partial-update-budget], reason: ...}' on any "
                   "one of the elements drawn in low-power mode to keep it"],
            confidence="HEURISTIC -- Garmin does not publish the numeric budget; this "
                       "flags relative cost, not a measured overrun",
        ))
        return

    # Trigger 2: a read that is known-expensive regardless of clip size.  Not
    # "you have overrun" -- there is no measurement here either -- just "this
    # specific read is the expensive kind", independent of the clip-fraction
    # heuristic above.
    for placed in low_power:
        if placed.kind == "graph":
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "partial-update-budget",
                f"{placed.id}: a 'graph' element draws in low-power mode -- its drawing "
                f"runs every onPartialUpdate, once a second, even though the series "
                f"itself only rebuilds on-device once a minute",
                placed.element.span,
                notes=["exceeding the power budget calls onPowerBudgetExceeded and "
                       "disables partial updates PERMANENTLY for the rest of the app's "
                       "lifecycle -- not just for the frame that overran",
                       "move this element out of 'modes: [low_power]', or accept the "
                       "cost with 'lint: {allow: [partial-update-budget], reason: ...}'"],
                confidence="HEURISTIC -- Garmin does not publish the numeric budget; this "
                           "flags a known-expensive draw, not a measured overrun",
            ))
            continue
        path = _expensive_low_power_reader(placed.element)
        if path is None:
            continue
        source = catalog.get(path)
        call = ("Weather.getCurrentConditions()/getDailyForecast()"
                if source.reader.startswith("weather") else
                "Complications.getComplication()")
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "partial-update-budget",
            f"{placed.id}: binds {path!r} in low-power mode, which reads {call} on "
            f"every onPartialUpdate, once a second",
            placed.element.span,
            notes=["since the per-source refresh-tier cache was removed, this is a "
                   "real API call every time, not a cached field read",
                   "exceeding the power budget calls onPowerBudgetExceeded and "
                   "disables partial updates PERMANENTLY for the rest of the app's "
                   "lifecycle -- not just for the frame that overran",
                   "bind a cheaper source here, move this element out of "
                   "'modes: [low_power]', or accept the cost with "
                   "'lint: {allow: [partial-update-budget], reason: ...}'"],
            confidence="HEURISTIC -- Garmin does not publish the numeric budget; this "
                       "flags a known-expensive read, not a measured overrun",
        ))


def _always_false(expression) -> bool:
    """Is this a constant-folded `visible:` expression that is always false?

    Shared by every "is this dead" test in :func:`check_dead_element`: an
    expression with no constant fold at all (`None`, or one whose value is
    not known at build time) is never reported, only one the compiler has
    proven folds to `False`.
    """
    return expression is not None and expression.constant is not None and not expression.constant


def check_dead_element(resolved: ResolvedFace, bag: Bag) -> None:
    """A `visible:` that folded to a constant `false` -- the element never draws.

    Only the `false` case.  A constant `true` is a perfectly reasonable thing
    to write while iterating on a design (or what a config expression folds to
    on this particular device), and warning about it would be noise on every
    build.  A constant `false` is different: the author asked for an element
    and the compiler is quietly generating one nothing will ever call.

    Reported against the **outermost** dead element only.  `wfb.ir` conjoins a
    group's condition into every descendant, so a dead group would otherwise
    produce one warning per element beneath it, all saying the same thing about
    a condition written once.  `resolved.items` is the flattened tree in
    document order with `depth` on every entry, so skipping the subtree is just
    skipping forward while `depth` stays greater.

    Suppressible: a design under construction, or one whose condition is only
    dead on *this* device, is the author's call to make.
    """
    items = resolved.items
    index = 0
    while index < len(items):
        placed = items[index]
        index += 1
        expression = placed.element.visible
        if not _always_false(expression):
            continue
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "dead-element",
            f"{placed.id}: 'visible: {expression.text}' is always false, so this "
            f"element is never drawn",
            expression.span or placed.element.span,
            notes=(["a group's 'visible:' is conjoined into every element beneath "
                     "it, so the whole subtree is dead too"]
                   if placed.kind == "group" else []) + ["delete it, or fix the condition"],
            confidence="exact -- constant-folded at build time",
        ))
        # Everything under a dead group is dead for the same one reason.
        while index < len(items) and items[index].depth > placed.depth:
            index += 1

    # A `type: pattern` part's own `visible:` -- the same constant-false
    # rule, against one part instead of the whole element.
    # Independent of the loop above: a pattern is never a group, so it is
    # exactly one entry in `resolved.items` with no descendants to skip.
    # Skipped when the *element's* own `visible:` is already dead -- that
    # warning already says everything, and a part inside it would just be
    # noise repeating the same fact.
    for placed in resolved.items:
        if not isinstance(placed.element, PatternElement):
            continue
        element_expression = placed.element.visible
        if _always_false(element_expression):
            continue
        for part_index, part in enumerate(placed.element.parts):
            expression = part.visible
            if not _always_false(expression):
                continue
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "dead-element",
                f"{placed.id}.parts[{part_index}]: 'visible: {expression.text}' is "
                f"always false, so this part is never drawn",
                expression.span or placed.element.span,
                notes=["delete the part, or fix the condition"],
                confidence="exact -- constant-folded at build time",
            ))


def check_aod_unreachable(resolved: ResolvedFace, bag: Bag) -> None:
    """An element/group whose own `aod:` (a `show` or an override block) can
    never draw because an ancestor already wrote an explicit `aod: hide`
    (plan 14 §3): that hide is sticky and unconditional, so the descendant's
    own `aod:` is dead weight the moment it is written, not just a redundant
    duplicate.

    `Builder._resolve_aod` stamps `aod_ancestor_hidden` on every element,
    hidden or not, specifically so this check does not have to re-walk the
    ancestry: an element with its own `aod_own` (a `show`/override -- never
    set for `aod: hide`, which resolves to `aod_own_hide` instead) that was
    still reached with `aod_ancestor_hidden` set is exactly the unreachable
    case.
    """
    for placed in resolved.items:
        element = placed.element
        if not element.aod_ancestor_hidden or element.aod_own is None:
            continue
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "aod-unreachable",
            f"{placed.id}: has its own 'aod:', but an ancestor group already "
            f"writes 'aod: hide', which hides the whole subtree and cannot "
            f"be undone below it",
            element.span,
            notes=["plan 14 §3: an explicit 'aod: hide' on a group is sticky "
                   "-- nothing beneath it can turn AOD back on",
                   "delete this element's own 'aod:', or drop the ancestor's "
                   "'aod: hide'"],
            confidence="exact -- resolved at build time",
        ))


def check_aod_empty(resolved: ResolvedFace, bag: Bag) -> None:
    """D2: a face whose target is AMOLED but whose resolved `aod:` set is
    empty -- the face default is `hide` (D2), so an unconverted design
    silently ships a blank always-on frame on every AMOLED target unless an
    element opts back in. Garmin treats an absent always-on view as a defect
    on such a device, not a stylistic choice (research 11 §1.3).

    Face-level, like `check_memory`: there is no single element to blame for
    "nothing at all was ever turned on", so this carries no span and is
    suppressed through the face's own `aod: {lint: {allow: [...]}}` rather
    than an element's `lint:`.
    """
    if not resolved.device.is_amoled:
        return
    if any(placed.kind != "group" and placed.element.aod is not None
           for placed in resolved.items):
        return
    face = resolved.face
    if "aod-empty" in face.aod_lint_allow and "aod-empty" in SUPPRESSIBLE:
        return
    bag.warning(
        "aod-empty",
        f"{resolved.device.id} is AMOLED, but nothing in this design draws "
        f"in always-on display",
        notes=["Garmin treats an absent always-on view as a defect on an "
               "AMOLED target, not an optional extra "
               "(docs/research/11-always-on-display.md §1.3)",
               "add 'aod: show' (or an override) to at least the time, or "
               "set the face-wide 'aod: {default: show}'",
               "suppress with the face's own "
               "'aod: {lint: {allow: [aod-empty], reason: ...}}' if this is "
               "deliberate"],
        confidence="exact -- resolved 'aod:' set, this device",
    )


# -- hold targets -----------------------------------------------------------

#: The one way a live watch face can be told about a touch.
#:
#: `WatchFaceDelegate.onTap` is deliberately absent from this table even though
#: two of the three targets have the symbol: the SDK documents it "Only
#: available in WatchFace config mode", so it fires inside the on-device editor
#: and nowhere else (`docs/research/07-carousel-interaction.md` 1a).  Checking
#: for it would report a capability the author can never reach.
_HOLD_SYMBOL = "Toybox.WatchUi.WatchFaceDelegate.onPress"


def check_hold_targets(resolved: ResolvedFace, bag: Bag) -> None:
    """Will this device actually deliver the holds an `on_hold:` asks for?

    Resolved against the device's **own** ``api.debug.xml``, which is the only
    honest way to answer it -- ADR 0008's check 2, and the first thing in this
    compiler to use `Device.has_symbol` for real.  An API-level comparison is
    not a substitute: `onPress` is documented since 4.2.0, and the sibling
    symbol `onTap` is documented since 5.1.0 yet missing on `fr955` at 5.2.0
    (CLAUDE.md constraint 6), so a level says nothing dependable here.
    """
    held = [p for p in resolved.items if p.element.on_hold is not None]
    if not held:
        return
    device = resolved.device
    try:
        available = device.has_symbol(_HOLD_SYMBOL)
    except Exception:
        bag.note(
            "hold-unsupported",
            f"{device.id}: no symbol table, so touch support is not checked",
            confidence="not checked -- the device's api.debug.xml is unavailable",
        )
        return

    if not available:
        for placed in held:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "hold-unsupported",
                f"{placed.id}: {device.id} has no WatchFaceDelegate.onPress, so this "
                f"hold target can never fire there",
                placed.element.span,
                notes=["the face still works; it is simply not interactive on this "
                       "device, and the element draws as usual",
                       "onPress is the only gesture a live watch face receives; there "
                       "is no tap to fall back to"],
                confidence="exact -- the device's own api.debug.xml",
            ))
        return

    for first, second in _overlapping(held):
        _emit(bag, second, Diagnostic(
            Severity.WARNING,
            "hold-overlap",
            f"{second.id}'s hold region overlaps {first.id}'s on {device.id}, so a "
            f"touch in the shared area always opens {first.element.on_hold!r}",
            second.element.span,
            notes=["regions are tested in draw order and the first match wins, so the "
                   "second target is unreachable where they overlap",
                   "a hold region is the element's own drawn box; move them apart, or "
                   "drop one of the two 'on_hold:' declarations"],
            confidence="exact -- resolved geometry",
        ))


def _overlapping(held: list) -> list[tuple]:
    """Pairs whose hit rectangles intersect, earlier element first.

    A pair `ir.never_together` rules out is skipped: two hold targets in
    different layouts are never on screen at the same time, so a wearer's
    touch can never land on both at once regardless of where their boxes
    fall.
    """
    out = []
    for index, later in enumerate(held):
        for earlier in held[:index]:
            if never_together(earlier.element, later.element):
                continue
            if _intersects(earlier.box, later.box):
                out.append((earlier, later))
    return out


# -- api gating ---------------------------------------------------------------


def check_api_gated(resolved: ResolvedFace, bag: Bag) -> None:
    """Does *this* device actually have what this design's bindings need?

    Covers *every* catalogue read a design binds, not only
    `complication.*`: `wfb.availability` resolves any source path
    against the device's own `api.debug.xml` (module/field) the same way
    this file's `check_hold_targets` resolves `onPress`
    (`Device.has_symbol`). See `wfb/availability.py`'s module docstring and
    `docs/research/probes/api-gating/README.md`:
    a target device that lacks a module or a field the design reads gets a
    runtime `has`-guard in the one shared generated view
    (`wfb.availability.compute_guards`, `wfb/emit/monkeyc.py`), and the
    binding simply *reads as absent* there -- the same `when_absent`
    contract every nullable source already has (CLAUDE.md constraint 8) --
    rather than failing the build. This check is the human-facing half of
    that policy: it tells the author *which* binding degrades on *which*
    device and why, at build time, not on the wrist.

    Five cases below, one code (`api-gated`, WARNING, suppressible) except
    the last, which is a different code on purpose:

    1. **A catalogue read** -- any `value:`/`color:`/etc. source path an
       element binds that `wfb.availability.source_unavailable` says the
       device's own module or field table lacks. Covers every
       `complication.*` read via its reader's `Toybox.Complications` gate
       for free (`catalog.Reader.requires_module`), and every plain field
       read (`activity.stress_score` on fenix6, `ambient.pressure` on
       fr245, ...) the same way.
    2. **A complication *type* newer than the device's own ConnectIQ
       ceiling** (`ComplicationType.since` vs `Device.api_level`):
       `COMPLICATION_TYPE_*` values are constants, not `<functionEntry>`
       symbols, so they never appear in a device's `api.debug.xml` at all --
       a level compare against `since` is the only thing that *can* catch
       this one. Run only when the device actually *has*
       `Toybox.Complications`: a device
       missing the whole module is already case 1's (for a read) or case
       3/4's (for a hold/slot) more fundamental cause, and reporting both
       would say the same thing about the same binding twice -- "cut the
       whole path, not one branch," read the other way round: report the
       one path that is actually cut.
    3. **`on_hold:` on a device with no `Toybox.Complications`** -- the hold
       compiles to `Complications.exitTo`, which does nothing there
       (guarded by the same `Toybox has :Complications` the generated
       delegate already carries). Skipped when `check_hold_targets` already
       fires `hold-unsupported` for this element -- the device also lacks
       `onPress`, so the hold cannot even be triggered there, and that
       warning already says so. Every installed device missing
       `Complications` (fenix6, fenix6xpro, fr245) also lacks `onPress`
       today, but this does not assume that stays true of every future
       device -- it checks `onPress` directly.
    4. **A `complication_slot` (`config: data:`) on a device with no
       `Toybox.Complications`** -- the slot cannot resolve *any* type there,
       `default:` included (`WfbComplications.valueOf`'s `Complications.Id`
       construction is itself guarded), so it shows its absent state
       forever, never the declared default. **Not** deduped against
       `check_config_support`'s `config-unsupported` -- the two are
       different facts, not the same one said twice: `config-unsupported`
       (fired when the device merely lacks the *editor*) says the slot
       "keeps its declared default forever", which is true only when the
       device can still resolve that default through `Toybox.Complications`.
       On a device missing *both* (fenix6, fenix6xpro, fr245 today), that
       claim is false -- the default itself reads as null under the guard --
       so both warnings fire, each correct about a different half of the
       truth, and `check_config_support`'s own message is adjusted to say so
       (see that function). Contrast case 3: a hold is deduped against
       `hold-unsupported` because "it never fires" stays true regardless of
       whether `Complications` also works -- there is no second fact being
       hidden there.
    5. **A missing *function* symbol** (`Unavailable.kind == "function"`,
       from a reader's own `catalog.Reader.requires` or a
       `catalog.Source.requires` entry). `wfb.availability.compute_guards`
       and `wfb/emit/monkeyc.py` only ever guard a *module* or a *field* at
       runtime (`Toybox has :Module`, `x has :field`) -- there is no guard
       for an individual function, so the generated call would run
       unguarded and crash on a device that lacks it. "Reads as absent"
       would be a lie here, so this is a build **ERROR**, under the
       distinct code `api-gated-unguardable`, deliberately left out of
       `SUPPRESSIBLE` for the same reason the hard-platform-limit checks
       are (this module's own docstring): suppressing it would ship a face
       that crashes on the wrist. No installed device triggers this today
       -- every `Reader.requires` function is confirmed present on every
       currently-installed device (`catalog.Reader.requires`'s own
       docstring), and the catalogue has no `Source.requires` entry at all
       (see `catalog.Source.requires`'s docstring) -- so it is only
       reachable with a stubbed device, exercised in
       `tests/test_lint.py::test_api_gated_unguardable_function_is_an_error`.
    """
    device = resolved.device
    try:
        has_complications = device.has_module("Complications")
        has_onpress = device.has_symbol(_HOLD_SYMBOL)
    except Exception:
        bag.note(
            "api-gated",
            f"{device.id}: no symbol table, so API-level gating is not checked",
            confidence="not checked -- the device's api.debug.xml is unavailable",
        )
        return

    candidates: list[tuple] = []  # (placed, complication_name, span, kind) -- case 2 only
    for placed in resolved.items:
        element = placed.element
        for expression in element.expressions():
            for path in expression.sources:
                gap = availability.source_unavailable(path, device)
                span = expression.span or element.span
                if gap is not None:
                    _emit_source_gap(bag, placed, path, span, gap, device)
                if (has_complications and path.startswith("complication.")
                        and complications.get(path[len("complication."):]) is not None):
                    candidates.append((placed, path[len("complication."):], span, "read"))

        if element.on_hold is not None and complications.get(element.on_hold) is not None:
            if has_complications:
                candidates.append((placed, element.on_hold, element.span, "hold"))
            elif not has_onpress:
                pass  # hold-unsupported (check_hold_targets) already says so
            else:
                _emit(bag, placed, Diagnostic(
                    Severity.WARNING,
                    "api-gated",
                    f"{placed.id}: on_hold: {element.on_hold!r} needs Toybox.Complications, "
                    f"which {device.id} lacks, so it never fires there",
                    element.span,
                    notes=[
                        "the generated delegate guards this call with 'Toybox has "
                        ":Complications' (wfb.availability.compute_guards) -- the hold "
                        "compiles in but is a silent no-op here, not a crash",
                        "the face still works; the element itself still draws as usual",
                    ],
                    confidence=f"exact -- {device.id}'s own api.debug.xml",
                ))

        if isinstance(element, ComplicationSlot):
            # `default:` is checked unconditionally -- it is compiled in and
            # is the only type a device with no native editor (fr955) ever
            # shows, no matter what `choices:` says -- and every explicit
            # `choices:` entry too, since the wearer can pick any of them on a
            # device with the editor.  `choices: any` skips only the list
            # half, the same `check_config_palette` precedent: there is no
            # list to check when the wearer gets the editor's own
            # unrestricted picker instead.
            slot = resolved.face.config_data.get(element.slot)
            if slot is not None:
                if has_complications:
                    choices = (slot.default,) if slot.allow_any else slot.choices
                    for name in choices:
                        if complications.get(name) is not None:
                            candidates.append((placed, name, element.span, "slot"))
                else:
                    # Not deduped against `config-unsupported` (see this
                    # function's own docstring, case 4): that warning, when
                    # it also fires because this device lacks the editor
                    # too, says the slot "keeps its declared default" --
                    # true only if the default can still be resolved through
                    # `Toybox.Complications`. It cannot here, so this is a
                    # genuinely separate fact and fires independently of
                    # whether the editor is present or absent.
                    _emit(bag, placed, Diagnostic(
                        Severity.WARNING,
                        "api-gated",
                        f"{placed.id}: slot config.data.{element.slot} needs "
                        f"Toybox.Complications, which {device.id} lacks, so it shows its "
                        f"absent state here -- never the declared default",
                        element.span,
                        notes=[
                            "the generated code guards every reference to Complications "
                            "for this slot (wfb.availability.compute_guards) -- this is "
                            "silent, not a crash",
                            "the slot's own 'default:' is itself read through "
                            "WfbComplications.valueOf, so it is just as unreachable here "
                            "as any other choice -- there is no fallback to a compiled-in "
                            "value on a device with no Complications module at all",
                        ],
                        confidence=f"exact -- {device.id}'s own api.debug.xml",
                    ))

    _check_complication_since(bag, resolved, candidates)


def _emit_source_gap(bag: Bag, placed, path: str, span, gap: "availability.Unavailable",
                      device: Device) -> None:
    """Case 1 (module/field, WARNING) and case 5 (function, ERROR) of
    :func:`check_api_gated` -- factored out because both the plain
    catalogue-read loop and (indirectly, via `source_unavailable`) every
    kind of gap funnel through here."""
    if gap.kind == "function":
        _emit(bag, placed, Diagnostic(
            Severity.ERROR,
            "api-gated-unguardable",
            f"{placed.id}: {path!r} needs {gap.symbol}, which {device.id} lacks -- the "
            f"generator cannot gate this call yet",
            span,
            notes=[
                "wfb.availability.compute_guards only ever emits a runtime guard for a "
                "missing module ('Toybox has :Module') or field ('x has :field') -- there "
                "is no guard for an individual missing function, so this call would run "
                "unguarded and crash on this device",
                "drop this target, drop the binding, or add a guard for "
                f"{gap.symbol!r} to wfb/emit/monkeyc.py before shipping this",
            ],
            confidence="exact -- the device's own api.debug.xml",
        ))
        return
    need = f"module Toybox.{gap.symbol}" if gap.kind == "module" else f"field {gap.symbol!r}"
    confidence = f"exact -- {device.id}'s own api.debug.xml"
    if gap.kind == "field":
        confidence += " (a bare field name's absence from its symbol table is exact)"
    _emit(bag, placed, Diagnostic(
        Severity.WARNING,
        "api-gated",
        f"{placed.id}: {path!r} needs {need}, which {device.id} lacks, so it reads as "
        f"absent there ('when_absent' applies)",
        span,
        notes=[
            f"confirmed against {device.id}'s own api.debug.xml -- " + (
                "not one of its <dataEntry type=\"module\"> rows"
                if gap.kind == "module" else
                f"{gap.symbol!r} is not one of its <symbolTable> field entries"
            ),
            "the generated view guards this at runtime (wfb.availability.compute_guards) "
            "-- the build still succeeds; only this binding degrades on this device",
        ],
        confidence=confidence,
    ))


def _check_complication_since(bag: Bag, resolved: ResolvedFace, candidates: list[tuple]) -> None:
    """Case 2 of :func:`check_api_gated`: a complication *type* introduced
    after the device's own ConnectIQ ceiling, on a device that otherwise has
    `Toybox.Complications` -- see that function's docstring for why a level
    compare is the only thing that can catch this one, and why `candidates`
    only ever holds entries from a device that has the module at all.
    """
    if not candidates:
        return

    device = resolved.device
    device_level = device.api_level
    if device_level == "0.0.0":
        # `Device.api_level` never raises -- it falls back to this sentinel
        # when `compiler.json` has no `partNumbers`/`connectIQVersion` at all,
        # which no device this project vendors actually does. Treated as
        # "unavailable" rather than "the device supports nothing" so this
        # degrades honestly instead of firing a warning against every
        # gated type it happens to see.
        bag.note(
            "api-gated",
            f"{device.id}: no ConnectIQ version found in compiler.json, so "
            f"complication-type availability is not checked",
            confidence="not checked -- the device's compiler.json has no usable "
                       "partNumbers/connectIQVersion",
        )
        return

    for placed, name, span, kind in candidates:
        ctype = complications.TYPES[name]
        if version_key(ctype.since) <= version_key(device_level):
            continue
        confidence = (
            f"exact -- {name!r}'s since ({ctype.since}, Toybox/Complications.html) "
            f"vs {device.id}'s api_level ({device_level}, compiler.json)"
        )
        # The three cases differ only in message and notes -- the device,
        # complication type, and confidence text are the same regardless of
        # what kind of binding named it, so only those two vary below.
        if kind == "hold":
            message = (
                f"{placed.id}: holding to launch {name!r} needs ConnectIQ {ctype.since}, "
                f"but {device.id} tops out at {device_level}"
            )
            notes = [
                "Complications.subscribeToUpdates returning false or throwing "
                "ComplicationNotFoundException is already caught uniformly by "
                "WfbComplications.mc's subscribe() -- the hold simply becomes a "
                "no-op on this device, not a crash",
                "pick a launch target with a lower 'since' for this device, or "
                "accept that the hold does nothing here",
            ]
        elif kind == "slot":
            message = (
                f"{placed.id}: slot config.data.{placed.element.slot}'s "
                f"'complication.{name}' needs ConnectIQ {ctype.since}, but "
                f"{device.id} tops out at {device_level}"
            )
            notes = [
                "Complications.getComplication returns null for a type the device "
                "does not support -- the same 'absence is normal' contract every "
                "other nullable source already has, so this reads as absent rather "
                "than crashing",
                "the wearer simply cannot pick this type on this device (or, if it "
                "is the slot's 'default:', the slot never shows it here); drop it "
                "from 'choices:', or accept that it is unreachable on this target",
            ]
        else:
            message = (
                f"{placed.id}: 'complication.{name}' needs ConnectIQ {ctype.since}, "
                f"but {device.id} tops out at {device_level}"
            )
            notes = [
                "Complications.getComplication returns null for a type the device "
                "does not support -- the same 'absence is normal' contract every "
                "other nullable source already has, so this reads as absent rather "
                "than crashing",
                "drop this binding for this target, bind a lower-'since' source "
                "instead, or accept that it never updates here",
            ]
        _emit(bag, placed, Diagnostic(
            Severity.WARNING, "api-gated", message, span, notes=notes, confidence=confidence,
        ))


# -- the static hoist -------------------------------------------------------


def check_static_overlap(resolved: ResolvedFace, bag: Bag) -> None:
    """Where hoisting the static content to the front changed the picture.

    Static content is drawn once into an opaque, full-screen buffer, so its
    blit erases whatever was under it and it therefore has to be drawn first.
    The compiler arranges that itself (`wfb.ir.draw_sort_key`) instead of
    rejecting a design that wrote it in another order -- but arranging it
    *moves* elements past each other, and two elements that swapped places
    trade which one is on top.  Wherever their boxes overlap, that is a visible
    change from what the author wrote, and this is where they hear about it.

    Only the pairs the hoist actually swapped are reported, and only where the
    boxes intersect: a static decoration in one corner and a dynamic reading in
    another swap order every time and never once look different for it.  A
    pair in different modes, or in different layouts (`ir.never_together`),
    is never on screen together at all, so overlapping boxes there mean
    nothing -- a digital clock and analog hands sharing the centre on
    purpose is exactly this case.

    A WARNING, not an error, and suppressible: the element on top is usually
    where the author wanted it anyway -- writing the static content first says
    so explicitly, and accepting the warning is the other way to say it.  It is
    reported against the element that *ends up* on top, which is the one whose
    `lint:` block reaches it.

    It runs per device, like every other geometry check: two elements can
    overlap on the 280x280 target and not on the 260x260 one.

    **Bounding boxes, not ink.** Two boxes can intersect while nothing drawn
    inside them does, which is why the message says "may draw over" -- the same
    honesty ADR 0008 asks of every check that cannot be exact about pixels.
    """
    order = {p.id: i for i, p in enumerate(resolved.items) if p.kind != "group"}
    authored = authored_draw_order(resolved.face.elements)
    placed_by_id = {p.id: p for p in resolved.items if p.kind != "group"}
    covered: dict[str, list[str]] = {}
    for index, earlier in enumerate(authored):
        for later in authored[index + 1:]:
            if order.get(earlier.id, 0) <= order.get(later.id, 0):
                continue  # the hoist left this pair in the order it was written
            top, bottom = placed_by_id.get(earlier.id), placed_by_id.get(later.id)
            if top is None or bottom is None:
                continue
            if not set(top.element.modes) & set(bottom.element.modes):
                continue  # they are never on screen at the same time
            if never_together(top.element, bottom.element):
                continue  # different layouts -- never on screen together either
            if not _intersects(top.box, bottom.box):
                continue
            covered.setdefault(top.id, []).append(bottom.id)
    for element_id, under in covered.items():
        placed = placed_by_id[element_id]
        names = ", ".join(repr(name) for name in under)
        _emit(bag, placed, Diagnostic(
            Severity.WARNING,
            "static-overlap",
            f"{element_id!r} may draw over {names} on {resolved.device.id}: "
            f"hoisting the static content to the front of draw order swapped "
            f"them round",
            placed.element.span,
            notes=["the static buffer is opaque and full-screen, so every static "
                   "element is blitted before anything else is drawn -- there is "
                   "no order in which something can be under it",
                   "write them in the order they should paint, static content "
                   "first, to say so explicitly -- or accept it with "
                   "lint: {allow: [static-overlap], reason: \"...\"}"],
            confidence="exact -- resolved geometry, but boxes rather than ink: the "
                       "elements may not overlap where they actually draw",
        ))


def _same_provable_color(a, b) -> bool:
    """True only when both expressions are known, at build time, to always
    evaluate to the identical colour value.

    Both sides must have folded to a build-time constant (`Expression.
    constant`): a palette entry's own constant *is* its resolved colour
    (`Builder._define_palette_color`), so comparing `.constant` already
    covers "the same palette role" and "equal literals" in one test --
    there is no separate "same role" check to write, because a role is
    just a name for a constant this project already resolves before this
    check ever runs. `config.*` colours bind with `constant=None`
    (`Builder._define_config_color` -- deliberately, since a config colour
    is user-editable at runtime) and any expression that stayed
    data-conditional after folding also has `constant=None`
    (`expr.fold`'s Ref-substitution rule only fires when the referenced
    binding itself is constant) -- either side being one of those makes
    this `False`, per plan 15's own instruction: provably equal means
    provably equal at build time, not "probably matches in practice."
    """
    if a is None or b is None:
        return False
    if a.constant is None or b.constant is None:
        return False
    return a.constant == b.constant


def _fully_contains(outer: IntBox, inner: IntBox) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y
            and outer.right >= inner.right and outer.bottom >= inner.bottom)


def _is_solid_backdrop_shape(placed) -> bool:
    """True for an earlier element this check is willing to trust to paint
    *every* pixel of its own bounding box -- the same `_BACKDROP_SHAPES`
    vocabulary `check_contrast`'s own `_backdrop()` already uses, for the
    same reason: an arc, a polygon, an unfilled shape or a line of text can
    each have a bounding box far larger than what they actually ink, so
    "the box matches" proves nothing about what a pixel inside it actually
    shows once that box is only *part* of what covers the outlined
    element's own box (see `check_text_outline_interior`'s docstring).
    """
    element = placed.element
    return (placed.kind == "shape" and getattr(element, "shape", None) in _BACKDROP_SHAPES
            and getattr(element, "filled", True))


def _outlined_interiors(element) -> list[tuple]:
    """Every `(outline, interior colour)` pair this element draws with an
    `outline:` -- a `text` element has at most one (its own `.outline`/
    `.color`); a `type: pattern` element (plan 15 §14 slice 2) may have one
    per `shape: text` part that carries its own `outline:`, since the key
    lives on the part, not on `PatternElement` itself. Anything else
    (`getattr` finding neither `outline` nor `parts`) returns `[]`, which is
    what keeps `check_text_outline_interior` a no-op for every element kind
    that cannot have one at all.
    """
    outline = getattr(element, "outline", None)
    if outline is not None:
        return [(outline, getattr(element, "color", None))]
    parts = getattr(element, "parts", None) or ()
    return [(part.outline, part.color) for part in parts if part.outline is not None]


def check_text_outline_interior(resolved: ResolvedFace, bag: Bag) -> None:
    """`outline:`'s interior pass paints over whatever is beneath it -- it
    does not reveal it (research 14 §6.4, plan 15 §3/§7). Fires when an
    `outline:`-bearing element's own (ring-grown) box overlaps an
    **earlier-drawn** element's box, in the same modes and layout, *unless*
    this check can prove that particular overlap is invisible -- the
    mechanical half of that authoring trap, modelled on
    `check_static_overlap`'s own `_intersects` box test (`wfb/lint.py`
    above), generic over `Placed` (any element kind, via `_outlined_
    interiors` -- a `text` element's own `.outline`/`.color`, or, since
    plan 15 §14 slice 2, every outlined part of a `type: pattern` element,
    since the key lives per-part there rather than on the element itself).

    **When a pair is provably safe.** Repainting a pixel in the exact
    colour it already is changes nothing, so a pair is suppressed only when
    *every* one of these holds for that specific earlier element:

    1. `_same_provable_color` says the interior colour and the earlier
       element's own colour are the same build-time constant (see that
       function's own docstring for exactly what counts).
    2. The earlier element is a filled `rectangle`/`rounded_rectangle`/
       `circle`/`ellipse` (`_is_solid_backdrop_shape`) -- the same
       "reliably fills its own box" vocabulary `check_contrast` already
       trusts, and for the same reason: nothing else in this format
       promises to paint every pixel of its own bounding box.
    3. The earlier element's box **fully contains** the outlined element's
       own (ring-grown) box (`_fully_contains`) -- not merely intersects it.

    **Why full containment, not just a colour match, and why this is
    decided per earlier element rather than once for the whole pair list.**
    A colour match alone does not prove invisibility for a *partially*
    covering earlier element -- research 14's own example is exactly this:
    a decorative ring that only partly crosses the outlined text's box.
    Suppose that ring's own colour happens to equal the interior colour:
    the pixels the ring actually covers would indeed repaint invisibly, but
    the *rest* of the outlined box -- wherever the ring does not reach --
    is not shown to be anything in particular. It could be the plain
    background (fine), but it could just as easily be a third element this
    check has not looked at, or bare unpainted framebuffer, and nothing
    here would know the difference from a box comparison alone. So a
    partially-overlapping earlier element is *never* treated as safe,
    matching colour or not, and stays in the reported list -- only an
    earlier element whose own box is a superset of the outlined box can
    stand in for "everything under here is accounted for." This is also
    why the check is per *earlier element*, not "does at least one
    provably-matching element exist somewhere": two earlier elements can
    each cover only part of the box, in different, individually-matching
    colours, without their union being provably identical to a single
    interior colour at every point -- so each one is judged solely against
    whether *it alone* proves the pixels it actually covers, and every
    other earlier element covering any pixel is still worth naming to the
    author, whether or not another element in the same list already is safe.

    Unlike `check_static_overlap`, there is no hoist to detect: draw order
    (`resolved.items`, already sorted) already says which element ends up
    on top, so every earlier-drawn element intersecting an outlined one's
    box is reported (except a provably-safe one, above), not only a pair
    the static hoist swapped. A WARNING, suppressible, "exact -- resolved
    geometry, but boxes rather than ink" (the same honesty
    `check_static_overlap` states for itself): two boxes can intersect
    while the glyphs never actually touch -- and, symmetrically, this
    check's own *suppression* is "boxes, not ink" too: it trusts a filled
    backdrop shape to ink every pixel of its box, which is a geometric
    fact about the shape, not a guarantee about what glyphs draw inside it.

    Scope (D10): box-level, element-level for a pattern (not per-copy) --
    a pattern's own (ring-grown) `later.box` is judged as one box, exactly
    like `off-screen`/`safe-area` already treat a pattern, never per-copy.
    A pattern has no single element-wide `outline:`/`color:` the way a
    `text` element does (`outline:` lives per-part, plan 15 §14 slice 2),
    so `_outlined_interiors` below collects every outlined part's own
    `(outline, interior colour)` pair instead of the element's own two
    attributes -- **all** of them must independently prove safe against a
    given earlier element for that pair to be suppressed: a pattern with
    two outlined parts in two different interior colours is not safe
    merely because one of them happens to match the backdrop, since the
    other still paints an unaccounted-for patch over it.
    """
    drawn = [p for p in resolved.items if p.kind != "group"]
    for index, later in enumerate(drawn):
        outlines = _outlined_interiors(later.element)
        if not outlines:
            continue
        under: list[str] = []
        for earlier in drawn[:index]:
            if not set(later.element.modes) & set(earlier.element.modes):
                continue  # never on screen at the same time
            if never_together(later.element, earlier.element):
                continue  # different layouts -- never on screen together either
            if not _intersects(later.box, earlier.box):
                continue
            earlier_color = getattr(earlier.element, "color", None)
            if (_is_solid_backdrop_shape(earlier)
                    and _fully_contains(earlier.box, later.box)
                    and all(_same_provable_color(interior, earlier_color)
                            for _, interior in outlines)):
                continue  # provably repaints in the same colour that's already there
            under.append(earlier.id)
        if not under:
            continue
        names = ", ".join(repr(name) for name in under)
        _emit(bag, later, Diagnostic(
            Severity.WARNING,
            "text-outline-interior",
            f"{later.id!r}'s outline interior may paint over {names} on "
            f"{resolved.device.id}: the interior pass paints over what's "
            f"beneath it, it does not reveal it -- check the interior colour "
            f"matches what's actually there, or move one of them",
            later.element.span,
            notes=["'outline:' has no transparency of any kind -- "
                   "Graphics.BlendMode has no destination-out formula reachable "
                   "from drawText (docs/research/14-stamped-ring-text.md §6)",
                   "write lint: {allow: [text-outline-interior], reason: \"...\"} "
                   "once the interior colour is confirmed correct for what's "
                   "actually underneath"],
            confidence="exact -- resolved geometry, but boxes rather than ink: the "
                       "elements may not overlap where they actually draw",
        ))


def _intersects(a: IntBox, b: IntBox) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


# -- the graphics pool ------------------------------------------------------

#: Fraction of the graphics pool the static buffers may take before this warns.
#: A judgement, and labelled as one: the pool also holds every font and bitmap
#: the face loads at runtime, and a buffer taken with ``.get()`` is *locked* --
#: it cannot be purged to make room for them (Core_Topics/Graphics).  Half the
#: pool is where "there is plenty left for everything else" stops being obvious.
GRAPHICS_POOL_BUDGET = 0.5


def check_graphics_pool(resolved: ResolvedFace, bag: Bag) -> None:
    """What the static offscreen buffers cost in the graphics pool.

    An **estimate**, and it says so (ADR 0008).  Bytes per pixel for a
    ``BufferedBitmap`` is not published anywhere in the SDK; the device's own
    ``compiler.json`` gives ``bitsPerPixel`` for the *display*, and this uses it
    as the best available proxy (`Device.buffer_bytes`).  Real per-surface
    overhead is unknown and not included.

    The buffer is full-screen because Monkey C's ``Dc`` has no translate: a
    smaller one would mean threading an origin offset through every generated
    element method, and every coordinate in `Layout` is already absolute
    (ADR 0004).  So the size is not something the author can tune -- which is
    exactly why they should be told what it is.

    Reported against the first static root, so ``lint: {allow: [graphics-pool]}``
    on that element acknowledges the whole face's pool cost.
    """
    roots = [p for p in resolved.items if p.element.static]
    if not roots:
        return
    device = resolved.device
    per_buffer = device.buffer_bytes()
    pool = device.graphics_pool_bytes
    if per_buffer is None or not pool:
        return
    # One buffer per face today: an opaque full-screen blit cannot coexist with
    # a second one (`docs/research/probes/static-buffer/`), so every static
    # group paints into the same surface no matter how many there are.  The day
    # transparency is settled on real hardware this becomes a sum over roots,
    # which is why the message is phrased for a total rather than for one.
    total = per_buffer
    share = total / pool
    detail = (f"the static content buffers {total:,} B of the {pool:,} B graphics "
              f"pool ({share * 100:.1f}%) on {device.id}")
    notes = [f"{device.width}x{device.height} pixels at the display's own "
             f"{device.bits_per_pixel} bits/pixel; the buffer is full-screen "
             f"because Dc has no translate",
             "the graphics pool is separate from the "
             f"{device.watchface_memory_limit:,} B watch-face limit, so this is "
             "not charged against the face's own memory",
             "it is shared with every font and bitmap loaded at runtime, and a "
             "buffer held with .get() is locked and cannot be purged to make "
             "room for them"]
    confidence = ("estimate -- bytes per pixel for a BufferedBitmap is not published; "
                  "this uses the display's bitsPerPixel and ignores any per-surface "
                  "overhead")
    if share > GRAPHICS_POOL_BUDGET:
        _emit(bag, roots[0], Diagnostic(
            Severity.WARNING, "graphics-pool", detail, roots[0].element.span,
            notes=notes + ["drop `static:` from the largest group, or accept it "
                           "with lint: {allow: [graphics-pool], reason: \"...\"}"],
            confidence=confidence,
        ))
    else:
        _emit(bag, roots[0], Diagnostic(
            Severity.NOTE, "graphics-pool", detail, roots[0].element.span,
            notes=notes, confidence=confidence,
        ))


# -- pattern-step -------------------------------------------------------------


def check_pattern_step(resolved: ResolvedFace, bag: Bag) -> None:
    """A linear pattern's `step:` that rounds to `{0, 0}` px on this
    device -- every copy lands on top of copy 0, the same "draws nothing
    distinguishable" failure a radial `step: 0deg` is a
    build-time error for (`Builder._build_pattern_element`).  This one can
    only be caught per device: `step: {dx: 1%}` is a real, nonzero gap on a
    280x280 screen and rounds away to nothing on a screen too small (or an
    axis too short) for 1% of it to reach a whole pixel.

    An ERROR, not a suppressible lint: like the build-time radial checks
    this mirrors, a design that hits it does not work, so there is nothing
    for `lint: {allow: ...}` to accept.
    """
    for placed in resolved.items:
        if not isinstance(placed, PlacedPattern) or placed.element.pattern != "linear":
            continue
        if placed.dx != 0 or placed.dy != 0:
            continue
        step = placed.element.step
        authored = f"{{dx: {step.dx}, dy: {step.dy}}}" if step is not None else "{}"
        _emit(bag, placed, Diagnostic(
            Severity.ERROR,
            "pattern-step",
            f"{placed.id}: 'step: {authored}' rounds to {{0, 0}}px on "
            f"{resolved.device.id} -- every copy lands on copy 0",
            placed.element.span,
            notes=["a step this small only reaches a whole pixel on a larger "
                   "screen, or a larger fraction of the parent box -- use a "
                   "larger 'step:', or 'px' instead of '%'/'%r' if the gap "
                   "should not scale with the screen"],
            confidence="exact -- resolved geometry",
        ))


# -- check 7: memory (measured, post-build) ---------------------------------

_STATS_RE = re.compile(
    r"Data:\s*\n\s*Foreground:\s*(?P<data>\d+) bytes.*?"
    r"Code:\s*\n\s*Foreground:\s*(?P<code>\d+) bytes",
    re.S,
)
_PRG_RE = re.compile(r"Total PRG Size:\s*(?P<prg>\d+) bytes")


def check_memory(device: Device, build_output: str, bag: Bag) -> dict | None:
    """Compare ``monkeyc --build-stats`` against the device's watch-face limit.

    Measured, not estimated: static estimation of Monkey C bytecode size from an
    IR would be guesswork, and a wrong "fits" is worse than no answer.
    """
    stats = _STATS_RE.search(build_output)
    if not stats:
        return None
    data, code = int(stats.group("data")), int(stats.group("code"))
    total = data + code
    limit = device.watchface_memory_limit
    prg_match = _PRG_RE.search(build_output)
    result = {
        "data": data, "code": code, "total": total, "limit": limit,
        "prg": int(prg_match.group("prg")) if prg_match else None,
    }
    share = total / limit
    message = (
        f"{device.id}: {total:,} B of the {limit:,} B watch-face limit "
        f"({share * 100:.1f}%) -- {data:,} B data, {code:,} B code"
    )
    note = (
        "measured by `monkeyc --build-stats`, not estimated.  This is the static "
        "foreground figure; resources loaded at runtime (fonts, bitmaps) add to it, "
        "and that part is not measured here."
    )
    if share >= 1.0:
        bag.error("memory", message, notes=[note], confidence="measured")
    elif share >= 0.85:
        bag.warning("memory", message, notes=[note], confidence="measured")
    else:
        bag.note("memory", message, notes=[note], confidence="measured")
    return result
