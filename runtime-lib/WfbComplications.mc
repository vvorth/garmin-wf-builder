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
//! One place catches both outcomes uniformly, so a generated view's
//! subscription loop does not need to know which of the two ways a given
//! device declines a given type -- the cached field that complication backs
//! simply stays null forever, the same "absence is normal" contract every
//! other nullable source in this catalogue already has.
module WfbComplications {

    function subscribe(id as Complications.Id) as Void {
        try {
            Complications.subscribeToUpdates(id);
        } catch (ex instanceof Complications.ComplicationNotFoundException) {
            System.println("wfb: complication not available on this device: " + ex.getErrorMessage());
        }
    }
}
