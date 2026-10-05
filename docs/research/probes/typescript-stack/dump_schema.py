"""Every example face plus 40 seeded mutations of each, with what
jsonschema (Draft 2020-12, as wfb.validate runs it) reports, for schema.mjs
to compare with Ajv.

A mutation is one of: a value's type changed, a key removed, an unknown key
added, a string misspelt (or, where the chosen kind does not apply, a value
set to null). Leaf errors are flattened through oneOf/anyOf `context`, as
(instance path, keyword).

    ./.venv/bin/python docs/research/probes/typescript-stack/dump_schema.py > schema_cases.json
"""
import copy
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from jsonschema import Draft202012Validator  # noqa: E402

from wfb.edit.spans import parse  # noqa: E402
from wfb.validate import load_schema  # noqa: E402

schema = load_schema()
validator = Draft202012Validator(schema)
rng = random.Random(31)


def plain(x):
    return json.loads(json.dumps(x, default=str))


def leaves(errors):
    out = set()
    for e in errors:
        out.add(("/" + "/".join(map(str, e.absolute_path)), e.validator))
        if e.context:
            out |= leaves(e.context)
    return out


def spots(x, path=()):
    yield path, x
    if isinstance(x, dict):
        for k, v in x.items():
            yield from spots(v, path + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from spots(v, path + (i,))


def mutate(doc):
    d = copy.deepcopy(doc)
    p = rng.choice([p for p, _ in spots(d) if p])
    parent = d
    for k in p[:-1]:
        parent = parent[k]
    kind = rng.choice(["type", "remove", "unknown", "misspell"])
    v = parent[p[-1]]
    if kind == "type":
        parent[p[-1]] = 7 if isinstance(v, str) else "seven"
    elif kind == "remove" and isinstance(parent, dict):
        del parent[p[-1]]
    elif kind == "unknown" and isinstance(v, dict):
        v["bogus_key"] = 1
    elif kind == "misspell" and isinstance(v, str):
        parent[p[-1]] = v + "x"
    else:
        parent[p[-1]] = None
    return d, f"{kind} {'/'.join(map(str, p))}"


cases = []
for face in sorted(Path("examples").rglob("face.yaml")):
    doc = plain(parse(face.read_text(encoding="utf-8")))
    for i in range(41):
        data, what = (doc, "original") if i == 0 else mutate(doc)
        t = time.perf_counter()
        errs = list(validator.iter_errors(data))
        ms = (time.perf_counter() - t) * 1000
        cases.append({"face": str(face), "what": what, "data": data, "valid": not errs,
                      "ms": round(ms, 2), "leaves": sorted(leaves(errs))})
json.dump({"schema": schema, "cases": cases}, sys.stdout)
