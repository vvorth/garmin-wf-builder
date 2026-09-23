"""The device database, and the symbol resolution ADR 0008 check 2 depends on."""

import pytest


def test_targets_are_all_present(db):
    for device_id in ("fenix8solar47mm", "fenix8solar51mm", "fr955"):
        if device_id in db.ids():
            assert db.get(device_id).supports_watchface


def test_device_family_is_read_not_derived(db):
    """Two 260x260 devices share a family; the 280x280 one does not."""
    assert db.get("fenix8solar47mm").device_family == "round-260x260"
    assert db.get("fr955").device_family == "round-260x260"
    assert db.get("fenix8solar51mm").device_family == "round-280x280"


def test_watchface_limit_is_a_sixth_of_the_watch_app_limit(device):
    assert device.watchface_memory_limit == 131072


def test_display_colours_are_the_panel_not_the_framebuffer(device):
    """bitsPerPixel is 8, but the panel shows 64 colours -- the lint needs the panel."""
    assert device.bits_per_pixel == 8
    assert device.display_colors == 64


def test_alpha_blending_is_off_on_the_targets(device):
    assert device.alpha_blending is False


def test_mip_supports_partial_update(device):
    assert device.display_type == "mip"
    assert device.is_amoled is False
    assert device.supports_partial_update is True


def test_graphics_pool_is_separate_from_the_app_limit(device):
    """1 MB, distinct from the 128 KB watch-face budget."""
    assert device.graphics_pool_bytes == 1048576


def test_api_level_alone_does_not_decide_availability(db):
    """fr955 runs API 5.2.0 -- above onTap's documented 5.1.0 -- and still lacks it.

    This is the finding that forces per-device symbol tables (ADR 0008 check 2).
    """
    if "fr955" not in db.ids():
        pytest.skip("fr955 not installed")
    fr955 = db.get("fr955")
    fenix = db.get("fenix8solar47mm")
    assert fr955.api_level >= "5.1.0"
    assert fenix.has_symbol("Toybox.WatchUi.WatchFaceDelegate.onTap") is True
    assert fr955.has_symbol("Toybox.WatchUi.WatchFaceDelegate.onTap") is False


def test_a_bare_grep_would_be_fooled_by_the_wrong_parent(db):
    """fr955 *does* have InputDelegate.onTap -- a different symbol entirely."""
    if "fr955" not in db.ids():
        pytest.skip("fr955 not installed")
    assert db.get("fr955").has_symbol("Toybox.WatchUi.InputDelegate.onTap") is True


def test_unknown_symbol_is_false_not_an_error(device):
    assert device.has_symbol("Toybox.WatchUi.WatchFaceDelegate.onNothing") is False


# -- has_module / has_field (wfb/availability.py's foundation) ---------------


def test_fenix6_lacks_the_complications_module_and_field(db):
    """fenix6 is ConnectIQ 3.4.5, below Complications' 4.2.0 floor -- and,
    unlike a missing *function*, it lacks the module symbol entirely."""
    if "fenix6" not in db.ids():
        pytest.skip("fenix6 not installed")
    fenix6 = db.get("fenix6")
    assert fenix6.has_module("Complications") is False
    assert fenix6.has_field("stressScore") is False


def test_fr245_lacks_floors_climbed_but_has_the_complications_gap_too(db):
    if "fr245" not in db.ids():
        pytest.skip("fr245 not installed")
    fr245 = db.get("fr245")
    assert fr245.has_field("floorsClimbed") is False
    assert fr245.has_module("Complications") is False


def test_fenix8_has_every_module_and_field_the_lower_devices_lack(db):
    f8 = db.get("fenix8solar47mm")
    assert f8.has_module("Complications") is True
    assert f8.has_field("stressScore") is True
    assert f8.has_field("floorsClimbed") is True


def test_every_installed_device_has_activity_monitor_and_battery(db):
    """A module/field every installed device genuinely shares -- the negative
    control: `has_module`/`has_field` must not report every gap, only real
    ones.

    `Weather`/`solarIntensity` used to be this negative control, but they are
    not actually universal: `fenix5`/`fenix5x` (ConnectIQ 3.1.6, installed
    2026-09-23 alongside `fenix847mm` -- `tests/CLAUDE.md`) lack `Toybox.
    Weather` entirely and have no `solarIntensity` field, which is a real
    device gap, not a bug in `has_module`/`has_field` (see
    `test_fenix5_lacks_weather_and_solar_intensity` below for the
    corresponding positive gap). `ActivityMonitor` (module) and `battery`
    (`System.Stats.battery`, the same field `wfb.catalog`'s `system.battery`
    reads, API 1.0.0) are confirmed present on every one of the 20 installed
    devices as of 2026-09-23, including `fenix5`/`fenix5x`.
    """
    for device_id in db.ids():
        device = db.get(device_id)
        assert device.has_module("ActivityMonitor") is True, device_id
        assert device.has_field("battery") is True, device_id


def test_fenix5_lacks_weather_and_solar_intensity(db):
    """The positive gap `test_every_installed_device_has_activity_monitor_
    and_battery`'s docstring refers to: `fenix5` (ConnectIQ 3.1.6) has
    neither `Toybox.Weather` nor a `solarIntensity` field, confirmed against
    its own `api.debug.xml`. This is what makes `weather.*`-bound designs
    targeting `fenix5` a build error (`api-gated-unguardable`,
    `wfb.availability`/`wfb.lint`) rather than a silent guard -- there is no
    module guard for an individual missing function, only for a missing
    module/field."""
    if "fenix5" not in db.ids():
        pytest.skip("fenix5 not installed")
    fenix5 = db.get("fenix5")
    assert fenix5.has_module("Weather") is False
    assert fenix5.has_field("solarIntensity") is False


def test_unknown_module_and_field_are_false_not_errors(device):
    assert device.has_module("NoSuchToyboxModule") is False
    assert device.has_field("noSuchField") is False


def test_unknown_device_names_the_installed_ones(db):
    from wfb.devices import DeviceError

    with pytest.raises(DeviceError) as excinfo:
        db.get("nosuchwatch")
    assert "fenix8solar47mm" in str(excinfo.value)


def test_system_font_metrics_are_per_device(db):
    small = db.get("fenix8solar47mm").system_fonts.get("FONT_NUMBER_HOT")
    large = db.get("fenix8solar51mm").system_fonts.get("FONT_NUMBER_HOT")
    if small and large:
        assert large.size_px > small.size_px


def test_default_font_metrics_are_the_english_language_block(repo_root):
    """Regression test for a real bug: `tools/research/extract_device_db.py`'s
    "Languages" paragraph used to be matched only as `<strong>...</strong>`,
    but the actual doc HTML wraps it in `<em>` -- so the regex matched zero
    blocks, every device's per-language font tables collided onto one
    "default" key, and whichever language table was parsed *last* (often Thai
    or Korean, not English) silently won. Confirmed against the real SDK doc:
    `fenix8solar47mm`'s `FONT_XTINY` is 21px (Roboto Condensed) for English,
    but the bug reported it as 28px (Pridi, the Thai block).

    This checks the invariant directly against the JSON rather than hardcoding
    a pixel number, so it does not rot if Garmin changes a device's font in a
    future SDK release -- what must stay true is that "default" is *the block
    whose language list contains "eng"*, not merely *some* block.
    """
    import json

    for device_id in ("fenix8solar47mm", "fenix8solar51mm", "fr955"):
        path = repo_root / "docs" / "research" / "data" / "devices" / f"{device_id}.json"
        if not path.exists():
            pytest.skip(f"no scraped data for {device_id}")
        fonts = json.loads(path.read_text()).get("fonts", {})
        if "default" not in fonts:
            pytest.skip(f"{device_id} has no default font table")
        english_keys = [k for k in fonts if "eng" in k.split(",")]
        assert english_keys, f"{device_id}: no language block lists 'eng' at all"
        assert fonts["default"] == fonts[english_keys[0]], (
            f"{device_id}: 'default' font table does not match the English "
            f"language block ({english_keys[0]!r})"
        )
