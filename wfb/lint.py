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

from . import catalog
from .devices import Device
from .diagnostics import Bag, Diagnostic, Severity
from .fonts import BakedFont
from .ir import Element, Face, Text
from .layout import (
    PlacedText, ResolvedFace, inside_screen, inside_visible_area_for, is_full_bleed,
)
from .palette import Color

#: Checks an author may silence with ``lint: {allow: [...], reason: "..."}``.
#: The hard-platform-limit errors are deliberately absent: suppressing one
#: produces a face that does not work.
SUPPRESSIBLE = frozenset({
    "palette-dither", "safe-area", "text-overflow", "contrast", "partial-update-budget",
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
    "color", "contrast", "devices", "duplicate-id", "element", "expression",
    "font", "format", "format-version", "icon", "io", "lint-allow", "memory",
    "metrics", "missing-glyph", "monkeyc", "off-screen", "palette",
    "palette-dither", "partial-update", "partial-update-budget", "permission",
    "raw-color", "refresh-tier", "safe-area", "schema", "target",
    "text-overflow", "toolchain", "type", "units", "when-absent", "yaml",
})


def run(resolved: ResolvedFace, bag: Bag) -> None:
    """Stage 3: everything computable from resolved geometry on one device."""
    check_palette(resolved, bag)
    check_geometry(resolved, bag)
    check_text_fit(resolved, bag)
    check_glyphs(resolved, bag)
    check_contrast(resolved, bag)
    check_partial_update_budget(resolved, bag)
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


def _backdrop(resolved: ResolvedFace) -> Color | None:
    """The colour behind everything: the first full-screen shape, or palette.bg."""
    for placed in resolved.items:
        element = placed.element
        if placed.kind != "shape" or getattr(element, "color", None) is None:
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
                   "updates for the rest of the app's lifecycle",
                   "group the low-power elements closer together to tighten the clip",
                   "set 'lint: {allow: [partial-update-budget], reason: ...}' on any "
                   "one of the elements drawn in low-power mode to keep it"],
            confidence="HEURISTIC -- Garmin does not publish the numeric budget; this "
                       "flags relative cost, not a measured overrun",
        )


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
