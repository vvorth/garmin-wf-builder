import Toybox.Lang;

//! The expression language's function set.
//!
//! These exist as functions rather than being inlined by the generator because
//! inlining `clamp(x, 0, 100)` would evaluate `x` three times.  Expressions are
//! pure, so that would be correct -- but it triples the generated text and makes
//! the output unreadable, which ADR 0003 does not allow.
module WfbMath {

    //! The smaller of two numbers.
    function min(a as Numeric, b as Numeric) as Numeric {
        return (a < b) ? a : b;
    }

    //! The larger of two numbers.
    function max(a as Numeric, b as Numeric) as Numeric {
        return (a > b) ? a : b;
    }

    //! Constrain a value to the inclusive range [lo, hi].
    function clamp(value as Numeric, lo as Numeric, hi as Numeric) as Numeric {
        if (value < lo) { return lo; }
        if (value > hi) { return hi; }
        return value;
    }

    //! Absolute value.
    function abs(value as Numeric) as Numeric {
        return (value < 0) ? -value : value;
    }

    //! `value` as a percentage of `goal`, clamped to 0..100.
    //!
    //! A zero or negative goal yields 0 rather than dividing by zero: a goal of
    //! zero is a real reading on this platform (an unset step goal), not a bug.
    function percent(value as Numeric, goal as Numeric) as Float {
        if (goal <= 0) { return 0.0; }
        var pct = 100.0 * value.toFloat() / goal.toFloat();
        return clamp(pct, 0.0, 100.0) as Float;
    }
}
