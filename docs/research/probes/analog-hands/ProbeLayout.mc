//! Probe: what a hand's per-device Layout constants look like.
//!
//! Resolved for a 260x260 screen (minor radius 130).  The axis is the only
//! screen coordinate; every part is in the hand's own frame, origin = axis,
//! drawn pointing at 12 o'clock (negative y is toward the tip).

import Toybox.Graphics;
import Toybox.Lang;

module Layout {
    const SCREEN_WIDTH as Number = 260;
    const SCREEN_HEIGHT as Number = 260;

    //! `main_hands` -- the axis, on screen
    const MAIN_HANDS_CX as Number = 130;
    const MAIN_HANDS_CY as Number = 130;

    //! hour hand, part 0: a tapered polygon, 5 vertices, tail 8 px
    const MAIN_HANDS_HOUR_0_POINTS as Array<Graphics.Point2D> =
        [[-5, 8], [-4, -52], [0, -60], [4, -52], [5, 8]];
    //! minute hand, part 0: a polygon, 4 vertices
    const MAIN_HANDS_MINUTE_0_POINTS as Array<Graphics.Point2D> =
        [[-3, 10], [-2, -96], [2, -96], [3, 10]];
    //! minute hand, part 1: the hub, a filled circle at the axis
    const MAIN_HANDS_MINUTE_1_X as Number = 0;
    const MAIN_HANDS_MINUTE_1_Y as Number = 0;
    const MAIN_HANDS_MINUTE_1_RADIUS as Number = 6;
    //! second hand, part 0: a line from the counterweight to the tip
    const MAIN_HANDS_SECOND_0_X1 as Number = 0;
    const MAIN_HANDS_SECOND_0_Y1 as Number = 20;
    const MAIN_HANDS_SECOND_0_X2 as Number = 0;
    const MAIN_HANDS_SECOND_0_Y2 as Number = -110;
    const MAIN_HANDS_SECOND_0_THICKNESS as Number = 2;
    //! second hand, part 1: a lollipop off the axis -- exercises a moving centre
    const MAIN_HANDS_SECOND_1_X as Number = 0;
    const MAIN_HANDS_SECOND_1_Y as Number = -80;
    const MAIN_HANDS_SECOND_1_RADIUS as Number = 4;

    //! `sub_seconds` -- an off-centre axis (a small-seconds subdial at 6)
    const SUB_SECONDS_CX as Number = 130;
    const SUB_SECONDS_CY as Number = 195;
    const SUB_SECONDS_SECOND_0_POINTS as Array<Graphics.Point2D> =
        [[-1, 4], [-1, -28], [1, -28], [1, 4]];
}
