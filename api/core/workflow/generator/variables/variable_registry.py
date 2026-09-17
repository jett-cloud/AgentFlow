"""Immutable typed variable table used by Tool and container compilers.

The registry is the single resolve seam for selector existence, container
scope, producer-before-consumer availability, and conservative type checks.
It does not read the database or mutate the candidate graph.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

_CANONICAL_VARIABLE_TYPES: dict[str, str] = {
    "text-input": "string",
    "paragraph": "string",
    "select": "string",
    "dynamic-select": "string",
    "secret-input": "string",
    "integer": "number",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "app-selector": "object",
    "model-selector": "object",
    "list": "array",
    "arrayString": "array[string]",
    "arrayNumber": "array[number]",
    "arrayBoolean": "array[boolean]",
    "arrayObject": "array[object]",
    "arrayFile": "array[file]",
    "file-list": "array[file]",
}


def canonical_registry_type(value_type: str) -> str:
    """Normalize runtime form and legacy aliases for selector comparison/display."""
    return _CANONICAL_VARIABLE_TYPES.get(value_type, value_type)


class VariableResolutionError(ValueError):
    """Stable compile-time failure for one selector."""

    def __init__(self, code: str, selector: tuple[str, ...], detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.selector = selector
        self.detail = detail


@dataclass(frozen=True)
class VariableDeclaration:
    selector: tuple[str, ...]
    value_type: str
    owner_container_id: str | None
    producer_layer: int
    guaranteed: bool


@dataclass(frozen=True)
class VariableReferrer:
    node_id: str
    layer: int
    ancestor_container_ids: tuple[str, ...]
    allows_self_variables: bool = False


class VariableRegistry:
    """Frozen lookup of declared selectors keyed for one compile snapshot."""

    _declarations: Mapping[tuple[str, ...], VariableDeclaration]
    _referrers: Mapping[str, VariableReferrer]
    _known_node_ids: frozenset[str]

    def __init__(
        self,
        declarations: Iterable[VariableDeclaration],
        *,
        referrers: Iterable[VariableReferrer] = (),
        known_node_ids: frozenset[str] | None = None,
    ) -> None:
        declaration_map = {item.selector: item for item in declarations}
        referrer_map = {item.node_id: item for item in referrers}
        nodes = set(known_node_ids or ())
        nodes.update(selector[0] for selector in declaration_map if selector)
        nodes.update(referrer_map)
        self._declarations = MappingProxyType(declaration_map)
        self._referrers = MappingProxyType(referrer_map)
        self._known_node_ids = frozenset(nodes)

    def resolve(
        self,
        selector: tuple[str, ...],
        *,
        referrer_id: str,
        expected_type: str | None,
    ) -> VariableDeclaration:
        declaration = self._declarations.get(selector)
        if declaration is None:
            code = "UNKNOWN_OUTPUT" if selector and selector[0] in self._known_node_ids else "UNKNOWN_NODE_REFERENCE"
            detail = "变量未声明" if code == "UNKNOWN_OUTPUT" else "引用了未知节点"
            raise VariableResolutionError(code, selector, detail)
        self._assert_scope(declaration, referrer_id)
        self._assert_available(declaration, referrer_id)
        self._assert_compatible_type(declaration, expected_type)
        return declaration

    def outputs_for(self, node_id: str) -> tuple[str, ...]:
        """Return declared output names for ``node_id`` in declaration order."""
        names: list[str] = []
        seen: set[str] = set()
        for selector in self._declarations:
            if len(selector) < 2 or selector[0] != node_id:
                continue
            name = selector[1]
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return tuple(names)

    def _assert_scope(self, declaration: VariableDeclaration, referrer_id: str) -> None:
        owner = declaration.owner_container_id
        if owner is None:
            return
        if referrer_id == owner:
            return
        referrer = self._require_referrer(declaration.selector, referrer_id)
        if owner in referrer.ancestor_container_ids:
            return
        raise VariableResolutionError(
            "PRIVATE_CONTAINER_REFERENCE",
            declaration.selector,
            "变量仅限容器内部引用",
        )

    def _assert_available(self, declaration: VariableDeclaration, referrer_id: str) -> None:
        referrer = self._require_referrer(declaration.selector, referrer_id)
        if referrer.allows_self_variables and declaration.selector and declaration.selector[0] == referrer_id:
            return
        if declaration.producer_layer < referrer.layer and declaration.guaranteed:
            return
        raise VariableResolutionError(
            "REFERENCE_NOT_AVAILABLE",
            declaration.selector,
            "来源尚未在此节点之前执行",
        )

    def _assert_compatible_type(self, declaration: VariableDeclaration, expected_type: str | None) -> None:
        if expected_type is None:
            return
        actual = canonical_registry_type(declaration.value_type)
        expected = canonical_registry_type(expected_type)
        if actual == expected or (expected == "array" and actual.startswith("array[")):
            return
        raise VariableResolutionError(
            "VARIABLE_TYPE_MISMATCH",
            declaration.selector,
            f"期望 {expected}，实际 {actual}",
        )

    def _require_referrer(self, selector: tuple[str, ...], referrer_id: str) -> VariableReferrer:
        referrer = self._referrers.get(referrer_id)
        if referrer is None:
            raise VariableResolutionError("UNKNOWN_NODE_REFERENCE", selector, "引用了未知节点")
        return referrer
