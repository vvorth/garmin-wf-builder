import Toybox.ActivityMonitor;
import Toybox.Complications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

//! Dumps every complication the face can see: its type, value, unit and
//! `ranges`. Once to the log on load, and on screen a page of rows at a
//! time, turning to the next page every minute.
class ProbeView extends WatchUi.WatchFace {
    const ROWS_PER_PAGE = 7;

    var _rows as Array<String> = [];

    function initialize() {
        WatchFace.initialize();
    }

    function onLayout(dc as Dc) as Void {
        _rows = collect();
        var info = ActivityMonitor.getInfo();
        System.println("goals: stepGoal=" + info.stepGoal
            + " floorsClimbedGoal=" + info.floorsClimbedGoal
            + " activeMinutesWeekGoal=" + info.activeMinutesWeekGoal
            + " steps=" + info.steps
            + " floorsClimbed=" + info.floorsClimbed);
        for (var i = 0; i < _rows.size(); i++) {
            System.println(_rows[i]);
        }
    }

    //! One line per complication: `type|value|unit|ranges`. A `type` of 0
    //! (COMPLICATION_TYPE_INVALID) is a Connect IQ app's complication, so
    //! its long label is logged too.
    function collect() as Array<String> {
        var rows = [] as Array<String>;
        var iter = Complications.getComplications();
        var c = iter.next();
        while (c != null) {
            var type = c.getType();
            var row = "t" + type + "|v=" + c.value + "|u=" + c.unit
                + "|r=" + c.ranges;
            if (type == Complications.COMPLICATION_TYPE_INVALID) {
                row += "|" + c.longLabel;
            }
            rows.add(row);
            c = iter.next();
        }
        return rows;
    }

    function onUpdate(dc as Dc) as Void {
        // Re-read each minute: a value (and possibly its ranges) moves.
        _rows = collect();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();
        var pages = (_rows.size() + ROWS_PER_PAGE - 1) / ROWS_PER_PAGE;
        if (pages == 0) {
            dc.drawText(dc.getWidth() / 2, dc.getHeight() / 2,
                Graphics.FONT_XTINY, "no complications",
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }
        var page = System.getClockTime().min % pages;
        var lineHeight = dc.getFontHeight(Graphics.FONT_XTINY);
        var y = dc.getHeight() / 2 - (ROWS_PER_PAGE * lineHeight) / 2;
        dc.drawText(dc.getWidth() / 2, y - lineHeight, Graphics.FONT_XTINY,
            (page + 1) + "/" + pages, Graphics.TEXT_JUSTIFY_CENTER);
        for (var i = page * ROWS_PER_PAGE;
                i < _rows.size() && i < (page + 1) * ROWS_PER_PAGE; i++) {
            dc.drawText(dc.getWidth() / 2, y, Graphics.FONT_XTINY, _rows[i],
                Graphics.TEXT_JUSTIFY_CENTER);
            y += lineHeight;
        }
    }
}
