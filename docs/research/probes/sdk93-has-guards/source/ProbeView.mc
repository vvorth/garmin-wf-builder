// Each case is one guard form around one symbol a target lacks; the build's
// error lines name the cases SDK 9.3.0 rejects.  Absent on venu: the whole
// Toybox.Complications module and System.DISPLAY_MODE_OFF.  Absent on fr955:
// Complications.COMPLICATION_TYPE_SLEEP_SCORE.  Absent on venusq2:
// Application.WatchFaceConfig.
import Toybox.Application;
import Toybox.Complications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

class ProbeView extends WatchUi.WatchFace {
    // T1: a field typed with an absent class, constructed nowhere
    private var _id as Complications.Id? = null;

    function initialize() { WatchFace.initialize(); }

    function onUpdate(dc as Dc) as Void {
        var n = 0;
        // C1: module has-check, member call inside the if
        if (Toybox has :Complications) {
            n += Complications.getComplication(new Complications.Id(Complications.COMPLICATION_TYPE_HEART_RATE)) != null ? 1 : 0;
        }
        // C2: the same check as a ternary
        var c2 = (Toybox has :Complications) ? Complications.COMPLICATION_TYPE_STEPS : null;
        // C3: the check stored in a local first
        var hasModule = Toybox has :Complications;
        var c3 = hasModule ? Complications.COMPLICATION_TYPE_CALORIES : null;
        // C3b: the local, then a construction straight after it
        var c3b = hasModule ? new Complications.Id(Complications.COMPLICATION_TYPE_CALORIES) : null;
        // C3c: a second local, an unrelated statement between it and a construction
        var hasAgain = Toybox has :Complications;
        var clock = System.getClockTime();
        var c3c = hasAgain ? new Complications.Id(Complications.COMPLICATION_TYPE_STEPS) : null;
        // C3d: the check written out in the ternary, after the same unrelated statement
        var clock2 = System.getClockTime();
        var c3d = (Toybox has :Complications) ? new Complications.Id(Complications.COMPLICATION_TYPE_STEPS) : null;
        n += (c3b != null ? 1 : 0) + (c3c != null ? 1 : 0) + (c3d != null ? 1 : 0) + clock.hour + clock2.min;
        // C3e: the local, then the construction passed to a helper (as the generated view reads a complication)
        var c3e = hasModule ? pull(new Complications.Id(Complications.COMPLICATION_TYPE_STRESS)) : null;
        // C3f: the same, inside an else branch
        if (n < 0) {
            n = 0;
        } else {
            var hasHere = Toybox has :Complications;
            var c3f = hasHere ? pull(new Complications.Id(Complications.COMPLICATION_TYPE_STRESS)) : null;
            n += (c3e != null ? 1 : 0) + (c3f != null ? 1 : 0);
        }
        // C4: the check inside a && chain
        if ((Toybox has :Complications) && Complications.COMPLICATION_TYPE_FLOORS_CLIMBED != null) { n += 1; }
        // C5: a nested member of the checked module's class (Complication.value)
        if (Toybox has :Complications) {
            var got = Complications.getComplication(new Complications.Id(Complications.COMPLICATION_TYPE_STRESS));
            if (got != null) { var v = got.value; n += (v != null) ? 1 : 0; }
        }
        // C6: try/catch naming an absent exception class, inside the check
        if (Toybox has :Complications) {
            try {
                Complications.subscribeToUpdates(new Complications.Id(Complications.COMPLICATION_TYPE_BATTERY));
            } catch (ex instanceof Complications.ComplicationNotFoundException) {
                n -= 1;
            }
        }
        // D1: has-check on a sibling method only (what the generated view does today)
        if ((System has :getDisplayMode) && (System.getDisplayMode() == System.DISPLAY_MODE_OFF)) { n += 1; }
        // D2: has-check on the constant itself
        if ((System has :getDisplayMode) && (System has :DISPLAY_MODE_OFF) && (System.getDisplayMode() == System.DISPLAY_MODE_OFF)) { n += 1; }
        // S1: a constant absent on one device while its module is present: module check only
        if (Toybox has :Complications) {
            var s1 = Complications.COMPLICATION_TYPE_SLEEP_SCORE;
            n += s1 != null ? 1 : 0;
        }
        // S2: the constant's own has-check
        if ((Toybox has :Complications) && (Complications has :COMPLICATION_TYPE_SLEEP_SCORE)) {
            var s2 = Complications.COMPLICATION_TYPE_SLEEP_SCORE;
            n += s2 != null ? 1 : 0;
        }
        n += early() + guardedHelper() + (c2 != null ? 1 : 0) + (c3 != null ? 1 : 0);
        if (Application has :WatchFaceConfig) { n += editorSettings(); }
        n += annotated();
        dc.drawText(10, 10, Graphics.FONT_TINY, n.toString(), Graphics.TEXT_JUSTIFY_LEFT);
    }

    // H1: a helper whose body has its own module check
    private function pull(id as Complications.Id) as Complications.Complication? {
        if (Toybox has :Complications) {
            return Complications.getComplication(id);
        }
        return null;
    }

    // C7: an early return on the negated check
    private function early() as Number {
        if (!(Toybox has :Complications)) {
            return 0;
        }
        return Complications.COMPLICATION_TYPE_PULSE_OX != null ? 1 : 0;
    }

    // C8: a helper only called from inside a check, with none of its own
    private function guardedHelper() as Number {
        return Complications.COMPLICATION_TYPE_RESPIRATION_RATE != null ? 1 : 0;
    }

    // W1: a nested class member under the parent module's check (ComplicationRef.uniqueIdentifier)
    private function editorSettings() as Number {
        var n = 0;
        if (Application has :WatchFaceConfig) {
            var settings = WatchFaceConfig.getSettings(1 as WatchFaceConfig.Id);
            if (settings != null) {
                var slots = settings.complicationSettings;
                if (slots != null && slots.size() > 0) {
                    var unique = slots[0].uniqueIdentifier;
                    n += unique != null ? 1 : 0;
                }
            }
        }
        return n;
    }

    // X1: no guard at all, compiled out by the jungle's excludeAnnotations on venu/venusq2
    (:editor)
    private function annotatedBody() as Number {
        return WatchFaceConfig.getSettings(1 as WatchFaceConfig.Id) != null ? 1 : 0;
    }

    // X2: the call site of an excluded method, guarded by a has-check on the method symbol
    private function annotated() as Number {
        if (self has :annotatedBody) {
            return annotatedBody() as Number;
        }
        return 0;
    }

}
