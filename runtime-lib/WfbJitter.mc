import Toybox.Lang;

//! The deterministic per-minute AOD pixel offset for `aod: {jitter: ...}`
//! (plan 14 slice 5, docs/guide/always-on-display.md).
//!
//! Bit-for-bit the same arithmetic as `wfb.aod_jitter.offset` in Python --
//! that module's own docstring has the full derivation, including why a
//! plain raster scan (step `dx` every minute, `dy` only every `w` minutes)
//! was rejected: a horizontal line's own lit pixels only care about `dy`,
//! so they sat lit for up to `w` consecutive minutes under that scan,
//! violating Garmin's 3-minute rule on that axis even though the `(dx,
//! dy)` *pair* changed every minute. This module's own stride -- `2w + 1`
//! through the flattened `w x w` grid -- moves `dx` and `dy` together every
//! step, so a horizontal, vertical or 45-degree line all move along their
//! own axis every minute. `tests/test_aod_jitter.py` checks the two
//! implementations agree for every minute of the day (a spot-check table),
//! and a slow test compiles this module warning-free.
//!
//! Split into two functions, one per axis, rather than one function
//! returning a pair: every call site wants exactly one coordinate (an X
//! constant or a Y constant, never both at once -- `wfb.emit.monkeyc.
//! common._jitter_terms`), and Monkey C has no tuple return worth the
//! allocation here.
//!
//! Plain integer `%`/`/` throughout -- never `Float` -- so this needs no
//! agreement with Python about floating-point rounding: `/` between two
//! non-negative `Number`s truncates toward zero exactly like Python's `//`
//! does for the same operands, and `%`'s sign matches the same way too.
module WfbJitter {

    //! The X half of `offset(minuteOfDay, n)` -- see the module doc.
    function offsetX(minuteOfDay as Number, n as Number) as Number {
        var w = 2 * n + 1;
        var stride = 2 * w + 1;
        var cell = (minuteOfDay * stride) % (w * w);
        return (cell % w) - n;
    }

    //! The Y half of `offset(minuteOfDay, n)` -- see the module doc.
    function offsetY(minuteOfDay as Number, n as Number) as Number {
        var w = 2 * n + 1;
        var stride = 2 * w + 1;
        var cell = (minuteOfDay * stride) % (w * w);
        return (cell / w) - n;
    }
}
