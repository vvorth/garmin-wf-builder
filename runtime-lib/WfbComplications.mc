import Toybox.Lang;
import Toybox.Complications;
import Toybox.System;

//! Every `complication.*` source is read by *pull*, not delivered by a
//! callback: `valueOf` below is called fresh from `onUpdate` (and
//! `onPartialUpdate`) every frame, the same ordinary way every other reader
//! in the catalogue is called. There is nothing cached in this module or in
//! the generated view -- see docs/research/probes/complication-pull/, which
//! confirmed a pull needs no prior subscription at all: the SDK's own
//! `ConfigurableWatchFace` sample calls `Complications.getComplication(id)`
//! from `updateConfiguration`, which runs in `onLayout` *before* the first
//! `subscribeToUpdates`, and again in edit mode where it never subscribes.
//!
//! `subscribe` is kept anyway, and is not caching: it exists only so the
//! *platform's own* reading for a type stays current between pulls. Whether
//! a pull with no subscription at all would also stay fresh is genuinely
//! unverified here -- the simulator does not run in this sandbox (CLAUDE.md
//! §6 finding 11) -- so the subscription is cheap insurance against a value
//! that silently never updates, which is exactly the failure class this
//! project exists to eliminate. It costs one line per bound type in
//! `onLayout` and nothing per frame.
//!
//! Both `subscribe` and `valueOf` can fail simply because this hardware does
//! not support the type -- a device's own ConnectIQ ceiling can sit below a
//! complication's `Since` level; see wfb/catalog.py's `activity.sleep_score`
//! for a concrete case -- and Toybox/Complications.html documents the failure
//! two different ways depending on the call: `subscribeToUpdates` returns
//! `false` if the type could not be subscribed to, or throws
//! `ComplicationNotFoundException` if it was not found at all; `getComplication`
//! only ever throws. One place absorbs both outcomes uniformly, so neither the
//! generated `onLayout` subscription loop nor a bound element's `onUpdate`
//! read needs to know which of the two ways a given device declines a given
//! type -- the value a pull returns simply stays `null`, the same "absence is
//! normal" contract every other nullable source in this catalogue already
//! has. `subscribe`'s `false` return is not "caught" in any active sense --
//! there is nothing to catch, it is a plain return value -- it is simply
//! discarded, which is the correct handling here: a `false` and a caught
//! exception leave the device in the exact same state (never subscribed,
//! every pull still returns null), so there is nothing a `false` branch would
//! do differently.
module WfbComplications {

    function subscribe(id as Complications.Id) as Void {
        try {
            Complications.subscribeToUpdates(id);
        } catch (ex instanceof Complications.ComplicationNotFoundException) {
            System.println("wfb: complication not available on this device: " + ex.getErrorMessage());
        }
    }

    //! The read path: called from a generated element's `onUpdate` pull, once
    //! per bound complication per frame, exactly like `ActivityMonitor.getInfo()`
    //! or `Weather.getCurrentConditions()` for any other reader. Absorbs
    //! `ComplicationNotFoundException` ("if the complication...is not found",
    //! Toybox/Complications.html, which also covers a subscribed complication
    //! that "becomes unavailable") so an unsupported or momentarily-missing
    //! type reads as `null` instead of taking the face down -- the caller
    //! treats that the same as any other absent nullable source.
    function valueOf(id as Complications.Id) as Complications.Complication? {
        try {
            return Complications.getComplication(id);
        } catch (ex instanceof Complications.ComplicationNotFoundException) {
            return null;
        }
    }

    //! A `complication_slot` element's `unit: true` -- `Complication.unit` is
    //! typed `Complications.Unit or Lang.String or Null`: either the SDK's own
    //! enum (a plain Number under the hood, checked with `instanceof Number`)
    //! or a literal string a *user* complication supplied directly, which is
    //! returned as written. `wfb.complications.UNIT_SUFFIX` is this switch's Python twin,
    //! transcribed from the same `Toybox/Complications.html` "Unit" table --
    //! `tests/test_complication_slot.py` parses this file and checks every
    //! case against it directly, so the two cannot silently drift apart.
    //! `UNIT_INVALID` and anything this SDK build does not yet document fall
    //! through to the empty string, which is exactly as visible as no unit at
    //! all -- there is nothing sensible to guess at.
    function unitSuffix(unit as Complications.Unit or Lang.String or Null) as String {
        if (unit == null) {
            return "";
        }
        if (unit instanceof Lang.String) {
            return unit;
        }
        switch (unit) {
            case Complications.UNIT_DISTANCE: return "m";
            case Complications.UNIT_ELEVATION: return "m";
            case Complications.UNIT_HEIGHT: return "m";
            case Complications.UNIT_SPEED: return "m/s";
            case Complications.UNIT_TEMPERATURE: return "°C";
            case Complications.UNIT_WEIGHT: return "g";
            default: return "";
        }
    }
}
