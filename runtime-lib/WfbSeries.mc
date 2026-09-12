import Toybox.ActivityMonitor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Time;

//! Time-series acquisition, binning and drawing for a `type: graph` element.
//!
//! What is fixed across every design lives here, the same split
//! `WfbArc.mc` already draws: heart-rate acquisition and
//! binning, and the generic min/max over an array, are one shape shared by
//! every graph -- Monkey C offers no way to pass a field name, so the
//! per-series array loops (`day.steps` vs. `day.calories`, `hour.temperature`
//! vs. `hour.uvIndex`) are generated per project instead, straight into the
//! view (`wfb.emit.monkeyc._emit_graph_rebuild`).
//!
//! Every series here is cached in a private view field and rebuilt only when
//! `System.getClockTime().min` changes -- one `Number` comparison a frame.
//! **This is not the TTL cache this project deleted** (see `wfb/catalog.py`'s
//! module docstring): that deletion was about re-caching a value Garmin
//! already caches on its own side (`Weather.getCurrentConditions()` is
//! documented as returning the "most recently cached" reading). A series is
//! different -- it is *this compiler's own computation* over a source whose
//! sample interval is minutes (a heart-rate bucket, a calendar day, an
//! hourly forecast slot), so recomputing it every second cannot produce any
//! new information; the cache exists to avoid paying for that computation on
//! every one of the up-to-60 frames between two minutes that could show a
//! different answer.
//!
//! **Gaps are `null`, not a sentinel number.** The reference probe
//! (`docs/research/probes/graph-series/`) marks an empty heart-rate bucket
//! `-1`; this barrel uses `null` instead, uniformly, across every series --
//! several of the forecast fields (`forecast_temperature`,
//! `daily_high_temperature`, `daily_low_temperature`) are genuinely negative
//! in Celsius, so a numeric sentinel would collide with a real reading on
//! exactly the series where getting this wrong would be least visible.
//! `Array<Float?>` costs nothing extra to check and cannot collide with data.
module WfbSeries {

    //! A line: `setPenWidth` then a `drawLine` per segment, breaking the run
    //! wherever a sample is missing rather than joining across the gap.
    function drawLine(
        dc as Graphics.Dc, x as Number, y as Number, w as Number, h as Number,
        thickness as Number, values as Array<Float?>, lo as Float, hi as Float
    ) as Void {
        var n = values.size();
        if (n < 2) { return; }
        var span = hi - lo;
        if (span <= 0.0) { span = 1.0; }
        dc.setPenWidth(thickness);
        var havePrevious = false;
        var px = 0;
        var py = 0;
        for (var i = 0; i < n; i += 1) {
            var v = values[i];
            if (v == null) { havePrevious = false; continue; }
            var cx = x + (i * w / (n - 1));
            var cy = y + h - ((v - lo) * h / span).toNumber();
            if (havePrevious) { dc.drawLine(px, py, cx, cy); }
            px = cx;
            py = cy;
            havePrevious = true;
        }
        dc.setPenWidth(1);
    }

    //! A filled area: `fillPolygon`, the only fill `Dc` offers that follows a
    //! curve -- one call per contiguous run of present samples, each closed
    //! with its own two bottom corners, rather than one call for the whole
    //! series. A single `fillPolygon` cannot represent a gap partway through
    //! its own outline without visibly joining straight across it -- there
    //! is no "lift the pen" for a filled shape -- so a gap here ends one run
    //! and starts the next, exactly mirroring `wfb/preview.py`'s
    //! `_graph_area` (which draws the same runs in Pillow), rather than
    //! either interpolating across it (a guess) or leaving the whole graph
    //! blank for one missing sample.
    //!
    //! Every individual call still respects `fillPolygon`'s own 64-point
    //! limit: a run can hold at most as many points as the whole series
    //! does, and `wfb/ir.py`'s `GRAPH_AREA_MAX_SAMPLES` already refuses a
    //! `style: area` design whose series could exceed 62 (64 minus the two
    //! closing corners a *single* run would need).
    function drawArea(
        dc as Graphics.Dc, x as Number, y as Number, w as Number, h as Number,
        values as Array<Float?>, lo as Float, hi as Float
    ) as Void {
        var n = values.size();
        if (n < 2) { return; }
        var span = hi - lo;
        if (span <= 0.0) { span = 1.0; }
        var i = 0;
        while (i < n) {
            if (values[i] == null) { i += 1; continue; }
            var start = i;
            var end = i;
            while (end < n && values[end] != null) { end += 1; }
            var count = end - start;
            if (count >= 2) {
                // `Array<Array<Number> >` here, cast to
                // `Array<Graphics.Point2D>` at the call site below --
                // `Point2D` is a fixed-size tuple type, and a local built
                // this way is exactly what the reference probe compiles
                // warning-free (`docs/research/probes/graph-series/`,
                // `docs/research/probes/polygon-const/`).
                var run = new [count + 2] as Array<Array<Number> >;
                for (var j = 0; j < count; j += 1) {
                    var v = values[start + j];
                    var cx = x + ((start + j) * w / (n - 1));
                    // `v` is never actually null here -- `start`/`end` bound a
                    // run of indices already checked non-null above -- but
                    // the type checker narrows a local against a *repeated*
                    // read of `values[...]`, not the loop invariant, so the
                    // ternary (the same shape `ReadPlan.declarations` already
                    // relies on for a nullable intermediate) is what actually
                    // satisfies -l 3 rather than just reading intent into it.
                    var cy = (v != null) ? y + h - ((v - lo) * h / span).toNumber() : y + h;
                    run[j] = [cx, cy];
                }
                run[count] = [x + ((end - 1) * w / (n - 1)), y + h];
                run[count + 1] = [x + (start * w / (n - 1)), y + h];
                dc.fillPolygon(run as Array<Graphics.Point2D>);
            }
            i = end;
        }
    }

    //! Bars: a `fillRectangle` per bucket, `barWidth` centred in its slot.
    //! A missing sample simply draws no bar -- bars need no closing outline,
    //! so a gap here is exactly the honest "no data" the line style gives.
    function drawBars(
        dc as Graphics.Dc, x as Number, y as Number, w as Number, h as Number,
        barWidth as Number, values as Array<Float?>, lo as Float, hi as Float
    ) as Void {
        var n = values.size();
        if (n < 1) { return; }
        var span = hi - lo;
        if (span <= 0.0) { span = 1.0; }
        var pitch = w / n;
        for (var i = 0; i < n; i += 1) {
            var v = values[i];
            if (v == null) { continue; }
            var barHeight = ((v - lo) * h / span).toNumber();
            if (barHeight < 1) { barHeight = 1; }
            dc.fillRectangle(
                x + (i * pitch) + ((pitch - barWidth) / 2), y + h - barHeight,
                barWidth, barHeight
            );
        }
    }

    //! The extent of a series, ignoring gaps -- what `min: auto`/`max: auto`
    //! use for every array-backed series (heart rate uses the iterator's own
    //! `getMin`/`getMax` instead; see `binHeartRate`/`collectHeartRate`
    //! below and their call sites). `0.0`/`0.0` when every sample is
    //! missing, matching this platform's own "absence is normal" contract --
    //! the caller already clamps a non-positive span before dividing by it.
    function autoMin(values as Array<Float?>) as Float {
        var lo = 0.0;
        var have = false;
        for (var i = 0; i < values.size(); i += 1) {
            var v = values[i];
            if (v == null) { continue; }
            if (!have || v < lo) { lo = v; have = true; }
        }
        return lo;
    }

    function autoMax(values as Array<Float?>) as Float {
        var hi = 0.0;
        var have = false;
        for (var i = 0; i < values.size(); i += 1) {
            var v = values[i];
            if (v == null) { continue; }
            if (!have || v > hi) { hi = v; have = true; }
        }
        return hi;
    }

    //! Heart-rate history, binned by time -- `range:` was a duration. Average
    //! bpm per bucket, oldest bucket first (left-to-right on screen, matching
    //! `newestFirst: false`'s own left-to-right order), `null` where a bucket
    //! saw no sample. Bucket arithmetic is integer throughout except the
    //! average itself, which is computed as a `Float` deliberately -- `Number
    //! / Number` truncates on this platform (see the `activity.steps / 1000`
    //! bug this project already found and fixed elsewhere).
    function binHeartRate(
        iterator as ActivityMonitor.HeartRateIterator, buckets as Number,
        spanSeconds as Number
    ) as Array<Float?> {
        var sums = new [buckets] as Array<Number>;
        var counts = new [buckets] as Array<Number>;
        for (var i = 0; i < buckets; i += 1) {
            sums[i] = 0;
            counts[i] = 0;
        }
        var now = Time.now().value();
        while (true) {
            var sample = iterator.next();
            if (sample == null) { break; }
            var bpm = sample.heartRate;
            var when = sample.when;
            if (bpm == null || when == null) { continue; }
            if (bpm == ActivityMonitor.INVALID_HR_SAMPLE) { continue; }
            var age = now - when.value();
            if (age < 0) { age = 0; }
            if (age > spanSeconds) { continue; }
            var index = buckets - 1 - (age * buckets / spanSeconds);
            if (index < 0) { index = 0; }
            if (index >= buckets) { index = buckets - 1; }
            sums[index] = sums[index] + bpm;
            counts[index] = counts[index] + 1;
        }
        var out = new [buckets] as Array<Float?>;
        for (var i = 0; i < buckets; i += 1) {
            out[i] = (counts[i] > 0) ? (sums[i].toFloat() / counts[i]) : null;
        }
        return out;
    }

    //! Heart-rate history, raw -- `range:` was a bare sample count. No
    //! binning: a fixed count already asks for a fixed number of samples, one
    //! array slot each, oldest first.
    function collectHeartRate(iterator as ActivityMonitor.HeartRateIterator) as Array<Float?> {
        var out = [] as Array<Float?>;
        while (true) {
            var sample = iterator.next();
            if (sample == null) { break; }
            var bpm = sample.heartRate;
            if (bpm == null || bpm == ActivityMonitor.INVALID_HR_SAMPLE) { continue; }
            out.add(bpm.toFloat());
        }
        return out;
    }

    //! `min(a, b)` for a sample count against an acquired array's own size --
    //! `WfbMath.min` already exists, but this module must not assume the
    //! design bound anything that would pull `WfbMath.mc` into the barrel
    //! copy; a graph-only face needs no expression functions at all.
    function min(a as Number, b as Number) as Number {
        return (a < b) ? a : b;
    }
}
