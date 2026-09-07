import Toybox.Application;
import Toybox.Lang;

//! The selection state behind a `carousel` element (ADR 0006 §6, as amended by
//! `docs/research/07-carousel-interaction.md`).
//!
//! Only the parts every carousel shares live here: wrapping an index, and
//! remembering it across restarts.  Everything that differs per design -- how
//! many items there are, which glyph each draws, where the zones fall -- is
//! generated, because it is resolved per device.
//!
//! The storage key is the element's own `id:` from the YAML, so two carousels
//! in one face keep separate selections and an author can see in the design
//! which key is which.
module WfbCarousel {

    //! The selected index, as last left by the wearer.
    //!
    //! Clamped rather than trusted: `count` can shrink when the design is
    //! rebuilt with fewer items, and a stored index past the end would then
    //! read off the end of the generated `switch` -- silently drawing nothing
    //! until the wearer happened to press it back into range.
    function restore(key as String, count as Number) as Number {
        var stored = Application.Storage.getValue(key);
        if (!(stored instanceof Number) || stored < 0 || stored >= count) {
            return 0;
        }
        return stored;
    }

    //! Remember the selection.  Called on every step, which is a user action
    //! and therefore rare -- this is not a per-frame write.
    function remember(key as String, index as Number) as Void {
        Application.Storage.setValue(key, index);
    }

    //! Move `index` by `direction` (-1 or +1), wrapping at both ends.
    //!
    //! `+ count` before the modulo because Monkey C's `%` keeps the sign of
    //! its left operand, so stepping back from 0 would otherwise give -1.
    function step(index as Number, direction as Number, count as Number) as Number {
        return (index + direction + count) % count;
    }
}
