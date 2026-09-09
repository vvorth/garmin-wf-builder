import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! Probe: the three candidate polygon codegen shapes, plus the other new
//! `shape:` primitives, exercised through the calls the generator emits.
class ProbeView extends WatchUi.WatchFace {

    function initialize() { WatchFace.initialize(); }

    function onUpdate(dc as Dc) as Void {
        dc.clearClip();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        // -- A: a module-level const array, passed straight through --------
        dc.fillPolygon(ProbeLayout.PROBE_POINTS);

        // -- B: the same with no declared type ------------------------------
        dc.fillPolygon(ProbeLayout.PROBE_POINTS_UNTYPED);

        // -- C: per-coordinate constants, literal built at the call site -----
        dc.fillPolygon([[ProbeLayout.PROBE_P0X, ProbeLayout.PROBE_P0Y],
                        [ProbeLayout.PROBE_P1X, ProbeLayout.PROBE_P1Y],
                        [ProbeLayout.PROBE_P2X, ProbeLayout.PROBE_P2Y]]);

        // -- the rest of T1's new primitives --------------------------------
        dc.setPenWidth(3);
        dc.drawArc(130, 130, 100, Graphics.ARC_CLOCKWISE, 90.0, 10.0);
        dc.setPenWidth(1);
        dc.fillEllipse(60, 200, 30, 15);
        dc.drawEllipse(200, 200, 30, 15);
        dc.drawRectangle(10, 10, 20, 20);
        dc.drawRoundedRectangle(40, 10, 20, 20, 4);
    }
}
