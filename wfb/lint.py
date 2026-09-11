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
import math
import re

from . import catalog, complications
from .devices import Device, version_key
from .diagnostics import Bag, Diagnostic, Severity
from .fonts import BakedFont
from .ir import (
    CONFIG_SYMBOL, Carousel, ComplicationSlot, Element, Face, Text, authored_draw_order,
)
from .layout import (
    PlacedCarousel, PlacedProgress, PlacedShape, PlacedText, ResolvedFace, inside_screen,
    inside_visible_area, inside_visible_area_for, is_full_bleed,
)
from .palette import Color
from .units import IntBox

#: Checks an author may silence with ``lint: {allow: [...], reason: "..."}``.
#: The hard-platform-limit errors are deliberately absent: suppressing one
#: produces a face that does not work.
SUPPRESSIBLE = frozenset({
    "palette-dither", "safe-area", "text-overflow", "contrast", "partial-update-budget",
    "hold-unsupported", "hold-overlap", "carousel-zone", "complication-gated",
    "dead-element", "graphics-pool", "antialias-dither", "static-overlap",
    "config-unsupported",
})

#: Every diagnostic code emitted anywhere in this compiler -- not just the
#: checks in this file.  This is what lets :func:`check_lint_allow` tell a
#: misspelled code (not here at all) apart from a real one that is simply not
#: suppressible (here, but not in ``SUPPRESSIBLE``).  Derived by hand from a
#: grep of every ``bag.error/warning/note`` and ``Diagnostic(...)`` call across
#: ``wfb/`` -- ``tests/test_lint.py`` re-runs that grep and fails the build the
#: day this set drifts from what the compiler actually emits, so it cannot rot
#: silently the way the two codes in Bug 1 did.
ALL_CODES = frozenset({
    "antialias-dither",
    "carousel", "color", "color-scheme", "complication-gated", "complication-slot",
    "config", "config-unsupported",
    "contrast", "dead-element",
    "element-mapping",
    "devices", "duplicate-id", "element", "expression",
    "font", "format", "format-version", "graph", "graphics-pool", "icon", "io",
    "lint-allow", "memory",
    "metrics", "missing-glyph", "monkeyc", "off-screen", "palette",
    "carousel-zone", "carousel-on-hold", "hold-overlap", "hold-unsupported",
    "hold-auto-ambiguous", "hold-auto-unresolved",
    "palette-dither", "partial-update", "partial-update-budget", "permission",
    "on-hold", "on-tap-renamed", "raw-color", "safe-area", "schema", "source-renamed",
    "target",
    "static", "static-overlap",
    "text-antialias",
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
    check_text_fit(resolved, bag)
    check_glyphs(resolved, bag)
    check_contrast(resolved, bag)
    check_partial_update_budget(resolved, bag)
    check_hold_targets(resolved, bag)
    check_carousel_zones(resolved, bag)
    check_dead_element(resolved, bag)
    check_complication_availability(resolved, bag)
    check_graphics_pool(resolved, bag)
    check_static_overlap(resolved, bag)
    check_alpha(resolved, bag)
    for warning in resolved.warnings:
        bag.note("metrics", warning, confidence="not checked -- no metrics available")


def _suppressed(placed, code: str) -> bool:
    return code in placed.element.lint_allow and code in SUPPRESSIBLE


def _emit(bag: Bag, placed, diag: Diagnostic) -> None:
    if _suppressed(placed, diag.code):
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
    per build rather than once per device.
    """
    for element in face.walk():
        for code in sorted(element.lint_allow):
            if code in SUPPRESSIBLE:
                continue
            span = element.span
            if code in ALL_CODES:
                bag.error(
                    "lint-allow",
                    f"{element.id}: {code!r} is a real diagnostic code, but it is "
                    f"deliberately not suppressible",
                    span,
                    notes=[
                        "the hard-platform-limit checks stay unsuppressible on purpose: "
                        "silencing one would produce a face that does not work",
                        "suppressible codes: " + ", ".join(sorted(SUPPRESSIBLE)),
                    ],
                    confidence="exact -- SUPPRESSIBLE is this file's own registry",
                )
                continue
            near = difflib.get_close_matches(code, ALL_CODES, n=1, cutoff=0.6)
            notes = ["suppressible codes: " + ", ".join(sorted(SUPPRESSIBLE))]
            if near:
                notes.insert(0, f"did you mean {near[0]!r}?")
            bag.error(
                "lint-allow",
                f"{element.id}: {code!r} is not a diagnostic code this compiler emits",
                span,
                notes=notes,
                confidence="exact -- SUPPRESSIBLE is this file's own registry",
            )


# -- check 3: palette legality ---------------------------------------------


#: Element fields that can carry a bare ``palette.<name>`` reference.  Not
#: every element kind has both -- ``Text``/``Shape``/``IconElement`` have only
#: ``color``, ``Progress`` also has ``track_color`` -- ``getattr`` covers the
#: gap without needing an isinstance check per kind here.
_PALETTE_REFERENCING_FIELDS = ("color", "track_color")


def _palette_users(face: Face, name: str) -> list[Element]:
    """Elements whose ``color:``/``track_color:`` is exactly ``palette.<name>``.

    This is deliberately an exact textual match on the author's own expression
    text, not a search through folded constants -- a conditional expression
    that merely *mentions* the entry (``hr.current > 100 ? palette.fg : ...``)
    does not count, because the dithering the warning is about is a property
    of the named colour itself, not of any one place it is used, and claiming
    to trace it through arbitrary expressions would overclaim what this check
    can actually verify.
    """
    token = f"palette.{name}"
    return [
        element for element in face.walk()
        if any(
            (expression := getattr(element, field, None)) is not None
            and expression.text == token
            for field in _PALETTE_REFERENCING_FIELDS
        )
    ]


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
        if any("palette-dither" in element.lint_allow for element in users):
            continue
        nearest = color.nearest_legal(colors)
        if users:
            suppress_note = (
                f"set 'lint: {{allow: [palette-dither], reason: ...}}' on the element "
                f"whose 'color:' or 'track_color:' is 'palette.{name}' to keep it"
            )
        else:
            suppress_note = (
                f"no element's 'color:' or 'track_color:' is exactly 'palette.{name}', "
                f"so there is nowhere to put 'lint: {{allow: [palette-dither]}}' for it"
            )
        bag.warning(
            "palette-dither",
            f"palette.{name} = {color} is not one of {resolved.device.id}'s "
            f"{colors} colours and will be dithered",
            notes=[
                f"nearest legal colour: {nearest}",
                "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is "
                "dithered by the firmware and looks grainy",
                suppress_note,
            ],
            confidence="exact -- device display_colors",
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
        if isinstance(placed, (PlacedShape, PlacedProgress)) and placed.element.resolved_antialias
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
    token = f"config.{name}"
    return [
        element for element in face.walk()
        if any(
            (expression := getattr(element, field, None)) is not None
            and expression.text == token
            for field in _PALETTE_REFERENCING_FIELDS
        )
    ]


def _config_colors_role_users(face: Face, role: str) -> list[Element]:
    """Elements whose `color:`/`track_color:` is exactly `config.colors.<role>`.

    Same exact-textual-match rule as :func:`_config_users`/`_palette_users`.
    """
    token = f"config.colors.{role}"
    return [
        element for element in face.walk()
        if any(
            (expression := getattr(element, field, None)) is not None
            and expression.text == token
            for field in _PALETTE_REFERENCING_FIELDS
        )
    ]


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
        if any("palette-dither" in element.lint_allow for element in users):
            continue
        nearest = ", ".join(f"{c} -> {c.nearest_legal(colors)}" for c in bad)
        if users:
            suppress_note = (
                f"set 'lint: {{allow: [palette-dither], reason: ...}}' on the element "
                f"whose 'color:' or 'track_color:' is 'config.{name}' to keep it"
            )
        else:
            suppress_note = (
                f"no element's 'color:' or 'track_color:' is exactly 'config.{name}', "
                f"so there is nowhere to put 'lint: {{allow: [palette-dither]}}' for it"
            )
        bag.warning(
            "palette-dither",
            f"config.{name}: {len(bad)} declared colour(s) are not one of "
            f"{resolved.device.id}'s {colors} colours and will be dithered",
            notes=[
                f"off-grid -> nearest legal: {nearest}",
                "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is "
                "dithered by the firmware and looks grainy",
                suppress_note,
            ],
            confidence="exact -- device display_colors",
        )


def check_color_scheme_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Every colour a `config: colors:` axis can ever put on screen, checked
    the same way a `config:` colour axis is.

    A `color_scheme:` entry has no `choices: any` equivalent -- Styles has no
    unrestricted picker -- so every role of every scheme actually listed in
    `config.colors`' `choices:` is checked, the same "every listed choice, not
    only the default" scope :func:`check_config_palette` gives an explicit
    list.  A scheme declared but never put in `choices:` is unreachable on any
    device (`resolveColorScheme` only ever assigns for `choices:` entries), so
    it is not checked here -- there is nothing on the wrist for the warning to
    be about.
    """
    colors = resolved.device.display_colors
    if colors is None:
        return  # check_palette already emits the one "not checked" note per device
    axis = resolved.face.config_colors
    if axis is None:
        return
    roles = sorted(resolved.face.color_scheme[axis.default].colors)
    for role in roles:
        offenders = [
            (name, resolved.face.color_scheme[name].colors[role])
            for name in axis.choices
        ]
        bad = [(name, c) for name, c in offenders if not c.is_palette_legal(colors)]
        if not bad:
            continue
        users = _config_colors_role_users(resolved.face, role)
        if any("palette-dither" in element.lint_allow for element in users):
            continue
        nearest = ", ".join(
            f"color_scheme.{name}.colors.{role}={c} -> {c.nearest_legal(colors)}"
            for name, c in bad
        )
        if users:
            suppress_note = (
                f"set 'lint: {{allow: [palette-dither], reason: ...}}' on the element "
                f"whose 'color:' or 'track_color:' is 'config.colors.{role}' to keep it"
            )
        else:
            suppress_note = (
                f"no element's 'color:' or 'track_color:' is exactly "
                f"'config.colors.{role}', so there is nowhere to put "
                "'lint: {allow: [palette-dither]}' for it"
            )
        bag.warning(
            "palette-dither",
            f"config.colors.{role}: {len(bad)} declared colour(s) are not one of "
            f"{resolved.device.id}'s {colors} colours and will be dithered",
            notes=[
                f"off-grid -> nearest legal: {nearest}",
                "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is "
                "dithered by the firmware and looks grainy",
                suppress_note,
            ],
            confidence="exact -- device display_colors",
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
    if face.config_colors is not None:
        default_scheme = face.color_scheme[face.config_colors.default]
        role_tokens = [f"config.colors.{role}" for role in sorted(default_scheme.colors)]
        names_list += role_tokens
    slot_tokens = [f"config.data.{name}" for name in sorted(face.config_data)]
    names_list += slot_tokens
    names = ", ".join(names_list)
    # `_config_users`/`_config_colors_role_users`/`_slot_users` return raw IR
    # Elements, from `Face.walk()`, not the `resolved.items` layout wrappers
    # `_emit` expects -- the same reason `check_palette` (this check's own
    # model) does not call `_emit` either, and checks `lint_allow` on the
    # element directly instead.
    users: list[Element] = []
    for name in config:
        users.extend(_config_users(resolved.face, name))
    for role in [t.split(".", 2)[2] for t in role_tokens]:
        users.extend(_config_colors_role_users(resolved.face, role))
    for name in face.config_data:
        users.extend(_slot_users(resolved.face, name))
    if any("config-unsupported" in element.lint_allow for element in users):
        return
    notes = [
        "the face still works: every element bound to a config.* colour, or "
        "drawing a config.data.* slot, simply keeps its declared default "
        "forever on this device",
        "this follows from ADR 0006 2's chosen scope -- the native editor is "
        "fēnix 8 and newer only -- not from a missing feature in this compiler",
    ]
    if users:
        suppress_note = (
            "set 'lint: {allow: [config-unsupported], reason: ...}' on the "
            f"element whose 'color:'/'track_color:' or 'slot:' is one of {names} "
            "to accept it"
        )
    else:
        suppress_note = (
            f"no element's 'color:'/'track_color:'/'slot:' is exactly one of "
            f"{names}, so there is nowhere to put "
            "'lint: {allow: [config-unsupported]}' for it"
        )
    bag.warning(
        "config-unsupported",
        f"{device.id}: has no on-device watch face editor, so {names} "
        f"keep their declared defaults here",
        notes=notes + [suppress_note],
        confidence="exact -- the device's own api.debug.xml",
    )


# -- check 4: geometry ------------------------------------------------------


def check_geometry(resolved: ResolvedFace, bag: Bag) -> None:
    """Off the framebuffer is an error; outside the visible disc is a warning."""
    device = resolved.device
    unchecked_shape = False
    for placed in resolved.items:
        if placed.kind == "group":
            continue
        box = placed.box
        if not inside_screen(box, device):
            _emit(bag, placed, Diagnostic(
                Severity.ERROR,
                "off-screen",
                f"{placed.id}: {box.width}x{box.height} at ({box.x}, {box.y}) falls outside "
                f"the {device.width}x{device.height} framebuffer",
                placed.element.span,
                confidence="exact -- resolved geometry",
            ))
            continue
        if is_full_bleed(box, device):
            continue  # a background is meant to run under the bezel
        visible = inside_visible_area_for(placed, device)
        if visible is None:
            unchecked_shape = True
        elif not visible:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "safe-area",
                f"{placed.id} reaches outside the visible area of {device.id}'s "
                f"{device.shape} screen",
                placed.element.span,
                notes=["the framebuffer is rectangular but the panel is not; the outer "
                       "edge is cropped by the bezel"],
                confidence="exact for round and rectangle screens",
            ))
    if unchecked_shape:
        bag.note(
            "safe-area",
            f"{device.id}: no visible-area geometry is defined for a "
            f"{device.shape!r} screen, so element placement is not checked",
            confidence="not checked -- see ADR 0004",
        )


# -- check 5: text overflow -------------------------------------------------


def check_text_fit(resolved: ResolvedFace, bag: Bag) -> None:
    """Does the widest plausible rendering still fit on this screen?"""
    device = resolved.device
    for placed in resolved.items:
        if not isinstance(placed, PlacedText):
            continue
        if placed.font_px == 0:
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
    """
    backdrop = _backdrop(resolved)
    if backdrop is None:
        return
    for placed in resolved.items:
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


def check_partial_update_budget(resolved: ResolvedFace, bag: Bag) -> None:
    """Warn on relative grounds -- the numeric budget is not published.

    What *is* known: the clip is charged by region area, every pixel inside it
    counts as modified whenever any does, and exceeding the budget disables
    partial updates permanently.  So a large clip is worth flagging even without
    an exact threshold -- but the message must not pretend to one.

    Like :func:`check_palette`, this is about the whole face's clip rectangle
    rather than one element, so there is no single natural place to hang
    ``lint: {allow: ...}``.  The candidates that *do* exist are the elements
    the clip was actually built from -- everything drawn in ``low_power`` mode
    -- so suppression is honoured there: acknowledging the cost on any one of
    them acknowledges the shared clip they all pay into.
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
                   "styling difference; use 'always_on' for AMOLED targets"],
            confidence="exact -- device displayType",
        )
        return
    low_power = resolved.in_mode("low_power")
    fraction = clip.area / (device.width * device.height)
    operations = len([p for p in low_power if p.kind != "group"])
    if fraction > 0.25:
        if any("partial-update-budget" in p.element.lint_allow for p in low_power):
            return
        bag.warning(
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
                   "group the low-power elements closer together to tighten the clip",
                   "set 'lint: {allow: [partial-update-budget], reason: ...}' on any "
                   "one of the elements drawn in low-power mode to keep it"],
            confidence="HEURISTIC -- Garmin does not publish the numeric budget; this "
                       "flags relative cost, not a measured overrun",
        )


# -- carousel zones ---------------------------------------------------------


#: Below this many pixels wide, a hold zone is hard to hit reliably.  Garmin
#: publishes no minimum touch size, so this is a judgement rather than a
#: platform fact, and the diagnostic says so in its own confidence line.
MIN_ZONE_WIDTH = 40


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
        if expression is None or expression.constant is None or expression.constant:
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


def check_carousel_zones(resolved: ResolvedFace, bag: Bag) -> None:
    """Can the wearer actually reach all three of a carousel's zones?

    A carousel's box is its touch target, and it is checked here rather than
    by :func:`check_geometry`, which deliberately looks at the *drawn* extent
    instead (`PlacedCarousel.content_box`).  Two ways a generous-looking box
    is not generous in practice: it is narrow enough that a third of it is a
    sliver, or it is so wide that the outer thirds sit under the bezel of a
    round screen -- where a finger cannot land at all.
    """
    device = resolved.device
    for placed in resolved.items:
        if not isinstance(placed, PlacedCarousel):
            continue
        zone_width = placed.box.width / 3.0
        if zone_width < MIN_ZONE_WIDTH:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "carousel-zone",
                f"{placed.id}: each hold zone is only {zone_width:.0f}px wide on "
                f"{device.id}",
                placed.element.span,
                notes=["the box is split into thirds -- previous, open, next -- so a "
                       f"box under {MIN_ZONE_WIDTH * 3}px wide makes them hard to hit "
                       "apart",
                       "widen 'size:'; it is the touch target, and it does not have to "
                       "match what the row paints"],
                confidence="approximate -- Garmin publishes no minimum touch size, so "
                           f"{MIN_ZONE_WIDTH}px is this compiler's judgement",
            ))
            continue
        outer = _outer_zones(placed)
        unreachable = [name for name, box in outer
                       if inside_visible_area(box, device) is False]
        if unreachable:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "carousel-zone",
                f"{placed.id}: the {' and '.join(unreachable)} "
                f"zone{'s' if len(unreachable) > 1 else ''} "
                f"{'reach' if len(unreachable) > 1 else 'reaches'} under "
                f"{device.id}'s bezel",
                placed.element.span,
                notes=["a hold can only land on the part of the panel the wearer can "
                       "see and touch, so part of that zone is dead",
                       "narrow 'size:', or move the carousel toward the centre"],
                confidence="exact for round and rectangle screens",
            ))


def _outer_zones(placed: PlacedCarousel) -> list[tuple[str, IntBox]]:
    """The previous/next zones, as boxes.  The middle one is never the problem:
    it is by construction the part of the row closest to the screen centre."""
    box = placed.box
    return [
        ("previous", IntBox(box.x, box.y, placed.prev_edge - box.x, box.height)),
        ("next", IntBox(placed.next_edge, box.y,
                        box.right - placed.next_edge, box.height)),
    ]


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
    """Pairs whose hit rectangles intersect, earlier element first."""
    out = []
    for index, later in enumerate(held):
        for earlier in held[:index]:
            if _intersects(earlier.box, later.box):
                out.append((earlier, later))
    return out


# -- complication gating -----------------------------------------------------


def check_complication_availability(resolved: ResolvedFace, bag: Bag) -> None:
    """Does this device actually know the complication types this design uses?

    The obvious fix -- wiring `catalog.Source.requires` through
    `Device.has_symbol`, the way `check_hold_targets` resolves `onPress` --
    was investigated and does not work: `COMPLICATION_TYPE_*` values are
    constants, not `<functionEntry>` symbols, and simply do not appear in a
    device's `api.debug.xml` at all (confirmed by grep against the real
    vendored files for `COMPLICATION_TYPE_BATTERY`, the one type every target
    is documented to support unconditionally -- it is absent from all three).
    So this checks the thing that *does* carry the information:
    `wfb.complications.ComplicationType.since`, the API level the SDK
    introduced that type at (`Toybox/Complications.html`'s own Type table),
    against `Device.api_level`, the device's own ConnectIQ ceiling
    (`compiler.json`'s `connectIQVersion`). Unlike `check_hold_targets`'s
    `onPress` question, a level comparison *is* honest here: `since` is
    exactly the number the SDK publishes for a type's introduction, not an
    inferred floor a device might silently miss (constraint 6's `onTap` trap
    was about a *method* documented at one level and absent on a device above
    it -- there is no equivalent "documented since but device doesn't really
    have it" case known for a `COMPLICATION_TYPE_*` constant).

    Two things a design can do with a gated type, both checked here, both
    producing the same silent-degradation outcome at runtime rather than a
    crash: **read** it (`complication.<name>` in `value:`/`color:`/etc, via
    `Complications.getComplication` returning null -- the ordinary "absence is
    normal" contract every nullable source already has) or **hold to launch
    it** (`on_hold:`/a carousel item's `launch:`, via
    `Complications.subscribeToUpdates` returning `false` or throwing
    `ComplicationNotFoundException` -- both already caught, uniformly, by
    `WfbComplications.mc`'s `subscribe()`). Either way the face still works;
    the warning exists so the author can decide "fine, it just never updates
    there" instead of discovering it on the wrist.

    A WARNING, not an error (SPEC2 D1): runtime degrades gracefully, and an
    error would force dropping a target or a source that is fine on the other
    two devices.
    """
    candidates: list[tuple] = []  # (placed, complication_name, span, kind)
    for placed in resolved.items:
        element = placed.element
        for expression in element.expressions():
            for path in expression.sources:
                if not path.startswith("complication."):
                    continue
                name = path[len("complication."):]
                if complications.get(name) is not None:
                    candidates.append((placed, name, expression.span or element.span, "read"))
        if element.on_hold is not None and complications.get(element.on_hold) is not None:
            candidates.append((placed, element.on_hold, element.span, "hold"))
        if isinstance(element, Carousel):
            for item in element.items:
                if item.launch is not None and complications.get(item.launch) is not None:
                    candidates.append((placed, item.launch, item.span or element.span, "hold"))
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
                choices = (slot.default,) if slot.allow_any else slot.choices
                for name in choices:
                    if complications.get(name) is not None:
                        candidates.append((placed, name, element.span, "slot"))

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
            "complication-gated",
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
        if kind == "hold":
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "complication-gated",
                f"{placed.id}: holding to launch {name!r} needs ConnectIQ {ctype.since}, "
                f"but {device.id} tops out at {device_level}",
                span,
                notes=[
                    "Complications.subscribeToUpdates returning false or throwing "
                    "ComplicationNotFoundException is already caught uniformly by "
                    "WfbComplications.mc's subscribe() -- the hold simply becomes a "
                    "no-op on this device, not a crash",
                    "pick a launch target with a lower 'since' for this device, or "
                    "accept that the hold does nothing here",
                ],
                confidence=confidence,
            ))
        elif kind == "slot":
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "complication-gated",
                f"{placed.id}: slot config.data.{placed.element.slot}'s "
                f"'complication.{name}' needs ConnectIQ {ctype.since}, but "
                f"{device.id} tops out at {device_level}",
                span,
                notes=[
                    "Complications.getComplication returns null for a type the device "
                    "does not support -- the same 'absence is normal' contract every "
                    "other nullable source already has, so this reads as absent rather "
                    "than crashing",
                    "the wearer simply cannot pick this type on this device (or, if it "
                    "is the slot's 'default:', the slot never shows it here); drop it "
                    "from 'choices:', or accept that it is unreachable on this target",
                ],
                confidence=confidence,
            ))
        else:
            _emit(bag, placed, Diagnostic(
                Severity.WARNING,
                "complication-gated",
                f"{placed.id}: 'complication.{name}' needs ConnectIQ {ctype.since}, "
                f"but {device.id} tops out at {device_level}",
                span,
                notes=[
                    "Complications.getComplication returns null for a type the device "
                    "does not support -- the same 'absence is normal' contract every "
                    "other nullable source already has, so this reads as absent rather "
                    "than crashing",
                    "drop this binding for this target, bind a lower-'since' source "
                    "instead, or accept that it never updates here",
                ],
                confidence=confidence,
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
    another swap order every time and never once look different for it.

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


# -- alpha ------------------------------------------------------------------


def check_alpha(resolved: ResolvedFace, bag: Bag) -> None:
    if resolved.device.alpha_blending:
        return
    # Nothing in format 1 expresses transparency yet; this check exists so the
    # gate is in place before any property that implies it is added.
    return


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
