"""garmin-wf-builder — a declarative watch face builder for Garmin Connect IQ.

The public entry point is :mod:`wfb.cli`.  The pipeline is:

    YAML  ->  schema validation  ->  IR  ->  per-device layout resolve
          ->  lint  ->  Monkey C + resources + jungle + manifest  ->  monkeyc

Each stage is a separate module so that the stages which need no Garmin
toolchain (everything up to and including codegen) stay testable in CI.
"""

__version__ = "0.1.0"

#: The document ``format:`` majors this compiler accepts (ADR 0009).
SUPPORTED_FORMATS = (1,)
