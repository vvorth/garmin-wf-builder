"""What a doc may cite (`docs/CLAUDE.md`, "What a doc may cite").

Records -- `docs/research/`, `docs/plans/`, `docs/adr/` -- carry history and
may cite each other. Everything else states what is true now:

* **no plan citations anywhere outside the records**: not in a doc, a
  `CLAUDE.md`, the schema, an example, or a code comment;
* **no research citations** in the guide, the schema, a README, an example
  face or a `CLAUDE.md`, which point to the guide or `docs/limitations.md`
  instead. `docs/limitations.md`, `docs/lore/` and code comments may cite
  research as evidence, so they are not checked for it.

A citation that wraps across a line break counts: the patterns allow any
whitespace inside one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: "plan 14", "slice 2", "plans 01-02", a link into `docs/plans/`.
PLAN = re.compile(r"\b[Pp]lans?\s+\d+|\b[Ss]lices?\s+\d+|docs/plans/")

#: "research 11", a numbered research file, a probe. The research index
#: (`research/00-summary.md`) is a pointer, not a citation.
RESEARCH = re.compile(r"\b[Rr]esearch\s+\d+|research/(?!00-summary)\d{2}|research/probes")

RECORDS = ("docs/research/", "docs/plans/", "docs/adr/")

#: Passages that name the records rather than cite them: the rules
#: themselves and the index pointing at them. Each is (file, text on the
#: matching line).
ALLOWED = {
    ("CLAUDE.md", "`docs/plans/README.md` (open plans, and how to read deleted ones)"),
    ("CLAUDE.md", "probes), `docs/plans/` and `docs/adr/`: they carry history"),
    ("CLAUDE.md", "`docs/plans/` links). **Research may be cited only"),
    ("CLAUDE.md", "| 0 research (`docs/research/00`–`12`) | complete, reviewed |"),
    ("docs/CLAUDE.md", 'no "plan 14 §4.3",'),
    ("docs/CLAUDE.md", '"slice 2", decision ids (D3, R2.1, A5), `docs/plans/` links'),
    ("docs/CLAUDE.md", "| `research/NN-*.md` | investigations"),
    ("docs/CLAUDE.md", "| `research/probes/` | minimal Monkey C projects"),
}

SUFFIXES = {".md", ".py", ".mc", ".js", ".json", ".yaml", ".yml", ".sh"}


def _files(*roots: str) -> list[Path]:
    out = []
    for root in roots:
        path = ROOT / root
        found = [path] if path.is_file() else path.rglob("*")
        for f in found:
            rel = f.relative_to(ROOT).as_posix()
            if (f.is_file() and f.suffix in SUFFIXES and not rel.startswith(RECORDS)
                    and "/vendor/" not in rel and "__pycache__" not in rel
                    and "/node_modules/" not in rel and f != Path(__file__)):
                out.append(f)
    return sorted(out)


def _offences(pattern: re.Pattern[str], files: list[Path]) -> list[str]:
    found = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        rel = f.relative_to(ROOT).as_posix()
        for m in pattern.finditer(text):
            line = text.count("\n", 0, m.start())
            shown = lines[line]
            if any(rel == path and part in shown for path, part in ALLOWED):
                continue
            found.append(f"{rel}:{line + 1}: {m.group()!r} in {shown.strip()!r}")
    return found


def _claude_files() -> list[str]:
    return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("CLAUDE.md")
            if not p.relative_to(ROOT).as_posix().startswith((".venv/", "vendor/", "build/"))]


def test_nothing_outside_the_records_cites_a_plan():
    files = _files("docs", "README.md", "wfb", "runtime-lib", "tests", "tools", "schema",
                   "examples", *_claude_files())
    offences = _offences(PLAN, files)
    assert not offences, ("plans are never cited outside docs/research, docs/plans and "
                          "docs/adr; state the fact instead:\n" + "\n".join(offences))


def test_the_guide_readmes_schema_examples_and_claude_files_cite_no_research():
    files = _files("docs/guide", "README.md", "docs/README.md", "schema", "examples",
                   *_claude_files())
    offences = _offences(RESEARCH, files)
    assert not offences, ("point to the guide or docs/limitations.md instead of citing "
                          "research:\n" + "\n".join(offences))
