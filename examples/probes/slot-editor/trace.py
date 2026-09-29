#!/usr/bin/env python3
"""Build the slot-editor probe with the editor trace drawn on the face.

A throwaway instrumented build, never an ordinary one: it generates the
probe with `wfb build --no-compile`, copies `EditorTrace.mc` into the
generated project, patches a call into each editor callback and view
lifecycle method, and compiles with the same `monkeyc` flags `wfb build`
uses. The app gets its own id and name (`Probe Slot Editor Trace`), so it
installs beside the plain probe instead of replacing it.

The trace takes the clock's place: `EditorTrace.draw` puts three lines of
text in the middle and bottom of the face (what they mean is in
`EditorTrace.mc`).

Every patch must match the generated code exactly once, or the script stops,
so a change in the generator cannot silently drop a trace point.

    ./.venv/bin/python examples/probes/slot-editor/trace.py
    # -> build/trace/probe-slot-editor/probe-slot-editor-trace-<device>.prg
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from wfb.build import _strip_noise  # noqa: E402  the same JVM-noise filter wfb build uses

ROOT = HERE.parents[2]
OUT = ROOT / "build" / "trace"
PROJECT = OUT / "probe-slot-editor"
DEVICES = ["fenix8solar47mm", "fenix8solar51mm"]
APP_ID = "7f3c1e582b9a4d6e8c051a9e4f7b2d64"  # the probe's own id, last digit +1

VIEW = "source/ProbeSlotEditorView.mc"
DELEGATE = "source/ProbeSlotEditorDelegate.mc"
DRAWABLE = "source/ProbeSlotEditorSlotDrawable.mc"

#: (file, exact text in the generated code, replacement)
PATCHES: list[tuple[str, str, str]] = [
    ("manifest.xml",
     'id="7f3c1e582b9a4d6e8c051a9e4f7b2d63"',
     f'id="{APP_ID}"'),
    ("resources/strings/strings.xml",
     ">Probe Slot Editor<",
     ">Probe Slot Editor Trace<"),
    (VIEW,
     "        drawClock(dc, clock);\n",
     ""),
    (VIEW,
     "        drawBoxedSlot(dc);\n",
     "        drawBoxedSlot(dc);\n        EditorTrace.draw(dc, _pulsing);\n"),
    (VIEW,
     "    //! Awake: full-power updates resume.\n",
     "    function onShow() as Void {\n        EditorTrace.note(\"V\");\n    }\n\n"
     "    function onHide() as Void {\n        EditorTrace.note(\"H\");\n    }\n\n"
     "    //! Awake: full-power updates resume.\n"),
    (VIEW,
     "        // data for this frame\n        var clock = System.getClockTime();\n\n",
     ""),
    (VIEW,
     "    function onLayout(dc as Dc) as Void {\n",
     "    function onLayout(dc as Dc) as Void {\n        EditorTrace.note(\"L\");\n"),
    (VIEW,
     "    function onExitSleep() as Void {\n",
     "    function onExitSleep() as Void {\n        EditorTrace.note(\"W\");\n"),
    (VIEW,
     "    function onEnterSleep() as Void {\n",
     "    function onEnterSleep() as Void {\n        EditorTrace.note(\"Z\");\n"),
    (DELEGATE,
     "        :committed as $.Toybox.Lang.Boolean}) as Void {\n",
     "        :committed as $.Toybox.Lang.Boolean}) as Void {\n"
     "        EditorTrace.edited(options[:type], options[:committed]);\n"),
    (DELEGATE,
     "        var unique = complication.uniqueIdentifier;\n"
     "        if (unique == null) {\n",
     "        var unique = complication.uniqueIdentifier;\n"
     "        EditorTrace.note(\"G\" + (unique == null ? \"?\" : unique.toString()));\n"
     "        if (unique == null) {\n"),
    (DELEGATE,
     "            setSelectedComplication(1);\n",
     "            EditorTrace.note(\"T1\");\n            setSelectedComplication(1);\n"),
    (DELEGATE,
     "            setSelectedComplication(2);\n",
     "            EditorTrace.note(\"T2\");\n            setSelectedComplication(2);\n"),
    (DELEGATE,
     "            setSelectedComplication(3);\n",
     "            EditorTrace.note(\"T3\");\n            setSelectedComplication(3);\n"),
    (DELEGATE,
     "            return true;\n        }\n\n        return false;\n    }\n\n"
     "    //! Only fires inside the on-device config editor: hands back",
     "            return true;\n        }\n\n        EditorTrace.note(\"T0\");\n"
     "        return false;\n    }\n\n"
     "    //! Only fires inside the on-device config editor: hands back"),
    (DRAWABLE,
     "    function draw(dc as Dc) as Void {\n",
     "    function draw(dc as Dc) as Void {\n        EditorTrace.drew(_unique);\n"),
]


def main() -> int:
    python = ROOT / ".venv" / "bin" / "python"
    shutil.rmtree(OUT, ignore_errors=True)
    subprocess.run(
        [str(python), "wfb.py", "build", "--no-compile", "-o", str(OUT),
         str(HERE / "face.yaml")],
        cwd=ROOT, check=True,
    )
    shutil.copy(HERE / "EditorTrace.mc", PROJECT / "source" / "EditorTrace.mc")
    for name, old, new in PATCHES:
        path = PROJECT / name
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            print(f"trace: {name}: expected 1 match, found {count}:\n{old}", file=sys.stderr)
            return 1
        path.write_text(text.replace(old, new))

    sdk = Path(os.environ["CIQ_SDK"])
    key = Path.home() / "ciq" / "developer_key.der"
    for device in DEVICES:
        prg = PROJECT / f"probe-slot-editor-trace-{device}.prg"
        result = subprocess.run(
            [str(sdk / "bin" / "monkeyc"), "-f", "monkey.jungle", "-d", device,
             "-o", str(prg), "-y", str(key), "-w", "--no-gen-styles"],
            cwd=PROJECT, capture_output=True, text=True, check=False,
        )
        output = _strip_noise(result.stdout + result.stderr)
        noise = [line for line in output.splitlines()
                 if line.startswith(("ERROR", "WARNING"))]
        print("\n".join(noise) or f"{device}: ok -> {prg.relative_to(ROOT)}")
        if result.returncode != 0 or noise:
            print(output, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
