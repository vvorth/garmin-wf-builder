"""The device database, built from the installed Connect IQ device definitions.

Source of truth is ``~/.Garmin/ConnectIQ/Devices/<id>/``:

``compiler.json``          screen resolution, ``deviceFamily`` (which *is* the
                           resource-qualifier directory name -- ADR 0004 3b),
                           display type, alpha blending, per-app-type memory
                           limits, and the API level of each part number.
``simulator.json``         screen shape, ppi, graphics pool size, font table.
``<id>.api.debug.xml``     the device's own symbol table.  ADR 0008 check 2:
                           availability is resolved against this and never
                           against ``minApiLevel``, because fr955 runs API 5.2.0
                           and still lacks ``WatchFaceDelegate.onTap``.

The doc-scraped database under ``docs/research/data/`` is used only for the
per-device, per-language font pixel metrics, which the device files do not
carry.
"""

from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, cast

DEFAULT_DEVICE_ROOTS = (
    Path.home() / ".Garmin" / "ConnectIQ" / "Devices",
    Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Devices",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRAPED_FONTS = _REPO_ROOT / "docs" / "research" / "data" / "devices"


class DeviceError(Exception):
    pass


@lru_cache(maxsize=1)
def _documented_font_symbols() -> frozenset[str]:
    """The union of every ``FONT_*`` key across every scraped device's
    ``fonts.default.fixed`` table (``docs/research/data/devices/*.json``) --
    22 symbols (``FONT_XTINY`` ... ``FONT_NUMBER_THAI_HOT``, ``FONT_SYSTEM_*``,
    ``FONT_GLANCE*``, ``FONT_AUX1``/``FONT_AUX2``) at the time plan 17 was
    written. Gate 2 of :attr:`Device.system_fonts`' third source (plan 17
    §3): a ``simulator.json`` ``ww`` entry whose derived ``FONT_*`` symbol
    (:meth:`Device._symbol_for_simulator_name`) is *not* in this set is a
    scalable-table-only or simulator-extension name with no ``FONT_*``
    counterpart at all (``glanceFont`` -> ``FONT_GLANCE_FONT``, not the real
    ``FONT_GLANCE``) and is never derived. Computed once, lazily, at module
    level -- every scraped file is read only the first time any device asks.
    """
    vocabulary: set[str] = set()
    for path in _SCRAPED_FONTS.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fixed = data.get("fonts", {}).get("default", {}).get("fixed", {})
        vocabulary.update(fixed.keys())
    return frozenset(vocabulary)


#: One ``name="value"`` attribute of an ``api.debug.xml`` tag.
_XML_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')


#: The two sfnt version tags this project's minimal reader accepts --
#: TrueType outlines (``0x00010000``) and OpenType/CFF outlines (``OTTO``).
#: Anything else (a bitmap-only ``.cft``, a corrupt file, ``true``/``typ1``
#: Apple-only variants this project has no evidence any Garmin/registry file
#: uses) is rejected rather than guessed at.
_SFNT_VERSIONS = (b"\x00\x01\x00\x00", b"OTTO")


@lru_cache(maxsize=64)
def _sfnt_head_hhea(path: str) -> tuple[int, int, int] | None:
    """``(head.unitsPerEm, hhea.ascent, hhea.descent)`` read directly out of
    the sfnt table directory with :mod:`struct` -- **stdlib only**, so this
    module never needs Pillow/fontTools just to derive a fallback metric for
    a device the scraped reference has nothing for (plan 17 §3; the module
    docstring's own "never import Pillow/fontTools" rule stays true).

    Parses the offset table (``numTables`` at offset 4, big-endian
    ``uint16``), then the table directory (16-byte records from offset 12:
    ``tag``, ``checksum``, ``offset``, ``length``), then ``head`` at its own
    offset 18 (``unitsPerEm``, ``uint16``) and ``hhea`` at offsets 4/6
    (``ascender``/``descender``, signed ``int16``). Accepts the
    ``0x00010000`` and ``'OTTO'`` sfnt versions (:data:`_SFNT_VERSIONS`).
    Cached per resolved path -- a device's own ``ww`` set repeats the same
    handful of filenames across every ``FONT_*`` symbol it needs one for.

    **Never raises**: anything malformed, truncated, or missing either
    table returns ``None``, the same "derive what you can, never fail a
    build over an estimate" stance every other font fallback in this
    project takes (`wfb.fonts.fallback`'s own `_hhea`, which this mirrors
    for `wfb.devices`' own stdlib-only sibling case).
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    try:
        if len(data) < 12 or data[0:4] not in _SFNT_VERSIONS:
            return None
        num_tables = struct.unpack_from(">H", data, 4)[0]
        tables: dict[bytes, tuple[int, int]] = {}
        for i in range(num_tables):
            record = 12 + i * 16
            tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, record)
            tables[tag] = (offset, length)
        head = tables.get(b"head")
        hhea = tables.get(b"hhea")
        if head is None or hhea is None:
            return None
        units_per_em = struct.unpack_from(">H", data, head[0] + 18)[0]
        ascent, descent = struct.unpack_from(">hh", data, hhea[0] + 4)
        if units_per_em <= 0:
            return None
        return int(units_per_em), int(ascent), int(descent)
    except (struct.error, IndexError):
        return None


def _locate_garmin_outline_font(filename: str, fonts_root: str | os.PathLike[str] | None = None,
                                ) -> Path | None:
    """A local ``.ttf``/``.otf`` for ``filename`` under the user's own
    Garmin font root, or ``None`` -- **local files only**
    (`wfb.fonts.fetch_system.garmin_font_root`/`garmin_any_file`), never the
    registry's `ensure()` (no download from inside a device property). A
    located ``.cft`` doesn't qualify: it is Garmin's bitmap container, not a
    scalable outline this reader's `head`/`hhea` model applies to (plan 17
    §3 rule 4, plan 10 §2.3's own "no verified model for `.cft` height").

    ``fonts_root`` is the same ``--fonts DIR`` override every other font
    locator takes (:attr:`Device.fonts_root`, passed straight to
    `garmin_font_root`) -- without it, a device with no scraped page (the
    fenix 9 family) derived its metrics from whatever root happened to be
    installed, never the one a caller actually pointed `--fonts` at
    (plan 18 item 8).

    **Imported lazily**, not at module level: `wfb.fonts` (the package
    `wfb.fonts.fetch_system` lives in) has its own `__init__` that imports
    `wfb.fonts.fallback`, which imports `FontMetric` back out of *this*
    module -- importing `wfb.fonts` while `wfb.devices` is still mid-load
    would be a real cycle. Calling this only from inside
    :attr:`Device.system_fonts` (a `cached_property`, never touched until a
    caller already holds a fully-constructed `Device`) means `wfb.devices`
    has always finished loading by the time this import runs.
    """
    from .fonts import fetch_system

    root = fetch_system.garmin_font_root(fonts_root)
    if root is None:
        return None
    found = fetch_system.garmin_any_file(filename, root)
    if found is not None and found.suffix.lower() in (".ttf", ".otf"):
        return found
    return None


@dataclass(frozen=True)
class FontMetric:
    """A system font's real pixel metrics on one device, for one language
    (see :attr:`Device.system_fonts` for where each field comes from).

    ``size_px`` is the published *line height*, and stays authoritative for
    layout even when the fields below add precision, so a face that never
    gains better data does not shift. ``font`` is the installed
    ``simulator.json`` ``filename`` when there is one -- for a bitmap symbol
    the real ``FNT_``-prefixed ``.cft`` stem `wfb.fonts.fetch_system.locate`
    matches exactly.

    ``em_px`` (``size_pt * ppi / 72``), ``ascent_px`` and ``height_px`` are
    enrichments from a ``type: "ttf"`` ``ww`` entry, ``None`` for a bitmap
    entry or when the device file does not state them. A located ``.cft``'s
    own ``height``/``ascent`` override ``size_px`` for a bitmap symbol, but
    that is location-dependent and happens in `wfb.fonts.fallback`, never
    here: this dataclass only holds what the device data states outright.
    Frozen and hashable, so it keys `fallback.system_face`'s cache.
    """

    symbol: str
    face: str
    font: str
    size_px: int
    em_px: float | None = None
    ascent_px: int | None = None
    height_px: int | None = None


@dataclass
class Device:
    id: str
    root: Path
    compiler: dict[str, Any]
    simulator: dict[str, Any]
    #: The ``--fonts DIR`` override this device was built with -- ``None``
    #: for the ordinary search order (`wfb.fonts.fetch_system.
    #: garmin_font_root`'s own candidates). Set once, by
    #: `DeviceDatabase.discover`/`.get`, and read by :attr:`system_fonts`'
    #: third (derived) source and by every measuring/drawing caller that
    #: holds a `Device` (`wfb.layout`, `wfb.preview`) -- the one field that
    #: keeps "what a build measured a font with" and "what it drew that
    #: font with" from ever being two different roots (plan 18 item 8).
    fonts_root: str | None = None

    # -- geometry ---------------------------------------------------------

    @property
    def width(self) -> int:
        return int(self.compiler["resolution"]["width"])

    @property
    def height(self) -> int:
        return int(self.compiler["resolution"]["height"])

    @property
    def shape(self) -> str:
        """``round`` | ``rectangle`` | ``semi-round`` | ``semi-octagon``."""
        return cast(str, self.simulator.get("display", {}).get("shape", "unknown"))

    @property
    def minor_radius(self) -> float:
        """Half the smaller screen dimension -- what ``%r`` resolves against."""
        return min(self.width, self.height) / 2.0

    @property
    def device_family(self) -> str:
        """The resource-qualifier directory name, read rather than derived."""
        return cast(str, self.compiler["deviceFamily"])

    # -- display ----------------------------------------------------------

    @property
    def display_type(self) -> str:
        return cast(str, self.compiler.get("displayType", "unknown"))

    @property
    def is_amoled(self) -> bool:
        return self.display_type.lower() in ("amoled", "oled")

    @property
    def supports_partial_update(self) -> bool:
        """AMOLED forbids ``onPartialUpdate`` outright; MIP depends on it."""
        return not self.is_amoled

    @cached_property
    def _scraped(self) -> dict[str, Any]:
        """The SDK device-reference scrape, for facts the device files omit."""
        path = _SCRAPED_FONTS / f"{self.id}.json"
        if not path.exists():
            return {}
        return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))

    @property
    def display_colors(self) -> int | None:
        """Size of the displayable palette, *not* the framebuffer depth.

        ``bitsPerPixel`` is 8 on all three targets, but the panels display 64
        colours -- each channel must be 0x00/0x55/0xAA/0xFF or the firmware
        dithers.  Only the device-reference pages state this, so the value is
        ``None`` (and the palette lint degrades to "not checked") when the
        scrape is unavailable.
        """
        value = self._scraped.get("normalized", {}).get("display_colors")
        return int(value) if value else None

    @property
    def alpha_blending(self) -> bool:
        return bool(self.compiler.get("alphaBlendingSupport", False))

    @property
    def graphics_pool_bytes(self) -> int | None:
        """Separate from the watch-face limit -- see ADR 0006 5."""
        return self.simulator.get("graphicsResourcePoolSize")

    @property
    def bits_per_pixel(self) -> int | None:
        """The display's own pixel depth, from ``compiler.json``.

        8 on all three targets, with ``pixelFormat: ARGB2222``.  Used only to
        *estimate* what a full-screen ``BufferedBitmap`` costs in the graphics
        pool: the SDK nowhere says that a no-palette surface is allocated in the
        display's format, nor what per-surface overhead the pool adds, so the
        `graphics-pool` lint that consumes this labels itself an estimate
        (ADR 0008).  See `docs/research/probes/static-buffer/`.
        """
        value = self.compiler.get("bitsPerPixel")
        return int(value) if value else None

    def buffer_bytes(self, width: int | None = None, height: int | None = None) -> int | None:
        """Estimated pool cost of one offscreen buffer, default full-screen."""
        depth = self.bits_per_pixel
        if not depth:
            return None
        w = self.width if width is None else width
        h = self.height if height is None else height
        return (w * h * depth + 7) // 8

    # -- limits -----------------------------------------------------------

    @property
    def _watchface_app_type(self) -> dict[str, Any] | None:
        return next((e for e in self.compiler.get("appTypes", [])
                     if e.get("type") == "watchFace"), None)

    @property
    def watchface_memory_limit(self) -> int:
        entry = self._watchface_app_type
        if entry is None:
            raise DeviceError(f"{self.id} declares no watchFace app type")
        return int(entry["memoryLimit"])

    @property
    def supports_watchface(self) -> bool:
        return self._watchface_app_type is not None

    @property
    def api_level(self) -> str:
        """The highest Connect IQ version across the device's part numbers."""
        versions: list[str] = [
            pn.get("connectIQVersion")
            for pn in self.compiler.get("partNumbers", [])
            if pn.get("connectIQVersion")
        ]
        if not versions:
            return "0.0.0"
        return max(versions, key=version_key)

    @property
    def languages(self) -> list[str]:
        seen: list[str] = []
        for pn in self.compiler.get("partNumbers", []):
            for lang in pn.get("languages", []):
                code = lang.get("code") if isinstance(lang, dict) else lang
                if code and code not in seen:
                    seen.append(code)
        return seen

    # -- symbols ----------------------------------------------------------

    @cached_property
    def _api_debug_xml(self) -> str:
        """The raw text of the device's own ``<id>.api.debug.xml``, read once
        and shared by every :meth:`_tags` scan.
        """
        path = self.root / f"{self.id}.api.debug.xml"
        if not path.exists():
            raise DeviceError(f"{self.id}: missing {path.name}")
        return path.read_text(encoding="utf-8", errors="replace")

    def _tags(self, tag: str) -> list[dict[str, str]]:
        """The attributes of every ``<tag ...>`` in the symbol table, one dict
        per tag -- read by name, since attribute order in this XML is not
        guaranteed."""
        return [dict(_XML_ATTR.findall(m.group(0)))
                for m in re.finditer(rf"<{tag}\b[^>]*>", self._api_debug_xml)]

    @cached_property
    def _symbols(self) -> tuple[set[tuple[str, str]], dict[str, str]]:
        """``({(parent, name)}, {classId: fully_qualified_label})``."""
        functions = {
            (attrs["parent"], attrs["name"])
            for attrs in self._tags("functionEntry")
            if "parent" in attrs and "name" in attrs
        }
        scopes = {
            attrs["classId"]: attrs["label"]
            for attrs in self._tags("apiScopeEntry")
            if "classId" in attrs and "label" in attrs
        }
        return functions, scopes

    def has_symbol(self, qualified: str) -> bool:
        """Is ``Parent.name`` present on *this* device?

        ``qualified`` may be given short (``WatchFaceDelegate.onTap``) or fully
        (``Toybox.WatchUi.WatchFaceDelegate.onTap``); the parent is matched on
        its fully-qualified label so that ``InputDelegate.onTap`` cannot be
        mistaken for ``WatchFaceDelegate.onTap``.
        """
        functions, scopes = self._symbols
        parent, _, name = qualified.rpartition(".")
        if not parent:
            raise ValueError(f"expected Parent.name, got {qualified!r}")
        short_parent = parent.rsplit(".", 1)[-1]
        if (short_parent, name) not in functions:
            return False
        want = parent.replace(".", "_")
        label = scopes.get(short_parent)
        if label and "." in parent and not label.endswith(want):
            return False
        return True

    @cached_property
    def _modules(self) -> frozenset[str]:
        """Every ``symbolId`` the device's own ``<dataEntry type="module">``
        rows declare -- e.g. ``Complications``, ``Weather``.

        Used by :meth:`has_module`.
        """
        return frozenset(attrs["symbolId"] for attrs in self._tags("dataEntry")
                         if attrs.get("type") == "module" and "symbolId" in attrs)

    def has_module(self, name: str) -> bool:
        """Is the ``Toybox`` (or nested) module ``name`` present on this
        device -- e.g. ``"Complications"``, ``"Weather"``?

        ``name`` is the bare module symbol, not a dotted path: the device XML
        indexes a module by its own ``symbolId`` alone, with the parent given
        separately as ``parentId`` (unlike `has_symbol`'s ``Parent.name``
        pairs, `_modules` does not need the parent to disambiguate --
        Connect IQ has no two same-named modules at different nesting, unlike
        the class-name collisions `has_symbol` guards against). fenix6 and
        fr245 (this project's lowest-level installed devices, both below API
        4.2.0) both lack ``Complications`` entirely, which is the gap this
        exists to detect: a device missing the module fails at *runtime* on
        any reference to it, not at compile time (`monkeyc` checks the
        SDK-wide API -- CLAUDE.md constraint 6d), so this is what a runtime
        ``Toybox has :ModuleName`` guard has to be conditioned on at
        generation time.
        """
        return name in self._modules

    @cached_property
    def _fields(self) -> frozenset[str]:
        """Every bare ``symbol`` name the device's ``<symbolTable>`` marks
        ``field="true"`` -- e.g. ``stressScore``, ``floorsClimbed``.

        Used by :meth:`has_field`. **Exact for absence, approximate for
        presence**: the symbol table records only the bare field name, with
        no owning class -- so a name absent here is definitely absent from
        every class, but a name present here merely means *some* class on
        this device declares a field by that name, not necessarily the one
        `wfb.catalog` reads it off (`ActivityMonitor.Info.stressScore` and a
        hypothetical unrelated class's own `stressScore` field would be
        indistinguishable). Every catalogue field this project currently
        binds happens to have a name that is unique enough in practice
        (checked against the installed device set), so the approximation has
        not produced a false positive; a caller that needs certainty should
        also check the *reader* it comes off is available
        (`has_symbol`/`has_module`), which narrows the class independently.
        """
        return frozenset(attrs["symbol"] for attrs in self._tags("entry")
                         if attrs.get("field") == "true" and "symbol" in attrs)

    def has_field(self, name: str) -> bool:
        """Is the bare field ``name`` present on this device -- e.g.
        ``"stressScore"``, ``"floorsClimbed"``?

        See `_fields`' docstring for the exact-for-absence,
        approximate-for-presence caveat: this cannot tell two different
        classes' same-named fields apart, because the device's own
        ``<symbolTable>`` does not record which class a ``field="true"``
        entry belongs to.
        """
        return name in self._fields

    # -- fonts ------------------------------------------------------------

    #: The ``simulator.json`` `fontSet` this project measures against --
    #: worldwide/default, per plan 09 R2.1 (English-only scope, `docs/
    #: research/10-system-fonts.md` §1).
    _SIMULATOR_FONT_SET = "ww"

    #: Gate 1 of plan 11's four vector-font gates (`docs/research/
    #: 12-vector-fonts.md` §3): the three ``Toybox`` symbols a device needs
    #: before ``Graphics.getVectorFont`` -- and rotated/curved text through
    #: it -- can be used at all. Named here so a caller asks
    #: ``device.has_symbol(Device.VECTOR_FONT_SYMBOL)`` rather than
    #: retyping the string, and checks each independently: **verified**
    #: (2026-09-20) that all three move together on every installed device
    #: -- present on `fenix8solar47mm`, `fenix8solar51mm`, `fenix7pro` and
    #: `fr955`, absent on `fenix6`, `fenix6xpro`, `fr245` and `fr255` -- but
    #: nothing in the SDK promises that across the full 164-device fleet,
    #: so gates 2/3 (:attr:`scalable_faces`) are never inferred from these
    #: alone.
    VECTOR_FONT_SYMBOL = "Graphics.getVectorFont"
    DRAW_ANGLED_TEXT_SYMBOL = "Dc.drawAngledText"
    DRAW_RADIAL_TEXT_SYMBOL = "Dc.drawRadialText"

    #: `System.DeviceSettings`' own burn-in flag (plan 14 D1) -- the runtime
    #: half of "is this a burn-in device", checked with `has_field` per
    #: device the same way any other bare field is (never by API level,
    #: CLAUDE.md constraint 6). Present on all four devices research 11 §2
    #: checked (two AMOLED, two MIP), but that is exactly why it is checked
    #: here rather than assumed: a device this project has not looked at
    #: could lack it.
    BURN_IN_FIELD = "requiresBurnInProtection"

    #: `System.getDisplayMode` (plan 14 slice 6, research 11 §6 F/§2) -- the
    #: FAQ's own ladder's second rung, checked with `has_symbol` per device
    #: (never by API level): a device can report `requiresBurnInProtection`
    #: (the original-Venu rule) without this newer (5.0.0) method existing
    #: at all -- the FAQ's own example code guards it with
    #: `System has :getDisplayMode` for exactly that reason. Verified
    #: present, moving together with `System.DISPLAY_MODE_*` and
    #: `Application.AppBase.onDisplayModeChanged`, on `fenix847mm`/
    #: `fenix947mm`; verified absent, all three together, on
    #: `fenix8solar47mm`/`fenix8solar51mm`/`fr955` (research 11 §2's table,
    #: re-checked directly against each installed device's own
    #: `has_symbol`).
    DISPLAY_MODE_SYMBOL = "System.getDisplayMode"

    @staticmethod
    def _symbol_for_simulator_name(name: str) -> str:
        """``simulator.json`` ``name`` (``"xtiny"``, ``"numberHot"``,
        ``"systemXtiny"``, ...) -> the ``FONT_*`` symbol it corresponds to
        (plan 09 §4 R2.1's table: ``FONT_XTINY``, ``FONT_NUMBER_HOT``,
        ``FONT_SYSTEM_XTINY``). A plain camelCase-to-`SCREAMING_SNAKE_CASE`
        split, prefixed with ``FONT_`` -- every observed name already reads
        as a `FONT_*` symbol's own lowerCamelCase spelling, with no separate
        handling needed for the `system*` names (unlike `tools/research/
        font_metric_check.py`'s own splitter, which deliberately collapses
        `systemXtiny` onto plain `FONT_XTINY` for a from-scratch metrics
        cross-check -- a different job from naming the real symbol here).
        """
        return "FONT_" + re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()

    @cached_property
    def _ww_font_entries(self) -> tuple[dict[str, Any], ...]:
        """Every font entry in this device's ``simulator.json`` ``ww`` font
        set, in file order -- empty for a hand-built test `Device` with none."""
        return tuple(
            entry
            for block in self.simulator.get("fonts", [])
            if block.get("fontSet") == self._SIMULATOR_FONT_SET
            for entry in block.get("fonts", [])
        )

    @cached_property
    def _simulator_ww_fonts(self) -> dict[str, dict[str, Any]]:
        """``FONT_*`` symbol -> this device's own ``simulator.json`` ``ww``
        font entry (the first, when several derive the same symbol)."""
        out: dict[str, dict[str, Any]] = {}
        for entry in self._ww_font_entries:
            name = entry.get("name")
            if name:
                out.setdefault(self._symbol_for_simulator_name(name), entry)
        return out

    @cached_property
    def scalable_faces(self) -> tuple[str, ...]:
        """Gates 2 and 3 of plan 11's four vector-font gates (`docs/
        research/12-vector-fonts.md` §3.1): the device-resident face names
        this device publishes to ``Graphics.getVectorFont``.

        The ``type: "system_ttf"`` entries of :attr:`_ww_font_entries` (the
        scalable catalogue), not ``type: "ttf"`` (fixed, ``FONT_*``-only
        system fonts, no ``:face`` string of their own). An entry's own
        ``name`` field *is* the ``:face`` string an author's ``face:``
        names -- there is no separate id to translate through, unlike
        :meth:`_symbol_for_simulator_name`'s ``FONT_*`` derivation for the
        bitmap set. Ordered and de-duplicated in the device file's own
        declaration order, so a ``face: [A, B]`` list's "first one this
        device actually publishes" resolution is deterministic. Empty for
        a device with no scalable faces at all -- 92 of the 136
        watch-face-capable devices, per the research doc's own count --
        which is the ordinary, expected case, not a degraded one.
        """
        return tuple(dict.fromkeys(
            entry["name"] for entry in self._ww_font_entries
            if entry.get("type") == "system_ttf" and entry.get("name")
        ))

    @cached_property
    def scalable_face_files(self) -> dict[str, str]:
        """:attr:`scalable_faces`' own ``name`` -> the same ``system_ttf``
        entry's ``filename`` (plan 11 §4: measuring a resolved vector face
        the same way a system font's real file is already located).
        ``name`` is the ``:face`` string an author writes and this device
        publishes (``"RobotoCondensedBold"``); ``filename`` is the on-disk
        stem the real TTF is named after everywhere it can be found --
        ``vendor/fonts/<filename>.ttf`` (`wfb.fonts.fetch_system.
        garmin_font_root`) and `wfb/fonts/registry.json`'s own ``names``
        table both key on it, never on ``name`` (confirmed against an
        installed device's own ``simulator.json``: a ``RobotoCondensedBold``
        entry's ``filename`` is ``RobotoCondensed-Bold``). Kept as its own
        mapping rather than folded into :attr:`scalable_faces`'s tuple, so a
        caller that only needs the ordered face names is not forced to
        thread a second value through everywhere that already works with a
        bare `str`. Missing an entry only when a ``system_ttf`` block
        somehow states a ``name`` with no ``filename`` at all -- not
        observed on any installed device, but a caller
        (:meth:`wfb.layout.Resolver._vector_font_metric`) falls back to the
        face name itself in that case rather than raising.
        """
        out: dict[str, str] = {}
        for entry in self._ww_font_entries:
            if entry.get("type") == "system_ttf" and entry.get("name") and entry.get("filename"):
                out.setdefault(entry["name"], entry["filename"])
        return out

    @cached_property
    def system_fonts(self) -> dict[str, FontMetric]:
        """``FONT_*`` pixel metrics for the default language, from three
        sources in priority order (see :class:`FontMetric` for the fields):

        1. The SDK's scraped device reference (``face``/``font``/``size_px``,
           ADR 0004 5), enriched from the installed ``simulator.json`` ``ww``
           entry: its ``filename`` always replaces ``font``, and a ``type:
           "ttf"`` entry adds ``em_px``/``ascent_px``/``height_px``
           (:func:`_ttf_enrichment`; `docs/research/10-system-fonts.md` §3).
        2. A ``ww`` ``ttf`` entry for a symbol the scrape lacks
           (``FONT_SYSTEM_*``, mostly), only when it states ``height``
           outright -- there is no other line height to use.
        3. For a device with no scrape at all (the fenix 9 family): a
           documented ``FONT_*`` symbol (:func:`_documented_font_symbols`)
           whose ``ww`` ``ttf`` entry's file is a real ``.ttf``/``.otf`` under
           :attr:`fonts_root` (:func:`_locate_garmin_outline_font`, never a
           download or a ``.cft``) gets ``size_px = round(em_px * (ascent -
           descent) / unitsPerEm)`` from that file's own tables
           (:func:`_sfnt_head_hhea`). No scraped device gains a symbol here.

        A symbol none of them covers is absent, and text-overflow linting
        degrades to "not checked" rather than a confident wrong answer.
        Whatever is still missing for a located TTF (the em, the ascent) is
        derived in `wfb.fonts.fallback`, which may import fontTools; this
        module stays stdlib-only.
        """
        fixed = self._scraped.get("fonts", {}).get("default", {}).get("fixed", {})
        ppi = self.simulator.get("ppi")
        sim_fonts = self._simulator_ww_fonts
        metrics: dict[str, FontMetric] = {}

        for symbol, entry in fixed.items():
            if "size_px" not in entry:
                continue
            font = entry.get("font", "")
            enrichment: tuple[float | None, int | None, int | None] = (None, None, None)
            sim_entry = sim_fonts.get(symbol)
            if sim_entry is not None:
                # The installed device's own filename always replaces the
                # scraped `font`, TTF or bitmap alike: it is the more precise
                # of the two, and for a bitmap symbol it is the exact `.cft`
                # file stem (`FNT_...`), which the scraped column never
                # carries the prefix for. A bitmap entry's `.cft` carries its
                # own height/ascent, read by `wfb.fonts.fallback`.
                font = sim_entry.get("filename", font)
                if sim_entry.get("type") == "ttf":
                    enrichment = _ttf_enrichment(sim_entry, ppi)
            metrics[symbol] = FontMetric(symbol, entry.get("face", ""), font,
                                         int(entry["size_px"]), *enrichment)

        for symbol, sim_entry in sim_fonts.items():
            if symbol in metrics or sim_entry.get("type") != "ttf":
                continue
            em_px, ascent_px, height_px = _ttf_enrichment(sim_entry, ppi)
            if height_px is None:
                continue
            metrics[symbol] = FontMetric(
                symbol, "", sim_entry.get("filename", ""), height_px,
                em_px, ascent_px, height_px,
            )

        if ppi:
            vocabulary = _documented_font_symbols()
            for symbol, sim_entry in sim_fonts.items():
                if symbol in metrics or sim_entry.get("type") != "ttf":
                    continue
                if symbol not in vocabulary or "size" not in sim_entry:
                    continue
                filename = sim_entry.get("filename")
                if not filename:
                    continue
                path = _locate_garmin_outline_font(filename, self.fonts_root)
                if path is None:
                    continue
                sfnt = _sfnt_head_hhea(str(path))
                if sfnt is None:
                    continue
                units_per_em, ascent, descent = sfnt
                em_px, _, _ = _ttf_enrichment(sim_entry, ppi)
                assert em_px is not None  # `ppi` and `size` are both checked above
                size_px = round(em_px * (ascent - descent) / units_per_em)
                metrics[symbol] = FontMetric(symbol, "", filename, size_px, em_px, None, size_px)
        return metrics

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Device {self.id} {self.width}x{self.height} {self.shape} {self.display_type}>"


def _ttf_enrichment(sim_entry: dict[str, Any],
                    ppi: float | None) -> tuple[float | None, int | None, int | None]:
    """``(em_px, ascent_px, height_px)`` from one ``simulator.json`` ``type:
    "ttf"`` font entry: ``em_px = size * ppi / 72`` when both are known, the
    other two only where the device file states them outright."""
    em_px = sim_entry["size"] * ppi / 72 if ppi and "size" in sim_entry else None
    ascent_px = int(sim_entry["ascent"]) if "ascent" in sim_entry else None
    height = sim_entry.get("height")
    height_px = int(height) if height is not None else None
    return em_px, ascent_px, height_px


def version_key(v: str) -> tuple[int, ...]:
    """``"5.2.0"`` -> ``(5, 2, 0)``, so two dotted version strings sort right.

    Public so a per-device gating check outside this module --
    ``wfb.lint``'s complication-availability check -- can compare a
    ``wfb.complications.ComplicationType.since`` string against
    :attr:`Device.api_level` without re-deriving this.
    """
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


@dataclass
class DeviceDatabase:
    root: Path
    #: The ``--fonts DIR`` override every `Device` this database creates is
    #: stamped with (:attr:`Device.fonts_root`) -- one root for the whole
    #: build, so a device's measured metrics and its drawn glyphs can never
    #: come from two different places (plan 18 item 8).
    fonts_root: str | None = None
    _cache: dict[str, Device] = field(default_factory=dict, repr=False)

    @classmethod
    def discover(cls, override: str | os.PathLike[str] | None = None, *,
                fonts_root: str | os.PathLike[str] | None = None) -> "DeviceDatabase":
        candidates = []
        if override:
            candidates.append(Path(override))
        env = os.environ.get("WFB_DEVICES")
        if env:
            candidates.append(Path(env))
        candidates.extend(DEFAULT_DEVICE_ROOTS)
        for path in candidates:
            if path.is_dir() and any(path.iterdir()):
                return cls(path, fonts_root=None if fonts_root is None else os.fspath(fonts_root))
        raise DeviceError(
            "no Connect IQ device definitions found.  They cannot be downloaded "
            "(api.gcs.garmin.com returns HTTP 401); run ./tools/setup-env.sh, "
            "or set WFB_DEVICES to a directory containing them."
        )

    def ids(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if (p / "compiler.json").exists())

    def get(self, device_id: str) -> Device:
        if device_id in self._cache:
            return self._cache[device_id]
        root = self.root / device_id
        if not (root / "compiler.json").exists():
            known = ", ".join(self.ids())
            raise DeviceError(f"unknown device {device_id!r}.  Installed: {known}")
        device = Device(
            id=device_id,
            root=root,
            compiler=json.loads((root / "compiler.json").read_text(encoding="utf-8")),
            simulator=json.loads((root / "simulator.json").read_text(encoding="utf-8")),
            fonts_root=self.fonts_root,
        )
        self._cache[device_id] = device
        return device
