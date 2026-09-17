"""Canonical variable type rules shared by container and child compilers."""

_TYPE_ALIASES = {
    "file-list": "array[file]",
    "arrayFile": "array[file]",
    "arrayString": "array[string]",
    "arrayNumber": "array[number]",
    "arrayBoolean": "array[boolean]",
    "arrayObject": "array[object]",
}
_ARRAY_ITEM_TYPES = {
    "array": "object",
    "array[string]": "string",
    "array[number]": "number",
    "array[boolean]": "boolean",
    "array[object]": "object",
    "array[file]": "file",
}
_AGGREGATE_TYPES = {
    "string": "array[string]",
    "number": "array[number]",
    "boolean": "array[boolean]",
    "object": "array[object]",
    "file": "array[file]",
    "array": "array",
    "array[string]": "array[string]",
    "array[number]": "array[number]",
    "array[boolean]": "array[boolean]",
    "array[object]": "array[object]",
    "array[file]": "array[file]",
}


def canonical_value_type(value_type: str) -> str:
    """Normalize Dify aliases to the selector registry's canonical spelling."""
    return _TYPE_ALIASES.get(value_type, value_type)


def array_item_type(array_type: str) -> str:
    """Return the item type for an iteration input array."""
    canonical = canonical_value_type(array_type)
    item_type = _ARRAY_ITEM_TYPES.get(canonical)
    if item_type is None:
        raise ValueError(f"iterator type {array_type!r} is not an array")
    return item_type


def is_array_type(value_type: str) -> bool:
    """Return whether a type is a supported iteration array spelling."""
    return canonical_value_type(value_type) in _ARRAY_ITEM_TYPES


def aggregate_type(value_type: str) -> str:
    """Return the public iteration output type for one child result type."""
    aggregated = _AGGREGATE_TYPES.get(canonical_value_type(value_type))
    if aggregated is None:
        raise ValueError(f"cannot aggregate iteration output type {value_type!r}")
    return aggregated
