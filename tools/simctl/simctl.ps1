<#
.SYNOPSIS
  Drives the Connect IQ simulator's GUI (Windows) so a test run can set the
  data and state a watch face shows: battery, time, weather, activity, the
  Watch Face Editor, menus, and screenshots.

.DESCRIPTION
  Run a command:   powershell -File tools/simctl/simctl.ps1 <command> [args]
  Or dot-source:   . tools/simctl/simctl.ps1   (defines the Set-Sim* functions)

  Every setter emulates user input (posted key and character messages) and
  reads the result back; a mismatch throws, naming the field and the value
  read. README.md explains why it works this way and how to repair it after
  an SDK update.
#>
param(
  [Parameter(Position = 0)] [string] $Command,
  [Parameter(Position = 1, ValueFromRemainingArguments = $true)] $CommandArgs
)

# Strict only when run as a script: dot-sourcing must not change the caller's session.
if ($MyInvocation.InvocationName -ne '.') { Set-StrictMode -Version 2; $ErrorActionPreference = 'Stop' }

# ---------------------------------------------------------------------------
# Native layer
# ---------------------------------------------------------------------------

if (-not ('SimNative' -as [type])) {
  Add-Type -AssemblyName System.Drawing
  Add-Type -ReferencedAssemblies System.Drawing @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class SimNative {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", EntryPoint="SendMessageTimeoutW")]
  static extern IntPtr SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint flags, uint ms, out IntPtr result);
  [DllImport("user32.dll", EntryPoint="SendMessageTimeoutW", CharSet=CharSet.Unicode)]
  static extern IntPtr SendMessageTimeoutSB(IntPtr h, uint m, IntPtr w, StringBuilder l, uint flags, uint ms, out IntPtr result);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr m);
  [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr m, int i);
  [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr m, int i);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr m, uint id, StringBuilder s, int max, uint flags);
  [DllImport("user32.dll")] public static extern uint GetMenuState(IntPtr m, uint id, uint flags);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint type);
  [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
  [DllImport("kernel32.dll")] public static extern IntPtr VirtualAllocEx(IntPtr p, IntPtr a, UIntPtr size, uint type, uint protect);
  [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr p, IntPtr a, byte[] b, UIntPtr n, out UIntPtr r);
  [DllImport("kernel32.dll")] public static extern bool VirtualFreeEx(IntPtr p, IntPtr a, UIntPtr size, uint type);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);

  // Every synchronous send has a timeout, so a simulator blocked in a modal
  // box cannot hang the caller.
  const uint SMTO_ABORTIFHUNG = 2;
  public static long Send(IntPtr h, uint m, long w, long l) {
    IntPtr r;
    if (SendMessageTimeout(h, m, (IntPtr)w, (IntPtr)l, SMTO_ABORTIFHUNG, 3000, out r) == IntPtr.Zero)
      throw new TimeoutException(String.Format("message 0x{0:X} to window {1} timed out", m, h));
    // Every message sent here returns a 32-bit result; sign-extend it so CB_ERR reads -1.
    return (long)(int)(long)r;
  }
  public static bool Post(IntPtr h, uint m, long w, long l) { return PostMessage(h, m, (IntPtr)w, (IntPtr)l); }

  public static List<IntPtr> Windows(uint pid) {
    var r = new List<IntPtr>();
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p); if (p == pid && IsWindowVisible(h)) r.Add(h); return true; }, IntPtr.Zero);
    return r;
  }
  public static List<IntPtr> Children(IntPtr parent) {
    var r = new List<IntPtr>();
    EnumChildWindows(parent, (h, l) => { r.Add(h); return true; }, IntPtr.Zero);
    return r;
  }
  public static string Cls(IntPtr h) { var s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }
  // The window's caption as Windows caches it: right for labels and buttons,
  // stale for another process's Edit (use Value for those).
  public static string Caption(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  // WM_GETTEXT asks the control itself; Windows marshals the buffer across processes.
  public static string Value(IntPtr h) {
    var s = new StringBuilder(2048); IntPtr r;
    if (SendMessageTimeoutSB(h, 0x000D, (IntPtr)2048, s, SMTO_ABORTIFHUNG, 3000, out r) == IntPtr.Zero)
      throw new TimeoutException("WM_GETTEXT timed out");
    return s.ToString();
  }
  // CB_GETLBTEXT is marshalled across processes for the standard ComboBox class.
  public static string ComboItem(IntPtr h, int i) {
    int n = (int)Send(h, 0x0149, i, 0);
    if (n < 0) return null;
    var s = new StringBuilder(n + 2); IntPtr r;
    SendMessageTimeoutSB(h, 0x0148, (IntPtr)i, s, SMTO_ABORTIFHUNG, 3000, out r);
    return s.ToString();
  }
  public static RECT Rect(IntPtr h) { RECT r; GetWindowRect(h, out r); return r; }

  // Sends a message whose lParam must point at a buffer of `size` bytes in
  // the simulator's own address space, and returns that buffer. The buffer is
  // allocated there first; a message is never sent with an invalid pointer
  // (a null lParam once crashed the simulator).
  public static byte[] SendRemote(IntPtr h, uint pid, uint m, long w, int size) {
    IntPtr proc = OpenProcess(0x0438, false, pid);   // VM_OPERATION | VM_READ | VM_WRITE | QUERY_INFORMATION
    if (proc == IntPtr.Zero) throw new InvalidOperationException("OpenProcess on the simulator failed");
    try {
      IntPtr mem = VirtualAllocEx(proc, IntPtr.Zero, (UIntPtr)(ulong)size, 0x3000, 0x04);
      if (mem == IntPtr.Zero) throw new InvalidOperationException("VirtualAllocEx in the simulator failed");
      try {
        Send(h, m, w, (long)mem);
        var b = new byte[size]; UIntPtr got;
        if (!ReadProcessMemory(proc, mem, b, (UIntPtr)(ulong)size, out got)) throw new InvalidOperationException("ReadProcessMemory failed");
        return b;
      } finally { VirtualFreeEx(proc, mem, UIntPtr.Zero, 0x8000); }
    } finally { CloseHandle(proc); }
  }

  public static System.Drawing.Bitmap Capture(IntPtr h) {
    RECT r = Rect(h);
    var bmp = new System.Drawing.Bitmap(Math.Max(1, r.Right - r.Left), Math.Max(1, r.Bottom - r.Top));
    using (var g = System.Drawing.Graphics.FromImage(bmp)) {
      IntPtr hdc = g.GetHdc();
      PrintWindow(h, hdc, 2);   // PW_RENDERFULLCONTENT
      g.ReleaseHdc(hdc);
    }
    return bmp;
  }
}
"@
}
# Physical pixels everywhere: window rectangles and captures must agree.
[SimNative]::SetProcessDPIAware() | Out-Null

$script:WM = @{
  KILLFOCUS = 0x0008; GETTEXT = 0x000D; CLOSE = 0x0010; KEYDOWN = 0x0100; KEYUP = 0x0101; CHAR = 0x0102
  COMMAND = 0x0111; EM_SETSEL = 0x00B1; BM_GETCHECK = 0x00F0; BM_CLICK = 0x00F5
  CB_GETCOUNT = 0x0146; CB_GETCURSEL = 0x0147; DTM_GETSYSTEMTIME = 0x1001
  TBM_GETPOS = 0x0400; TBM_GETRANGEMIN = 0x0401; TBM_GETRANGEMAX = 0x0402
  TCM_GETITEMCOUNT = 0x1304; TCM_GETCURSEL = 0x130B
}
$script:VK = @{
  BACK = 0x08; TAB = 0x09; RETURN = 0x0D; ESCAPE = 0x1B; SPACE = 0x20; PRIOR = 0x21; NEXT = 0x22
  END = 0x23; HOME = 0x24; LEFT = 0x25; UP = 0x26; RIGHT = 0x27; DOWN = 0x28; DELETE = 0x2E; F2 = 0x71
}
# Keys posted faster than ~120 ms apart get lost; a dialog drops keys posted
# in its first second.
$script:KeyDelayMs = 140
$script:DialogSettleMs = 1200

# ---------------------------------------------------------------------------
# Process, windows, controls
# ---------------------------------------------------------------------------

function Get-SimProcess {
  $p = Get-Process simulator -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if (-not $p) { throw "simulator.exe is not running (start it with 'wfb simulate <face.yaml>')" }
  $p
}
function Get-SimMainWindow { [IntPtr](Get-SimProcess).MainWindowHandle }
function Get-SimPid { [uint32](Get-SimProcess).Id }

# Visible top-level windows of the simulator other than its main window.
function Get-SimPopups {
  $main = Get-SimMainWindow
  @([SimNative]::Windows((Get-SimPid)) | Where-Object { $_ -ne $main })
}

# One record per child control, with its geometry, for searching by label.
function Get-SimControls([IntPtr] $Window, [switch] $All) {
  foreach ($h in [SimNative]::Children($Window)) {
    $visible = [SimNative]::IsWindowVisible($h)
    if (-not $All -and -not $visible) { continue }
    $r = [SimNative]::Rect($h)
    [pscustomobject]@{
      H = $h; Class = [SimNative]::Cls($h); Text = [SimNative]::Caption($h); Id = [SimNative]::GetDlgCtrlID($h)
      Visible = $visible; Left = $r.Left; Top = $r.Top; Right = $r.Right; Bottom = $r.Bottom
      CenterY = ($r.Top + $r.Bottom) / 2
    }
  }
}

function Format-Label([string] $s) { ($s -replace '&', '').Trim().TrimEnd(':').Trim() }

$script:InputClasses = @('Edit', 'ComboBox', 'SysDateTimePick32', 'Button', 'msctls_trackbar32')

# A field spec names an input by what a user sees:
#   "Label"                 the input beside (right of) or under the label
#   "Label#2"               the second input in that row (e.g. a time picker after a date picker)
#   "Label@2"               under the second label with that text, top to bottom
#   "Label (*"              a label that starts with this text
#   "button:Text"           a checkbox that carries its own text
#   "...|time" / "|date"    how to type into a date/time picker
#   "?Label"                optional: some devices' dialogs lack it (skipped there)
function Resolve-SimFieldSpec([string] $Spec) {
  $kind = ''; $optional = $Spec.StartsWith('?')
  if ($optional) { $Spec = $Spec.Substring(1) }
  if ($Spec -match '^(.*)\|(\w+)$') { $Spec = $Matches[1]; $kind = $Matches[2] }
  $nth = 1; $labelIndex = 1
  if ($Spec -match '^(.*)#(\d+)$') { $Spec = $Matches[1]; $nth = [int]$Matches[2] }
  if ($Spec -match '^(.*)@(\d+)$') { $Spec = $Matches[1]; $labelIndex = [int]$Matches[2] }
  @{ Label = $Spec; Nth = $nth; LabelIndex = $labelIndex; Kind = $kind; Optional = $optional }
}

# Finds the input a label names, by geometry: Z-order is no guide (some
# dialogs list every input before every label). Inputs to the right whose
# vertical centre is in the label's row come first; failing that, inputs
# directly under the label.
function Find-SimInput([IntPtr] $Window, [string] $Spec, $Controls) {
  if (-not $Controls) { $Controls = @(Get-SimControls $Window) }
  $s = Resolve-SimFieldSpec $Spec
  $title = [SimNative]::Caption($Window)
  if ($s.Label -like 'button:*') {
    $text = $s.Label.Substring(7)
    $b = @($Controls | Where-Object { $_.Class -eq 'Button' -and (Format-Label $_.Text) -eq $text })
    if (-not $b.Count) { throw "no checkbox '$text' in '$title'" }
    return $b[0].H
  }
  $want = Format-Label $s.Label
  # A trailing * matches labels whose end varies, e.g. the unit in "Height (in)" / "Height (cm)".
  $match = if ($want.EndsWith('*')) { { param($t) $t.StartsWith($want.TrimEnd('*')) } } else { { param($t) $t -eq $want } }
  $labels = @($Controls | Where-Object { $_.Class -eq 'Static' -and (& $match (Format-Label $_.Text)) } | Sort-Object Top, Left)
  if ($labels.Count -lt $s.LabelIndex) {
    $have = ($Controls | Where-Object { $_.Class -eq 'Static' -and $_.Text.Trim() } | ForEach-Object { "'$(Format-Label $_.Text)'" }) -join ', '
    throw "no label '$want' (#$($s.LabelIndex)) in '$title'; labels: $have"
  }
  # With a label index, only that label counts; otherwise the first label that has an input.
  $candidates = if ($s.LabelIndex -gt 1) { @($labels[$s.LabelIndex - 1]) } else { $labels }
  $inputs = @($Controls | Where-Object { $script:InputClasses -contains $_.Class -and -not ($_.Class -eq 'Button' -and $_.Text -ne '') })
  foreach ($l in $candidates) {
    $lc = ($l.Top + $l.Bottom) / 2
    $band = [Math]::Max(12, ($l.Bottom - $l.Top) * 0.75)
    $right = @($inputs | Where-Object { $_.Left -ge ($l.Right - 4) -and [Math]::Abs($_.CenterY - $lc) -le $band } | Sort-Object { $_.Left - $l.Right })
    if ($right.Count -ge $s.Nth) { return $right[$s.Nth - 1].H }
    $below = @($inputs | Where-Object { $_.Top -ge ($l.Bottom - 2) -and $_.Top -le ($l.Bottom + 40) -and [Math]::Abs($_.Left - $l.Left) -le 20 } | Sort-Object Top, Left)
    if ($below.Count -ge $s.Nth) { return $below[$s.Nth - 1].H }
  }
  throw "no input beside or under label '$want' in '$title'"
}

function Find-SimButton([IntPtr] $Window, [string[]] $Text) {
  [SimNative]::Children($Window) | Where-Object { [SimNative]::Cls($_) -eq 'Button' -and $Text -contains [SimNative]::Caption($_) } | Select-Object -First 1
}

# Posting BM_CLICK, never sending it: a button that opens a modal box would
# block a SendMessage until the box closed.
function Invoke-SimClick([IntPtr] $Button) { [SimNative]::Post($Button, $WM.BM_CLICK, 0, 0) | Out-Null }

# ---------------------------------------------------------------------------
# Input emulation. wxWidgets keeps its own copy of each control's value and
# only updates it from the control's own notifications, so values are typed
# and keyed, never set with WM_SETTEXT / CB_SETCURSEL / DTM_SETSYSTEMTIME.
# ---------------------------------------------------------------------------

# lParam carries the scan code and, for the navigation keys, the extended-key
# bit: wx reads an arrow or Home key without that bit as its numpad twin
# (WXK_NUMPAD_RIGHT), which wxGrid ignores.
function Get-SimKeyLParam([int] $Vk, [bool] $Up) {
  $scan = [int64][SimNative]::MapVirtualKey([uint32]$Vk, 0)
  $l = 1 -bor ($scan -shl 16)
  if (($Vk -ge 0x21 -and $Vk -le 0x28) -or $Vk -eq 0x2D -or $Vk -eq 0x2E) { $l = $l -bor (1 -shl 24) }
  if ($Up) { $l = $l -bor 0xC0000000L }
  $l
}
function Send-SimKey([IntPtr] $Hwnd, [int] $Vk, [int] $Count = 1) {
  $down = Get-SimKeyLParam $Vk $false; $up = Get-SimKeyLParam $Vk $true
  for ($i = 0; $i -lt $Count; $i++) {
    [SimNative]::Post($Hwnd, $WM.KEYDOWN, $Vk, $down) | Out-Null
    [SimNative]::Post($Hwnd, $WM.KEYUP, $Vk, $up) | Out-Null
    Start-Sleep -Milliseconds $script:KeyDelayMs
  }
}
function Send-SimChars([IntPtr] $Hwnd, [string] $Text) {
  foreach ($ch in $Text.ToCharArray()) {
    [SimNative]::Post($Hwnd, $WM.CHAR, [int]$ch, 1) | Out-Null
    Start-Sleep -Milliseconds $script:KeyDelayMs
  }
}

# Compares numbers numerically ("7" = "7.0" = "7.00"), comma-separated lists
# item by item ("51.5, -0.12" = "51.500000, -0.120000"), anything else as text.
function Test-SimSame([string] $Got, [string] $Want) {
  if ($Want.Contains(',') -and $Got.Contains(',')) {
    $g = $Got -split ','; $w = $Want -split ','
    if ($g.Count -ne $w.Count) { return $false }
    for ($i = 0; $i -lt $g.Count; $i++) { if (-not (Test-SimSame $g[$i] $w[$i])) { return $false } }
    return $true
  }
  $g = 0.0; $w = 0.0
  $inv = [Globalization.CultureInfo]::InvariantCulture
  if ([double]::TryParse($Got.Trim(), [Globalization.NumberStyles]::Float, $inv, [ref]$g) -and
      [double]::TryParse($Want.Trim(), [Globalization.NumberStyles]::Float, $inv, [ref]$w)) {
    return [Math]::Abs($g - $w) -lt 1e-6
  }
  $Got.Trim() -eq $Want.Trim()
}

# Types into an Edit (plain, or the text part of a spin control) and reads it
# back. -Commit posts WM_KILLFOCUS, as tabbing away would: a wxSpinCtrlDouble
# takes its text as the value only on losing focus (Return does not do it),
# and the window never had real focus to lose.
function Set-SimEdit([IntPtr] $Edit, [string] $Value, [string] $Field, [switch] $Commit) {
  [SimNative]::Send($Edit, $WM.EM_SETSEL, 0, -1) | Out-Null
  Send-SimKey $Edit $VK.DELETE
  Send-SimChars $Edit $Value
  if ($Commit) { [SimNative]::Post($Edit, $WM.KILLFOCUS, 0, 0) | Out-Null; Start-Sleep -Milliseconds 200 }
  Start-Sleep -Milliseconds 200
  $got = [SimNative]::Value($Edit)
  if (-not (Test-SimSame $got $Value)) { throw "$Field`: typed '$Value', the field reads '$got'" }
}

function Get-SimComboItems([IntPtr] $Combo) {
  $n = [SimNative]::Send($Combo, $WM.CB_GETCOUNT, 0, 0)
  for ($i = 0; $i -lt $n; $i++) { [SimNative]::ComboItem($Combo, $i) }
}
function Get-SimComboText([IntPtr] $Combo) {
  $i = [SimNative]::Send($Combo, $WM.CB_GETCURSEL, 0, 0)
  if ($i -lt 0) { return $null }
  [SimNative]::ComboItem($Combo, [int]$i)
}
# Selects a combo item by its text (case-insensitive) with Home + Down keys,
# so the combo raises its own selection notifications.
function Set-SimCombo([IntPtr] $Combo, [string] $Text, [string] $Field) {
  $items = @(Get-SimComboItems $Combo)
  $i = -1
  for ($k = 0; $k -lt $items.Count; $k++) { if ($items[$k] -ieq $Text) { $i = $k; break } }
  if ($items.Count -eq 0) { throw "$Field`: the list is empty, so '$Text' cannot be chosen (a face without styles has an empty Style list)" }
  if ($i -lt 0) { throw "$Field`: '$Text' is not in the list; choices: $($items -join ' | ')" }
  if ([SimNative]::Send($Combo, $WM.CB_GETCURSEL, 0, 0) -eq $i) { return }
  Send-SimKey $Combo $VK.HOME
  Send-SimKey $Combo $VK.DOWN $i
  Start-Sleep -Milliseconds 300
  $now = Get-SimComboText $Combo
  if ($now -ne $items[$i]) { throw "$Field`: wanted '$($items[$i])', the list shows '$now'" }
}

function Get-SimCheck([IntPtr] $Button) { [SimNative]::Send($Button, $WM.BM_GETCHECK, 0, 0) -eq 1 }
function Set-SimCheck([IntPtr] $Button, [bool] $On, [string] $Field) {
  if ((Get-SimCheck $Button) -ne $On) {
    Invoke-SimClick $Button
    Start-Sleep -Milliseconds 400
  }
  if ((Get-SimCheck $Button) -ne $On) { throw "$Field`: wanted $(if ($On) {'checked'} else {'unchecked'}), the box did not follow" }
}

# Reads a date/time picker's SYSTEMTIME through a buffer in the simulator.
function Get-SimPicker([IntPtr] $Picker) {
  $b = [SimNative]::SendRemote($Picker, (Get-SimPid), $WM.DTM_GETSYSTEMTIME, 0, 16)
  $f = 0..7 | ForEach-Object { [BitConverter]::ToUInt16($b, $_ * 2) }
  New-Object DateTime ([int]$f[0]), ([int]$f[1]), ([int]$f[3]), ([int]$f[4]), ([int]$f[5]), ([int]$f[6])
}

# The short-date field order of this Windows user (the pickers follow it).
function Get-SimDateOrder {
  $fmt = (Get-ItemProperty 'HKCU:\Control Panel\International').sShortDate
  $order = @()
  foreach ($ch in $fmt.ToCharArray()) {
    $k = switch -CaseSensitive ($ch) { 'd' { 'd' } 'M' { 'M' } 'y' { 'y' } default { $null } }
    if ($k -and $order -notcontains $k) { $order += $k }
  }
  if ($order.Count -ne 3) { throw "cannot read the date order from sShortDate '$fmt'" }
  $order
}

# The pickers are 24-hour (fields H, m, s); a 12-hour format adds an AM/PM field.
function Assert-Sim24Hour {
  $fmt = (Get-ItemProperty 'HKCU:\Control Panel\International').sTimeFormat
  if ($fmt -cmatch 'h|t') { throw "the Windows time format '$fmt' is 12-hour; the picker typing assumes 24-hour (HH:mm:ss)" }
}

function Get-SimPickerPart([datetime] $t, [string] $Part) {
  switch -CaseSensitive ($Part) { 'd' { $t.Day } 'M' { $t.Month } 'y' { $t.Year } 'H' { $t.Hour } 'm' { $t.Minute } 's' { $t.Second } }
}

# Types one value per field into a picker. Arrow keys move between fields and
# wrap around, but which field is current at the start varies (none on a
# picker never typed into, else the last one used), so: one Left makes some
# field current, one Up reveals which (its part changes), then Left reaches
# the first field and Right steps through the rest.
function Send-SimPickerFields([IntPtr] $Picker, [string[]] $Parts, [string[]] $Values, [string] $Field) {
  Send-SimKey $Picker $VK.LEFT
  $before = Get-SimPicker $Picker
  Send-SimKey $Picker $VK.UP
  Start-Sleep -Milliseconds 200
  $after = Get-SimPicker $Picker
  $cur = -1
  for ($i = 0; $i -lt $Parts.Count; $i++) {
    if ((Get-SimPickerPart $before $Parts[$i]) -ne (Get-SimPickerPart $after $Parts[$i])) { $cur = $i; break }
  }
  if ($cur -lt 0) { throw "$Field`: the picker did not react to the Up key (no current field)" }
  Send-SimKey $Picker $VK.LEFT $cur
  for ($i = 0; $i -lt $Values.Count; $i++) {
    Send-SimChars $Picker $Values[$i]
    if ($i -lt $Values.Count - 1) { Send-SimKey $Picker $VK.RIGHT }
  }
  Start-Sleep -Milliseconds 300
}
# Date fields take the number without a leading zero.
function Set-SimPickerDate([IntPtr] $Picker, [datetime] $When, [string] $Field) {
  $parts = @(Get-SimDateOrder)
  $values = @($parts | ForEach-Object { [string](Get-SimPickerPart $When $_) })
  Send-SimPickerFields $Picker $parts $values $Field
  $got = Get-SimPicker $Picker
  if ($got.Date -ne $When.Date) { throw "$Field`: wanted $($When.ToString('yyyy-MM-dd')), the picker reads $($got.ToString('yyyy-MM-dd'))" }
}
# Time fields take two digits each.
function Set-SimPickerTime([IntPtr] $Picker, [datetime] $When, [string] $Field) {
  Assert-Sim24Hour
  Send-SimPickerFields $Picker @('H', 'm', 's') @($When.ToString('HH'), $When.ToString('mm'), $When.ToString('ss')) $Field
  $got = Get-SimPicker $Picker
  if ($got.ToString('HH:mm:ss') -ne $When.ToString('HH:mm:ss')) { throw "$Field`: wanted $($When.ToString('HH:mm:ss')), the picker reads $($got.ToString('HH:mm:ss'))" }
}

# ---------------------------------------------------------------------------
# Menus: native Win32 menus, triggered with WM_COMMAND. Ids are resolved from
# the labels every time, so a renumbering SDK does not break callers.
# ---------------------------------------------------------------------------

function Format-MenuLabel([string] $s) { (($s -split "`t")[0] -replace '&', '').Trim() }

function Get-SimMenuItems([IntPtr] $Menu = [IntPtr]::Zero, [string] $Prefix = '') {
  if ($Menu -eq [IntPtr]::Zero) {
    $Menu = [SimNative]::GetMenu((Get-SimMainWindow))
    if ($Menu -eq [IntPtr]::Zero) { throw "the simulator window has no menu" }
  }
  $n = [SimNative]::GetMenuItemCount($Menu)
  for ($i = 0; $i -lt $n; $i++) {
    $sb = New-Object System.Text.StringBuilder 256
    [SimNative]::GetMenuString($Menu, [uint32]$i, $sb, 256, 0x400) | Out-Null
    $label = Format-MenuLabel $sb.ToString()
    if ($label -eq '') { continue }   # separator
    $state = [SimNative]::GetMenuState($Menu, [uint32]$i, 0x400)
    $sub = [SimNative]::GetSubMenu($Menu, $i)
    $path = if ($Prefix) { "$Prefix/$label" } else { $label }
    [pscustomobject]@{
      Path = $path; Label = $label; Id = [int64][SimNative]::GetMenuItemID($Menu, $i)
      Checked = [bool]($state -band 0x8); Disabled = [bool]($state -band 0x3)
      Submenu = ($sub -ne [IntPtr]::Zero); Menu = $Menu; Index = $i
    }
    if ($sub -ne [IntPtr]::Zero) { Get-SimMenuItems $sub $path }
  }
}

function Resolve-SimMenu([string] $Path) {
  $want = (($Path -split '/') | ForEach-Object { Format-MenuLabel $_ }) -join '/'
  $items = @(Get-SimMenuItems)
  $hit = @($items | Where-Object { $_.Path -ieq $want })
  if ($hit.Count -eq 0) {
    $parent = ($want -split '/' | Select-Object -SkipLast 1) -join '/'
    $siblings = $items | Where-Object { ($_.Path -split '/' | Select-Object -SkipLast 1) -join '/' -ieq $parent } | ForEach-Object { $_.Label }
    if (-not $siblings) { $siblings = $items | Where-Object { $_.Path -notmatch '/' } | ForEach-Object { $_.Label } }
    throw "no menu item '$want'; items at that level: $($siblings -join ' | ')"
  }
  $hit[0]
}

function Show-SimMenus {
  foreach ($m in Get-SimMenuItems) {
    $depth = ($m.Path -split '/').Count - 1
    $flags = @(); if ($m.Checked) { $flags += 'checked' }; if ($m.Disabled) { $flags += 'disabled' }
    if ($m.Submenu) { ('  ' * $depth) + "$($m.Label) >" }
    else { ('  ' * $depth) + "$($m.Label)  [id $($m.Id)] $($flags -join ',')" }
  }
}

# Posts a menu command and reports the item's check mark afterwards when it
# has one (a toggle or a radio item); a plain command reports "done".
function Invoke-SimMenu([Parameter(Mandatory)] [string] $Path) {
  $m = Resolve-SimMenu $Path
  if ($m.Submenu) { throw "'$($m.Path)' is a submenu, not a command" }
  if ($m.Disabled) { throw "'$($m.Path)' is disabled" }
  [SimNative]::Post((Get-SimMainWindow), $WM.COMMAND, $m.Id, 0) | Out-Null
  Start-Sleep -Milliseconds 500
  $after = Resolve-SimMenu $Path
  if ($after.Checked -or $m.Checked) { "$($after.Path): $(if ($after.Checked) { 'checked' } else { 'unchecked' })" }
  else { "$($after.Path): done" }
}

# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

# Opens the dialog behind a menu path and returns its window once it has
# settled. Any leftover popup is closed first so the new window is unambiguous.
function Open-SimDialog([string] $MenuPath) {
  Close-SimPopups | Out-Null
  $m = Resolve-SimMenu $MenuPath
  if ($m.Disabled) { throw "'$($m.Path)' is disabled" }
  $before = @([SimNative]::Windows((Get-SimPid)))
  [SimNative]::Post((Get-SimMainWindow), $WM.COMMAND, $m.Id, 0) | Out-Null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 200
    $new = @([SimNative]::Windows((Get-SimPid)) | Where-Object { $before -notcontains $_ })
    if ($new.Count) {
      Start-Sleep -Milliseconds $script:DialogSettleMs
      return $new[0]
    }
  }
  throw "'$MenuPath' opened no window"
}

# Closes a dialog with its OK/Save/Apply button (Apply-only dialogs are
# closed afterwards) and fails if a wx Debug Alert appears.
function Complete-SimDialog([IntPtr] $Dialog, [string[]] $Buttons = @('OK', 'Save', '&OK', '&Save', '&Apply', 'Apply')) {
  $b = Find-SimButton $Dialog $Buttons
  if (-not $b) { throw "no $($Buttons -join '/') button in '$([SimNative]::Caption($Dialog))'" }
  $label = [SimNative]::Caption($b)
  Invoke-SimClick $b
  Start-Sleep -Milliseconds 800
  Assert-SimNoAlert
  if ($label -match 'Apply' -and [SimNative]::IsWindow($Dialog) -and [SimNative]::IsWindowVisible($Dialog)) {
    [SimNative]::Post($Dialog, $WM.CLOSE, 0, 0) | Out-Null
    Start-Sleep -Milliseconds 500
    Close-SimPopups | Out-Null
  }
}

# The alert is a Task Dialog, whose text lives in a DirectUIHWND that Win32
# cannot read; UI Automation can.
function Get-SimAlertText([IntPtr] $Alert) {
  try {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    $el = [System.Windows.Automation.AutomationElement]::FromHandle($Alert)
    $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $texts = foreach ($e in $all) {
      $n = $e.Current.Name
      if ($n -and $e.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text) { $n }
    }
    (($texts | Select-Object -Unique) -join ' ' -replace '\s+', ' ').Trim()
  } catch { '' }
}

# A wxWidgets Debug Alert means wx's copy of a value diverged from the
# native control; it is dismissed with Continue and reported as a failure.
function Assert-SimNoAlert {
  foreach ($h in (Get-SimPopups)) {
    if ([SimNative]::Caption($h) -like '*Debug Alert*') {
      $msg = Get-SimAlertText $h
      $c = Find-SimButton $h @('Continue', '&Continue')
      if ($c) { Invoke-SimClick $c } else { [SimNative]::Post($h, $WM.CLOSE, 0, 0) | Out-Null }
      Start-Sleep -Milliseconds 400
      throw "wxWidgets Debug Alert: $msg"
    }
  }
}

# Dismisses every leftover simulator popup without applying anything:
# Debug Alerts get Continue, the "Stop Time Simulation?" box gets No (the
# simulation keeps running), other dialogs Cancel/Close or WM_CLOSE.
function Close-SimPopups {
  $closed = @()
  for ($round = 0; $round -lt 6; $round++) {
    $pops = @(Get-SimPopups)
    if ($pops.Count -eq 0) { break }
    foreach ($h in $pops) {
      if (-not [SimNative]::IsWindow($h)) { continue }
      $title = [SimNative]::Caption($h)
      $btn = $null
      if ($title -like '*Debug Alert*') { $btn = Find-SimButton $h @('Continue', '&Continue') }
      elseif ($title -eq 'Simulation') { $btn = Find-SimButton $h @('&No', 'No') }
      else { $btn = Find-SimButton $h @('Cancel', '&Cancel', 'Close', '&Close') }
      if ($btn) { Invoke-SimClick $btn } else { [SimNative]::Post($h, $WM.CLOSE, 0, 0) | Out-Null }
      $closed += "'$title'"
    }
    Start-Sleep -Milliseconds 700
  }
  if (@(Get-SimPopups).Count) { throw "popups still open after closing: $((@(Get-SimPopups) | ForEach-Object { [SimNative]::Caption($_) }) -join ', ')" }
  if ($closed.Count) { "closed $($closed -join ', ')" } else { "no popups" }
}

# Lists a dialog's controls with label, value and geometry: the reference
# for repairing a setter after an SDK changes a dialog.
function Get-SimDialogDump([Parameter(Mandatory)] [string] $MenuPath, [string] $Shot) {
  $dlg = Open-SimDialog $MenuPath
  try {
    "### '$([SimNative]::Caption($dlg))' ($MenuPath)"
    foreach ($c in (Get-SimControls $dlg -All)) {
      $value = ''
      switch ($c.Class) {
        'Edit' { $value = " value='$([SimNative]::Value($c.H))'" }
        'ComboBox' { $value = " selected='$(Get-SimComboText $c.H)' items=[$(@(Get-SimComboItems $c.H) -join ' | ')]" }
        'SysDateTimePick32' { $value = " value='$((Get-SimPicker $c.H).ToString('yyyy-MM-dd HH:mm:ss'))'" }
        'Button' { if ($c.Text -eq '' -or $c.Text -match 'Available') { $value = " checked=$(Get-SimCheck $c.H)" } }
        'msctls_trackbar32' { $value = " pos=$([SimNative]::Send($c.H, $WM.TBM_GETPOS, 0, 0)) range=$([SimNative]::Send($c.H, $WM.TBM_GETRANGEMIN, 0, 0))..$([SimNative]::Send($c.H, $WM.TBM_GETRANGEMAX, 0, 0))" }
        '_wx_SysTabCtl32' { $value = " tabs=$([SimNative]::Send($c.H, $WM.TCM_GETITEMCOUNT, 0, 0)) current=$([SimNative]::Send($c.H, $WM.TCM_GETCURSEL, 0, 0))" }
      }
      $vis = if ($c.Visible) { '' } else { ' hidden' }
      "  [{0}] {1} '{2}' @({3},{4} {5}x{6}){7}{8}" -f $c.Id, $c.Class, ($c.Text -replace "`r?`n", ' '), $c.Left, $c.Top, ($c.Right - $c.Left), ($c.Bottom - $c.Top), $vis, $value
    }
    if ($Shot) { Save-SimScreenshot -Path $Shot -Window $dlg | Out-Null; "  screenshot: $Shot" }
  } finally { Close-SimPopups | Out-Null }
}

# PrintWindow capture of the main window (or a given window), DPI-aware.
function Save-SimScreenshot([Parameter(Mandatory)] [string] $Path, [IntPtr] $Window = [IntPtr]::Zero) {
  if ($Window -eq [IntPtr]::Zero) { $Window = Get-SimMainWindow }
  $full = [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path (Get-Location) $Path }))
  $dir = Split-Path $full
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  Start-Sleep -Milliseconds 300
  $bmp = [SimNative]::Capture($Window)
  try { $bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png) } finally { $bmp.Dispose() }
  "screenshot: $full"
}

# ---------------------------------------------------------------------------
# Typed field access: one setter and one reader per control class
# ---------------------------------------------------------------------------

function ConvertTo-SimBool($Value, [string] $Field) {
  if ($Value -is [bool]) { return $Value }
  switch -Regex ([string]$Value) { '^(1|true|on|yes)$' { return $true } '^(0|false|off|no)$' { return $false } }
  throw "$Field`: '$Value' is not true/false"
}
function ConvertTo-SimDateTime($Value, [string] $Field) {
  if ($Value -is [datetime]) { return $Value }
  $t = [datetime]::MinValue
  if ([datetime]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$t)) { return $t }
  throw "$Field`: '$Value' is not a date/time (use 2026-09-03T10:09:42 or 07:30)"
}
# A hashtable from a hashtable, a JSON object, or "k=v,k=v" text.
function ConvertTo-SimMap($Value) {
  $m = @{}
  if ($null -eq $Value) { return $m }
  if ($Value -is [Collections.IDictionary]) { foreach ($k in $Value.Keys) { $m[[string]$k] = $Value[$k] }; return $m }
  if ($Value -is [pscustomobject]) { foreach ($p in $Value.PSObject.Properties) { $m[$p.Name] = $p.Value }; return $m }
  foreach ($pair in (([string]$Value) -split ',')) {
    if ($pair.Trim() -eq '') { continue }
    $kv = $pair -split '=', 2
    if ($kv.Count -ne 2) { throw "'$pair' is not name=value" }
    $m[$kv[0].Trim()] = $kv[1].Trim()
  }
  $m
}
# A list from a list, or from one comma-separated string.
function ConvertTo-SimList($Value) {
  if ($null -eq $Value) { return @() }
  @(@($Value) | ForEach-Object { ([string]$_) -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
}

# The Edit of a wxSpinCtrlDouble only takes typed text as its value on Enter
# or focus loss; a plain Edit or a native spin control reads its text directly.
function Test-SimSpinDoubleText([IntPtr] $Edit) {
  $p = [SimNative]::GetParent($Edit)
  $p -ne [IntPtr]::Zero -and [SimNative]::Caption($p) -eq 'wxSpinCtrlDouble'
}

function Set-SimTrackbar([IntPtr] $Bar, [int] $Pos, [string] $Field) {
  $min = [SimNative]::Send($Bar, $WM.TBM_GETRANGEMIN, 0, 0); $max = [SimNative]::Send($Bar, $WM.TBM_GETRANGEMAX, 0, 0)
  if ($Pos -lt $min -or $Pos -gt $max) { throw "$Field`: $Pos is outside $min..$max" }
  # Arrow keys step by the line size; an application that snaps the value
  # (Font Scale keeps multiples of 5) undoes that, so when an arrow changes
  # nothing the page keys take over, one press at a time with readback.
  $usePage = $false
  for ($n = 0; $n -lt 200; $n++) {
    $cur = [SimNative]::Send($Bar, $WM.TBM_GETPOS, 0, 0)
    if ($cur -eq $Pos) { break }
    $up = $Pos -gt $cur
    $key = if ($usePage) { if ($up) { $VK.NEXT } else { $VK.PRIOR } } else { if ($up) { $VK.RIGHT } else { $VK.LEFT } }
    Send-SimKey $Bar $key
    $now = [SimNative]::Send($Bar, $WM.TBM_GETPOS, 0, 0)
    if ($now -eq $cur) { if ($usePage) { break } else { $usePage = $true } }
    elseif (($up -and $now -gt $Pos) -or (-not $up -and $now -lt $Pos)) { break }   # stepped past: not a reachable value
  }
  Start-Sleep -Milliseconds 200
  $got = [SimNative]::Send($Bar, $WM.TBM_GETPOS, 0, 0)
  if ($got -ne $Pos) { throw "$Field`: wanted position $Pos, the slider stopped at $got (the dialog may only allow some steps)" }
}

function Set-SimInput([IntPtr] $H, $Value, [string] $Field, [string] $Kind) {
  switch ([SimNative]::Cls($H)) {
    'Edit' { Set-SimEdit $H ([string]$Value) $Field -Commit:(Test-SimSpinDoubleText $H) }
    'ComboBox' { Set-SimCombo $H ([string]$Value) $Field }
    'Button' { Set-SimCheck $H (ConvertTo-SimBool $Value $Field) $Field }
    'SysDateTimePick32' {
      $t = ConvertTo-SimDateTime $Value $Field
      if ($Kind -eq 'date') { Set-SimPickerDate $H $t $Field } else { Set-SimPickerTime $H $t $Field }
    }
    'msctls_trackbar32' { Set-SimTrackbar $H ([int]$Value) $Field }
    default { throw "$Field`: cannot type into a $_" }
  }
}
function Get-SimInput([IntPtr] $H, [string] $Kind) {
  switch ([SimNative]::Cls($H)) {
    'Edit' { [SimNative]::Value($H) }
    'ComboBox' { Get-SimComboText $H }
    'Button' { [string](Get-SimCheck $H) }
    'SysDateTimePick32' { $t = Get-SimPicker $H; if ($Kind -eq 'date') { $t.ToString('yyyy-MM-dd') } else { $t.ToString('HH:mm:ss') } }
    'msctls_trackbar32' { [string][SimNative]::Send($H, $WM.TBM_GETPOS, 0, 0) }
  }
}
function Test-SimInputValue([string] $Got, $Want, [string] $Class, [string] $Kind) {
  switch ($Class) {
    'Button' { return (ConvertTo-SimBool $Got '') -eq (ConvertTo-SimBool $Want '') }
    'ComboBox' { return $Got -ieq [string]$Want }
    'SysDateTimePick32' {
      $fmt = if ($Kind -eq 'date') { 'yyyy-MM-dd' } else { 'HH:mm:ss' }
      return $Got -eq (ConvertTo-SimDateTime $Want '').ToString($fmt)
    }
  }
  Test-SimSame $Got ([string]$Want)
}

# Opens a dialog, runs $Before (view selectors such as a sport type), types
# each given field in table order, runs $Extra (grids), confirms with
# OK/Save/Apply, then reopens the dialog, runs $Before again and checks every
# field (and runs $Check) unless -Verify is false. $Fields maps a parameter
# name to a field spec (see Resolve-SimFieldSpec).
function Set-SimDialog([string] $Menu, $Fields, [hashtable] $Values, [scriptblock] $Before, [scriptblock] $Extra, [scriptblock] $Check, [bool] $Verify = $true) {
  $order = @($Fields.Keys | Where-Object { $Values.ContainsKey($_) -and $null -ne $Values[$_] })
  $dlg = Open-SimDialog $Menu
  try {
    if ($Before) { & $Before $dlg }
    $ctl = @(Get-SimControls $dlg)
    # An optional field this device's dialog lacks is dropped, with a note.
    $present = @()
    foreach ($name in $order) {
      if ((Resolve-SimFieldSpec $Fields[$name]).Optional) {
        try { Find-SimInput $dlg $Fields[$name] $ctl | Out-Null } catch { "$name skipped: not in this device's dialog"; continue }
      }
      $present += $name
    }
    $order = $present
    foreach ($name in $order) {
      $s = Resolve-SimFieldSpec $Fields[$name]
      Set-SimInput (Find-SimInput $dlg $Fields[$name] $ctl) $Values[$name] $name $s.Kind
      Assert-SimNoAlert
    }
    if ($Extra) { & $Extra $dlg }
    Complete-SimDialog $dlg
  } catch {
    try { Close-SimPopups | Out-Null } catch { }
    throw
  }
  if (-not $Verify) { foreach ($name in $order) { "$name = $($Values[$name]) (not verified)" }; return }
  if (-not $order.Count -and -not $Check) { return }
  Start-Sleep -Milliseconds 500
  $dlg = Open-SimDialog $Menu
  try {
    if ($Before) { & $Before $dlg }
    $ctl = @(Get-SimControls $dlg)
    foreach ($name in $order) {
      $s = Resolve-SimFieldSpec $Fields[$name]
      $h = Find-SimInput $dlg $Fields[$name] $ctl
      $got = Get-SimInput $h $s.Kind
      if (-not (Test-SimInputValue $got $Values[$name] ([SimNative]::Cls($h)) $s.Kind)) {
        throw "$name`: set to '$($Values[$name])', but '$Menu' reads '$got' after reopening"
      }
      "$name = $got"
    }
    if ($Check) { & $Check $dlg }
  } finally { Close-SimPopups | Out-Null }
}

# The bound parameters of a dialog function, minus its own switches.
function Get-SimValues($Bound) {
  $v = @{}
  foreach ($k in $Bound.Keys) { if (@('NoVerify') -notcontains $k) { $v[$k] = $Bound[$k] } }
  $v
}

# ---------------------------------------------------------------------------
# Grids (wxGrid). Cells have no window of their own: the cursor is moved
# with arrow keys on the GridWindow, F2 opens the cell editor (typing alone
# does not), Return commits, Escape cancels. Column names are not readable
# through Win32, so each dialog lists its columns (from a screenshot).
# ---------------------------------------------------------------------------

# A dialog's visible grids, top to bottom as on screen (Windows enumerates
# them in another order).
function Get-SimGridWindows([IntPtr] $Dialog) {
  @(Get-SimControls $Dialog | Where-Object { $_.Class -eq 'wxWindowNR' -and $_.Text -eq 'GridWindow' } | Sort-Object Top, Left | ForEach-Object { $_.H })
}

function Open-SimGridEditor([IntPtr] $Dialog, [IntPtr] $Grid, [int] $Row, [int] $Col, [int] $Rows, [string] $Field) {
  Send-SimKey $Grid $VK.HOME
  Send-SimKey $Grid $VK.UP $Rows
  Send-SimKey $Grid $VK.DOWN $Row
  Send-SimKey $Grid $VK.RIGHT $Col
  $before = @(Get-SimControls $Dialog | ForEach-Object { $_.H })
  Send-SimKey $Grid $VK.F2
  for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 100
    $ed = @(Get-SimControls $Dialog | Where-Object { $before -notcontains $_.H -and @('Edit', 'ComboBox') -contains $_.Class })
    if ($ed.Count) { return $ed[0].H }
  }
  throw "$Field`: no cell editor opened at row $Row, column $Col (read-only cell?)"
}
function Get-SimGridCell([IntPtr] $Dialog, [IntPtr] $Grid, [int] $Row, [int] $Col, [int] $Rows, [string] $Field) {
  $ed = Open-SimGridEditor $Dialog $Grid $Row $Col $Rows $Field
  $v = if ([SimNative]::Cls($ed) -eq 'ComboBox') { Get-SimComboText $ed } else { [SimNative]::Value($ed) }
  Send-SimKey $ed $VK.ESCAPE
  Start-Sleep -Milliseconds 200
  $v
}
function Set-SimGridCell([IntPtr] $Dialog, [IntPtr] $Grid, [int] $Row, [int] $Col, [int] $Rows, $Value, [string] $Field) {
  $Value = [string]$Value
  $ed = Open-SimGridEditor $Dialog $Grid $Row $Col $Rows $Field
  try {
    if ([SimNative]::Cls($ed) -eq 'ComboBox') { Set-SimCombo $ed $Value $Field }
    else { Set-SimEdit $ed $Value $Field }
  } catch { Send-SimKey $ed $VK.ESCAPE; throw }
  Send-SimKey $ed $VK.RETURN
  Start-Sleep -Milliseconds 300
  Assert-SimNoAlert
  $got = Get-SimGridCell $Dialog $Grid $Row $Col $Rows $Field
  if (-not (Test-SimSame $got $Value)) { throw "$Field`: typed '$Value', the cell reads '$got' after Enter (out of range?)" }
}

# Turns a caller's rows into cell edits. $Rows is one map (a single-row grid)
# or a list of maps; a map's optional Row key picks the row, else its place
# in the list does. Column names are checked against $Columns.
function ConvertTo-SimCellEdits($Rows, [string[]] $Columns, [int] $RowCount, [string] $Field, [string[]] $RowNames) {
  $list = @($Rows)
  $edits = @()
  for ($i = 0; $i -lt $list.Count; $i++) {
    if ($null -eq $list[$i]) { continue }
    $m = ConvertTo-SimMap $list[$i]
    $row = $i
    if ($m.ContainsKey('Row')) {
      $r = [string]$m['Row']; $m.Remove('Row')
      if ($RowNames -and $RowNames -contains $r) { $row = [array]::IndexOf($RowNames, $r) } else { $row = [int]$r }
    }
    if ($row -lt 0 -or $row -ge $RowCount) { throw "$Field`: row $row is outside 0..$($RowCount - 1)" }
    foreach ($k in $m.Keys) {
      $col = -1
      for ($c = 0; $c -lt $Columns.Count; $c++) { if ($Columns[$c] -ieq $k) { $col = $c } }
      if ($col -lt 0) { throw "$Field`: no column '$k'; columns: $($Columns -join ', ')" }
      $edits += [pscustomobject]@{ Row = $row; Col = $col; Name = "$Field[$row].$($Columns[$col])"; Value = $m[$k] }
    }
  }
  # Left to right, as a user would fill zones whose bounds are checked in order.
  $edits | Sort-Object Row, Col
}
function Set-SimGridEdits([IntPtr] $Dialog, [IntPtr] $Grid, $Edits, [int] $RowCount) {
  foreach ($e in $Edits) { Set-SimGridCell $Dialog $Grid $e.Row $e.Col $RowCount $e.Value $e.Name }
}
function Test-SimGridEdits([IntPtr] $Dialog, [IntPtr] $Grid, $Edits, [int] $RowCount) {
  foreach ($e in $Edits) {
    $got = Get-SimGridCell $Dialog $Grid $e.Row $e.Col $RowCount $e.Name
    if (-not (Test-SimSame $got ([string]$e.Value))) { throw "$($e.Name): set to '$($e.Value)', but reads '$got' after reopening" }
    "$($e.Name) = $got"
  }
}

# ---------------------------------------------------------------------------
# Dialogs: one function each. The field tables are what to repair when an
# SDK changes a dialog (see README.md, "Repair").
# ---------------------------------------------------------------------------

$script:BatteryFields = [ordered]@{
  Percent = 'Battery Percentage'; DaysRemaining = 'Days Remaining'; Solar = 'Solar Intensity Percentage'; Charging = 'Battery Charging'
}
function Set-SimBattery([string] $Percent, [string] $DaysRemaining, [string] $Solar, [string] $Charging, [switch] $NoVerify) {
  Set-SimDialog 'Settings/Set Battery Status' $script:BatteryFields (Get-SimValues $PSBoundParameters) -Verify (-not $NoVerify)
}

$script:NotificationFields = [ordered]@{ Count = 'Phone Notifications'; NextEvent = 'Next Event Time|time' }
function Set-SimNotifications([string] $Count, [string] $NextEvent, [switch] $NoVerify) {
  Set-SimDialog 'Settings/Set Phone Notifications' $script:NotificationFields (Get-SimValues $PSBoundParameters) -Verify (-not $NoVerify)
}

$script:AlarmFields = [ordered]@{ Count = 'Number alarms' }
function Set-SimAlarms([string] $Count, [switch] $NoVerify) {
  Set-SimDialog 'Settings/Set Alarm Count' $script:AlarmFields (Get-SimValues $PSBoundParameters) -Verify (-not $NoVerify)
}

$script:PositionFields = [ordered]@{ LatLon = 'Enter the current position in decimal degrees (latitude, longitude)' }
function Set-SimPosition([string] $LatLon, [switch] $NoVerify) {
  Set-SimDialog 'Settings/Set Position' $script:PositionFields (Get-SimValues $PSBoundParameters) -Verify (-not $NoVerify)
}

# Font Scale: 0.80..1.45 in steps of 0.05 (slider position / 100).
function Set-SimTextSize([string] $Scale, [switch] $NoVerify) {
  $pos = [int][Math]::Round([double]::Parse($Scale, [Globalization.CultureInfo]::InvariantCulture) * 100)
  if ($pos % 5) { throw "Scale: $Scale is not a multiple of 0.05 (the dialog snaps to 0.05 steps)" }
  Set-SimDialog 'Settings/Font Scale' ([ordered]@{ Scale = 'A' }) @{ Scale = $pos } -Verify (-not $NoVerify) |
    ForEach-Object { if ($_ -match '^Scale = (\d+)$') { 'Scale = {0:0.00}' -f ([int]$Matches[1] / 100) } else { $_ } }
}

$script:WeatherFields = [ordered]@{
  ObservationDate = 'Observation Time|date'; ObservationTime = 'Observation Time#2|time'
  LocationName = 'Observation Location Name'; Lat = 'Observation Location Position'; Lon = 'Observation Location Position#2'
  Condition = 'Condition'; Temperature = 'Temperature (C)'; FeelsLike = 'Feels Like (C)'
  High = 'High Temperature (C)'; Low = 'Low Temperature (C)'; Humidity = 'Relative Humidity (%)'
  PrecipChance = 'Precipitation Chance (%)'; WindSpeed = 'Wind Speed (m/s)'; WindBearing = 'Wind Bearing (degrees)'
  UV = 'UV Index'; DewPoint = 'Dew Point (C)'; Visibility = 'Visibility (m)'; Pressure = 'Pressure (Pa)'
  CloudCover = 'Cloud Cover (%)'
}
$script:WeatherAvailable = 'button:Weather Data Available'
$script:HourlyColumns = @('Hour', 'Condition', 'Temperature', 'PrecipChance', 'Humidity', 'WindSpeed', 'WindBearing', 'UV', 'DewPoint', 'CloudCover')
$script:HourlyRows = 12
$script:DailyColumns = @('Day', 'Condition', 'High', 'Low', 'PrecipChance')
$script:DailyRows = 5

# Brings tab $Index of the dialog's tab control forward with arrow keys.
function Select-SimTab([IntPtr] $Dialog, [int] $Index) {
  $tab = @(Get-SimControls $Dialog | Where-Object { $_.Class -like '*SysTabCtl32' })[0].H
  $cur = [SimNative]::Send($tab, $WM.TCM_GETCURSEL, 0, 0)
  if ($Index -gt $cur) { Send-SimKey $tab $VK.RIGHT ($Index - $cur) } elseif ($Index -lt $cur) { Send-SimKey $tab $VK.LEFT ($cur - $Index) }
  Start-Sleep -Milliseconds 600
  $now = [SimNative]::Send($tab, $WM.TCM_GETCURSEL, 0, 0)
  if ($now -ne $Index) { throw "tab $Index wanted, tab $now is showing" }
}

# Weather Editor: current conditions, the hourly and daily forecast grids,
# and "Weather Data Available" (false makes the face's weather data null).
# Hourly/Daily rows: maps of column=value, optionally with Row (0 = top).
function Set-SimWeather {
  param(
    [string] $Available, [string] $Condition, [string] $Temperature, [string] $FeelsLike, [string] $High, [string] $Low,
    [string] $Humidity, [string] $PrecipChance, [string] $WindSpeed, [string] $WindBearing, [string] $UV,
    [string] $DewPoint, [string] $Visibility, [string] $Pressure, [string] $CloudCover,
    [string] $LocationName, [string] $Lat, [string] $Lon, [string] $ObservationDate, [string] $ObservationTime,
    [object[]] $Hourly, [object[]] $Daily, [switch] $NoVerify
  )
  $v = Get-SimValues $PSBoundParameters
  $v.Remove('Hourly'); $v.Remove('Daily')
  # Availability goes first when switching on and last when switching off,
  # so no field is typed while the editor treats the data as absent.
  $fields = [ordered]@{}
  $on = $PSBoundParameters.ContainsKey('Available') -and (ConvertTo-SimBool $Available 'Available')
  if ($on) { $fields['Available'] = $script:WeatherAvailable }
  foreach ($k in $script:WeatherFields.Keys) { $fields[$k] = $script:WeatherFields[$k] }
  if (-not $on) { $fields['Available'] = $script:WeatherAvailable }
  $hourlyEdits = @(if ($Hourly) { ConvertTo-SimCellEdits $Hourly $script:HourlyColumns $script:HourlyRows 'Hourly' })
  $dailyEdits = @(if ($Daily) { ConvertTo-SimCellEdits $Daily $script:DailyColumns $script:DailyRows 'Daily' })
  $grids = {
    param($dlg)
    if ($hourlyEdits.Count) { Select-SimTab $dlg 1; Set-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $hourlyEdits $script:HourlyRows }
    if ($dailyEdits.Count) { Select-SimTab $dlg 2; Set-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $dailyEdits $script:DailyRows }
  }
  $check = {
    param($dlg)
    if ($hourlyEdits.Count) { Select-SimTab $dlg 1; Test-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $hourlyEdits $script:HourlyRows }
    if ($dailyEdits.Count) { Select-SimTab $dlg 2; Test-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $dailyEdits $script:DailyRows }
  }
  Set-SimDialog 'Settings/Set Weather' $fields $v -Extra $grids -Check $check -Verify (-not $NoVerify)
}

$script:ActivityFields = [ordered]@{
  WeeklyActiveMinutesGoal = 'Weekly Active Minutes Goal'; RecoveryTime = 'Recovery Time (hours)'
  BreathsPerMinute = 'Breaths per Minute'; StressLevel = '?Current Stress Level'
}
$script:ActivityTodayColumns = @('StepsPerMinute', 'StepGoal', 'Steps', 'Distance', 'Calories', 'FloorsClimbed', 'FloorsDescended', 'FloorsClimbedGoal', 'ModerateMinutes', 'VigorousMinutes')
$script:ActivityHistoryColumns = @('Steps', 'StepGoal', 'Distance', 'Calories', 'ModerateMinutes', 'VigorousMinutes', 'FloorsClimbed', 'FloorsDescended', 'FloorsClimbedGoal')
$script:ActivityHistoryRows = 7   # Yesterday .. 7 Days Ago

# Edit Activity Monitor Info. -Today is one map (Steps=12345,Calories=800);
# -History a list of maps, row 0 = yesterday. Distance is in centimetres.
function Set-SimActivity {
  param(
    [object] $Today, [object[]] $History, [string] $WeeklyActiveMinutesGoal, [string] $RecoveryTime,
    [string] $BreathsPerMinute, [string] $StressLevel, [switch] $NoVerify
  )
  $v = Get-SimValues $PSBoundParameters
  $todayEdits = @(if ($Today) { ConvertTo-SimCellEdits @(, $Today) $script:ActivityTodayColumns 1 'Today' })
  $historyEdits = @(if ($History) { ConvertTo-SimCellEdits $History $script:ActivityHistoryColumns $script:ActivityHistoryRows 'History' })
  $grids = {
    param($dlg)
    $g = Get-SimGridWindows $dlg
    if ($todayEdits.Count) { Set-SimGridEdits $dlg $g[0] $todayEdits 1 }
    if ($historyEdits.Count) { Set-SimGridEdits $dlg $g[1] $historyEdits $script:ActivityHistoryRows }
  }
  $check = {
    param($dlg)
    $g = Get-SimGridWindows $dlg
    if ($todayEdits.Count) { Test-SimGridEdits $dlg $g[0] $todayEdits 1 }
    if ($historyEdits.Count) { Test-SimGridEdits $dlg $g[1] $historyEdits $script:ActivityHistoryRows }
  }
  Set-SimDialog 'Simulation/Activity Monitoring/Set Activity Monitor Info' $script:ActivityFields $v -Extra $grids -Check $check -Verify (-not $NoVerify)
}

$script:TrainingFields = [ordered]@{
  WeeklyRunKm = 'Weekly Distance Run (km)'; WeeklyBikeKm = 'Weekly Distance Biked (km)'; Status = 'Training Status'
}
$script:RaceColumns = @('PaceMinPerMile', 'PaceMps', 'TotalTime')
$script:RaceRows = @('5K', '10K', 'HalfMarathon', 'Marathon')

# Training Status. -RacePredictor: maps with Row (5K, 10K, HalfMarathon,
# Marathon) and one of PaceMinPerMile (mm:ss), PaceMps, TotalTime (hh:mm:ss).
function Set-SimTraining([string] $Status, [string] $WeeklyRunKm, [string] $WeeklyBikeKm, [object[]] $RacePredictor, [switch] $NoVerify) {
  $v = Get-SimValues $PSBoundParameters
  $edits = @(if ($RacePredictor) { ConvertTo-SimCellEdits $RacePredictor $script:RaceColumns $script:RaceRows.Count 'RacePredictor' $script:RaceRows })
  $grids = { param($dlg) if ($edits.Count) { Set-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $edits $script:RaceRows.Count } }
  $check = { param($dlg) if ($edits.Count) { Test-SimGridEdits $dlg (Get-SimGridWindows $dlg)[0] $edits $script:RaceRows.Count } }
  Set-SimDialog 'Settings/Set Training Status' $script:TrainingFields $v -Extra $grids -Check $check -Verify (-not $NoVerify)
}

# Units of height, weight and step length follow Settings > Units Display.
$script:ProfileFields = [ordered]@{
  Gender = 'Gender'; BirthYear = 'Birth Year'; Height = 'Height (*'; Weight = 'Weight (*'
  WakeTime = 'Wake Time|time'; SleepTime = 'Sleep Time|time'; RestingHR = 'Resting Heart Rate (bpm)'
  ActivityClass = 'Activity Class'; WalkingStepLength = 'Walking Step Length (*'; RunningStepLength = 'Running Step Length (*'
  VO2Max = 'Activity Type#2'; FTP = 'FTP (watts)'
}
$script:HrZoneColumns = @('Zone1Min', 'Zone1Max', 'Zone2Max', 'Zone3Max', 'Zone4Max', 'Zone5Max')
$script:PowerZoneColumns = @('Zone1Min', 'Zone1Max', 'Zone2Max', 'Zone3Max', 'Zone4Max', 'Zone5Max', 'Zone6Max', 'Zone7Max')

# User Profile Editor. -HrZones / -PowerZones: values in column order (or a
# map Zone1Min=..), for the sport chosen with -HrSport / -PowerSport; -VO2Max
# and -FTP likewise apply to -VO2MaxActivity / -PowerSport. Those three only
# pick what the dialog shows; they are not saved state.
function Set-SimProfile {
  param(
    [string] $Gender, [string] $BirthYear, [string] $Height, [string] $Weight, [string] $WakeTime, [string] $SleepTime,
    [string] $RestingHR, [string] $ActivityClass, [string] $WalkingStepLength, [string] $RunningStepLength,
    [string] $VO2Max, [string] $VO2MaxActivity, [string] $FTP,
    [string] $HrSport, [object] $HrZones, [string] $PowerSport, [object] $PowerZones, [switch] $NoVerify
  )
  $v = Get-SimValues $PSBoundParameters
  foreach ($k in 'VO2MaxActivity', 'HrSport', 'HrZones', 'PowerSport', 'PowerZones') { $v.Remove($k) }
  $zoneMap = {
    param($z, [string[]] $cols)
    if ($null -eq $z) { return $null }
    if ($z -is [string] -and $z -notmatch '=') { $z = @($z -split ',') }
    if ($z -is [array]) { $m = @{}; for ($i = 0; $i -lt $z.Count; $i++) { if ([string]$z[$i] -ne '') { $m[$cols[$i]] = $z[$i] } }; return $m }
    $z
  }
  $hrEdits = @(if ($HrZones) { ConvertTo-SimCellEdits @(, (& $zoneMap $HrZones $script:HrZoneColumns)) $script:HrZoneColumns 1 'HrZones' })
  $pwEdits = @(if ($PowerZones) { ConvertTo-SimCellEdits @(, (& $zoneMap $PowerZones $script:PowerZoneColumns)) $script:PowerZoneColumns 1 'PowerZones' })
  # The selectors run before the fields, when setting and again when verifying.
  $select = {
    param($dlg)
    $ctl = @(Get-SimControls $dlg)
    if ($VO2MaxActivity) { Set-SimCombo (Find-SimInput $dlg 'Activity Type' $ctl) $VO2MaxActivity 'VO2MaxActivity' }
    if ($HrSport) { Set-SimCombo (Find-SimInput $dlg 'Sport Type@1' $ctl) $HrSport 'HrSport' }
    if ($PowerSport) { Set-SimCombo (Find-SimInput $dlg 'Sport Type@2' $ctl) $PowerSport 'PowerSport' }
    Start-Sleep -Milliseconds 300
  }
  $grids = {
    param($dlg)
    $g = Get-SimGridWindows $dlg
    if ($hrEdits.Count) { Set-SimGridEdits $dlg $g[0] $hrEdits 1 }
    if ($pwEdits.Count) { Set-SimGridEdits $dlg $g[1] $pwEdits 1 }
  }
  $check = {
    param($dlg)
    $g = Get-SimGridWindows $dlg
    if ($hrEdits.Count) { Test-SimGridEdits $dlg $g[0] $hrEdits 1 }
    if ($pwEdits.Count) { Test-SimGridEdits $dlg $g[1] $pwEdits 1 }
  }
  Set-SimDialog 'Settings/Set User Profile' $script:ProfileFields $v -Before $select -Extra $grids -Check $check -Verify (-not $NoVerify)
}

# Watch Face Editor (the face's on-device configuration). -Slot takes
# "1=Steps","3=Battery": complication slot number = complication name.
$script:FaceFields = [ordered]@{ Style = 'Style'; Accent = 'Accent Color'; Data = 'Data Color' }
function Set-SimFace([string] $Style, [string] $Accent, [string] $Data, [string[]] $Slot, [switch] $NoVerify) {
  $v = Get-SimValues $PSBoundParameters
  $v.Remove('Slot')
  $slots = [ordered]@{}
  foreach ($s in (ConvertTo-SimList $Slot)) {
    $kv = $s -split '=', 2
    if ($kv.Count -ne 2) { throw "Slot: '$s' is not <number>=<complication>" }
    $slots[$kv[0].Trim()] = $kv[1].Trim()
  }
  $pick = {
    param($dlg, [string] $n)
    $ctl = @(Get-SimControls $dlg)
    Set-SimCombo (Find-SimInput $dlg 'Data Field' $ctl) $n "Slot $n"
    Start-Sleep -Milliseconds 300
    Find-SimInput $dlg 'Complications' $ctl
  }
  $grids = {
    param($dlg)
    foreach ($n in $slots.Keys) { $c = & $pick $dlg $n; Set-SimCombo $c $slots[$n] "Slot $n"; if ($NoVerify) { "Slot $n = $($slots[$n]) (not verified)" } }
  }
  $check = {
    param($dlg)
    foreach ($n in $slots.Keys) {
      $got = Get-SimComboText (& $pick $dlg $n)
      if ($got -ne $slots[$n]) { throw "Slot $n`: set to '$($slots[$n])', but reads '$got' after reopening" }
      "Slot $n = $got"
    }
  }
  Set-SimDialog 'File/Edit Watch Face' $script:FaceFields $v -Extra $grids -Check $check -Verify (-not $NoVerify)
}

# Time Simulation: types the date and time, checks the pickers before
# pressing Start, and leaves the simulation running (closing the dialog asks
# "Stop Time Simulation?", answered No). -Stop returns to real time.
function Set-SimTime([string] $When, [switch] $Stop, [switch] $NoVerify) {
  if (-not $Stop -and -not $When) { throw "time: give a date-time (2026-09-03T10:09:42) or -Stop" }
  $dlg = Open-SimDialog 'Simulation/Time Simulation'
  try {
    Invoke-SimClick (Find-SimButton $dlg @('Stop'))
    Start-Sleep -Milliseconds 600
    Assert-SimNoAlert
    if ($Stop) { "time simulation stopped"; return }
    $t = ConvertTo-SimDateTime $When 'time'
    $pickers = @(Get-SimControls $dlg | Where-Object { $_.Class -eq 'SysDateTimePick32' } | Sort-Object Left)
    Set-SimPickerDate $pickers[0].H $t 'time (date)'
    Set-SimPickerTime $pickers[1].H $t 'time (clock)'
    Invoke-SimClick (Find-SimButton $dlg @('Start'))
    Start-Sleep -Milliseconds 800
    Assert-SimNoAlert
  } finally { Close-SimPopups | Out-Null }
  if ($NoVerify) { "time simulation running from $($t.ToString('s')) (not verified)"; return }
  # Reopened, the pickers show the running clock: a little after the start.
  $dlg = Open-SimDialog 'Simulation/Time Simulation'
  try {
    $pickers = @(Get-SimControls $dlg | Where-Object { $_.Class -eq 'SysDateTimePick32' } | Sort-Object Left)
    $d = Get-SimPicker $pickers[0].H; $c = Get-SimPicker $pickers[1].H
    $now = New-Object DateTime $d.Year, $d.Month, $d.Day, $c.Hour, $c.Minute, $c.Second
    $lag = ($now - $t).TotalSeconds
    if ($lag -lt -2 -or $lag -gt 300) { throw "time: started at $($t.ToString('s')), but the simulation reads $($now.ToString('s'))" }
    "time simulation running from $($t.ToString('s')) (reads $($now.ToString('s')))"
  } finally { Close-SimPopups | Out-Null }
}

# ---------------------------------------------------------------------------
# Scenarios and the command line
# ---------------------------------------------------------------------------

# Command name -> function, and the parameter a bare (positional) value fills.
$script:SimCommands = [ordered]@{
  'menu' = @('Invoke-SimMenu', 'Path'); 'menus' = @('Show-SimMenus', $null)
  'battery' = @('Set-SimBattery', $null); 'time' = @('Set-SimTime', 'When'); 'face' = @('Set-SimFace', $null)
  'weather' = @('Set-SimWeather', $null); 'activity' = @('Set-SimActivity', $null)
  'notifications' = @('Set-SimNotifications', 'Count'); 'alarms' = @('Set-SimAlarms', 'Count')
  'position' = @('Set-SimPosition', 'LatLon'); 'profile' = @('Set-SimProfile', $null)
  'training' = @('Set-SimTraining', $null); 'textsize' = @('Set-SimTextSize', 'Scale')
  'screenshot' = @('Save-SimScreenshot', 'Path'); 'dump' = @('Get-SimDialogDump', 'MenuPath')
  'close-popups' = @('Close-SimPopups', $null); 'scenario' = @('Invoke-SimScenario', 'Path')
}

function Invoke-SimCommand([string] $Name, [hashtable] $Named = @{}, $Positional) {
  if (-not $script:SimCommands.Contains($Name)) { throw "unknown command '$Name'; commands: $($script:SimCommands.Keys -join ', ')" }
  $fn, $pos = $script:SimCommands[$Name]
  $args2 = @{} + $Named
  $plist = @($Positional | Where-Object { $null -ne $_ })
  if ($plist.Count) {
    if (-not $pos) { throw "$Name takes no bare value (got '$($plist -join ' ')')" }
    $args2[$pos] = if ($plist.Count -eq 1) { $plist[0] } else { $plist }
  }
  & $fn @args2
}

# Parses "-Name value [value...]" tokens. A token is a name only if it is
# -Letter...; "-5" stays a value. A name with no value is a switch.
function ConvertFrom-SimArgs([object[]] $Tokens) {
  $named = @{}; $positional = @(); $cur = $null; $vals = @()
  $flush = { if ($cur) { $named[$cur] = if ($vals.Count -eq 0) { $true } elseif ($vals.Count -eq 1) { $vals[0] } else { $vals } } }
  foreach ($t in @($Tokens)) {
    if ($t -is [string] -and $t -match '^-([A-Za-z]\w*)$') { . $flush; $cur = $Matches[1]; $vals = @() }
    elseif ($cur) { $vals += $t }
    else { $positional += $t }
  }
  . $flush
  @{ Named = $named; Positional = $positional }
}

# Runs a JSON scenario: a list of one-key objects, {"command": arguments}.
# Arguments are an object (named), or a bare value (the command's
# positional parameter). Time is applied last: other dialogs make the time
# simulation fall back to real time, so a step after "time" earns a warning.
function Invoke-SimScenario([Parameter(Mandatory)] [string] $Path) {
  # PowerShell 5.1 returns a JSON array as one object; the pipeline unrolls it.
  $steps = @(ConvertFrom-Json (Get-Content -Raw -Encoding UTF8 $Path) | ForEach-Object { $_ })
  $timeAt = -1
  for ($i = 0; $i -lt $steps.Count; $i++) {
    $props = @($steps[$i].PSObject.Properties)
    if ($props.Count -ne 1) { throw "step $($i + 1): expected one command per step, got $($props.Name -join ', ')" }
    $name = $props[0].Name
    if (-not $script:SimCommands.Contains($name)) { throw "step $($i + 1): unknown command '$name'" }
    if ($name -eq 'time') { $timeAt = $i }
    elseif ($timeAt -ge 0 -and @('screenshot', 'close-popups') -notcontains $name) {
      Write-Warning "step $($i + 1) ('$name') comes after 'time': the time simulation may fall back to real time"
    }
  }
  for ($i = 0; $i -lt $steps.Count; $i++) {
    $p = @($steps[$i].PSObject.Properties)[0]
    "[$($i + 1)/$($steps.Count)] $($p.Name)"
    if ($p.Value -is [pscustomobject]) { Invoke-SimCommand $p.Name (ConvertTo-SimMap $p.Value) }
    elseif ($null -eq $p.Value -or ($p.Value -is [bool] -and $p.Value)) { Invoke-SimCommand $p.Name @{} }
    else { Invoke-SimCommand $p.Name @{} @(, $p.Value) }
  }
}

if ($MyInvocation.InvocationName -ne '.') {
  if (-not $Command -or @('help', '-h', '--help', '/?') -contains $Command) {
    "usage: simctl.ps1 <command> [args]   (README.md has examples)"
    "commands: $($script:SimCommands.Keys -join ', ')"
    exit 0
  }
  try {
    $parsed = ConvertFrom-SimArgs @($CommandArgs)
    Invoke-SimCommand $Command $parsed.Named $parsed.Positional
    exit 0
  } catch {
    [Console]::Error.WriteLine("simctl $Command failed: $($_.Exception.Message)")
    exit 1
  }
}
