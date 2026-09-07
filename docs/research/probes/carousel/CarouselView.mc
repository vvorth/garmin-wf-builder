//! Carousel feasibility probe -- hand-written, NOT generated.
//!
//! Every API claim in docs/research/07 is exercised here so that the real
//! compiler, not a doc page, is the thing that says it works.

import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
import Toybox.Complications;

//! Number of carousel items.
const ITEM_COUNT as Number = 4;

//! Horizontal pitch between carousel slots, in pixels.
const PITCH as Number = 56;

class CarouselView extends WatchUi.WatchFace {

    //! Whether the watch is asleep.  animate() crashes the app if called in
    //! low power mode, so this gates every animation.
    private var _sleeping as Boolean = false;

    //! Index of the centred item.  Persisted across restarts.
    private var _index as Number = 0;

    //! Horizontal slide offset in pixels, driven by WatchUi.animate().
    //! Public because animate() takes a Symbol naming a property of an
    //! object -- a private member cannot be animated.
    public var slide as Number = 0;

    function initialize() {
        WatchFace.initialize();
        var stored = Application.Storage.getValue("carouselIndex");
        if (stored instanceof Number) {
            _index = stored;
        }
    }

    function onLayout(dc as Dc) as Void {
    }

    //! Advance the carousel by one slot.
    //!
    //! @param direction -1 for previous, +1 for next
    public function step(direction as Number) as Void {
        _index = (_index + direction + ITEM_COUNT) % ITEM_COUNT;
        Application.Storage.setValue("carouselIndex", _index);
        if (_sleeping) {
            // No timers, no animations in low power mode -- jump instead.
            slide = 0;
            WatchUi.requestUpdate();
            return;
        }
        WatchUi.cancelAllAnimations();
        slide = direction * PITCH;
        WatchUi.animate(self, :slide, WatchUi.ANIM_TYPE_EASE_OUT,
                        direction * PITCH, 0, 0.3, method(:onSlideDone));
    }

    //! Called by animate() when the slide completes.
    public function onSlideDone() as Void {
        slide = 0;
        WatchUi.requestUpdate();
    }

    //! Which item is centred, for the delegate's launch zone.
    public function selectedIndex() as Number {
        return _index;
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        var cx = dc.getWidth() / 2;
        var cy = dc.getHeight() / 2;
        for (var slot = -1; slot <= 1; slot += 1) {
            var item = (_index + slot + ITEM_COUNT) % ITEM_COUNT;
            var x = cx + slot * PITCH - slide;
            dc.setColor(slot == 0 ? Graphics.COLOR_WHITE : Graphics.COLOR_DK_GRAY,
                        Graphics.COLOR_TRANSPARENT);
            dc.drawText(x, cy, Graphics.FONT_SMALL, item.toString(),
                        Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
    }

    function onExitSleep() as Void {
        _sleeping = false;
        WatchUi.requestUpdate();
    }

    function onEnterSleep() as Void {
        _sleeping = true;
        WatchUi.cancelAllAnimations();
        slide = 0;
        WatchUi.requestUpdate();
    }
}
