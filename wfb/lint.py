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
from .ir import Carousel, Element, Face, Text
from .layout import (
    PlacedCarousel, PlacedText, ResolvedFace, inside_screen, inside_visible_area,
    inside_visible_area_for, is_full_bleed,
)
from .palette import Color
from .units import IntBox

#: Checks an author may silence with ``lint: {allow: [...], reason: "..."}``.
#: The hard-platform-limit errors are deliberately absent: suppressing one
#: produces a face that does not work.
SUPPRESSIBLE = frozenset({
    "palette-dither", "safe-area", "text-overflow", "contrast", "partial-update-budget",
    "hold-unsupported", "hold-overlap", "carousel-zone", "complication-gated",
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
    "carousel", "color", "complication-gated", "contrast", "devices", "duplicate-id",
    "element", "expression",
    "font", "format", "format-version", "icon", "io", "lint-allow", "memory",
    "metrics", "missing-glyph", "monkeyc", "off-screen", "palette",
    "carousel-zone", "carousel-on-hold", "hold-overlap", "hold-unsupported",
    "hold-auto-ambiguous", "hold-auto-unresolved",
    "palette-dither", "partial-update", "partial-update-budget", "permission",
    "on-hold", "on-tap-renamed", "raw-color", "safe-area", "schema", "source-renamed",
    "target",
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
    check_hold_targets(resolved, bag)
    check_carousel_zones(resolved, bag)
    check_complication_availability(resolved, bag)
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
                   "onPartialUpdate -- a 'weather.*' or 'complication.*' binding on a "
                   "low_power element is the expensive case to look at first",
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
            a, b = earlier.box, later.box
            if a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom:
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
    candidates: list[tuple] = []  # (placed, complication_name, span, is_hold)
    for placed in resolved.items:
        element = placed.element
        for expression in element.expressions():
            for path in expression.sources:
                if not path.startswith("complication."):
                    continue
                name = path[len("complication."):]
                if complications.get(name) is not None:
                    candidates.append((placed, name, expression.span or element.span, False))
        if element.on_hold is not None and complications.get(element.on_hold) is not None:
            candidates.append((placed, element.on_hold, element.span, True))
        if isinstance(element, Carousel):
            for item in element.items:
                if item.launch is not None and complications.get(item.launch) is not None:
                    candidates.append((placed, item.launch, item.span or element.span, True))

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

    for placed, name, span, is_hold in candidates:
        ctype = complications.TYPES[name]
        if version_key(ctype.since) <= version_key(device_level):
            continue
        confidence = (
            f"exact -- {name!r}'s since ({ctype.since}, Toybox/Complications.html) "
            f"vs {device.id}'s api_level ({device_level}, compiler.json)"
        )
        if is_hold:
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
