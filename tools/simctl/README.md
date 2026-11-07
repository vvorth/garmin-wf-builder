# simctl: drive the Connect IQ simulator's GUI (Windows)

`simctl.ps1` sets the data and state a watch face shows in the running
`simulator.exe` (battery, time, weather, activity, notifications, the Watch
Face Editor, settings menus) and takes screenshots, so a test run can put a
face into a known state before capturing it. Windows only, Windows
PowerShell 5.1, nothing to install.

```powershell
powershell -File tools/simctl/simctl.ps1 <command> [args]
. tools/simctl/simctl.ps1          # dot-source: Set-SimBattery, Set-SimWeather, ...
```

The simulator must be running with the face loaded (`wfb simulate face.yaml -d
<device>`). It may stay in the background: `simctl` posts messages to its
windows and never takes focus. Nothing else should use the simulator while a
command runs.

Every setter types the value as a user would, reads it back from the
control, confirms the dialog, then **reopens the dialog and checks that the
value stuck** (`-NoVerify` skips that). Any mismatch exits 1 and names the
field and what was read, e.g.
`Count: set to '5', but 'Settings/Set Alarm Count' reads '3' after reopening`.
A failure while typing cancels the dialog, so nothing is applied; a mismatch
found on reopening means the dialog accepted a different (clamped) value.

## Commands

| Command | Arguments | Dialog |
|---|---|---|
| `menu <path>` | `"Settings/Units Display/Statute"` | any menu item; prints the check mark it ends with |
| `menus` | | prints the menu tree with ids, checked and disabled state |
| `battery` | `-Percent -DaysRemaining -Solar -Charging` | Settings > Set Battery Status |
| `time <iso>` | `2026-09-03T10:09:42`, or `-Stop` | Simulation > Time Simulation (left running) |
| `face` | `-Accent -Data -Style -Slot "1=Steps,3=Battery"` | File > Edit Watch Face, then Save |
| `weather` | see below | Settings > Set Weather |
| `activity` | `-Today -History -WeeklyActiveMinutesGoal -RecoveryTime -BreathsPerMinute -StressLevel` | Simulation > Activity Monitoring > Set Activity Monitor Info |
| `notifications <n>` | `-NextEvent 14:30` | Settings > Set Phone Notifications |
| `alarms <n>` | 0..3 | Settings > Set Alarm Count |
| `position "<lat>, <lon>"` | | Settings > Set Position |
| `profile` | see below | Settings > Set User Profile |
| `training` | `-Status -WeeklyRunKm -WeeklyBikeKm -RacePredictor` | Settings > Set Training Status |
| `textsize <scale>` | 0.80..1.45, steps of 0.05 | Settings > Font Scale |
| `screenshot <png>` | | captures the simulator window (PrintWindow, DPI-aware) |
| `dump "<menu path>"` | `-Shot dialog.png` | lists a dialog's controls, labels, values and geometry, then cancels |
| `close-popups` | | dismisses leftover simulator dialogs without applying them |
| `scenario <file.json>` | | runs a list of steps |

Booleans take `true/false/on/off/1/0`. A value that starts with `-` and a
digit (`-Low -3.5`) is a value, not a parameter name.

**weather**: `-Available` (the "Weather Data Available" box), `-Condition`
(any name in the editor's list, e.g. `Rain`, `"Partly cloudy"`),
`-Temperature -FeelsLike -High -Low -DewPoint` (°C), `-Humidity
-PrecipChance -CloudCover` (%), `-WindSpeed` (m/s), `-WindBearing`, `-UV`,
`-Visibility` (m), `-Pressure` (Pa), `-LocationName -Lat -Lon`,
`-ObservationDate -ObservationTime`, and the forecast grids:

- `-Hourly`: 12 rows (row 0 = the next hour). Columns `Condition,
  Temperature, PrecipChance, Humidity, WindSpeed, WindBearing, UV, DewPoint,
  CloudCover` (`Hour` is the row's hour).
- `-Daily`: 5 rows (row 0 = today). Columns `Condition, High, Low,
  PrecipChance` (`Day` is the row's date).

A row is `"Row=5,PrecipChance=90,UV=7.5"`, or a JSON object; without `Row`
its place in the list is its row.

**activity**: `-Today "Steps=12345,StepGoal=10000"` with columns
`StepsPerMinute` (0-300), `StepGoal` (1000-40000), `Steps, Distance` (cm),
`Calories, FloorsClimbed, FloorsDescended, FloorsClimbedGoal,
ModerateMinutes, VigorousMinutes`. `-History` takes rows for the 7 previous
days (row 0 = yesterday) with columns `Steps, StepGoal, Distance, Calories,
ModerateMinutes, VigorousMinutes, FloorsClimbed, FloorsDescended,
FloorsClimbedGoal`.

**profile**: `-Gender` (Female/Male/Not Specified), `-BirthYear -Height
-Weight` (in the units of Settings > Units Display: in/lbs or cm/kg),
`-WakeTime -SleepTime` (`06:30`), `-RestingHR -ActivityClass
-WalkingStepLength -RunningStepLength`, `-VO2MaxActivity`
(Running/Biking) with `-VO2Max`, `-HrSport` (Generic/Running/Biking/
Swimming/Rowing) with `-HrZones "93,111,130,148,167,185"` (Zone 1 min, then
Zone 1-5 max), `-PowerSport` (Cycling/...) with `-FTP` and `-PowerZones`
(Zone 1 min, Zone 1-7 max). The three selectors only choose what the dialog
shows; they are not saved.

**training**: `-Status` (No Result, Detraining, Recovery, Maintaining,
Productive, Peaking, Overreaching, Unproductive, Strained), and
`-RacePredictor "Row=5K,TotalTime=00:22:30"` (rows `5K, 10K, HalfMarathon,
Marathon`; columns `PaceMinPerMile` mm:ss, `PaceMps`, `TotalTime`
hh:mm:ss). Setting one column makes the simulator derive the other two.

**face** slots are numbered as in the editor's "Data Field" list; the
complication names are the editor's (`"Current Temperature"`,
`"High/Low Temperature"`, `"5k Race Prediction"`, ...). A name not in the
list fails with the full list of choices.

### Examples

```powershell
$s = 'tools/simctl/simctl.ps1'
powershell -File $s menu "Settings/Time Display/24 Hour"
powershell -File $s battery -Percent 7 -Charging false
powershell -File $s weather -Available true -Condition Rain -Temperature 25 -High 30 -Low -3.5
powershell -File $s weather -Hourly "Row=0,Temperature=5,Condition=Snow"
powershell -File $s activity -Today "Steps=4321,ModerateMinutes=30,VigorousMinutes=20" -History "Steps=8000"
powershell -File $s face -Accent "Bright Green" -Slot "1=Battery,2=Sunrise"
powershell -File $s time 2026-09-03T10:09:42
powershell -File $s screenshot out/face.png
powershell -File $s dump "Settings/Set Weather" -Shot weather.png
```

### Scenarios

A scenario is a JSON list of one-key steps, `{"<command>": <arguments>}`.
Arguments are an object (named parameters) or a bare value (the command's
positional argument); `true` means no arguments. Relative screenshot paths
are relative to the current directory. See
[`examples/coverage-basic.json`](examples/coverage-basic.json):

```json
[
  { "menu": "Settings/Units Display/Statute" },
  { "battery": { "Percent": 7 } },
  { "weather": { "Available": false } },
  { "time": "2026-09-03T10:09:42" },
  { "screenshot": "out.png" }
]
```

Every step is checked before the first one runs. **Put `time` last, just
before the screenshot**: saving the Watch Face Editor and changing a setting
from the menus (units, 12/24 hour) put the simulated clock back on real
time, so a step after `time` earns a warning.

## What the face sees (fēnix 8 Solar 47mm, SDK 9.3.0)

- Weather Editor values reach the weather complications (temperature, high/
  low, condition icon). Unchecking "Weather Data Available" makes the
  condition icon fall back, but the Current Temperature and High/Low
  Temperature complications keep their last values: it does not make them
  absent.
- Battery, notification count, steps and step goal, intensity minutes
  (moderate + 2 x vigorous), training status and race predictions all show
  on a face whose slots hold those complications.
- Settings > Display Mode > Always-Active shows the face's low-power frame
  (trail4 drops its seconds); Sleep Mode changes nothing visible; Force
  onHide blanks the screen until Force onShow.
- Simulation > Complications stays disabled with a watch face loaded.
- Font Scale changes nothing on a face drawn with bitmap fonts.

## Why it works this way

The simulator's dialogs are wxWidgets on native Win32 controls. Each rule
below cost a failure.

1. **Menus** are native: `WM_COMMAND` with the item id, posted to the main
   window. Ids are looked up by label path on every call, never hardcoded.
2. **Input is emulated, never set.** wx keeps its own copy of each value and
   updates it only from the control's own notifications, so `WM_SETTEXT`,
   `CB_SETCURSEL` or `DTM_SETSYSTEMTIME` change what is drawn but not what is
   saved, or raise a "wxWidgets Debug Alert" (`m_date not in sync`). Edits
   get `EM_SETSEL` + one `WM_CHAR` per character, combos Home + Down x n,
   checkboxes a posted `BM_CLICK`, sliders arrow or page keys.
3. **Focus is faked where wx needs it.** A `wxSpinCtrlDouble` takes its text
   as the value only on losing focus (Return does not do it), so a
   `WM_KILLFOCUS` is posted after typing. The window never gets real focus
   (no `SetForegroundWindow`/`SendInput`), so the simulator can stay behind
   other windows.
4. **Navigation keys carry the extended-key bit** (lParam bit 24) and a scan
   code. Without it wx reads an arrow or Home key as its numpad twin, which
   wxGrid ignores (the grid scrolls instead of moving the cursor).
5. **Date/time pickers**: arrows move between fields and wrap, but which
   field is current at the start varies (none on a fresh picker, else the
   last one used). One Left makes a field current, one Up shows which field
   it is (that part changes), then Left reaches the first field. Date parts
   follow the Windows short-date order (`HKCU\Control Panel\International
   sShortDate`) and are typed without leading zeros; time parts take two
   digits, 24-hour (a 12-hour Windows time format is refused).
6. **Grids** (wxGrid) have no child window per cell: arrows on the
   `GridWindow`, F2 opens the cell editor (typing alone does not), Return
   commits, Escape cancels; F2 + read + Escape is the readback. Grids are
   ordered by screen position (Windows enumerates them differently), and
   column names, which Win32 cannot read, live in tables in the script.
7. **Pacing**: keys ~140 ms apart (60-80 ms loses keys); wait ~1.2 s after a
   dialog opens before typing.
8. **Readback**: `GetWindowText` on another process's Edit returns a stale
   caption, so values are read with `WM_GETTEXT`. A picker's value comes
   from `DTM_GETSYSTEMTIME` into a buffer allocated in the simulator
   (`VirtualAllocEx`/`ReadProcessMemory`). A message whose lParam is a
   pointer is only ever sent with memory that is valid in the simulator: a
   null pointer once crashed it.
9. **Modal boxes**: buttons are clicked with `PostMessage` (a `SendMessage`
   to a button that opens a modal box blocks). Every synchronous send has a
   3 s timeout. Closing Time Simulation while it runs asks "Stop Time
   Simulation?", answered No. A Debug Alert is dismissed with Continue and
   reported as a failure, with its text read through UI Automation.
10. **Labels are found by geometry**, not Z-order (some dialogs list every
    input before every label): the Static with the label text, then the
    nearest input to its right in the same row, else directly under it.

## Repair after an SDK update

When a command starts failing after Garmin changes a dialog:

1. `powershell -File tools/simctl/simctl.ps1 dump "<menu path>" -Shot d.png`
   lists every control with its class, text, value, position and visibility,
   and saves a picture (grid column headers are only visible there).
2. Compare it with the field table of the failing command in `simctl.ps1`
   (`$script:WeatherFields`, `$script:ActivityTodayColumns`, ...). A field
   spec is the label text a user sees: `"Label"`, `"Label#2"` (second input
   in that row), `"Label@2"` (second label with that text), `"Label*"`
   (label prefix), `"button:Text"` (a checkbox with its own text), with
   `|date` or `|time` for pickers.
3. Fix that one table or function (a renamed label, a new grid column, a
   moved menu path) and rerun the command; its reopen-and-check pass is the
   verification. Then rerun `examples/coverage-basic.json` and compare the
   screenshot.
