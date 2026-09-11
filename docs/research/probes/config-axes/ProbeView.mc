import Toybox.Application;
import Toybox.Application.WatchFaceConfig;
import Toybox.Complications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! Probe: can one face carry (a) a colour *scheme* axis, (b) two independent
//! author-defined content selectors, and (c) two native complication slots
//! whose icon is chosen from the type the wearer picked?
class ProbeView extends WatchUi.WatchFace {
    private var _editMode as Boolean;

    // -- (a)+(b): everything author-defined rides the single styleId ------
    // 3 schemes x 2 choices x 2 choices = 12 style ids, decoded by arithmetic.
    private var _scheme as Number = 0;
    private var _pick1 as Number = 0;
    private var _pick2 as Number = 0;

    // the scheme's three roles, resolved from _scheme
    private var _bg as Number = Graphics.COLOR_BLACK;
    private var _fg as Number = Graphics.COLOR_WHITE;
    private var _dim as Number = Graphics.COLOR_DK_GRAY;

    private var _accent as Number = 0xFFAA00;
    private var _dataColor as Number = 0x00FFFF;

    // -- (c): two native slots -------------------------------------------
    private var _slot1 as Complications.Id =
        new Complications.Id(Complications.COMPLICATION_TYPE_STEPS);
    private var _slot2 as Complications.Id =
        new Complications.Id(Complications.COMPLICATION_TYPE_HEART_RATE);

    function initialize(editMode as Boolean) {
        WatchFace.initialize();
        _editMode = editMode;
    }

    function onLayout(dc as Dc) as Void {
        if (Application has :WatchFaceConfig) {
            var settings = WatchFaceConfig.getSettings(null);
            if (settings != null) { applyConfig(settings); }
        }
    }

    function applyConfig(settings as WatchFaceConfig.Settings) as Void {
        var style = settings.styleId;
        if (style != null && style >= 0 && style < 12) {
            _scheme = style / 4;
            _pick1 = (style / 2) % 2;
            _pick2 = style % 2;
            resolveScheme();
        }
        var accent = settings.accentColor;
        if (accent != null) {
            var value = accent.color;
            if (value != null) { _accent = value as Number; }
        }
        var data = settings.complicationColor;
        if (data != null) {
            var value = data.color;
            if (value != null) { _dataColor = value as Number; }
        }
        var slots = settings.complicationSettings;
        if (slots != null) {
            for (var i = 0; i < slots.size(); i += 1) {
                var ref = slots[i];
                var unique = ref.uniqueIdentifier;
                var picked = ref.complicationId;
                if (unique == null || picked == null) { continue; }
                if (unique == 1) { _slot1 = picked; }
                else if (unique == 2) { _slot2 = picked; }
            }
        }
        WatchUi.requestUpdate();
    }

    //! A colour scheme is several colours moving together, which no colour
    //! axis offers -- so it is decoded from styleId into compiled-in constants.
    private function resolveScheme() as Void {
        if (_scheme == 0) {          // dark
            _bg = 0x000000; _fg = 0xFFFFFF; _dim = 0x555555;
        } else if (_scheme == 1) {   // light
            _bg = 0xFFFFFF; _fg = 0x000000; _dim = 0xAAAAAA;
        } else {                     // slate
            _bg = 0x000055; _fg = 0xAAFFFF; _dim = 0x005555;
        }
    }

    //! The question this probe exists for: the wearer picked a complication
    //! *type*, and the face wants an icon for it.  `Id.getType()` is the route.
    private function iconFor(id as Complications.Id) as String {
        var type = id.getType();
        switch (type) {
            case Complications.COMPLICATION_TYPE_STEPS:        return "steps";
            case Complications.COMPLICATION_TYPE_HEART_RATE:   return "heart";
            case Complications.COMPLICATION_TYPE_CALORIES:     return "flame";
            case Complications.COMPLICATION_TYPE_BODY_BATTERY: return "battery";
            default:                                           return "dot";
        }
    }

    //! Hit regions for the editor's own tap, and nothing else.
    function slotAt(x as Number, y as Number) as Number? {
        if (y < 130) { return 1; }
        if (y < 200) { return 2; }
        return null;
    }

    //! Public so the editor's Drawable can reuse the one implementation.
    function drawSlotAt(dc as Dc, slot as Number) as Void {
        if (slot == _pulsing) { return; }
        drawSlot(dc, (slot == 1) ? 140 : 180, (slot == 1) ? _slot1 : _slot2);
    }

    //! The slot the editor is currently animating, or 0.
    private var _pulsing as Number = 0;

    function setPulsing(slot as Number) as Void { _pulsing = slot; }

    function drawableFor(slot as Number) as WatchUi.ComplicationDrawableRef {
        var d = new SlotDrawable(self, slot, 0, (slot == 1) ? 120 : 160, 260, 40);
        return new WatchUi.ComplicationDrawableRef({ :drawable => d, :boundingBox => d.boundingBox() });
    }

    private function drawSlot(dc as Dc, y as Number, id as Complications.Id) as Void {
        var text = iconFor(id) + " ";
        var reading = WfbComplications.valueOf(id);
        if (reading != null) {
            var value = reading.value as Number?;
            text += (value != null) ? value.toString() : "--";
            var label = reading.shortLabel;
            if (label != null) { text = label + " " + text; }
            var unit = reading.unit as String?;
            if (unit != null) { text += unit; }
        } else {
            text += "--";
        }
        dc.setColor(_dataColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(130, y, Graphics.FONT_SMALL, text, Graphics.TEXT_JUSTIFY_CENTER);
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(_bg, _bg);
        dc.clear();
        dc.setColor(_accent, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(10, 10, 30, 30);
        dc.setColor(_fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(130, 60, Graphics.FONT_MEDIUM,
                    _scheme.toString() + "/" + _pick1.toString() + "/" + _pick2.toString(),
                    Graphics.TEXT_JUSTIFY_CENTER);
        // (b) author-defined variants, selected by the decoded style
        dc.setColor(_dim, Graphics.COLOR_TRANSPARENT);
        if (_pick1 == 0) {
            dc.drawText(130, 100, Graphics.FONT_XTINY, "ring", Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            dc.fillCircle(130, 100, 12);
        }
        drawSlotAt(dc, 1);
        drawSlotAt(dc, 2);
        if (_editMode) {
            dc.drawText(130, 220, Graphics.FONT_XTINY, "edit", Graphics.TEXT_JUSTIFY_CENTER);
        }
    }
}
