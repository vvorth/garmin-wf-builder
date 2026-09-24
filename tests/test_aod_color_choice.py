"""`wfb.ir.aod_color_choice` (plan 19 A1): the one decision behind an
AOD-shown colour -- override, dim, or the awake colour unchanged -- that
`wfb.preview._aod_color` and `wfb.emit.monkeyc.common.AodStyle.color`/
`.part_color` both now read instead of each re-deriving it.
"""

from __future__ import annotations

from wfb.ir import AodOverride, aod_color_choice


def test_override_wins_regardless_of_dim():
    """An element's own `aod: {color: ...}` wins whether or not the face
    also has `aod: {dim: ...}` -- dimming never applies on top of an
    explicit override. Must fail against an implementation that dims an
    override colour when `dim_set` is true."""
    override = object()
    aod = AodOverride(color=override)
    assert aod_color_choice(aod, "color", dim_set=True) == ("override", override)
    assert aod_color_choice(aod, "color", dim_set=False) == ("override", override)


def test_dim_when_no_override_and_dim_set():
    """No override for this key, but the face has `aod: {dim: ...}`: the
    awake colour is dimmed. Must fail against an implementation that
    returns `"awake"` whenever no override is set, ignoring `dim_set`."""
    assert aod_color_choice(AodOverride(), "color", dim_set=True) == ("dim", None)


def test_awake_when_no_override_and_no_dim():
    """Neither an override nor `aod: {dim: ...}`: the awake colour is used
    unchanged. Must fail against an implementation that always dims once
    `aod` is not `None`."""
    assert aod_color_choice(AodOverride(), "color", dim_set=False) == ("awake", None)


def test_aod_none_falls_through_to_dim_or_awake():
    """`aod=None` (a `None` resolved override -- the element's own
    ``element.aod`` is `None`) has no override to read, so the outcome
    follows `dim_set` exactly as an `AodOverride()` with every field unset
    does. Must fail against an implementation that crashes on `None`, or
    that treats it differently from an override with nothing set."""
    assert aod_color_choice(None, "color", dim_set=True) == ("dim", None)
    assert aod_color_choice(None, "color", dim_set=False) == ("awake", None)


def test_reads_the_key_named_role():
    """`track_color`/`icon_color` are read independently of `color` -- an
    override on one key must not leak into another. Must fail against an
    implementation that always reads `AodOverride.color` regardless of
    `key`."""
    aod = AodOverride(track_color=object())
    assert aod_color_choice(aod, "color", dim_set=False) == ("awake", None)
    choice, override = aod_color_choice(aod, "track_color", dim_set=False)
    assert choice == "override" and override is aod.track_color
