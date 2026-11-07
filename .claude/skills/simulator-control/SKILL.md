---
name: simulator-control
description: Put a Garmin watch face into a chosen state in the Connect IQ simulator on Windows -- battery, time and date, weather, steps and activity, notifications, units and 12/24 h, display mode, accent/data colours and slot complications -- and capture it, usually to compare against `wfb preview` at the same state or to cover edge cases (missing data, zero, huge numbers, long names). Use when asked to test or check a face in the simulator, compare simulator and preview, cover more data states, or set simulator data.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Bash
  - PowerShell
---

# Drive the Connect IQ simulator

**Read `skills/simulator-control.md` from the repository root and follow
it.** It is kept model-agnostic; `tools/simctl/README.md` is the command
reference.

## Specific to Claude Code

- Run the tool with the PowerShell tool:
  `powershell -NoProfile -File tools/simctl/simctl.ps1 <command>`. A full
  scenario can take minutes; give it a long timeout.
- **Look at every capture with the Read tool** before saying it matches the
  preview, and name each difference you see.
- The person sees the simulator on their desktop. Tell them before a run;
  if they report a dialog they did not expect, run `close-popups` and
  check the last step's output.
