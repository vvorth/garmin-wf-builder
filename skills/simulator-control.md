# Putting a face into a known state in the simulator (Windows)

Use this when a watch face has to be checked in the Connect IQ simulator at
a chosen state -- a time, a battery level, weather, activity numbers, a
colour or slot choice -- usually to compare it with `wfb preview` at the
same state, or to cover states the defaults never show (missing data, zero,
very large numbers, long names). The tool is `tools/simctl/simctl.ps1`;
its README (`tools/simctl/README.md`) is the reference for every command
and argument. This file is the procedure.

Windows only. On macOS or Linux there is no equivalent yet: say so and use
`wfb preview` with `--time`, `--date`, `--sample`, `--units` and `--style`.

## Before you start

- The simulator is a window on the person's desktop. Tell them you are about
  to drive it and that dialogs will flash up; ask them not to click in it
  while a run is going.
- Load the face first: `wfb simulate face.yaml -d <device>`. It returns once
  the face is running.
- Record what you change and set it back at the end (a scenario of the
  original values). The simulator keeps every setting across faces and
  restarts.

## The loop

1. **Write a scenario** (JSON list, see the README) for the state you want:
   settings menus, then data dialogs, then `face` choices, then `time`,
   then `screenshot`. **`time` goes last**: saving the Watch Face Editor or
   changing units / 12-24 h puts the simulated clock back on real time.
2. **Run it**: `powershell -File tools/simctl/simctl.ps1 scenario s.json`.
   Exit 0 means every value was typed, read back, saved and found again on
   reopening. Exit 1 names the field and what was read; fix the scenario
   (out-of-range values are clamped or rejected) rather than retrying.
3. **Render the preview at the same state**: the same `--date`/`--time`
   (the simulated clock keeps running, so read the seconds off the capture
   or ignore them), `--units` matching the Units Display menu, and
   `--sample` for each reading you set (`battery=7`, `notification_count=3`,
   `steps=12345`, `current_temperature=-12`, ...). Add `--skin` to get the
   watch case around it, as in the capture.
4. **Compare the two images yourself**: layout, clipping at the round edge,
   text that overflows its box, colours, icons. They are not expected to be
   pixel-identical (fonts are stand-ins in the preview). A difference in a
   *value* or *format* is a finding: either the preview's sample does not
   match what the watch shows, or the face mishandles that state.
5. **Restore** the original state.

## States worth covering

Settings: 12 h and 24 h; Metric and Statute; Display Mode Always-Active
(the low-power frame); Do Not Disturb; phone disconnected.
Data: battery 1-7 % and 100 % charging; notifications 0 and a large count;
alarms 0 and 3; steps 0 and 5 digits against a goal; intensity minutes
(moderate + 2 x vigorous); weather with negative and 3-digit temperatures,
high below low, unusual conditions (Hail, Wintry mix); training status with
the longest names (Overreaching, Unproductive); race predictions over 5 h.
Face: every style, both colour axes, every complication each slot offers.

## What the simulator cannot produce

- **Missing weather values**: unchecking "Weather Data Available" changes
  the condition icon only; temperature complications keep their values.
- **Body Battery, pulse ox, sleep score**: no control. Cover them with the
  preview's `--sample` only.
- **Heart rate** comes from Activity Data's random simulation (or a FIT
  file): never stable between captures.
- **Simulation > Complications** stays disabled with a watch face loaded.
- The Watch Face Editor exists only on watches with on-device config (API
  5.1+, e.g. fēnix 8); other watches use the face's own settings menu,
  which simctl does not drive.

## When a command breaks

After an SDK update a dialog may change. Follow the README's "Repair after
an SDK update": `dump` the dialog, compare it with that command's field
table in `simctl.ps1`, fix the one entry, rerun the command (its reopen
check is the verification). Do not work around a failing setter by setting
controls directly (`WM_SETTEXT`, `CB_SETCURSEL`, `DTM_SETSYSTEMTIME`): the
simulator draws the new value but does not save it, or raises a "wxWidgets
Debug Alert". The README's "Why it works this way" lists the rules.
