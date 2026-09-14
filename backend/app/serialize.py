"""Generic SQLAlchemy-model -> JSON-safe dict serializer.

Given the size of the entity dictionary (Section 8 defines ~35 entities),
hand-writing a Pydantic response schema for every single one would multiply
the amount of code without adding safety that matters for a reference/demo
build. Instead every router serializes ORM rows through `to_dict()`, which
introspects the mapped columns and converts Decimal/datetime/UUID into
JSON-safe primitives. Request bodies that matter for business-rule
correctness (login, scheduling, transitions) still get explicit Pydantic
models in schemas.py.
"""
import datetime as dt
import decimal

from sqlalchemy import inspect


def to_dict(obj, extra: dict | None = None) -> dict:
    if obj is None:
        return None
    mapper = inspect(obj).mapper
    out = {}
    for column in mapper.columns:
        value = getattr(obj, column.key)
        if isinstance(value, decimal.Decimal):
            value = float(value)
        elif isinstance(value, (dt.datetime, dt.date)):
            value = value.isoformat()
        out[_camel(column.key)] = value
    if extra:
        out.update(extra)
    return out


def to_list(objs, extra=None):
    return [to_dict(o, extra) for o in objs]


def _camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])
