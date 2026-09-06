import Toybox.Lang;
import Toybox.Time;

//! Staleness for a `slow`-tier data source (ADR 0005 §Tier), cached in a view
//! field rather than re-read every frame.
//!
//! What is cached, and the actual re-read call, are generated per source --
//! this module holds only the one piece of logic every cache shares: whether
//! it is old enough to refresh.  `lastRefresh` is a UTC-seconds timestamp
//! (`Time.now().value()`), not a `Moment`, so the generated code has nothing
//! to null-check beyond the timestamp field itself.
module WfbCache {

    //! Whether a value last refreshed at `lastRefresh` (or never, if `null`)
    //! is old enough that the generated code should call its reader again.
    function stale(lastRefresh as Number?, ttlSeconds as Number) as Boolean {
        if (lastRefresh == null) {
            return true;
        }
        return (Time.now().value() - lastRefresh) >= ttlSeconds;
    }
}
