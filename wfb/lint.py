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
from collections.abc import Iterable

from . import availability, catalog, complications, series
from .devices import Device, version_key
from .diagnostics import Bag, Diagnostic, Severity
from .fonts import BakedFont
from .ir import (
    CONFIG_SYMBOL, ComplicationSlot, Element, Face, FontSpec, Graph, HandsElement,
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
#: produces a face that does not work.  So is `api-gated-unguardable`
#: (`check_api_gated` case 5): it means an unguarded call that crashes.
SUPPRESSIBLE = frozenset({
    "palette-dither", "safe-area", "text-overflow", "contrast", "partial-update-budget",
    "hold-unsupported", "hold-overlap", "api-gated",
    "dead-element", "graphics-pool", "antialias-dither", "static-overlap",
    "config-unsupported", "duplicate-style", "unreachable-layout",
    "sub-pixel-length", "font-unavailable", "off-screen", "text-outline-interior",
    "aod-unreachable", "aod-empty", "aod-burn-in",
})

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
    "aod", "aod-unreachable", "aod-empty", "aod-burn-in",
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


def run_design(face: Face, bag: Bag) -> None:
    """Every check that depends on the design alone, not on a device: run
    once per build, before any target is resolved."""
    for check in DESIGN_CHECKS:
        check(face, bag)


def run(resolved: ResolvedFace, bag: Bag) -> None:
    """Stage 3: everything computable from resolved geometry on one device."""
    for check in DEVICE_CHECKS:
        check(resolved, bag)
    for warning in resolved.warnings:
        bag.note("metrics", warning, confidence="not checked -- no metrics available")


def _suppressed(code: str, allows: Iterable[frozenset[str]]) -> bool:
    """The one definition of "suppressed": ``code`` names a real suppressible
    diagnostic, and at least one owner's ``lint: {allow: [...]}`` (an
    element's, a `config: style:` entry's, a layout's, the face's `aod:`)
    accepted it."""
    return code in SUPPRESSIBLE and any(code in allow for allow in allows)


def _emit(bag: Bag, placed, diag: Diagnostic) -> None:
    """Add a diagnostic about one placed element, unless that element
    accepted its code."""
    _emit_for_users(bag, [placed.element], diag)


def _emit_for_users(bag: Bag, users: Iterable[Element], diag: Diagnostic) -> None:
    """Add a diagnostic about a shared declaration (a `palette:` entry, a
    `config:` axis, a colour-scheme role, the low-power clip) unless any
    element that uses it accepted its code.  There is no element of the
    declaration's own to hang `lint:` on, and a dithered colour dithers
    everywhere it is drawn, so acknowledging it on any one use acknowledges
    the declaration itself.
    """
    if not _suppressed(diag.code, (user.lint_allow for user in users)):
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
    and behave, identically.  With no `layouts:`, `layout` is `None` on every
    entry and this reduces to "two entries name the same `colors:` scheme".

    A warning, suppressible on the *second* entry of the pair -- the one that
    makes the combination a duplicate (two labels while iterating is a
    legitimate reason).  Design-level: runs once, from :func:`run_design`.
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
        if _suppressed("duplicate-style", [entry.lint_allow]):
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
    its `layout:` -- its content ships in the `.prg` but nothing lets the
    wearer switch to it.

    A warning (the author may be mid-iteration), suppressible on the
    layout's own `lint:`.  Design-level: runs once, from :func:`run_design`.
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
        if _suppressed("unreachable-layout", [decl.lint_allow]):
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


def _vector_text_carriers(face: Face):
    """Every `(what, carrier, part_index, element)` that can draw text in a
    `face:` font: a `Text` element (`part_index` is `None`) and each
    `shape: text` part of a pattern (named `<pattern id>.parts[<i>]`).  The
    carrier has the `font`/`font_is_custom`/`curve`/`if_unavailable`/`span`
    the check reads; `element` owns the `lint:` block (a part has none)."""
    for element in face.walk():
        if isinstance(element, Text):
            yield element.id, element, None, element
        elif isinstance(element, PatternElement):
            for index, part in enumerate(element.parts):
                if part.shape == "text":
                    yield f"{element.id}.parts[{index}]", part, index, element


def _font_unavailable(placed, part_index: int | None) -> bool:
    """Did layout decide this carrier's vector font failed gates 1-3 on the
    device `placed` was resolved for?  `False` when it is not placed there."""
    if part_index is None:
        return isinstance(placed, PlacedText) and not placed.font_available
    return (isinstance(placed, PlacedPattern) and part_index < len(placed.parts)
            and not placed.parts[part_index].font_available)


def check_vector_font_availability(
    face: Face, resolved: dict[str, ResolvedFace], bag: Bag,
) -> None:
    """`if_unavailable:` (plan 11 §2.4) is a cross-device question ("did
    gates 1-3 fail on any target?"), so unlike :func:`run`'s per-device
    checks this takes every target's `ResolvedFace` and `wfb.build.
    resolve_all` calls it once, after all of them are resolved.  Layout has
    already decided each device's gates (`PlacedText.font_available`, and
    a pattern part's `ResolvedHandPart.font_available`); this only reports.

    **`error` (the default) is a hard build failure, never suppressible**,
    even though `font-unavailable` is in `SUPPRESSIBLE` for `hide`: an
    author who wants leniency switches to `hide` rather than silencing a
    design that still asks for a face that will never draw.  The message
    names each failing device and *why* -- gate 1 (the symbol is missing)
    and gates 2/3 (none of the requested faces is published) have different
    fixes (plan 11 §1), so they are never collapsed.

    **`hide`** draws nothing there: a suppressible warning naming every
    device the carrier will not draw on.

    A `Text` element and a pattern's `shape: text` part (plan 11 slice 2)
    go through the same gates, the same `if_unavailable:` precedence (the
    carrier's own value over the font's) and the same wording; a part is
    suppressed through its pattern's `lint:`.
    """
    placed_by_device = {
        device_id: {p.id: p for p in rf.items} for device_id, rf in resolved.items()
    }
    for what, carrier, part_index, element in _vector_text_carriers(face):
        if not carrier.font_is_custom:
            continue
        spec = face.fonts.get(carrier.font)
        if spec is None or not spec.is_vector:
            continue
        failing = sorted(
            device_id for device_id, placed in placed_by_device.items()
            if _font_unavailable(placed.get(element.id), part_index)
        )
        if not failing:
            continue
        effective = carrier.if_unavailable or spec.if_unavailable or "error"
        requested = ", ".join(spec.face)
        if effective == "error":
            bag.error(
                "font-unavailable",
                f"{what}: 'font: font.{carrier.font}' has no usable face on "
                + ", ".join(failing),
                carrier.span,
                notes=[
                    f"requested face(s), in author order: {requested}",
                    *(_vector_font_failure_reason(resolved[device_id].device, spec,
                                                  carrier.curve)
                      for device_id in failing),
                    f"set 'if_unavailable: hide' on 'font.{carrier.font}' or on "
                    f"'{what}' to let it disappear on a target that cannot "
                    "draw it, drop the device from 'targets:', or add a face it "
                    "actually publishes",
                ],
                confidence="exact -- resolved per-device gates 1-3",
            )
            continue
        if _suppressed("font-unavailable", [element.lint_allow]):
            continue
        bag.warning(
            "font-unavailable",
            f"{what}: will not draw on " + ", ".join(failing)
            + f" -- 'font: font.{carrier.font}' has no usable face there",
            carrier.span,
            notes=[
                f"requested face(s), in author order: {requested}",
                "set 'lint: {allow: [font-unavailable], reason: ...}' on "
                f"'{what}' to accept it",
            ],
            confidence="exact -- resolved per-device gates 1-3",
        )


def _vector_font_failure_reason(device: Device, spec: FontSpec, curve) -> str:
    """One line naming *why* `spec.face` failed to resolve on `device`:
    gate 1 (the symbol itself is absent) or gates 2/3 (the device's own
    catalogue has none of the requested faces)."""
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
    """:func:`check_lint_allow` for one code on one owner (an element, a
    `config: style:` entry or a layout), so every owner gets the same text."""
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
    actually suppress -- otherwise a typo and a deliberately unsuppressible
    code would both fail the same way: silently, with the warning still
    firing.

    Covers every owner of a `lint:` block: elements, `config: style:`
    entries and `layouts:` entries.  Design-level: runs once, from
    :func:`run_design`.
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


#: Element fields that can carry a bare colour reference.  Not every kind
#: has all three; ``getattr`` covers the gap.
_PALETTE_REFERENCING_FIELDS = ("color", "track_color", "icon_color")


def _users_of(face: Face, token: str) -> list[Element]:
    """Elements with a colour whose author text is exactly ``token``
    (``palette.<name>``, ``config.<name>``, ``config.colors.<role>``).

    Deliberately an exact textual match, not a search through folded
    constants: a conditional that merely *mentions* the reference
    (``hr.current > 100 ? palette.fg : ...``) does not count, because
    dithering is a property of the named colour, and tracing it through
    arbitrary expressions would overclaim what this can verify.

    A `hands`/`pattern` element is matched through its `.colors` (every
    effective part colour, already folded at build time) rather than a
    `color:` field: a hand has none, and a pattern's is only the default a
    part may override. A `text` element's `outline: {color: ...}`, and any
    element's resolved `aod:` colour override, are colours it draws too
    (plan 18 item 6).
    """
    out = []
    for element in face.walk():
        if any(expression.text == token for expression in _colors_drawn_by(element)):
            out.append(element)
    return out


def _colors_drawn_by(element: Element) -> list:
    """Every colour `Expression` ``element`` itself can draw with: its own
    colour fields (or a hand's/pattern's folded part colours), a text's
    outline, and its resolved AOD override's colours."""
    if isinstance(element, (HandsElement, PatternElement)):
        colors = list(element.colors)
    else:
        colors = [e for field in _PALETTE_REFERENCING_FIELDS
                  if (e := getattr(element, field, None)) is not None]
    if isinstance(element, Text) and element.outline is not None:
        colors.append(element.outline.color)
    if element.aod is not None:
        colors += [e for field in _PALETTE_REFERENCING_FIELDS
                   if (e := getattr(element.aod, field, None)) is not None]
    return colors


def _emit_dither(
    bag: Bag, users: list[Element], message: str, nearest_note: str, token: str,
) -> None:
    """The `palette-dither` warning every declared-colour check shares,
    suppressible on any element that uses the declaration."""
    if users:
        suppress_note = (
            f"set 'lint: {{allow: [palette-dither], reason: ...}}' on an element "
            f"that draws '{token}' ({', '.join(u.id for u in users)}) to keep it"
        )
    else:
        # Never claim a suppression site that does not exist.
        suppress_note = (
            f"no element draws exactly '{token}' (as 'color:', 'track_color:', "
            f"'icon_color:', 'outline:' or an 'aod:' override), so there is nowhere "
            f"to put 'lint: {{allow: [palette-dither]}}' for it"
        )
    _emit_for_users(bag, users, Diagnostic(
        Severity.WARNING,
        "palette-dither",
        message,
        notes=[
            nearest_note,
            "each channel must be 0x00, 0x55, 0xAA or 0xFF; anything else is "
            "dithered by the firmware and looks grainy",
            suppress_note,
        ],
        confidence="exact -- device display_colors",
    ))


def check_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Each channel must be 0x00/0x55/0xAA/0xFF on a 64-colour panel.

    The warning is about a *palette entry*, which has no `lint:` of its
    own, so suppression is honoured on any element that references it
    (:func:`_emit_for_users`).
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
        token = f"palette.{name}"
        _emit_dither(
            bag, _users_of(resolved.face, token),
            f"{token} = {color} is not one of {resolved.device.id}'s "
            f"{colors} colours and will be dithered",
            f"nearest legal colour: {color.nearest_legal(colors)}",
            token,
        )


def check_antialias_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Anti-aliasing manufactures the exact intermediate values a 64-colour
    panel cannot show cleanly (constraint 13, the same firmware behaviour
    :func:`check_palette` reports): a soft edge blends the shape's colour
    into whatever is behind it, so even two legal colours produce illegal
    ones in between.

    Once per **device**, not per element: "is anti-aliasing used anywhere
    here" is the only fact this can responsibly state, since how visible
    each soft edge is depends on geometry it does not model.  Reported
    against the first anti-aliased element, whose `lint:` silences it.

    A WARNING, like `palette-dither`, even though -- unlike a palette colour
    -- there is no legal soft edge to switch to: on a 64-colour target it
    fires whenever primitive anti-aliasing is on, and an author who made
    that tradeoff on purpose acknowledges it once.
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


def _check_declared_colors(
    resolved: ResolvedFace, bag: Bag, token: str, declared: list[tuple[str, Color]],
) -> None:
    """`palette-dither` for one config token that can show any of several
    declared colours; each `(label, colour)` is named in the nearest-legal
    note as ``<label><colour> -> <nearest>``."""
    colors = resolved.device.display_colors
    bad = [(label, c) for label, c in declared if not c.is_palette_legal(colors)]
    if not bad:
        return
    nearest = ", ".join(f"{label}{c} -> {c.nearest_legal(colors)}" for label, c in bad)
    _emit_dither(
        bag, _users_of(resolved.face, token),
        f"{token}: {len(bad)} declared colour(s) are not one of "
        f"{resolved.device.id}'s {colors} colours and will be dithered",
        f"off-grid -> nearest legal: {nearest}",
        token,
    )


def check_config_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """A declared `config:` colour axis, checked like a `palette:` entry.

    The compiled-in `default:` is always checked (it is all a device with no
    native editor -- fr955 -- ever shows), and every explicit `choices:`
    entry too.  `choices: any` skips only the list half: the editor's
    unrestricted picker gives this compiler no list to check.
    """
    if resolved.device.display_colors is None:
        return  # check_palette already emits the one "not checked" note per device
    for name, entry in resolved.face.config.items():
        declared = [entry.default] if entry.allow_any else (
            [entry.default] + [c.color for c in entry.choices]
        )
        _check_declared_colors(resolved, bag, f"config.{name}", [("", c) for c in declared])


def check_color_scheme_palette(resolved: ResolvedFace, bag: Bag) -> None:
    """Every colour a `config: style:` entry's `colors:` can put on screen,
    checked per role across every scheme some entry references
    (deduplicated, first-reference order).  Styles has no unrestricted
    picker, so there is no `choices: any` carve-out; an unreferenced scheme
    can never be shown, so it is not checked.
    """
    if resolved.device.display_colors is None:
        return  # check_palette already emits the one "not checked" note per device
    axis = resolved.face.config_style
    if axis is None:
        return
    default_entry = axis.default_entry
    if default_entry.colors is None:
        return  # a layout-only default entry has no scheme role to check
    schemes = resolved.face.color_scheme
    roles = sorted(schemes[default_entry.colors].colors)
    scheme_names = list(dict.fromkeys(
        e.colors for e in axis.entries if e.colors is not None))
    for role in roles:
        _check_declared_colors(resolved, bag, f"config.colors.{role}", [
            (f"color_scheme.{name}.colors.{role}=", schemes[name].colors[role])
            for name in scheme_names
        ])


def _probe_symbols(bag: Bag, device: Device, code: str, what: str, probe):
    """``probe()`` against the device's symbol table, or -- when the device
    has no ``api.debug.xml`` -- a "not checked" note and ``None``."""
    try:
        return probe()
    except Exception:
        bag.note(
            code,
            f"{device.id}: no symbol table, so {what} is not checked",
            confidence="not checked -- the device's api.debug.xml is unavailable",
        )
        return None


def check_config_support(resolved: ResolvedFace, bag: Bag) -> None:
    """Does this device actually have the native on-device editor?

    Resolved against the device's own symbol table, not an API level
    (constraint 6: fr955 reports 5.2.0, above the editor's documented
    5.1.0, and has no editor -- `docs/research/probes/watchface-config/`).
    Without it the face still runs and keeps every declared `default:`
    forever -- ADR 0006 §2's chosen scope, not a bug, but not silent either.

    **Except a `config.data.*` slot on a device that also lacks
    `Toybox.Complications`** (fenix6, fenix6xpro, fr245 today): a slot's
    `default:` is itself read through `WfbComplications.valueOf`, so there
    it shows its absent state instead of "keeping" anything, and the
    message says so.  `check_api_gated` (case 4) reports the same slot
    independently -- the two are different facts.
    """
    face = resolved.face
    if not face.has_config:
        return
    device = resolved.device
    available = _probe_symbols(bag, device, "config-unsupported", "on-device config support",
                               lambda: device.has_symbol(CONFIG_SYMBOL))
    if available is not False:
        return

    colour_tokens = [f"config.{name}" for name in sorted(face.config)]
    non_default_entries: list[str] = []
    if face.config_style is not None:
        default_entry = face.config_style.default_entry
        if default_entry.colors is not None:
            # A layout-only default entry names no role at all.
            default_scheme = face.color_scheme[default_entry.colors]
            colour_tokens += [f"config.colors.{role}" for role in sorted(default_scheme.colors)]
        non_default_entries = [
            e.name for e in face.config_style.entries if e.name != face.config_style.default
        ]
    slot_tokens = [f"config.data.{name}" for name in sorted(face.config_data)]
    names_list = colour_tokens + slot_tokens
    if not names_list and not non_default_entries:
        # Nothing the wearer could ever observe differently.
        return
    names = ", ".join(names_list)

    # A slot's default is read through Toybox.Complications, so on a device
    # that lacks the module too it shows as absent rather than "kept".
    has_complications = not slot_tokens or device.has_module("Complications")
    kept_names_list = names_list if has_complications else colour_tokens
    absent_slot_tokens = [] if has_complications else slot_tokens

    users = [user for token in colour_tokens for user in _users_of(face, token)]
    users += [element for element in face.walk()
              if isinstance(element, ComplicationSlot) and element.slot in face.config_data]
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
    if non_default_entries:
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
        # Only layout-only style entries made this fire: nothing binds a
        # colour or slot to point the note at.
        suppress_note = (
            "nothing here binds a 'color:'/'track_color:'/'slot:' at all -- "
            "this is purely about the unreachable style entries named above"
        )
    editor = f"{device.id}: has no on-device watch face editor"
    kept, absent = ", ".join(kept_names_list), ", ".join(absent_slot_tokens)
    if kept_names_list and absent_slot_tokens:
        message = (f"{editor}, so {kept} keep their declared defaults here; it also "
                   f"lacks Toybox.Complications, so {absent} show as absent here instead")
    elif kept_names_list:
        message = f"{editor}, so {kept} keep their declared defaults here"
    elif absent_slot_tokens:
        message = (f"{editor}, and also lacks Toybox.Complications, so {absent} show as "
                   f"absent here rather than their declared defaults")
    else:
        message = f"{editor}, so every 'config: style:' entry but the default is stuck there"
    _emit_for_users(bag, users, Diagnostic(
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
                # Name the two numbers a shape-aware reach (a disc, a curved
                # text's real ink) came down to -- `box` alone is not what
                # was tested for those kinds.
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
    """A nonzero `%`/`%r` length that resolves under 1px with `min_1px:`
    off: legal, but it silently vanishes on this device while drawing on a
    larger one, which an author almost never means.  `Resolver` records each
    occurrence while it still has the authored length
    (`wfb.layout.SubPixelLength` in `resolved.sub_pixel`); this only reports.

    **One diagnostic per record** -- unlike `antialias-dither`'s single
    device-wide warning, each record is a different authored line with its
    own fix.  A hand/pattern part has no `lint:` of its own, so it is
    suppressed through its owning element, which then silences every part's
    finding (the note says so).
    """
    for sp in resolved.sub_pixel:
        is_part = sp.owner != sp.element.id
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
        _emit_for_users(bag, [sp.element], Diagnostic(
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
            # The box is the rotated/radial one, which `check_geometry`
            # already judges; this check's horizontal-framing message would
            # not describe what happened.
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


def _missing_glyph_error(bag: Bag, what: str, font_reference: str, missing: set[str],
                         span, notes: list[str]) -> None:
    characters = ", ".join(repr(c) for c in sorted(missing))
    bag.error(
        "missing-glyph",
        f"{what}: font {font_reference!r} has no glyph for {characters}",
        span,
        notes=notes + ["widen the font's 'glyphs:' set, or remove it to let the compiler "
                       "derive the set from the design"],
        confidence="exact -- the baked font's own character map",
    )


def check_glyphs(resolved: ResolvedFace, bag: Bag) -> None:
    """A subsetted font must contain every character the design can render.

    A `text` element is checked on its widest rendering; a pattern's
    `shape: text` part on every drawn copy's exact string, collected into
    one error per part ("one error, not N", docs/lore/codegen.md).
    """
    for placed in resolved.items:
        if isinstance(placed, PlacedPattern):
            for index, part in enumerate(placed.parts):
                if part.shape != "text" or not part.font_is_custom:
                    continue
                font = resolved.fonts.get(part.font_reference)
                if font is None:
                    continue
                missing: set[str] = set()
                for copy_index in placed.copies:
                    missing |= font.missing(part.texts[copy_index])
                if missing:
                    _missing_glyph_error(
                        bag, f"{placed.id}.parts[{index}]", part.font_reference, missing,
                        placed.element.parts[index].span, [])
        elif isinstance(placed, PlacedText) and placed.font_is_custom:
            font: BakedFont | None = resolved.fonts.get(placed.font_reference)
            if font is None:
                continue
            missing = font.missing(placed.widest)
            if missing:
                _missing_glyph_error(
                    bag, placed.id, placed.font_reference, missing, placed.element.span,
                    [f"the widest rendering of this element is {placed.widest!r}"])


# -- check 10: contrast -----------------------------------------------------


def _constant_color(expression) -> Color | None:
    """The colour an expression folds to at build time, or `None` when it
    is absent or not a build-time constant (`config.*`, a data conditional)."""
    if expression is None or expression.constant is None:
        return None
    return Color.parse(int(expression.constant))


def _contrast_subjects(placed):
    """Every `(label, colour, ring, allow_backdrop_match)` one placed
    element draws, for :func:`check_contrast`.

    `ring` is the `outline:` colour, or `None` for plain ink.  A `hands`
    element yields each part of each hand (its effective colour,
    `ResolvedHandPart.color`), and a `pattern` each template part once (every
    copy shares its colours) -- neither has a single `color:` to read.

    `allow_backdrop_match`: a shape-drawn ink exactly matching the backdrop
    is presumed deliberate (a punched-out hole, an "off" indicator, the
    backdrop shape itself), which a glyph (`text`/`icon`, a `shape: text`
    part) never gets -- there an exact match is invisible content by
    mistake.  A hand part is never `shape: text`.
    """
    element = placed.element
    if isinstance(element, HandsElement):
        for hand in ("hour", "minute", "second"):
            resolved_hand = getattr(placed, hand)
            if resolved_hand is None:
                continue
            for index, part in enumerate(resolved_hand.parts):
                yield f"{placed.id}.{hand}.parts[{index}]", part.color, None, True
    elif isinstance(element, PatternElement):
        for index, part in enumerate(placed.parts):
            yield (f"{placed.id}.parts[{index}]", part.color, part.outline_color,
                   part.shape != "text")
    else:
        outline = getattr(element, "outline", None)
        yield (placed.id, getattr(element, "color", None),
               outline.color if outline is not None else None, placed.kind == "shape")


def check_contrast(resolved: ResolvedFace, bag: Bag) -> None:
    """WCAG-style ratio between each drawn colour and the backdrop behind it.

    The arithmetic is exact; the 3.0 threshold is a judgement call, which is why
    this is a warning and is suppressible.

    **An `outline:`-bearing element or pattern part (plan 15) is judged on
    its ring, never its interior**: the interior is *supposed* to match what
    is underneath (the hollow-text idiom, `docs/guide/text.md`), so the ring
    is the only ink that reads.  It can fail two ways independently:

    * **ring vs. backdrop** -- the whole character vanishes into the page;
    * **ring vs. interior** -- the ring's inner edge disappears into the
      fill and the glyph reads as one soft blob instead of an outline.
    """
    backdrop = _backdrop(resolved)
    if backdrop is None:
        return
    for placed in resolved.items:
        for label, color, ring, allow_backdrop_match in _contrast_subjects(placed):
            if ring is not None:
                _check_outline_contrast(bag, placed, ring, color, backdrop, label=label)
            else:
                _check_plain_color_contrast(bag, placed, color, backdrop, label=label,
                                            allow_backdrop_match=allow_backdrop_match)


def _contrast_warning(bag: Bag, placed, message: str, note: str) -> None:
    _emit(bag, placed, Diagnostic(
        Severity.WARNING, "contrast", message, placed.element.span, notes=[note],
        confidence="exact arithmetic; the 3.0 threshold is a judgement call",
    ))


def _check_plain_color_contrast(
    bag: Bag, placed, color_expression, backdrop: Color, *, label: str,
    allow_backdrop_match: bool = False,
) -> None:
    """Ordinary ink-vs-backdrop contrast for one colour (see
    :func:`_contrast_subjects` for `allow_backdrop_match`)."""
    color = _constant_color(color_expression)
    if color is None:
        return
    if allow_backdrop_match and color.value == backdrop.value:
        return
    ratio = color.contrast_ratio(backdrop)
    if ratio < 3.0:
        _contrast_warning(
            bag, placed, f"{label}: {color} on {backdrop} has a contrast ratio of {ratio:.1f}",
            "below 3.0 this is hard to read on a transflective display in low light")


def _check_outline_contrast(
    bag: Bag, placed, ring_expression, interior_expression, backdrop: Color, *, label: str,
) -> None:
    """The two ring-based comparisons :func:`check_contrast` makes for an
    `outline:` in place of the plain one; either, both or neither may fire.
    Silent for a colour that is not a build-time constant."""
    ring = _constant_color(ring_expression)
    if ring is None:
        return
    ratio = ring.contrast_ratio(backdrop)
    if ratio < 3.0:
        _contrast_warning(
            bag, placed,
            f"{label}: outline ring {ring} on {backdrop} has a contrast ratio of {ratio:.1f}",
            "with a hollow interior the ring is the only ink drawn -- "
            "below 3.0 the whole character can disappear into the page")
    interior = _constant_color(interior_expression)
    if interior is None:
        return
    inner_ratio = ring.contrast_ratio(interior)
    if inner_ratio < 3.0:
        _contrast_warning(
            bag, placed,
            f"{label}: outline ring {ring} on its own interior {interior} has a "
            f"contrast ratio of {inner_ratio:.1f}",
            "the ring's inner edge is invisible against its own fill -- the "
            "glyph reads as one soft-edged blob in the fill colour instead of "
            "a crisp outline")


#: Shapes whose *ink* fills their bounding box closely enough to be the thing
#: behind everything else.  An `arc` or a `polygon` can easily have a
#: screen-sized bounding box while painting a sliver of it, and an outlined
#: shape of any kind paints only its edge -- neither is a backdrop.
_BACKDROP_SHAPES = ("rectangle", "rounded_rectangle", "circle", "ellipse")


def _is_solid_backdrop_shape(placed) -> bool:
    """A filled shape trusted to paint every pixel of its own bounding box
    (:data:`_BACKDROP_SHAPES`)."""
    element = placed.element
    return (placed.kind == "shape" and getattr(element, "shape", None) in _BACKDROP_SHAPES
            and getattr(element, "filled", True))


def _backdrop(resolved: ResolvedFace) -> Color | None:
    """The colour behind everything: the first full-screen shape, or palette.bg."""
    for placed in resolved.items:
        if not _is_solid_backdrop_shape(placed):
            continue
        color = _constant_color(getattr(placed.element, "color", None))
        if placed.box.area >= resolved.screen.area * 0.9 and color is not None:
            return color
    return resolved.face.palette.get("bg")


# -- check 9: partial-update budget (heuristic) -----------------------------


def _expensive_low_power_reader(element: Element) -> tuple[str, str] | None:
    """``(path, call)`` for the first ``weather.*``/``complication.*`` path
    this element binds -- a real API call every time, not a local field
    read -- or ``None``.  Identified by ``catalog.Reader``, not by path
    prefix, so a future reader with the same cost is caught by construction.
    """
    for expression in element.expressions():
        for path in expression.sources:
            source = catalog.get(path)
            if source is None:
                continue
            if source.reader in ("weather_current", "weather_daily"):
                return path, "Weather.getCurrentConditions()/getDailyForecast()"
            reader = catalog.READERS.get(source.reader)
            if reader is not None and reader.complication_type is not None:
                return path, "Complications.getComplication()"
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

    1. **Clip-area, face-wide.** Like :func:`check_palette`, this is
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
        _emit_for_users(bag, [p.element for p in low_power], Diagnostic(
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
        expensive = _expensive_low_power_reader(placed.element)
        if expensive is None:
            continue
        path, call = expensive
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
    if _suppressed("aod-empty", [face.aod_lint_allow]):
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


# -- burn-in (plan 14 slice 4, research 11 §6 D, ADR 0008 check 8) ----------

#: Garmin's 10% rule (research 11 §1.2) has two different bases depending on
#: device generation -- the original Venu counts **lit pixels**, Venu 2 and
#: later count **luminance** -- and nothing in the device files
#: (`compiler.json`/`simulator.json`) says which generation a given AMOLED
#: target is. Checking *both* bases and erroring when either exceeds 10% is
#: the conservative reading: it can never pass a design that would fail on
#: either generation, only (rarely) fail one that would have passed on one
#: specific generation's own rule.
AOD_BURN_IN_THRESHOLD = 0.10

#: Two worst-case sample clocks (plan 14 slice 4 §2), not an exhaustive scan
#: of all 1,440 minutes -- that is what the simulator's own Screen Heat Map
#: is for (research 11 §1.5), and it is unreachable in this environment
#: (root `CLAUDE.md` §3). "10:08" and "20:08" between them draw a 24-hour
#: clock's two different tens-of-hours digits (1 and 2) against the same
#: units/minutes digits (0, 8) -- cheap (two renders), not a claim of being
#: the actual worst minute of the day. The max over these two is reported,
#: never just one arbitrarily chosen time.
AOD_BURN_IN_SAMPLE_TIMES: tuple[tuple[int, int, int], ...] = ((10, 8, 0), (20, 8, 0))

#: Full battery, so a `progress`/`graph` element bound to `system.battery`
#: is measured at its own worst case too -- every other sample value stays
#: `wfb.preview.SAMPLE`'s own default (plan 14 slice 4 §2: "whatever sample
#: values wfb preview uses by default").
AOD_BURN_IN_SAMPLE: dict[str, object] = {"system.battery": 100.0}

#: How many top contributors the diagnostic names (plan 14 slice 4 §3).
_AOD_BURN_IN_TOP_N = 3


def _aod_burn_in_lut(weight: float):
    """A 256-entry lookup table mapping an sRGB-encoded 0-255 channel value
    to its share of `weight` of full-white relative luminance, 0-255 --
    built once from `wfb.palette.srgb_channel_to_linear` so a whole
    rendered frame can be scored with three `Image.point` calls (fast, in
    Pillow's own C loop) instead of a per-pixel Python loop over
    device-resolution images."""
    from .palette import srgb_channel_to_linear
    return bytes(min(255, round(weight * srgb_channel_to_linear(v) * 255)) for v in range(256))


#: Rec. 709 primaries, the same weights `Color.relative_luminance` uses --
#: built lazily (module import time has no Pillow-free reason to pay for
#: this) by `_aod_burn_in_luts`.
_AOD_LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)
_aod_burn_in_luts_cache: tuple | None = None


def _aod_burn_in_luts():
    global _aod_burn_in_luts_cache
    if _aod_burn_in_luts_cache is None:
        _aod_burn_in_luts_cache = tuple(_aod_burn_in_lut(w) for w in _AOD_LUMINANCE_WEIGHTS)
    return _aod_burn_in_luts_cache


def _aod_burn_in_mask(width: int, height: int, shape: str):
    """Which pixels count in the denominator (research 11 §1.1: Garmin's
    rule is about *screen* pixels/luminance) -- on a round screen, the
    pixels the bezel physically crops are not part of the display at all,
    so they must not count on either side of the fraction. Built the same
    way `wfb.preview._mask_round`'s own bezel crop is (a hard-edged
    ellipse inscribed in the framebuffer), but returned as a mask rather
    than applied to an image, because this lint needs the pixel *count*
    the crop leaves behind, not just a masked picture.

    Every other screen shape (rectangle, and semi-round/semi-octagon, for
    which ADR 0008 check 4 already says "unavailable" -- ADR 0008) uses the
    whole framebuffer: not exactly the true visible area on a semi-shape,
    but the two AMOLED devices this project has today (`fenix847mm`,
    `fenix947mm`) are both `round-454x454`, so this never actually differs
    from an exact answer in practice; it is flagged here for the day a
    semi-shaped AMOLED device shows up.
    """
    from PIL import Image, ImageDraw
    if shape == "round":
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, width - 1, height - 1], fill=255)
        return mask
    return Image.new("L", (width, height), 255)


def _aod_burn_in_measure(image, mask) -> tuple[float, float, int, int]:
    """`(lit_fraction, luminance_fraction, lit_pixels, mask_pixels)` over
    `mask`'s own pixels only.

    **Lit**, research 11 §1.1, quoting Garmin's FAQ verbatim: "a pixel is
    considered on when rendering any color other than black" -- so lit is
    *any* non-`(0, 0, 0)` pixel, never a brightness threshold of this
    compiler's own invention (there is no such threshold to justify from
    the source).

    **Luminance** is the mean of `wfb.palette.Color.relative_luminance`
    (WCAG-style: Rec. 709 primaries over sRGB-degamma'd channels) across
    the same pixels, already a 0-1 fraction of full white by construction
    (`relative_luminance()` of pure white is exactly `1.0`). Garmin's own
    integral is unpublished (plan 14 §8, research 11 §5) -- this is a
    stated, reused choice (the same formula the contrast lint already
    uses), not a claim of matching Garmin's firmware bit for bit.
    """
    from PIL import Image, ImageChops
    zero = Image.new("L", image.size, 0)
    r, g, b = image.split()
    activity = Image.composite(ImageChops.lighter(ImageChops.lighter(r, g), b), zero, mask)
    lit = sum(activity.histogram()[1:])

    lut_r, lut_g, lut_b = _aod_burn_in_luts()
    luminance = ImageChops.add(ImageChops.add(r.point(lut_r), g.point(lut_g)), b.point(lut_b))
    luminance = Image.composite(luminance, zero, mask)
    luminance_total = sum(value * count for value, count in enumerate(luminance.histogram()))

    denom = mask.histogram()[255]
    if denom == 0:
        return 0.0, 0.0, lit, 0
    return lit / denom, (luminance_total / denom) / 255.0, lit, denom


def _aod_burn_in_options(sample_time: tuple[int, int, int]):
    """Device-resolution, unmasked AOD render options for one sample time:
    :func:`check_aod_burn_in` applies the pixel mask itself, per phase."""
    from . import preview
    return preview.PreviewOptions(scale=1, quantise=True, mask_shape=False, aod=True,
                                  time=sample_time, sample=AOD_BURN_IN_SAMPLE,
                                  aod_mask=False)


def check_aod_burn_in(resolved: ResolvedFace, bag: Bag) -> None:
    """research 11 §6 D / ADR 0008 check 8: is this AOD frame within
    Garmin's 10% rule?

    **Measured with the renderer `wfb preview --aod` uses**
    (`wfb.preview.render`), at device resolution, so it can never disagree
    with the author's own preview.  **Worst case, not every frame:** the
    worse of `AOD_BURN_IN_SAMPLE_TIMES` with `AOD_BURN_IN_SAMPLE`.  With the
    pixel mask on (plan 16), each sample is rendered unmasked and scored
    under all 4 phases (`wfb.aod_mask.apply`) -- every phase recurs every
    hour, so the worst one counts, not the sampled minute's own.

    **Attribution (plan 14 slice 4 §3):** each AOD-shown leaf is rendered
    alone (`resolved.items` narrowed to it -- geometry is already absolute)
    at the worst time and phase; the top contributors are named and the
    diagnostic is anchored at the biggest one's line.

    **Severity:** over `AOD_BURN_IN_THRESHOLD` (lit pixels *or* luminance)
    is an ERROR, but suppressible, unlike ADR 0008's default for errors:
    exceeding it breaks nothing the compiler emits -- at worst the OS turns
    always-on off for the app.  Under it, a NOTE with the numbers.
    MIP devices never reach this (`aod:` does not apply there).
    """
    device = resolved.device
    if not device.is_amoled:
        return
    shown = [placed for placed in resolved.items
             if placed.kind != "group" and placed.element.aod is not None]
    if not shown:
        return  # aod-empty already reports this face; nothing here to measure or blame

    from dataclasses import replace as _dc_replace
    from . import aod_mask as _aod_mask
    from . import preview as _preview

    mask = _aod_burn_in_mask(device.width, device.height, device.shape)
    phases = range(4) if resolved.face.aod_mask else (None,)
    best: tuple[float, float, int, tuple[int, int, int], int | None] | None = None
    for sample_time in AOD_BURN_IN_SAMPLE_TIMES:
        image = _preview.render(resolved, _aod_burn_in_options(sample_time))
        for phase in phases:
            scored = _aod_mask.apply(image, phase) if phase is not None else image
            lit_fraction, luminance_fraction, lit_pixels, _ = _aod_burn_in_measure(scored, mask)
            if best is None or max(lit_fraction, luminance_fraction) > max(best[0], best[1]):
                best = (lit_fraction, luminance_fraction, lit_pixels, sample_time, phase)
    lit_fraction, luminance_fraction, total_lit_pixels, worst_time, worst_phase = best
    total_lit_pixels = max(total_lit_pixels, 1)  # guard the (all-black) division below

    solo_options = _aod_burn_in_options(worst_time)
    contributions = []
    for placed in shown:
        solo_image = _preview.render(_dc_replace(resolved, items=[placed]), solo_options)
        if worst_phase is not None:
            solo_image = _aod_mask.apply(solo_image, worst_phase)
        _, _, solo_lit_pixels, _ = _aod_burn_in_measure(solo_image, mask)
        contributions.append((placed, solo_lit_pixels))
    contributions.sort(key=lambda pair: pair[1], reverse=True)
    top_line = ", ".join(
        f"{placed.id} ({100 * count / total_lit_pixels:.1f}%)"
        for placed, count in contributions[:_AOD_BURN_IN_TOP_N]
    )
    anchor = contributions[0][0]

    hh, mm, _ = worst_time
    masked = ""
    if worst_phase is not None:
        dx, dy = _aod_mask.offset(worst_phase)
        masked = f"with the pixel mask (phase {worst_phase}, dx={dx} dy={dy}), "
    message = (
        f"{device.id}: {masked}the AOD frame lights {lit_fraction * 100:.1f}% of pixels and "
        f"{luminance_fraction * 100:.1f}% of luminance at {hh:02d}:{mm:02d} (Garmin's 10% "
        f"rule, research 11 §1.2) -- top contributor: {top_line}"
    )
    notes = [
        f"worst of {len(AOD_BURN_IN_SAMPLE_TIMES)} sampled clock times "
        + ", ".join(f"{h:02d}:{m:02d}" for h, m, _ in AOD_BURN_IN_SAMPLE_TIMES)
        + (" x 4 mask phases" if worst_phase is not None else "")
        + ", full battery, wfb.preview.SAMPLE's other defaults unchanged -- not every "
          "possible time/data value",
        "lit: any pixel rendering other than pure black (research 11 §1.1); luminance: mean "
        "relative luminance (Color.relative_luminance, Rec. 709 primaries over sRGB-decoded "
        "channels) as a fraction of full white -- Garmin's own integral is unpublished "
        "(research 11 §5)",
        "checked against both AMOLED generations' 10% rules at once (original Venu: lit-pixel "
        "share; Venu 2+: luminance share), since the device files do not say which generation "
        "a target is",
        (
            "the moving pixel mask (aod: {mask: ...}, on by default, plan 16) guarantees no "
            "pixel is lit two consecutive minutes, so the 3-minute static-pixel rule holds by "
            "construction -- this still cannot see any minute or data value but the sampled "
            "ones (`wfb preview --heatmap` approximates that) -- docs/limitations.md"
            if worst_phase is not None else
            "cannot see the 3-minute static-pixel rule or any minute but the sampled ones "
            "(`wfb preview --heatmap` approximates both) -- docs/limitations.md"
        ),
        f"share is each element's own lit-pixel count against the full frame's "
        f"{total_lit_pixels:,} lit pixels at {hh:02d}:{mm:02d} -- overlapping elements' shares "
        f"can sum past 100%",
    ]
    over = max(lit_fraction, luminance_fraction) > AOD_BURN_IN_THRESHOLD
    if over:
        notes += [
            "over Garmin's 10% rule risks the system switching always-on off for this "
            "app entirely (research 11 §1.2)",
            "lighten the top contributor(s) -- hide, thin, or dim them further in 'aod:' -- "
            "or accept it with lint: {allow: [aod-burn-in], reason: \"...\"} on the "
            "element named above",
        ]
    _emit(bag, anchor, Diagnostic(
        Severity.ERROR if over else Severity.NOTE, "aod-burn-in", message,
        anchor.element.span, notes=notes,
        confidence=("estimate -- rasterised from a chosen worst-case sample frame, not the "
                    "simulator's own Screen Heat Map (root CLAUDE.md §3, unreachable here), "
                    "which is authoritative; the luminance formula is this compiler's own "
                    "choice, since Garmin's is unpublished"),
    ))


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

    Resolved against the device's **own** ``api.debug.xml`` (ADR 0008 check
    2), never an API level: `onPress` is documented since 4.2.0, and its
    sibling `onTap` since 5.1.0 yet is missing on `fr955` at 5.2.0
    (constraint 6).

    Where holds are delivered, two targets whose boxes overlap (and that can
    be on screen together) are reported against the later one: regions are
    tested in draw order and the first match wins.
    """
    held = [p for p in resolved.items if p.element.on_hold is not None]
    if not held:
        return
    device = resolved.device
    available = _probe_symbols(bag, device, "hold-unsupported", "touch support",
                               lambda: device.has_symbol(_HOLD_SYMBOL))
    if available is None:
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

    for index, second in enumerate(held):
        for first in held[:index]:
            if never_together(first.element, second.element):
                continue  # different layouts: a touch can never land on both
            if not _intersects(first.box, second.box):
                continue
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


# -- api gating ---------------------------------------------------------------


def check_api_gated(resolved: ResolvedFace, bag: Bag) -> None:
    """Does *this* device actually have what this design's bindings need?

    A target that lacks a module or field a binding reads gets a runtime
    `has`-guard in the one shared view (`wfb.availability.compute_guards`)
    and the binding *reads as absent* there -- the `when_absent` contract
    every nullable source already has (constraint 8).  This check is the
    human-facing half: *which* binding degrades on *which* device, and why
    (`wfb/availability.py`, `docs/research/probes/api-gating/README.md`).

    Six cases, all `api-gated` (WARNING, suppressible) except the fifth:

    1. **A catalogue read** the device's module/field table lacks
       (`wfb.availability.source_unavailable`) -- every `complication.*`
       read's `Toybox.Complications` gate included.
    2. **A complication *type* newer than the device's ConnectIQ ceiling**
       (`ComplicationType.since` vs `Device.api_level`): the type constants
       never appear in `api.debug.xml`, so a level compare is the only test.
       Only on a device that has `Toybox.Complications` -- otherwise case
       1/3/4 already names the more fundamental cause.
    3. **`on_hold:` on a device with no `Toybox.Complications`** -- the
       guarded `Complications.exitTo` is a silent no-op.  Skipped when the
       device also lacks `onPress` (checked directly, not assumed):
       `hold-unsupported` already says the hold never fires.
    4. **A `complication_slot` on a device with no `Toybox.Complications`**
       -- it shows its absent state forever, `default:` included (read
       through `WfbComplications.valueOf`).  Deliberately *not* deduped
       against `config-unsupported`: that one's "keeps its declared default"
       is false here, so both fire and `check_config_support` words its
       message accordingly.
    5. **A missing *function* symbol** (`Unavailable.kind == "function"`):
       codegen guards only modules and fields, so the call would run
       unguarded and crash.  A build ERROR under the distinct, deliberately
       unsuppressible code `api-gated-unguardable`
       (`tests/test_lint.py::test_api_gated_unguardable_function_is_an_error`).
    6. **A forecast `graph` on a device with no `Toybox.Weather`** -- its
       acquisition is not a catalogue read, so case 1 never sees it; the
       guarded call yields null there and the graph draws empty.
    """
    device = resolved.device
    probed = _probe_symbols(bag, device, "api-gated", "API-level gating",
                            lambda: (device.has_module("Complications"),
                                     device.has_symbol(_HOLD_SYMBOL)))
    if probed is None:
        return
    has_complications, has_onpress = probed

    # Case 2's candidates: (placed, complication name, span, kind).
    candidates: list[tuple] = []
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
            elif has_onpress:  # without onPress, hold-unsupported already says so
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

        if isinstance(element, Graph) and element.series_def is not None:
            module = series.ACQUISITION[element.series_def.acquisition].module
            gap = availability.module_unavailable(module.removeprefix("Toybox."), device)
            if gap is not None:
                _emit(bag, placed, Diagnostic(
                    Severity.WARNING,
                    "api-gated",
                    f"{placed.id}: series {element.series!r} needs module {module}, which "
                    f"{device.id} lacks, so the graph draws empty there",
                    element.span,
                    notes=[
                        f"confirmed against {device.id}'s own api.debug.xml -- not one of its "
                        "<dataEntry type=\"module\"> rows",
                        "the generated view guards the acquisition with 'Toybox has "
                        f":{module.removeprefix('Toybox.')}' (wfb.availability.compute_guards) "
                        "-- the build still succeeds; only this graph degrades on this device",
                    ],
                    confidence=f"exact -- {device.id}'s own api.debug.xml",
                ))

        if isinstance(element, ComplicationSlot):
            slot = resolved.face.config_data.get(element.slot)
            if slot is None:
                continue
            if has_complications:
                # `choices: any` has no list to check: only the default.
                choices = (slot.default,) if slot.allow_any else slot.choices
                for name in choices:
                    if complications.get(name) is not None:
                        candidates.append((placed, name, element.span, "slot"))
            else:
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
    :func:`check_api_gated`."""
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
    after the device's own ConnectIQ ceiling."""
    if not candidates:
        return

    device = resolved.device
    device_level = device.api_level
    if device_level == "0.0.0":
        # `Device.api_level`'s sentinel for a `compiler.json` with no
        # version: "unknown", not "supports nothing".
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
        _emit(bag, placed, Diagnostic(
            Severity.WARNING, "api-gated",
            f"{placed.id}: {_since_subject(placed, name, kind)} needs ConnectIQ "
            f"{ctype.since}, but {device.id} tops out at {device_level}",
            span,
            notes=list(_SINCE_NOTES[kind]),
            confidence=(
                f"exact -- {name!r}'s since ({ctype.since}, Toybox/Complications.html) "
                f"vs {device.id}'s api_level ({device_level}, compiler.json)"
            ),
        ))


def _since_subject(placed, name: str, kind: str) -> str:
    """What :func:`_check_complication_since` names as needing the newer level."""
    if kind == "hold":
        return f"holding to launch {name!r}"
    if kind == "slot":
        return f"slot config.data.{placed.element.slot}'s 'complication.{name}'"
    return f"'complication.{name}'"


_READS_AS_ABSENT_NOTE = (
    "Complications.getComplication returns null for a type the device "
    "does not support -- the same 'absence is normal' contract every "
    "other nullable source already has, so this reads as absent rather "
    "than crashing"
)

#: :func:`_check_complication_since`'s notes, per binding kind.
_SINCE_NOTES = {
    "hold": (
        "Complications.subscribeToUpdates returning false or throwing "
        "ComplicationNotFoundException is already caught uniformly by "
        "WfbComplications.mc's subscribe() -- the hold simply becomes a "
        "no-op on this device, not a crash",
        "pick a launch target with a lower 'since' for this device, or "
        "accept that the hold does nothing here",
    ),
    "slot": (
        _READS_AS_ABSENT_NOTE,
        "the wearer simply cannot pick this type on this device (or, if it "
        "is the slot's 'default:', the slot never shows it here); drop it "
        "from 'choices:', or accept that it is unreachable on this target",
    ),
    "read": (
        _READS_AS_ABSENT_NOTE,
        "drop this binding for this target, bind a lower-'since' source "
        "instead, or accept that it never updates here",
    ),
}


# -- overlap: the static hoist and outline interiors -------------------------


def _intersects(a: IntBox, b: IntBox) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def _fully_contains(outer: IntBox, inner: IntBox) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y
            and outer.right >= inner.right and outer.bottom >= inner.bottom)


def _may_overlap(a, b) -> bool:
    """Two placed elements that can be on screen together -- a shared mode,
    and not in different layouts (`ir.never_together`) -- with intersecting
    boxes.  Boxes, not ink: the drawn pixels may still never touch."""
    return (bool(set(a.element.modes) & set(b.element.modes))
            and not never_together(a.element, b.element)
            and _intersects(a.box, b.box))


def check_static_overlap(resolved: ResolvedFace, bag: Bag) -> None:
    """Where hoisting the static content to the front changed the picture.

    Static content is blitted first from an opaque, full-screen buffer, so
    the compiler moves it to the front (`wfb.ir.draw_sort_key`) rather than
    rejecting a design written in another order.  Two elements the hoist
    swapped trade which one is on top; wherever they may overlap
    (:func:`_may_overlap`) that is a visible change from what was written.
    Per device, since overlap depends on resolved geometry.

    A suppressible WARNING, reported against the element that *ends up* on
    top -- usually where the author wanted it anyway.
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
            if top is None or bottom is None or not _may_overlap(top, bottom):
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
    """True only when both expressions fold to the same build-time constant.

    A palette reference's constant *is* its resolved colour, so this covers
    "same palette role" and "equal literals" at once.  A `config.*` colour
    or a data-conditional has no constant and is never provably equal
    (plan 15: provably equal at build time, not "probably matches").
    """
    if a is None or b is None:
        return False
    if a.constant is None or b.constant is None:
        return False
    return a.constant == b.constant


def _outlined_interiors(element) -> list[tuple]:
    """Every `(outline, interior colour)` pair this element draws: a `text`
    element's own, or one per outlined `shape: text` part of a pattern
    (plan 15 §14 slice 2).  `[]` for any kind that cannot have one."""
    outline = getattr(element, "outline", None)
    if outline is not None:
        return [(outline, getattr(element, "color", None))]
    parts = getattr(element, "parts", None) or ()
    return [(part.outline, part.color) for part in parts if part.outline is not None]


def check_text_outline_interior(resolved: ResolvedFace, bag: Bag) -> None:
    """`outline:`'s interior pass paints over whatever is beneath it -- it
    does not reveal it (research 14 §6.4, plan 15 §3/§7).  Fires when an
    outlined element's (ring-grown) box may overlap (:func:`_may_overlap`)
    an **earlier-drawn** element's, unless that overlap is provably
    invisible: repainting a pixel in the colour it already is changes
    nothing, so an earlier element is exempt only when

    1. every interior colour the outlined element draws is the same
       build-time constant as the earlier element's colour
       (:func:`_same_provable_color`) -- all of a pattern's outlined parts,
       not just one;
    2. the earlier element is a solid backdrop shape
       (:func:`_is_solid_backdrop_shape`) -- nothing else promises to paint
       every pixel of its box; and
    3. its box **fully contains** the outlined box.  A partial cover proves
       nothing about the rest of the box (research 14's own example: a
       decorative ring crossing part of the text), so each earlier element
       is judged alone, and a partial one is always reported.

    Draw order is already final in `resolved.items`, so every earlier
    overlapping element is a candidate (unlike `static-overlap`, which only
    looks at hoisted pairs).  Box-level, and element-level for a pattern
    (D10).  A suppressible WARNING.
    """
    drawn = [p for p in resolved.items if p.kind != "group"]
    for index, later in enumerate(drawn):
        outlines = _outlined_interiors(later.element)
        if not outlines:
            continue
        under: list[str] = []
        for earlier in drawn[:index]:
            if not _may_overlap(later, earlier):
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
    over = share > GRAPHICS_POOL_BUDGET
    if over:
        notes.append("drop `static:` from the largest group, or accept it "
                     "with lint: {allow: [graphics-pool], reason: \"...\"}")
    _emit(bag, roots[0], Diagnostic(
        Severity.WARNING if over else Severity.NOTE, "graphics-pool", detail,
        roots[0].element.span, notes=notes,
        confidence=("estimate -- bytes per pixel for a BufferedBitmap is not published; "
                    "this uses the display's bitsPerPixel and ignores any per-surface "
                    "overhead"),
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


#: Checks that read the design alone, in the order :func:`run_design` runs them.
DESIGN_CHECKS = (
    check_permissions, check_lint_allow, check_duplicate_style, check_unreachable_layout,
)

#: Per-device checks, in the order :func:`run` runs them -- which is the
#: order their diagnostics reach the author, so it is fixed here rather than
#: derived from definition order.
DEVICE_CHECKS = (
    check_palette, check_antialias_palette, check_config_palette,
    check_color_scheme_palette, check_config_support, check_geometry,
    check_sub_pixel_length, check_text_fit, check_glyphs, check_contrast,
    check_partial_update_budget, check_hold_targets, check_dead_element,
    check_aod_unreachable, check_aod_empty, check_aod_burn_in, check_api_gated,
    check_graphics_pool, check_static_overlap, check_text_outline_interior,
    check_pattern_step,
)
