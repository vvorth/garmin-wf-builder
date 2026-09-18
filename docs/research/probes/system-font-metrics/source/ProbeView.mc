import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

//! Probe: system-font-metrics (docs/plans/09-system-font-metrics.md S4 R3).
//!
//! On the first `onUpdate`, prints one line per `FONT_*` constant the SDK
//! defines ($CIQ_SDK/bin/api.debug.xml, `symbol="FONT_*"`) to the console
//! via `System.println`, then draws the same data as a compact table on
//! screen in `FONT_XTINY`. See README.md for the exact console line shape,
//! how to read it in the simulator, what the numbers feed into
//! (`docs/plans/09-system-font-metrics.md` S4 R2/R3), and the SDK doc
//! paths for every API this file calls.
class ProbeView extends WatchUi.WatchFace {
    //! One "SHORT:height" entry per reported font, built once and reused
    //! by every `onUpdate` (the console line is `System.println`'d once
    //! too -- nothing here changes frame to frame, so there is no reason
    //! to repeat either).
    private var _rows as Array<String> = [] as Array<String>;
    private var _collected as Boolean = false;

    function initialize() {
        WatchFace.initialize();
    }

    //! Load resources once. Loading is expensive and must not happen per frame.
    function onLayout(dc as Dc) as Void {
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        if (!_collected) {
            collect(dc);
            _collected = true;
        }
        drawTable(dc);
    }

    function onExitSleep() as Void {
        WatchUi.requestUpdate();
    }

    function onEnterSleep() as Void {
        WatchUi.requestUpdate();
    }

    //! Reports every `FONT_*` constant the SDK defines. Each is
    //! `has`-guarded: `CLAUDE.md` constraint 6 ("API level does not decide
    //! availability -- resolve against the device's own `api.debug.xml`"),
    //! and per-device availability is exactly what `Graphics has :FONT_*`
    //! answers at runtime. All 29 constants happen to be present in all
    //! three probe targets' own `<id>.api.debug.xml` (checked before
    //! writing this file), so every guard here is true on the targets this
    //! probe actually ships to -- but the guard is what makes the same
    //! source correct on a fourth target that lacks one, without a
    //! per-device source split (`docs/research/probes/device-symbol-gate/`).
    private function collect(dc as Dc) as Void {
        // -- the five text sizes ------------------------------------------
        if (Graphics has :FONT_XTINY) { report(dc, "FONT_XTINY", "XT", Graphics.FONT_XTINY); }
        if (Graphics has :FONT_TINY) { report(dc, "FONT_TINY", "TI", Graphics.FONT_TINY); }
        if (Graphics has :FONT_SMALL) { report(dc, "FONT_SMALL", "SM", Graphics.FONT_SMALL); }
        if (Graphics has :FONT_MEDIUM) { report(dc, "FONT_MEDIUM", "MD", Graphics.FONT_MEDIUM); }
        if (Graphics has :FONT_LARGE) { report(dc, "FONT_LARGE", "LG", Graphics.FONT_LARGE); }

        // -- the four number sizes -----------------------------------------
        if (Graphics has :FONT_NUMBER_MILD) { report(dc, "FONT_NUMBER_MILD", "NM", Graphics.FONT_NUMBER_MILD); }
        if (Graphics has :FONT_NUMBER_MEDIUM) { report(dc, "FONT_NUMBER_MEDIUM", "NMD", Graphics.FONT_NUMBER_MEDIUM); }
        if (Graphics has :FONT_NUMBER_HOT) { report(dc, "FONT_NUMBER_HOT", "NH", Graphics.FONT_NUMBER_HOT); }
        if (Graphics has :FONT_NUMBER_THAI_HOT) { report(dc, "FONT_NUMBER_THAI_HOT", "NTH", Graphics.FONT_NUMBER_THAI_HOT); }

        // -- the five FONT_SYSTEM_* sizes (glance/complication editors) ----
        if (Graphics has :FONT_SYSTEM_XTINY) { report(dc, "FONT_SYSTEM_XTINY", "sXT", Graphics.FONT_SYSTEM_XTINY); }
        if (Graphics has :FONT_SYSTEM_TINY) { report(dc, "FONT_SYSTEM_TINY", "sTI", Graphics.FONT_SYSTEM_TINY); }
        if (Graphics has :FONT_SYSTEM_SMALL) { report(dc, "FONT_SYSTEM_SMALL", "sSM", Graphics.FONT_SYSTEM_SMALL); }
        if (Graphics has :FONT_SYSTEM_MEDIUM) { report(dc, "FONT_SYSTEM_MEDIUM", "sMD", Graphics.FONT_SYSTEM_MEDIUM); }
        if (Graphics has :FONT_SYSTEM_LARGE) { report(dc, "FONT_SYSTEM_LARGE", "sLG", Graphics.FONT_SYSTEM_LARGE); }

        // -- the four FONT_SYSTEM_NUMBER_* sizes ----------------------------
        if (Graphics has :FONT_SYSTEM_NUMBER_MILD) { report(dc, "FONT_SYSTEM_NUMBER_MILD", "sNM", Graphics.FONT_SYSTEM_NUMBER_MILD); }
        if (Graphics has :FONT_SYSTEM_NUMBER_MEDIUM) { report(dc, "FONT_SYSTEM_NUMBER_MEDIUM", "sNMD", Graphics.FONT_SYSTEM_NUMBER_MEDIUM); }
        if (Graphics has :FONT_SYSTEM_NUMBER_HOT) { report(dc, "FONT_SYSTEM_NUMBER_HOT", "sNH", Graphics.FONT_SYSTEM_NUMBER_HOT); }
        if (Graphics has :FONT_SYSTEM_NUMBER_THAI_HOT) { report(dc, "FONT_SYSTEM_NUMBER_THAI_HOT", "sNTH", Graphics.FONT_SYSTEM_NUMBER_THAI_HOT); }

        // -- glance ----------------------------------------------------------
        if (Graphics has :FONT_GLANCE) { report(dc, "FONT_GLANCE", "GL", Graphics.FONT_GLANCE); }
        if (Graphics has :FONT_GLANCE_NUMBER) { report(dc, "FONT_GLANCE_NUMBER", "GLN", Graphics.FONT_GLANCE_NUMBER); }

        // -- the nine auxiliary fonts ------------------------------------
        if (Graphics has :FONT_AUX1) { report(dc, "FONT_AUX1", "A1", Graphics.FONT_AUX1); }
        if (Graphics has :FONT_AUX2) { report(dc, "FONT_AUX2", "A2", Graphics.FONT_AUX2); }
        if (Graphics has :FONT_AUX3) { report(dc, "FONT_AUX3", "A3", Graphics.FONT_AUX3); }
        if (Graphics has :FONT_AUX4) { report(dc, "FONT_AUX4", "A4", Graphics.FONT_AUX4); }
        if (Graphics has :FONT_AUX5) { report(dc, "FONT_AUX5", "A5", Graphics.FONT_AUX5); }
        if (Graphics has :FONT_AUX6) { report(dc, "FONT_AUX6", "A6", Graphics.FONT_AUX6); }
        if (Graphics has :FONT_AUX7) { report(dc, "FONT_AUX7", "A7", Graphics.FONT_AUX7); }
        if (Graphics has :FONT_AUX8) { report(dc, "FONT_AUX8", "A8", Graphics.FONT_AUX8); }
        if (Graphics has :FONT_AUX9) { report(dc, "FONT_AUX9", "A9", Graphics.FONT_AUX9); }
    }

    //! `System.println`s exactly:
    //!   FONT_X h=<Graphics.getFontHeight> a=<Graphics.getFontAscent>
    //!          d=<Graphics.getFontDescent> w1=<dc.getTextWidthInPixels("Hxg0123", f)>
    //!          w2=<dc.getTextWidthInPixels("0123456789", f)>
    //! (one line; wrapped here only for this comment) and appends a
    //! "SHORT:height" entry to `_rows` for the on-screen table.
    private function report(dc as Dc, label as String, short as String, font as Graphics.FontType) as Void {
        var h = Graphics.getFontHeight(font);
        var a = Graphics.getFontAscent(font);
        var d = Graphics.getFontDescent(font);
        var w1 = dc.getTextWidthInPixels("Hxg0123", font);
        var w2 = dc.getTextWidthInPixels("0123456789", font);
        System.println(Lang.format("$1$ h=$2$ a=$3$ d=$4$ w1=$5$ w2=$6$", [label, h, a, d, w1, w2]));
        _rows.add(Lang.format("$1$:$2$", [short, h]));
    }

    //! The same table `collect` built, drawn on screen in `FONT_XTINY`.
    //! Three columns, computed from the live screen size rather than a
    //! hardcoded one, so ~29 rows fit a 260px round screen without
    //! guessing at a per-device layout.
    private function drawTable(dc as Dc) as Void {
        var font = Graphics.FONT_XTINY;
        var lineHeight = Graphics.getFontHeight(font);
        var margin = 4;
        var usableHeight = dc.getHeight() - 2 * margin;
        var rowsPerColumn = usableHeight / lineHeight;
        if (rowsPerColumn < 1) {
            rowsPerColumn = 1;
        }
        var columnWidth = (dc.getWidth() - 2 * margin) / 3;

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        var i = 0;
        while (i < _rows.size()) {
            var column = i / rowsPerColumn;
            var row = i % rowsPerColumn;
            var x = margin + column * columnWidth;
            var y = margin + row * lineHeight;
            dc.drawText(x, y, font, _rows[i], Graphics.TEXT_JUSTIFY_LEFT);
            i = i + 1;
        }
    }
}
