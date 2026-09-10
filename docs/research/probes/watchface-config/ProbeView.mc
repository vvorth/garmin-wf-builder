import Toybox.Application;
import Toybox.Complications;
import Toybox.Application.WatchFaceConfig;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeView extends WatchUi.WatchFace {
    private var _editMode as Boolean;
    private var _accent as Number = Graphics.COLOR_ORANGE;
    private var _dataColor as Number = Graphics.COLOR_WHITE;
    private var _style as Number = 1;
    //! The complication the user picked for slot 1, or the author's default.
    private var _slot1 as Complications.Id =
        new Complications.Id(Complications.COMPLICATION_TYPE_STEPS);

    function initialize(editMode as Boolean) {
        WatchFace.initialize();
        _editMode = editMode;
    }

    function onLayout(dc as Dc) as Void {
        // the `has` guard is what keeps this off a device with no editor:
        // getSettings is absent there and calling it would take the face down
        // In edit mode the face is launched by the editor; a real design
        // subscribes to nothing there, since the editor only needs a snapshot.
        if (!_editMode) { WatchUi.requestUpdate(); }
        if (Application has :WatchFaceConfig) {
            var settings = WatchFaceConfig.getSettings(null);
            if (settings != null) { apply(settings); }
        }
    }

    function apply(settings as WatchFaceConfig.Settings) as Void {
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
        var style = settings.styleId;
        if (style != null) { _style = style; }
        var slots = settings.complicationSettings;
        if (slots != null) {
            for (var i = 0; i < slots.size(); i += 1) {
                var slot = slots[i];
                var unique = slot.uniqueIdentifier;
                var picked = slot.complicationId;
                if (unique == null || picked == null) { continue; }
                if (unique == 1) { _slot1 = picked; }
            }
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        dc.setColor(_accent, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(10, 10, 40, 40);
        dc.setColor(_dataColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(130, 130, Graphics.FONT_MEDIUM, _style.toString(),
                    Graphics.TEXT_JUSTIFY_CENTER);
        var reading = WfbComplications.valueOf(_slot1);
        var text = "--";
        if (reading != null) {
            var value = reading.value as Number?;
            if (value != null) { text = value.toString(); }
            var label = reading.shortLabel;
            if (label != null) { text = label + " " + text; }
        }
        dc.drawText(130, 170, Graphics.FONT_SMALL, text,
                    Graphics.TEXT_JUSTIFY_CENTER);
    }
}
