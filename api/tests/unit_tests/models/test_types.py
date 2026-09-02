from typing import cast

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import StatementError
from sqlalchemy.sql.sqltypes import TEXT

from models.types import JSONModelColumn, LimitedAdjustedJSON, LimitedLongText


class JsonColumnSample(BaseModel):
    name: str
    count: int = 0


class NotPydanticModel:
    pass


def test_json_model_column_serializes_supported_input_shapes():
    column = JSONModelColumn(JsonColumnSample)
    dialect = sqlite.dialect()

    assert column.process_bind_param(None, dialect) is None
    assert column.process_bind_param(JsonColumnSample(name="model", count=2), dialect) == '{"count":2,"name":"model"}'
    assert column.process_bind_param({"name": "dict", "count": 3}, dialect) == '{"count":3,"name":"dict"}'
    assert column.process_bind_param('{"name":"json","count":4}', dialect) == '{"count":4,"name":"json"}'


def test_json_model_column_deserializes_empty_and_json_values():
    column = JSONModelColumn(JsonColumnSample)
    dialect = sqlite.dialect()

    assert column.process_result_value(None, dialect) is None
    assert column.process_result_value("", dialect) is None
    assert column.process_result_value('{"name":"stored","count":5}', dialect) == JsonColumnSample(
        name="stored",
        count=5,
    )


def test_json_model_column_keeps_model_class_directly():
    column = JSONModelColumn(JsonColumnSample)

    assert column.process_bind_param({"name": "class", "count": 6}, sqlite.dialect()) == '{"count":6,"name":"class"}'
    assert column._model_class is JsonColumnSample


def test_json_model_column_rejects_non_pydantic_model_class():
    with pytest.raises(TypeError, match="must be a Pydantic BaseModel subclass"):
        JSONModelColumn(cast(type[BaseModel], NotPydanticModel))


def test_json_model_column_uses_long_text_compatible_dialect_types():
    column = JSONModelColumn(JsonColumnSample)

    assert isinstance(column.load_dialect_impl(postgresql.dialect()), TEXT)
    assert isinstance(column.load_dialect_impl(sqlite.dialect()), TEXT)
    assert isinstance(column.load_dialect_impl(mysql.dialect()), LONGTEXT)


def test_json_model_column_rejects_string_model_paths():
    with pytest.raises(TypeError):
        JSONModelColumn(cast(type[BaseModel], "tests.unit_tests.models.test_types.JsonColumnSample"))


@pytest.mark.parametrize(
    "dialect",
    [sqlite.dialect(), postgresql.dialect(), mysql.dialect()],
    ids=["sqlite", "postgresql", "mysql"],
)
@pytest.mark.parametrize(
    ("accepted", "rejected"),
    [
        ({"data": "x" * 20}, {"data": "x" * 21}),
        ({"data": ("é" * 3) + "xx"}, {"data": ("é" * 3) + "xxx"}),
    ],
    ids=["ascii", "multibyte"],
)
def test_limited_json_full_bind_processor_enforces_exact_dialect_bytes(dialect, accepted, rejected):
    column = LimitedAdjustedJSON(max_bytes=32, field_name="payload")
    dialect_type = column.dialect_impl(dialect)
    processor = dialect_type.bind_processor(dialect)
    raw_processor = dialect_type.impl_instance.bind_processor(dialect)
    assert processor is not None
    assert raw_processor is not None

    bound = processor(accepted)
    assert isinstance(bound, str)
    assert len(bound.encode("utf-8")) == 32
    assert len(raw_processor(rejected).encode("utf-8")) == 33
    with pytest.raises(ValueError, match="payload exceeds 32 bytes"):
        processor(rejected)


@pytest.mark.parametrize(
    "dialect",
    [sqlite.dialect(), postgresql.dialect(), mysql.dialect()],
    ids=["sqlite", "postgresql", "mysql"],
)
def test_limited_json_full_bind_processor_rejects_non_json_values(dialect):
    column = LimitedAdjustedJSON(max_bytes=100, field_name="payload")
    processor = column.dialect_impl(dialect).bind_processor(dialect)
    assert processor is not None

    with pytest.raises(ValueError, match="payload must contain JSON-native values"):
        processor({"unsupported": object()})


def test_limited_types_preserve_none_results_and_dialect_storage_types():
    text_column = LimitedLongText(max_bytes=10, field_name="input")
    json_column = LimitedAdjustedJSON(max_bytes=10, field_name="payload")

    assert text_column.process_bind_param(None, sqlite.dialect()) is None
    assert text_column.process_result_value(None, sqlite.dialect()) is None
    assert text_column.process_result_value("stored", sqlite.dialect()) == "stored"
    assert json_column.process_bind_param(None, sqlite.dialect()) is None
    assert json_column.process_result_value(None, sqlite.dialect()) is None
    assert json_column.process_result_value({"stored": True}, sqlite.dialect()) == {"stored": True}
    assert isinstance(text_column.load_dialect_impl(postgresql.dialect()), TEXT)
    assert isinstance(text_column.load_dialect_impl(sqlite.dialect()), TEXT)
    assert isinstance(text_column.load_dialect_impl(mysql.dialect()), LONGTEXT)
    assert isinstance(json_column.load_dialect_impl(postgresql.dialect()), JSONB)
    assert isinstance(json_column.load_dialect_impl(sqlite.dialect()), sa.JSON)
    assert isinstance(json_column.load_dialect_impl(mysql.dialect()), sa.JSON)


def test_limited_type_cache_keys_include_all_behavior_parameters():
    text = LimitedLongText(max_bytes=100, field_name="input")
    assert text._static_cache_key != LimitedLongText(max_bytes=5, field_name="input")._static_cache_key
    assert text._static_cache_key != LimitedLongText(max_bytes=100, field_name="other input")._static_cache_key

    json = LimitedAdjustedJSON(max_bytes=100, field_name="payload")
    assert json._static_cache_key != LimitedAdjustedJSON(max_bytes=5, field_name="payload")._static_cache_key
    assert json._static_cache_key != LimitedAdjustedJSON(max_bytes=100, field_name="other payload")._static_cache_key
    assert (
        LimitedAdjustedJSON(
            max_bytes=100,
            field_name="payload",
            astext_type=sa.String(10),
        )._static_cache_key
        != LimitedAdjustedJSON(
            max_bytes=100,
            field_name="payload",
            astext_type=sa.String(20),
        )._static_cache_key
    )


@pytest.mark.parametrize("kind", ["text", "json"])
def test_shared_compiled_cache_cannot_reuse_a_loose_limited_type_for_a_strict_one(kind):
    if kind == "text":
        loose_type = LimitedLongText(max_bytes=100, field_name="loose input")
        strict_type = LimitedLongText(max_bytes=5, field_name="strict input")
        value = "123456"
        error = "strict input exceeds 5 bytes"
    else:
        loose_type = LimitedAdjustedJSON(max_bytes=100, field_name="loose payload")
        strict_type = LimitedAdjustedJSON(max_bytes=5, field_name="strict payload")
        value = {"x": 1}
        error = "strict payload exceeds 5 bytes"

    compiled_cache: dict = {}
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect().execution_options(compiled_cache=compiled_cache) as connection:
        connection.execute(sa.select(sa.bindparam("value", type_=loose_type)), {"value": value})
        with pytest.raises(StatementError, match=error):
            connection.execute(sa.select(sa.bindparam("value", type_=strict_type)), {"value": value})

    assert len(compiled_cache) == 2
