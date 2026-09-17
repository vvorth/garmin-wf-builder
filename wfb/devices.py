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
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

DEFAULT_DEVICE_ROOTS = (
    Path.home() / ".Garmin" / "ConnectIQ" / "Devices",
    Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Devices",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRAPED_FONTS = _REPO_ROOT / "docs" / "research" / "data" / "devices"


class DeviceError(Exception):
    pass


@dataclass(frozen=True)
class FontMetric:
    """A system font's real pixel height on one device, for one language."""

    symbol: str
    face: str
    size_px: int


@dataclass
class Device:
    id: str
    root: Path
    compiler: dict
    simulator: dict

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
        return self.simulator.get("display", {}).get("shape", "unknown")

    @property
    def minor_radius(self) -> float:
        """Half the smaller screen dimension -- what ``%r`` resolves against."""
        return min(self.width, self.height) / 2.0

    @property
    def device_family(self) -> str:
        """The resource-qualifier directory name, read rather than derived."""
        return self.compiler["deviceFamily"]

    # -- display ----------------------------------------------------------

    @property
    def display_type(self) -> str:
        return self.compiler.get("displayType", "unknown")

    @property
    def is_amoled(self) -> bool:
        return self.display_type.lower() in ("amoled", "oled")

    @property
    def supports_partial_update(self) -> bool:
        """AMOLED forbids ``onPartialUpdate`` outright; MIP depends on it."""
        return not self.is_amoled

    @cached_property
    def _scraped(self) -> dict:
        """The SDK device-reference scrape, for facts the device files omit."""
        path = _SCRAPED_FONTS / f"{self.id}.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

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
    def watchface_memory_limit(self) -> int:
        for entry in self.compiler.get("appTypes", []):
            if entry.get("type") == "watchFace":
                return int(entry["memoryLimit"])
        raise DeviceError(f"{self.id} declares no watchFace app type")

    @property
    def supports_watchface(self) -> bool:
        return any(e.get("type") == "watchFace" for e in self.compiler.get("appTypes", []))

    @property
    def api_level(self) -> str:
        """The highest Connect IQ version across the device's part numbers."""
        versions = [
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
        and shared by :attr:`_symbols`, :attr:`_modules` and :attr:`_fields`,
        which each scan it for a different tag.
        """
        path = self.root / f"{self.id}.api.debug.xml"
        if not path.exists():
            raise DeviceError(f"{self.id}: missing {path.name}")
        return path.read_text(encoding="utf-8", errors="replace")

    @cached_property
    def _symbols(self) -> tuple[set[tuple[str, str]], dict[str, str]]:
        """``({(parent, name)}, {classId: fully_qualified_label})``."""
        text = self._api_debug_xml
        functions = {
            (m.group("parent"), m.group("name"))
            for m in re.finditer(
                r'<functionEntry\b[^>]*?\bname="(?P<name>[^"]*)"[^>]*?\bparent="(?P<parent>[^"]*)"',
                text,
            )
        }
        # attribute order is not guaranteed; catch the reversed spelling too
        functions |= {
            (m.group("parent"), m.group("name"))
            for m in re.finditer(
                r'<functionEntry\b[^>]*?\bparent="(?P<parent>[^"]*)"[^>]*?\bname="(?P<name>[^"]*)"',
                text,
            )
        }
        scopes = {
            m.group("cls"): m.group("label")
            for m in re.finditer(
                r'<apiScopeEntry\b[^>]*?\bclassId="(?P<cls>[^"]*)"[^>]*?\blabel="(?P<label>[^"]*)"',
                text,
            )
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

        Used by :meth:`has_module`. Built the same tolerant way as
        `_symbols`: attribute order in this XML is not guaranteed (the same
        finding `_symbols`' own comment already records for
        ``functionEntry``), so this matches ``symbolId="..."`` and
        ``type="module"`` independently within one tag rather than assuming
        either comes first.
        """
        text = self._api_debug_xml
        modules: set[str] = set()
        for tag in re.finditer(r"<dataEntry\b[^>]*/>", text):
            body = tag.group(0)
            if 'type="module"' not in body:
                continue
            m = re.search(r'\bsymbolId="([^"]*)"', body)
            if m:
                modules.add(m.group(1))
        return frozenset(modules)

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
        text = self._api_debug_xml
        fields: set[str] = set()
        for tag in re.finditer(r"<entry\b[^>]*/>", text):
            body = tag.group(0)
            if 'field="true"' not in body:
                continue
            m = re.search(r'\bsymbol="([^"]*)"', body)
            if m:
                fields.add(m.group(1))
        return frozenset(fields)

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

    @cached_property
    def system_fonts(self) -> dict[str, FontMetric]:
        """``FONT_*`` pixel metrics for the default language.

        These come from the SDK's device reference pages (ADR 0004 5); the
        device files carry point sizes only.  Empty when unavailable, in which
        case text-overflow linting degrades to "not checked" rather than to a
        confident wrong answer.
        """
        fixed = self._scraped.get("fonts", {}).get("default", {}).get("fixed", {})
        return {
            symbol: FontMetric(symbol, entry.get("face", ""), int(entry["size_px"]))
            for symbol, entry in fixed.items()
            if "size_px" in entry
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Device {self.id} {self.width}x{self.height} {self.shape} {self.display_type}>"


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
    _cache: dict[str, Device] = field(default_factory=dict, repr=False)

    @classmethod
    def discover(cls, override: str | os.PathLike | None = None) -> "DeviceDatabase":
        candidates = []
        if override:
            candidates.append(Path(override))
        env = os.environ.get("WFB_DEVICES")
        if env:
            candidates.append(Path(env))
        candidates.extend(DEFAULT_DEVICE_ROOTS)
        for path in candidates:
            if path.is_dir() and any(path.iterdir()):
                return cls(path)
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
        )
        self._cache[device_id] = device
        return device
