"""Write cases.json for check.mjs: every example face as written, and
mutated copies, each with how many errors `wfb`'s own validator
(jsonschema, Draft 2020-12) finds in it.

Backs docs/research/28-editor-open-questions.md §6.

    ./.venv/bin/python docs/research/probes/gui-editor/schema-dialect/cases.py
    cd docs/research/probes/gui-editor/schema-dialect && npm install && node check.mjs

`check.mjs` validates the same documents with `json-schema-library`'s
`Draft04` and `Draft07` -- the two drafts `codemirror-json-schema` 0.8.1
constructs for validation/hover and for completion -- and counts where they
disagree with jsonschema. Results: results.txt.
"""

from __future__ import annotations

import copy
import glob
import json
from pathlib import Path

import jsonschema
from ruamel.yaml import YAML

HERE = Path(__file__).resolve().parent
schema = json.loads(Path("schema/wfb-face-2.schema.json").read_text())
validator = jsonschema.Draft202012Validator(schema)
faces = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
               if "examples/dashboard/" not in f)
cases = []


def add(name: str, doc) -> None:
    cases.append({"name": name, "doc": doc, "py_errors": len(list(validator.iter_errors(doc)))})


MUTATIONS = {
    "unknown key": lambda e: e.__setitem__("colr", "x"),
    "bad type value": lambda e: e.__setitem__("type", "rectangel"),
    "missing type": lambda e: e.pop("type", None),
    "at not a mapping": lambda e: e.__setitem__("at", 5),
}

for f in faces:
    doc = json.loads(json.dumps(YAML(typ="safe").load(open(f)), default=str))
    add(f"{f} (as written)", doc)
    elements = doc.get("elements") or {}
    for element_id in list(elements)[:3]:
        if isinstance(elements[element_id], dict):
            for label, mutate in MUTATIONS.items():
                m = copy.deepcopy(doc)
                mutate(m["elements"][element_id])
                add(f"{f} {element_id}: {label}", m)
    # `dependentRequired` (2019-09+): `at.angle` needs `radius`; a gauge's
    # `value` needs `max`
    for element_id, e in elements.items():
        if isinstance(e, dict) and isinstance(e.get("at"), dict) and "angle" not in e["at"]:
            m = copy.deepcopy(doc)
            m["elements"][element_id]["at"]["angle"] = "30deg"
            add(f"{f} {element_id}: dependentRequired at.angle without radius", m)
            break
    for element_id, e in elements.items():
        if isinstance(e, dict) and e.get("type") == "gauge" and "value" in e and "max" in e:
            m = copy.deepcopy(doc)
            del m["elements"][element_id]["max"]
            add(f"{f} {element_id}: dependentRequired gauge value without max", m)
            break

HERE.joinpath("cases.json").write_text(json.dumps({"schema": schema, "cases": cases}))
print(len(cases), "cases")
