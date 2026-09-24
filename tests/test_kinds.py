"""`wfb.kinds`: the registry pins to the schema, and every
concrete `Element`/`Placed` subclass has exactly one kind."""

from __future__ import annotations

import json
from pathlib import Path

from wfb import kinds, validate
from wfb.ir import model as ir_model
from wfb import layout


def _schema_element_types() -> tuple[str, ...]:
    schema = json.loads(Path(validate.SCHEMA_PATH).read_text(encoding="utf-8"))
    defs = schema["$defs"]
    out = []
    for ref in defs["element"]["oneOf"]:
        name = ref["$ref"].rsplit("/", 1)[-1]
        out.append(defs[name]["properties"]["type"]["const"])
    return tuple(out)


def test_names_match_the_schema_and_validate():
    schema_order = _schema_element_types()
    assert kinds.names() == schema_order
    assert kinds.names() == validate.ELEMENT_TYPES


def _concrete_element_classes() -> set[type]:
    return {
        cls for cls in vars(ir_model).values()
        if isinstance(cls, type) and issubclass(cls, ir_model.Element) and cls is not ir_model.Element
    }


def _placed_classes() -> set[type]:
    return {
        cls for cls in vars(layout).values()
        if isinstance(cls, type) and issubclass(cls, layout.Placed) and cls is not layout.Placed
    }


def test_every_element_class_has_exactly_one_kind():
    for cls in _concrete_element_classes():
        kind = kinds.for_element(cls.__new__(cls))
        assert kind.ir_class is cls


def test_every_placed_class_has_exactly_one_kind():
    for cls in _placed_classes():
        kind = kinds.for_placed(cls.__new__(cls))
        assert kind.placed_class is cls


def test_group_placed_class_is_the_base_placed():
    assert kinds.get("group").placed_class is layout.Placed


def test_every_kind_name_is_registered_once():
    all_kinds = kinds.all()
    assert [k.name for k in all_kinds] == list(kinds.names())
    assert len({k.ir_class for k in all_kinds}) == len(all_kinds)
    assert len({k.placed_class for k in all_kinds}) == len(all_kinds)
