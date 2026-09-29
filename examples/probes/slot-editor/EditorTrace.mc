// Hand-written for the slot-editor probe's trace build (`trace.py`), which
// copies it into the generated project. Never part of an ordinary build.
//
// Records what the native editor calls, and draws it on the face so a photo
// is the log. Three lines, white, FONT_XTINY:
//
//   line 1, just below the centre:  P<pulsing> U<onUpdate count> :<seconds>
//   line 2, below it:               the last four events, newest first
//   line 3, below the bottom card:  D<slot> x<draw count> <seconds since>s
//
// Events: G<n> getComplicationDrawable(slot n); E<t><c> onWatchFaceConfigEdited
// with :type S style, C complication, A accent, K data colour, - null, and
// :committed y/n; T<n> onTap (0: no slot hit); L onLayout; V onShow;
// H onHide; W onExitSleep; Z onEnterSleep. Every event requests an update,
// so a callback shows even if the editor would not have redrawn on its own.

import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

module EditorTrace {
    var events as Array<String> = [] as Array<String>;
    var updates as Number = 0;
    var draws as Number = 0;
    var drawSlot as Number = 0;
    var drawAt as Number = 0;

    function note(event as String) as Void {
        events.add(event);
        if (events.size() > 4) {
            events = events.slice(1, null);
        }
        WatchUi.requestUpdate();
    }

    function edited(type as Number?, committed as Boolean?) as Void {
        var t = "-";
        if (type == WatchUi.WATCH_FACE_CONFIG_TYPE_STYLE) {
            t = "S";
        } else if (type == WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION) {
            t = "C";
        } else if (type == WatchUi.WATCH_FACE_CONFIG_TYPE_ACCENT_COLOR) {
            t = "A";
        } else if (type == WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION_COLOR) {
            t = "K";
        } else if (type != null) {
            t = type.toString();
        }
        note("E" + t + ((committed != null && committed) ? "y" : "n"));
    }

    function drew(slot as Number) as Void {
        draws += 1;
        drawSlot = slot;
        drawAt = System.getTimer();
    }

    function draw(dc as Dc, pulsing as Number) as Void {
        updates += 1;
        var r = dc.getWidth() / 2;
        var cx = r;
        var cy = dc.getHeight() / 2;
        var fh = dc.getFontHeight(Graphics.FONT_XTINY);
        var clock = System.getClockTime();

        var log = "";
        for (var i = events.size() - 1; i >= 0; i -= 1) {
            log += events[i] + " ";
        }
        var age = draws == 0 ? "-" : ((System.getTimer() - drawAt) / 1000.0).format("%.1f");

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, cy - 4, Graphics.FONT_XTINY,
                    "P" + pulsing + " U" + updates + " :" + clock.sec.format("%02d"),
                    Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx, cy - 4 + fh, Graphics.FONT_XTINY, log, Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx, cy + r * 58 / 100, Graphics.FONT_XTINY,
                    "D" + drawSlot + " x" + draws + " " + age + "s",
                    Graphics.TEXT_JUSTIFY_CENTER);
    }
}
