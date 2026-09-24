"""Host/device parity for the expression language (plan 19 A1).

`wfb.expr` evaluates every operator and function twice: on the host, for
constant folding (the answer is baked into generated code) and the preview;
and on the device, as the Monkey C `emit` produces. Plan 18 items 3-4 were
the two disagreeing (`round`, `percent`, `clamp`, `%`).

Nothing here can *run* Monkey C (no simulator, `docs/lore/codegen.md`
finding 11), so parity is checked as far as the compiler itself goes
(`docs/research/probes/math-parity/`):

* **Operators:** each case's *unfolded* expression is emitted as Monkey C
  and compiled at the generated jungle's `-O 3z`; `monkeyc`'s own constant
  folder evaluates it, and `optimizer.mir` in the `--debug-log-output` zip
  records the result, which must equal the host's fold. A case the compiler
  does not fold fails loudly rather than passing unchecked.
* **Functions:** `Math.*` and `WfbMath.*` calls are never folded, so each
  function is compile-checked instead, with Number and with Float
  arguments, warning-free under `-l 3` -- the check that would have caught
  `%` on a Float.

Strftime codes are compile-checked by
`tests/test_date_format_codegen.py::test_every_date_and_time_code_compiles_warning_free`.
"""

from __future__ import annotations

import re
import struct
import subprocess
import zipfile

import pytest

from wfb import expr
from wfb.build import _strip_noise, build as real_build
from wfb.diagnostics import Bag
from wfb.emit.project import RUNTIME_LIB

DEVICE = "fenix8solar47mm"

DESIGN = """
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f70, name: Parity}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - id: t
    type: text
    text: "x"
    color: palette.fg
"""

#: Expressions over literals only, each one the compiler folds. Negative
#: operands, mixed Number/Float and every comparison and boolean operator.
OPERATOR_CASES = [
    "7 + 3", "-7 + 3", "7 - 10", "-7 - 3", "6 * 7", "-6 * 7", "2.5 * 3", "0.1 * 3",
    "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "0 % 5",
    "7 / 2.0", "-7 / 2.0", "1 / 3.0", "2.5 / 0.5",
    "3 < 2.5", "3 <= 3", "-1 > -2", "2 >= 2.5", "3 == 3", "3 != 3.0",
    "true and false", "true or false", "not true",
    "true ? 1 : 2", "false ? 1 : 2",
]


def _probe_function(index: int) -> str:
    return f"case{index}"


def _unfolded_code(text: str) -> str:
    """The Monkey C `emit` produces for `text` *without* host folding -- the
    expression the device would evaluate, not the host's answer."""
    return expr.emit(expr.parse(text), expr.Scope())


def _compile(project, toolchain, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(toolchain.monkeyc), "-f", "monkey.jungle", "-d", DEVICE,
         "-o", str(project / "probe.prg"), "-y", str(toolchain.key), "-w", "--no-gen-styles",
         *extra],
        cwd=project, capture_output=True, text=True, check=False)


def _project(write_design, db, tmp_path, toolchain) -> "Path":
    bag = Bag()
    result = real_build(write_design(DESIGN), output=tmp_path / "out", bag=bag, db=db,
                        toolchain=toolchain, compile_prg=False)
    assert result is not None, bag.render()
    return result.output_dir


def _folded_returns(mir: str) -> dict[str, str]:
    """`{function name: the literal its body returns}` from `optimizer.mir`,
    for every function whose return value the compiler folded to a literal."""
    out = {}
    for match in re.finditer(r"function (case\d+)\(\)[^{]*\{(.*?)\n    \}", mir, re.S):
        name, body = match.group(1), match.group(2)
        ret = re.search(r"ret (%tmp\.\d+)", body)
        if ret is None:
            continue
        assigned = re.findall(rf"{re.escape(ret.group(1))} = (\S+)\s*$", body, re.M)
        if assigned:
            out[name] = assigned[-1]
    return out


def _as_float32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _device_value(literal: str):
    if literal in ("true", "false"):
        return literal == "true"
    if literal.endswith("f"):
        return float(literal[:-1])
    return int(literal)


@pytest.mark.slow
def test_every_operator_case_folds_to_the_hosts_answer(write_design, db, tmp_path, toolchain):
    project = _project(write_design, db, tmp_path, toolchain)
    lines = ["import Toybox.Lang;", "", "module ParityProbe {"]
    for index, text in enumerate(OPERATOR_CASES):
        lines.append(f"    function {_probe_function(index)}() as Numeric or Boolean {{ "
                     f"return {_unfolded_code(text)}; }}")
    lines.append("}")
    (project / "source" / "ParityProbe.mc").write_text("\n".join(lines) + "\n", encoding="utf-8")

    process = _compile(project, toolchain, "--debug-log-level", "3",
                       "--debug-log-output", str(project / "dbg.zip"))
    assert process.returncode == 0, process.stdout + process.stderr
    with zipfile.ZipFile(project / "dbg.zip") as archive:
        mir = archive.read("optimizer.mir").decode("utf-8")
    folded = _folded_returns(mir)

    problems = []
    for index, text in enumerate(OPERATOR_CASES):
        name = _probe_function(index)
        if name not in folded:
            problems.append(f"{text!r}: not folded by monkeyc -- move it out of this table")
            continue
        device = _device_value(folded[name])
        host = expr.evaluate(expr.parse(text), {})
        if isinstance(device, float) or isinstance(host, float):
            # The device computes in 32-bit Float; the host in a double that
            # emit then writes as a Float literal.
            same = _as_float32(float(host)) == _as_float32(float(device))
        else:
            same = host == device and type(host) is type(device)
        if not same:
            problems.append(f"{text!r}: host {host!r}, monkeyc {folded[name]}")
    assert not problems, "\n".join(problems)


@pytest.mark.slow
def test_every_function_compiles_with_number_and_float_arguments(
        write_design, db, tmp_path, toolchain):
    """Each `expr.FUNCTIONS` row's emitted call, with Number and with Float
    arguments, typechecks warning-free under the generated jungle's `-l 3`."""
    project = _project(write_design, db, tmp_path, toolchain)
    bodies = []
    for name, function in sorted(expr.FUNCTIONS.items()):
        for label, arg in (("number", "n"), ("float", "f")):
            call = expr._emit_call(name, [arg] * function.arity)
            bodies.append(f"    function {name}_{label}(n as Number, f as Float) as Numeric "
                          f"{{ return {call}; }}")
    source = "\n".join(["import Toybox.Lang;", "import Toybox.Math;", "",
                        "module ParityFunctions {", *bodies, "}"]) + "\n"
    (project / "source" / "ParityFunctions.mc").write_text(source, encoding="utf-8")
    barrel = project / "runtime-lib"
    barrel.mkdir(exist_ok=True)
    (barrel / "WfbMath.mc").write_text((RUNTIME_LIB / "WfbMath.mc").read_text(encoding="utf-8"),
                                       encoding="utf-8")

    process = _compile(project, toolchain)
    output = _strip_noise(process.stdout + process.stderr)
    assert process.returncode == 0, output
    assert "WARNING" not in output, output
