"""``manifest.xml`` generation.

The single strongest justification for the whole project lives here: **the
permission set is derived from the bindings**.  A missing permission does not
fail loudly on a Garmin device -- the API returns null and the element simply
never appears, with no diagnostic anywhere.  That is the most common
"works in the simulator, blank on the wrist" failure, and a compiler that knows
every source a face reads can make it structurally impossible.

The language list matters too, though less obviously: a manifest with no
declared languages makes the compiler ignore language-specific resources and
carry a much larger resource table, which on this measurement cost about 12 KB
of foreground data for an otherwise empty face.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..devices import Device
from ..ir import Face

#: The floor for generated faces, and -- as of 2026-09-15 -- the *only*
#: level this compiler ever emits.  ``manifest.xml`` is one file shared by
#: every target device (`<iq:products>` lists them all under one
#: `minApiLevel`), so raising it for a feature one device needs would raise
#: it for every device in the same build, including targets that do not use
#: that feature at all -- and, worse, a device whose own ConnectIQ ceiling
#: sits *below* the raised floor cannot build at all even though nothing it
#: lacks is unreachable on it (`examples/dashboard/face.yaml` targeting
#: `fenix6`, ConnectIQ 3.4.5, is exactly this: it failed with
#: `error[monkeyc]: Device 'fenix6' does not support API Level '4.2.0'`
#: purely because the manifest carried a level the design's *other* targets
#: needed, before this fix).
#:
#: Everything the generator emits -- ``Application.AppBase``, ``WatchUi.WatchFace``,
#: custom bitmap fonts, and the ``Dc`` primitives in the element vocabulary --
#: is documented at or below this level, and it sits far below every device this
#: project targets (fr955 is 5.2.0; the fenix 8 Solar pair are 6.0.2).
#:
#: A feature that needs a higher-level API (complications, API 4.2.0) is no
#: longer handled by raising this floor.  Instead, every place the generated
#: code would touch such a feature is guarded at *runtime* against the
#: device that is actually running it, via `wfb.availability` --
#: `Device.has_module`/`has_symbol`/`has_field`, never a level compare
#: (CLAUDE.md constraint 6: `monkeyc` checks the SDK-wide API, not the
#: device's, and a device's own ConnectIQ ceiling is not a reliable proxy for
#: what it actually implements -- fr955 is 5.2.0 and still lacks
#: `WatchFaceDelegate.onTap`). See `wfb/emit/monkeyc.py`'s guard emission
#: (keyed off `wfb.availability.compute_guards`) and this module's own
#: `permissions()` below, which still derives `ComplicationSubscriber` from
#: the design regardless of whether every target can use it -- an
#: unreachable permission declaration is harmless, unlike an unreachable
#: `minApiLevel`.
#:
#: `config:` (the native on-device editor, ADR 0006 1) was always handled
#: this way and never raised the floor: `docs/research/probes/
#: watchface-config/` confirms `<watchface-config>` forces no `minApiLevel`
#: bump, and the feature is gated entirely by
#: `Device.has_symbol("WatchFaceConfig.getSettings")` (constraint 6: fr955
#: reports 5.2.0, above the editor's documented 5.1.0, and still has no
#: editor). Complications now follow the same shape, rather than being the
#: one feature still bumping a shared floor.
BASE_API_LEVEL = "3.2.0"


def api_level(face: Face) -> str:
    """The floor every generated face declares -- always :data:`BASE_API_LEVEL`.

    Kept as a function, not a bare constant reference at the call site, so a
    future feature that genuinely cannot be runtime-guarded (unlike
    complications) has exactly one place to raise it again -- and so it
    stays obvious from the name, at the `render()` call site below, that the
    floor is a considered decision rather than a magic string.
    """
    return BASE_API_LEVEL


def permissions(face: Face) -> list[str]:
    """The permissions implied by the design's bindings, in a stable order.

    Bindings are not the only thing that implies one: an `on_hold:` compiles to
    `Complications.exitTo`, and `Toybox.Complications` is gated by
    `ComplicationSubscriber` (the SDK's own permission table marks it
    available to a Watch Face -- checked, not assumed). A design can therefore
    need that permission while reading no complication value at all.

    A `config: data:` slot needs it too, for the same reason it is not a
    catalogue reader `face.requirements()` would otherwise see: which type
    the wearer picked is not known until runtime, so
    `WfbComplications.valueOf` is called regardless of what the design binds
    directly.
    """
    from .. import complications as launchable
    from .monkeyc import launches_a_glance

    needed = set(face.requirements().permissions)
    if launches_a_glance(face):
        needed.add(launchable.EXIT_TO_PERMISSION)
    if face.config_data:
        needed.add(launchable.EXIT_TO_PERMISSION)
    return sorted(needed)


def languages(devices: list[Device]) -> list[str]:
    """Languages to declare.

    Only English is emitted: the face has no translatable strings beyond its own
    name, and every declared language multiplies the resource table.  This is a
    deliberate scope decision, recorded here rather than left implicit.
    """
    return ["eng"]


def render(face: Face, devices: list[Device]) -> str:
    uuid = face.uuid.replace("-", "")
    lines = [
        '<?xml version="1.0"?>',
        "<!--",
        f"    Generated by garmin-wf-builder from {face.source_path.name}. Do not edit.",
        "",
        "    Permissions below are derived from the design's data bindings, not",
        "    hand-maintained. A binding added to the YAML adds its permission here",
        "    automatically; a binding removed takes its permission away.",
        "-->",
        '<iq:manifest version="3" xmlns:iq="http://www.garmin.com/xml/connectiq">',
        f'    <iq:application id="{uuid}"',
        '                    type="watchface"',
        '                    name="@Strings.AppName"',
        f'                    entry="{face.entry}App"',
        '                    launcherIcon="@Drawables.LauncherIcon"',
        f'                    minApiLevel="{api_level(face)}">',
        "        <iq:products>",
    ]
    for device in devices:
        lines.append(f'            <iq:product id="{device.id}"/>')
    lines.append("        </iq:products>")

    perms = permissions(face)
    if perms:
        lines.append("        <iq:permissions>")
        for permission in perms:
            lines.append(f'            <iq:uses-permission id="{escape(permission)}"/>')
        lines.append("        </iq:permissions>")
    else:
        lines.append("        <!-- No binding in this design requires a permission. -->")
        lines.append("        <iq:permissions/>")

    lines.append("        <iq:languages>")
    for language in languages(devices):
        lines.append(f"            <iq:language>{language}</iq:language>")
    lines.append("        </iq:languages>")
    lines.append("        <iq:barrels/>")
    lines.append("    </iq:application>")
    lines.append("</iq:manifest>")
    return "\n".join(lines) + "\n"
