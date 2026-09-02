import enum
import json
import uuid
from typing import Any, cast, override

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy import CHAR, TEXT, VARCHAR, LargeBinary, TypeDecorator
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.type_api import TypeEngine, _BindProcessorType

from configs import dify_config


class StringUUID(TypeDecorator[uuid.UUID | str | None]):
    impl = CHAR
    cache_ok = True

    @override
    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        elif dialect.name in ["postgresql", "mysql"]:
            return str(value)
        else:
            if isinstance(value, uuid.UUID):
                return value.hex
            return value

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    @override
    def process_result_value(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        return str(value)


class LongText(TypeDecorator[str | None]):
    impl = TEXT
    cache_ok = True

    @override
    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        return value

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TEXT())
        elif dialect.name == "mysql":
            return dialect.type_descriptor(LONGTEXT())
        else:
            return dialect.type_descriptor(TEXT())

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        return value


def validate_text_byte_limit(value: str, *, max_bytes: int, field_name: str) -> str:
    """Validate the UTF-8 persistence budget shared by early and bind-time checks."""
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field_name} exceeds {max_bytes} bytes")
    return value


class LimitedLongText(LongText):
    """Dialect-adjusted long text with an authoritative UTF-8 bind limit."""

    cache_ok = True

    max_bytes: int
    field_name: str

    def __init__(self, max_bytes: int, field_name: str):
        self.max_bytes = max_bytes
        self.field_name = field_name
        super().__init__()

    @override
    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return validate_text_byte_limit(value, max_bytes=self.max_bytes, field_name=self.field_name)


class JSONModelColumn[T: BaseModel](TypeDecorator[T | None]):
    """Store a Pydantic model as dialect-adjusted LongText JSON."""

    impl = TEXT
    cache_ok = True

    _model_class: type[T]

    def __init__(self, model_class: type[T]):
        if not issubclass(model_class, BaseModel):
            raise TypeError(f"{model_class.__module__}.{model_class.__name__} must be a Pydantic BaseModel subclass")
        self._model_class = model_class
        super().__init__()

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TEXT())
        elif dialect.name == "mysql":
            return dialect.type_descriptor(LONGTEXT())
        else:
            return dialect.type_descriptor(TEXT())

    @override
    def process_bind_param(self, value: T | dict[str, Any] | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        match value:
            case _ if isinstance(value, self._model_class):
                model = value
            case str():
                model = self._model_class.model_validate_json(value)
            case _:
                model = self._model_class.model_validate(value)
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> T | None:
        if value is None or value == "":
            return None
        return self._model_class.model_validate_json(value)


class BinaryData(TypeDecorator[bytes | None]):
    impl = LargeBinary
    cache_ok = True

    @override
    def process_bind_param(self, value: bytes | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return value
        return value

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(BYTEA())
        elif dialect.name == "mysql":
            return dialect.type_descriptor(LONGBLOB())
        else:
            return dialect.type_descriptor(LargeBinary())

    @override
    def process_result_value(self, value: bytes | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return value
        return value


class AdjustedJSON(TypeDecorator[dict | list | None]):
    impl = sa.JSON
    cache_ok = True

    def __init__(self, astext_type=None):
        self.astext_type = astext_type
        super().__init__()

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            if self.astext_type:
                return dialect.type_descriptor(JSONB(astext_type=self.astext_type))
            else:
                return dialect.type_descriptor(JSONB())
        elif dialect.name == "mysql":
            return dialect.type_descriptor(sa.JSON())
        else:
            return dialect.type_descriptor(sa.JSON())

    @override
    def process_bind_param(
        self, value: dict[str, Any] | list[Any] | None, dialect: Dialect
    ) -> dict[str, Any] | list[Any] | None:
        return value

    @override
    def process_result_value(
        self, value: dict[str, Any] | list[Any] | None, dialect: Dialect
    ) -> dict[str, Any] | list[Any] | None:
        return value


def validate_json_value[T: dict[str, Any] | list[Any]](value: T, *, field_name: str) -> T:
    """Reject values that the standard JSON serializer cannot persist."""
    try:
        json.dumps(
            value,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-native values") from exc
    return value


class LimitedAdjustedJSON(AdjustedJSON):
    """Dialect-adjusted JSON with JSON-native and byte-budget checks at bind time."""

    cache_ok = True

    max_bytes: int
    field_name: str

    def __init__(self, max_bytes: int, field_name: str, astext_type=None):
        self.max_bytes = max_bytes
        self.field_name = field_name
        super().__init__(astext_type=astext_type)

    @override
    def process_bind_param(
        self, value: dict[str, Any] | list[Any] | None, dialect: Dialect
    ) -> dict[str, Any] | list[Any] | None:
        if value is None:
            return None
        return validate_json_value(value, field_name=self.field_name)

    @override
    def bind_processor(self, dialect: Dialect) -> _BindProcessorType[dict | list | None] | None:
        """Validate the exact serialized bytes emitted by this dialect's JSON type."""
        impl_processor = self.impl_instance.bind_processor(dialect)

        def process(value: dict[str, Any] | list[Any] | None) -> Any:
            validated = self.process_bind_param(value, dialect)
            try:
                bound = impl_processor(validated) if impl_processor is not None else validated
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.field_name} must contain JSON-native values") from exc

            if bound is None:
                return None
            if isinstance(bound, str):
                serialized = bound.encode("utf-8")
            elif isinstance(bound, bytes):
                serialized = bound
            else:
                raise ValueError(f"{self.field_name} must serialize to text or bytes")
            if len(serialized) > self.max_bytes:
                raise ValueError(f"{self.field_name} exceeds {self.max_bytes} bytes")
            return bound

        return process


class EnumText[T: enum.StrEnum](TypeDecorator[T | None]):
    impl = VARCHAR
    cache_ok = True

    _length: int
    _enum_class: type[T]

    def __init__(self, enum_class: type[T], length: int | None = None):
        self._enum_class = enum_class
        max_enum_value_len = max(len(e.value) for e in enum_class)
        if length is not None:
            if length < max_enum_value_len:
                raise ValueError("length should be greater than enum value length.")
            self._length = length
        else:
            # leave some rooms for future longer enum values.
            self._length = max(max_enum_value_len, 20)

    @override
    def process_bind_param(self, value: T | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        if isinstance(value, self._enum_class):
            return value.value
        # Since T is bound to StrEnum which inherits from str, at this point value must be str
        self._enum_class(value)
        return value

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(VARCHAR(self._length))

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> T | None:
        if value is None or value == "":
            return None
        try:
            # Type annotation guarantees value is str at this point
            return self._enum_class(value)
        except ValueError:
            value_of = getattr(self._enum_class, "value_of", None)
            if callable(value_of):
                return cast(T, value_of(value))
            raise

    @override
    def compare_values(self, x: T | None, y: T | None) -> bool:
        if x is None or y is None:
            return x is y
        return x == y


def adjusted_json_index(index_name, column_name):
    index_name = index_name or f"{column_name}_idx"
    if dify_config.DB_TYPE == "postgresql":
        return sa.Index(index_name, column_name, postgresql_using="gin")
    else:
        return None
