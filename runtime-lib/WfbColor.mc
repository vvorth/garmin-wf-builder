import Toybox.Lang;

//! Colour arithmetic for the generated view.
module WfbColor {

    //! Scale one packed 0xRRGGBB colour's channels by num/den, rounded to
    //! the nearest integer, for the AOD frame's `aod: {dim: ...}` (plan 14
    //! slice 3, docs/guide/always-on-display.md).
    //!
    //! Used only for a colour whose value is not known at build time -- a
    //! `config.colors.<role>` field read, or a conditional between several
    //! colours -- so the ternary at the call site can dim it. A
    //! build-time-constant colour (a bare hex literal, or a `palette.<name>`
    //! reference) is never routed through this call at all: it is
    //! pre-dimmed into a second literal in Python instead
    //! (`wfb.emit.monkeyc.common._dim_color_code`), because there is nothing
    //! left to compute once the device is running.
    //!
    //! Plain integer arithmetic throughout, never a Float: `wfb.palette.
    //! dim_channel` computes this exact formula in Python for the
    //! build-time half, and `wfb.preview` for the host-rendered half, and
    //! all three must agree bit for bit. A channel times `dim` landing near
    //! a `.5` boundary would be free to round differently under Python's
    //! banker's rounding, this platform's own `Math.round`, and 32-bit vs.
    //! 64-bit float precision -- integer division sidesteps all three, and
    //! this platform's `/` between two non-negative `Number`s truncates
    //! toward zero exactly like Python's `//` does for the same operands.
    function dim(color as Number, num as Number, den as Number) as Number {
        var r = (((color >> 16) & 0xFF) * num + den / 2) / den;
        var g = (((color >> 8) & 0xFF) * num + den / 2) / den;
        var b = ((color & 0xFF) * num + den / 2) / den;
        return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF);
    }
}
