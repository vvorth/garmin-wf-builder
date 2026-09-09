import Toybox.Graphics;
import Toybox.Lang;

//! Probe: what shape can a resolved polygon's vertices take in the generated
//! per-device `Layout` module?  ADR 0004 says the device does no layout
//! arithmetic, so the coordinates have to be constants here, not computed
//! on-watch -- the only question is what the compiler will accept.
module ProbeLayout {

    //! A: the shape the generator now emits.  `Dc.fillPolygon` takes
    //! `Array<Graphics.Point2D>` and `Point2D` is `[Numeric, Numeric]`
    //! (Toybox/Graphics.html), so the const is declared as exactly that.
    const PROBE_POINTS as Array<Graphics.Point2D> = [[10, 20], [40, 20], [25, 50]];

    //! B: no declared type at all.  Accepted, but it says nothing to a reader
    //! and gives the typechecker nothing to check, so it is not what shipped.
    const PROBE_POINTS_UNTYPED = [[60, 20], [90, 20], [75, 50]];

    //! C: the fallback the spec asked to fall back to if a const array were
    //! rejected -- per-coordinate constants, literal assembled at the call
    //! site.  It compiles too, and is not needed.
    const PROBE_P0X as Number = 110;
    const PROBE_P0Y as Number = 20;
    const PROBE_P1X as Number = 140;
    const PROBE_P1Y as Number = 20;
    const PROBE_P2X as Number = 125;
    const PROBE_P2Y as Number = 50;

    //! D: the near-miss.  `Array<Array<Number> >` declares fine here and then
    //! fails at the `fillPolygon` call site, because `Point2D` is a
    //! *fixed-size* tuple type rather than a variable-length array.  Left
    //! commented out because the whole file has to compile.
    // const PROBE_POINTS_WRONG as Array<Array<Number> > = [[10, 20], [40, 20], [25, 50]];
}
