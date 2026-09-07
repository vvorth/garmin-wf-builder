import Toybox.Lang;
import Toybox.Complications;
import Toybox.System;

//! Subscribing to a complication (ADR 0005's `event` tier) can fail two
//! different ways, per Toybox/Complications.html: `subscribeToUpdates`
//! returns `false` if the type could not be subscribed to, or throws
//! `ComplicationNotFoundException` if it was not found at all -- and either
//! can happen simply because this hardware does not support the type (a
//! device's own ConnectIQ ceiling can sit below a complication's `Since`
//! level; see wfb/catalog.py's `activity.sleep_score` for a concrete case).
//!
//! One place absorbs both outcomes uniformly, so a generated view's
//! subscription loop does not need to know which of the two ways a given
//! device declines a given type -- the cached field that complication backs
//! simply stays null forever, the same "absence is normal" contract every
//! other nullable source in this catalogue already has. `subscribe`'s `false`
//! return is not "caught" in any active sense -- there is nothing to catch,
//! it is a plain return value -- it is simply discarded, which is the correct
//! handling here: a `false` and a caught exception leave the device in the
//! exact same state (never subscribed, field stays null), so there is
//! nothing a `false` branch would do differently.
module WfbComplications {

    function subscribe(id as Complications.Id) as Void {
        try {
            Complications.subscribeToUpdates(id);
        } catch (ex instanceof Complications.ComplicationNotFoundException) {
            System.println("wfb: complication not available on this device: " + ex.getErrorMessage());
        }
    }

    //! `onComplicationChanged` only ever receives an `Id`, never the value
    //! itself, so it has to call `getComplication(id)` back -- which throws
    //! `ComplicationNotFoundException` if the complication "is not found"
    //! (Toybox/Complications.html), including the "changed or becomes
    //! unavailable" case the callback's own doc describes. An uncaught throw
    //! here would take the whole watch face down, so this absorbs it exactly
    //! the way `subscribe` above absorbs a declined subscription: the caller
    //! gets `null` instead of a value, and treats that the same as any other
    //! absent nullable source.
    function valueOf(id as Complications.Id) as Complications.Complication? {
        try {
            return Complications.getComplication(id);
        } catch (ex instanceof Complications.ComplicationNotFoundException) {
            return null;
        }
    }
}
