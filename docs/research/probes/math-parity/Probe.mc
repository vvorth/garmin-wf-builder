import Toybox.Lang;
import Toybox.Math;

// Dropped into a generated one-element face's source/ (fenix8solar47mm) and
// built with the project's own flags plus
//   --debug-log-level 3 --debug-log-output dbg.zip
// so dbg.zip's optimizer.mir and assembler.txt show what `-O 3z`'s
// constant-folding pass made of each body. See README.md.
module Probe {
    function roundNegHalf() as Number { return Math.round(-2.5f).toNumber(); }
    function roundPosHalf() as Number { return Math.round(2.5f).toNumber(); }
    function modNeg() as Number { return -7 % 3; }
    function modNegDivisor() as Number { return 7 % -3; }
    function modVar(a as Number, b as Number) as Number { return a % b; }
    function modLong(a as Long, b as Number) as Numeric { return a % b; }
}

// Each of these, added one at a time, fails under -l 3:
//   Cannot perform operation 'mod' on types '$.Toybox.Lang.Float' and '$.Toybox.Lang.Number'.
//   Cannot perform operation 'mod' on types '$.Toybox.Lang.Number' and '$.Toybox.Lang.Float'.
// module Probe2 {
//     function modFloatLit() as Numeric { return 5.5f % 2; }
//     function modFloatVar(a as Float, b as Number) as Numeric { return a % b; }
//     function modNumFloat(a as Number, b as Float) as Numeric { return a % b; }
// }
