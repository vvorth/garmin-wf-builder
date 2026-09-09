import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;
import Toybox.Complications;

//! Probe: can a complication be read by *pull* in onUpdate, with no cache
//! field and no per-type onComplicationChanged switch?
class ProbeView extends WatchUi.WatchFace {

    function initialize() { WatchFace.initialize(); }

    function onLayout(dc as Dc) as Void {
        Complications.registerComplicationChangeCallback(method(:onComplicationChanged));
        WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_BODY_BATTERY));
        WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_TRAINING_STATUS));
        WfbComplications.subscribe(new Complications.Id(Complications.COMPLICATION_TYPE_WEEKLY_RUN_DISTANCE));
    }

    //! No per-type cache: a change just asks for a redraw, and onUpdate pulls.
    function onComplicationChanged(id as Complications.Id) as Void {
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        dc.clearClip();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        // -- the exact shapes the generator would emit -------------------
        var complicationBodyBattery = WfbComplications.valueOf(
            new Complications.Id(Complications.COMPLICATION_TYPE_BODY_BATTERY));
        var complicationTrainingStatus = WfbComplications.valueOf(
            new Complications.Id(Complications.COMPLICATION_TYPE_TRAINING_STATUS));
        var complicationWeeklyRunDistance = WfbComplications.valueOf(
            new Complications.Id(Complications.COMPLICATION_TYPE_WEEKLY_RUN_DISTANCE));

        // Number, via a cast inside a ternary -- the shape ReadPlan.declarations
        // produces for a nullable reader.
        var bodyBattery = (complicationBodyBattery != null)
            ? complicationBodyBattery.value as Number? : null;
        var trainingStatus = (complicationTrainingStatus != null)
            ? complicationTrainingStatus.value as String? : null;
        var weeklyRunDistance = (complicationWeeklyRunDistance != null)
            ? complicationWeeklyRunDistance.value as Float? : null;

        if (bodyBattery != null) {
            dc.drawText(10, 10, Graphics.FONT_SMALL, bodyBattery.format("%d"),
                        Graphics.TEXT_JUSTIFY_LEFT);
        }
        if (trainingStatus != null) {
            dc.drawText(10, 40, Graphics.FONT_SMALL, trainingStatus,
                        Graphics.TEXT_JUSTIFY_LEFT);
        }
        if (weeklyRunDistance != null) {
            dc.drawText(10, 70, Graphics.FONT_SMALL, (weeklyRunDistance / 1000.0).format("%.1f"),
                        Graphics.TEXT_JUSTIFY_LEFT);
        }
    }
}
