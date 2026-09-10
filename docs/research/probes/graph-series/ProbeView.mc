import Toybox.Activity;
import Toybox.ActivityMonitor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

//! Probe: can a watch face build a time series for a graph element?
class ProbeView extends WatchUi.WatchFace {

    //! The series, rebuilt when the minute changes.
    private var _series as Array<Number> = [] as Array<Number>;
    private var _seriesMin as Number = 0;
    private var _seriesMax as Number = 0;
    private var _builtAt as Number = -1;

    function initialize() { WatchFace.initialize(); }

    //! 1. Heart-rate history by DURATION -- "the last 4 hours".
    function hrByDuration(minutes as Number, buckets as Number) as Void {
        var iterator = ActivityMonitor.getHeartRateHistory(
            new Time.Duration(minutes * 60), false);
        var sums = new [buckets] as Array<Number>;
        var counts = new [buckets] as Array<Number>;
        for (var i = 0; i < buckets; i += 1) { sums[i] = 0; counts[i] = 0; }

        var now = Time.now().value();
        var span = minutes * 60;
        var seen = 0;
        while (true) {
            var sample = iterator.next();
            if (sample == null) { break; }
            var bpm = sample.heartRate;
            var when = sample.when;
            if (bpm == null || when == null) { continue; }
            if (bpm == ActivityMonitor.INVALID_HR_SAMPLE) { continue; }
            var age = now - when.value();
            if (age < 0) { age = 0; }
            if (age > span) { continue; }
            var index = buckets - 1 - (age * buckets / span);
            if (index < 0) { index = 0; }
            if (index >= buckets) { index = buckets - 1; }
            sums[index] = sums[index] + bpm;
            counts[index] = counts[index] + 1;
            seen += 1;
        }

        var out = new [buckets] as Array<Number>;
        for (var i = 0; i < buckets; i += 1) {
            out[i] = (counts[i] > 0) ? (sums[i] / counts[i]) : -1;
        }
        _series = out;
        _seriesMin = 0;
        _seriesMax = 0;
    }

    //! 2. Heart-rate history by COUNT -- "the last 30 samples", and the
    //! iterator's own min/max, which is what an automatic axis wants.
    function hrByCount(count as Number) as Void {
        var iterator = ActivityMonitor.getHeartRateHistory(count, false);
        var lo = iterator.getMin();
        var hi = iterator.getMax();
        _seriesMin = (lo != null) ? lo : 0;
        _seriesMax = (hi != null) ? hi : 0;
        var out = [] as Array<Number>;
        while (true) {
            var sample = iterator.next();
            if (sample == null) { break; }
            var bpm = sample.heartRate;
            if (bpm == null || bpm == ActivityMonitor.INVALID_HR_SAMPLE) { continue; }
            out.add(bpm);
        }
        _series = out;
    }

    //! 3. Daily history -- up to 7 days of steps, newest first.
    function dailySteps() as Void {
        var history = ActivityMonitor.getHistory();
        var out = [] as Array<Number>;
        for (var i = history.size() - 1; i >= 0; i -= 1) {
            var day = history[i];
            var steps = day.steps;
            out.add((steps != null) ? steps : 0);
        }
        _series = out;
    }

    function onUpdate(dc as Dc) as Void {
        var clock = System.getClockTime();
        if (clock.min != _builtAt) {
            _builtAt = clock.min;
            hrByCount(30);
        }
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        drawLine(dc, 20, 60, 220, 80, 2);
        drawFilled(dc, 20, 160, 220, 60);
        drawBars(dc, 20, 200, 220, 40, 4);
    }

    //! Line graph, `thickness:` as a pen width.
    function drawLine(dc as Dc, x as Number, y as Number,
                      w as Number, h as Number, thickness as Number) as Void {
        var n = _series.size();
        if (n < 2) { return; }
        var lo = _seriesMin;
        var span = _seriesMax - lo;
        if (span <= 0) { span = 1; }
        dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.setPenWidth(thickness);
        var px = x;
        var py = y + h - ((_series[0] - lo) * h / span);
        for (var i = 1; i < n; i += 1) {
            var cx = x + (i * w / (n - 1));
            var cy = y + h - ((_series[i] - lo) * h / span);
            dc.drawLine(px, py, cx, cy);
            px = cx;
            py = cy;
        }
        dc.setPenWidth(1);
    }

    //! Filled graph -- one fillPolygon, which is the only fill Dc offers.
    function drawFilled(dc as Dc, x as Number, y as Number,
                        w as Number, h as Number) as Void {
        var n = _series.size();
        if (n < 2) { return; }
        var lo = _seriesMin;
        var span = _seriesMax - lo;
        if (span <= 0) { span = 1; }
        var points = new [n + 2] as Array<Array<Number> >;
        for (var i = 0; i < n; i += 1) {
            var cx = x + (i * w / (n - 1));
            var cy = y + h - ((_series[i] - lo) * h / span);
            points[i] = [cx, cy];
        }
        points[n] = [x + w, y + h];
        points[n + 1] = [x, y + h];
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.fillPolygon(points as Array<Graphics.Point2D>);
    }

    //! Bars -- `bar_width:` as an explicit pixel width inside each slot.
    function drawBars(dc as Dc, x as Number, y as Number,
                      w as Number, h as Number, barWidth as Number) as Void {
        var n = _series.size();
        if (n < 1) { return; }
        var lo = _seriesMin;
        var span = _seriesMax - lo;
        if (span <= 0) { span = 1; }
        var pitch = w / n;
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        for (var i = 0; i < n; i += 1) {
            var value = _series[i];
            if (value < 0) { continue; }
            var bh = (value - lo) * h / span;
            if (bh < 1) { bh = 1; }
            dc.fillRectangle(x + (i * pitch) + ((pitch - barWidth) / 2),
                             y + h - bh, barWidth, bh);
        }
    }
}
