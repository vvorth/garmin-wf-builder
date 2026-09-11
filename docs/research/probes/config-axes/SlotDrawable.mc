import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! A generated stand-in for one complication slot, handed to the editor so it
//! can animate ("pulse") the slot the wearer is about to change.  It delegates
//! straight back to the view's own per-slot draw method, so there is exactly
//! one implementation of what a slot looks like.
class SlotDrawable extends WatchUi.Drawable {
    private var _view as ProbeView;
    private var _slot as Number;

    function initialize(view as ProbeView, slot as Number,
                        x as Number, y as Number, w as Number, h as Number) {
        Drawable.initialize({ :locX => x, :locY => y, :width => w, :height => h });
        _view = view;
        _slot = slot;
    }

    function boundingBox() as Graphics.BoundingBox {
        var box = new Graphics.BoundingBox();
        box.addRectangle(locX.toNumber(), locY.toNumber(),
                         width.toNumber(), height.toNumber());
        return box;
    }

    function draw(dc as Dc) as Void {
        if (!isVisible) { return; }
        _view.drawSlotAt(dc, _slot);
    }
}
