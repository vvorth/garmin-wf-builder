//! Carousel feasibility probe -- hand-written, NOT generated.
//!
//! Only onPress is defined.  WatchFaceDelegate.onTap fires solely in the
//! on-device watch-face config editor, so it is useless for a live carousel;
//! the three behaviours are partitioned by touch coordinate instead.

import Toybox.Complications;
import Toybox.Lang;
import Toybox.WatchUi;

class CarouselDelegate extends WatchUi.WatchFaceDelegate {

    private var _view as CarouselView;

    function initialize(view as CarouselView) {
        WatchFaceDelegate.initialize();
        _view = view;
    }

    //! A touch and hold.  The only gesture a live watch face receives.
    function onPress(clickEvent as ClickEvent) as Boolean {
        var where = clickEvent.getCoordinates();
        var x = where[0];
        var y = where[1];

        // The carousel band: three zones across its width.
        if (y < 100 || y >= 160) {
            return false;
        }
        if (x < 90) {
            _view.step(-1);
            return true;
        }
        if (x >= 170) {
            _view.step(1);
            return true;
        }
        // Centre: open the glance owning the selected item's complication.
        var types = [
            Complications.COMPLICATION_TYPE_STEPS,
            Complications.COMPLICATION_TYPE_HEART_RATE,
            Complications.COMPLICATION_TYPE_BODY_BATTERY,
            Complications.COMPLICATION_TYPE_CALORIES,
        ] as Array<Complications.Type>;
        Complications.exitTo(new Complications.Id(types[_view.selectedIndex()]));
        return true;
    }
}
