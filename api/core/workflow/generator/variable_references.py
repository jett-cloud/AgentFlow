"""Variable discovery, rewriting, and repair for generated workflow graphs."""

import logging
import re
from typing import Any, ClassVar

from core.workflow.generator.types import WorkflowGenerationMode
from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)


class VariableReferences:
    _VAR_REF_RE: ClassVar = re.compile(
        r"\{\{#([a-zA-Z0-9_]{1,50})\.([a-zA-Z_][a-zA-Z0-9_]{0,29}(?:\.[a-zA-Z_][a-zA-Z0-9_]{0,29}){0,9})#\}\}"
    )
    _LENIENT_VAR_REF_RE: ClassVar = re.compile(r"\{\{#([^#.{}]+)\.([^#]+)#\}\}")
    _INVALID_ID_CHARS_RE: ClassVar = re.compile(r"[^a-zA-Z0-9_]")
    _ID_FIELDS: ClassVar = frozenset({"start_node_id", "iteration_id", "loop_id", "parentId"})
    _NON_SELECTOR_LIST_KEYS: ClassVar = frozenset(
        {"default", "options", "allowed_file_types", "allowed_file_extensions", "allowed_file_upload_methods"}
    )

    @classmethod
    def _inject_start_variable(cls, start_node: dict[str, Any], var: str) -> None:
        """Add a default paragraph input so a Start reference resolves."""
        data = start_node.setdefault("data", {})
        existing = data.setdefault("variables", [])
        if any(isinstance(value, dict) and value.get("variable") == var for value in existing):
            return
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", var).lower()
        label = " ".join(part.capitalize() for part in snake.split("_") if part)
        existing.append(
            {
                "variable": var,
                "label": label,
                "type": "paragraph",
                "required": True,
                "max_length": 4096,
                "options": [],
            }
        )

    @classmethod
    def _normalize_sys_query_references(
        cls,
        *,
        nodes: list[dict[str, Any]],
        mode: WorkflowGenerationMode,
    ) -> None:
        """Normalize malformed ``sys.query`` references without changing their intent.

        Chatflows expose ``sys.query`` directly. Plain workflows do not, so
        their query references become a Start-node input and the existing
        reconciliation pass declares that input immediately afterwards.
        """
        if mode == "advanced-chat":
            target_node_id = "sys"
        else:
            start_node = next(
                (node for node in nodes if node.get("data", {}).get("type") == BuiltinNodeTypes.START),
                None,
            )
            start_node_id = start_node.get("id") if start_node else None
            if not isinstance(start_node_id, str) or not start_node_id:
                return
            target_node_id = start_node_id

        for node in nodes:
            data = node.get("data")
            if isinstance(data, dict):
                cls._normalize_sys_query_reference_in_data(data, target_node_id=target_node_id)

    @classmethod
    def _normalize_sys_query_reference_in_data(
        cls,
        value: Any,
        *,
        target_node_id: str,
        allow_selector: bool = True,
    ) -> Any:
        """Rewrite query placeholders and selectors at any node-data depth.

        Some node schemas store selectors inside another list, for example a
        parameter extractor's ``query`` or a variable aggregator's
        ``variables``. Literal string-list fields opt out so an option list
        such as ``["sys", "query"]`` is preserved.
        """
        target_placeholder = f"{{{{#{target_node_id}.query#}}}}"
        if isinstance(value, str):
            return value.replace("{{#sys.query#}}", target_placeholder).replace("{{#sys,query#}}", target_placeholder)
        if isinstance(value, dict):
            for key, item in list(value.items()):
                item_allows_selector = allow_selector and key not in cls._NON_SELECTOR_LIST_KEYS
                if item_allows_selector and cls._is_sys_query_selector(item):
                    value[key] = [target_node_id, "query"]
                    continue
                if (
                    item_allows_selector
                    and cls._is_selector_field(key)
                    and isinstance(item, str)
                    and cls._is_sys_query_token(item)
                ):
                    value[key] = [target_node_id, "query"]
                    continue
                value[key] = cls._normalize_sys_query_reference_in_data(
                    item,
                    target_node_id=target_node_id,
                    allow_selector=item_allows_selector,
                )
            return value
        if isinstance(value, list):
            if allow_selector and cls._is_sys_query_selector(value):
                return [target_node_id, "query"]
            for index, item in enumerate(value):
                value[index] = cls._normalize_sys_query_reference_in_data(
                    item,
                    target_node_id=target_node_id,
                    allow_selector=allow_selector,
                )
        return value

    @staticmethod
    def _is_sys_query_selector(value: Any) -> bool:
        """Recognize the valid selector and common one-item LLM variants."""
        if value == ["sys", "query"]:
            return True
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str):
            return False
        return VariableReferences._is_sys_query_token(value[0])

    @staticmethod
    def _is_sys_query_token(value: str) -> bool:
        """Return whether a string is a compact malformed query selector."""
        return value.replace(" ", "") in {"sys.query", "sys,query"}

    @staticmethod
    def _is_selector_field(key: str) -> bool:
        """Return whether a data field explicitly stores one selector."""
        return key == "selector" or key.endswith("_selector")

    @classmethod
    def _reconcile_variable_references(cls, *, nodes: list[dict[str, Any]], mode: WorkflowGenerationMode) -> None:
        """
        Apply deterministic repairs to unresolved variable references.

        Missing start-node inputs are added as ``paragraph`` variables. For
        non-start nodes, a mistaken output name is rewritten only when the
        source exposes exactly one declared output. Sources with zero or
        multiple outputs remain untouched so validation fails closed instead
        of guessing which value the workflow should consume.

        For Advanced-Chat mode, ``sys.query`` and ``sys.files`` are always
        treated as resolved without any declaration. Tool nodes' parameter
        references aren't validated here because we don't know each tool's
        schema — the run time validates those.
        """
        nodes_by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}
        start_node = next(
            (n for n in nodes if n.get("data", {}).get("type") == BuiltinNodeTypes.START),
            None,
        )

        # Collect every (node_id, var) reference the builder emitted.
        refs: set[tuple[str, str]] = set()
        for node in nodes:
            cls._collect_refs_in_data(node.get("data") or {}, refs)

        for node_id, var in refs:
            # Advanced-Chat system variables are always resolved.
            if mode == "advanced-chat" and node_id == "sys":
                continue
            target = nodes_by_id.get(node_id)
            if target is None:
                # An edge / data dangling reference — we can't fix it; the
                # structural validator picks this up if it's a topology issue.
                continue
            if cls._declares_variable(target, var):
                continue
            if start_node is not None and target is start_node:
                cls._inject_start_variable(start_node, var)
                logger.info("Workflow generator: auto-injected missing start variable %r", var)
                continue

            replacement = cls._sole_declared_variable(target)
            if replacement is None:
                continue
            for node in nodes:
                data = node.get("data")
                if isinstance(data, dict):
                    cls._rewrite_variable_reference_in_data(
                        data,
                        node_id=node_id,
                        old_variable=var,
                        new_variable=replacement,
                    )
            logger.info(
                "Workflow generator: rewrote unresolved reference %s.%s to sole output %s.%s",
                node_id,
                var,
                node_id,
                replacement,
            )

    @classmethod
    def _rewrite_variable_reference_in_data(
        cls,
        value: Any,
        *,
        node_id: str,
        old_variable: str,
        new_variable: str,
        allow_selector: bool = True,
    ) -> Any:
        """Rewrite one exact placeholder or selector at any data depth."""
        if isinstance(value, str):
            return cls._VAR_REF_RE.sub(
                lambda match: (
                    f"{{{{#{node_id}.{new_variable}#}}}}"
                    if match.group(1) == node_id and match.group(2) == old_variable
                    else match.group(0)
                ),
                value,
            )
        if isinstance(value, dict):
            for key, item in list(value.items()):
                value[key] = cls._rewrite_variable_reference_in_data(
                    item,
                    node_id=node_id,
                    old_variable=old_variable,
                    new_variable=new_variable,
                    allow_selector=allow_selector and key not in cls._NON_SELECTOR_LIST_KEYS,
                )
            return value
        if isinstance(value, list):
            if allow_selector and value == [node_id, old_variable]:
                return [node_id, new_variable]
            for index, item in enumerate(value):
                value[index] = cls._rewrite_variable_reference_in_data(
                    item,
                    node_id=node_id,
                    old_variable=old_variable,
                    new_variable=new_variable,
                    allow_selector=allow_selector,
                )
        return value

    @classmethod
    def _collect_refs_in_data(
        cls,
        value: Any,
        out: set[tuple[str, str]],
        *,
        allow_selector: bool = True,
    ) -> None:
        """Recursively harvest placeholders and selectors at any data depth."""
        if isinstance(value, str):
            for match in cls._VAR_REF_RE.finditer(value):
                node_id, var = match.group(1).strip(), match.group(2).strip()
                if node_id and var:
                    out.add((node_id, var))
            return
        if isinstance(value, dict):
            for k, v in value.items():
                cls._collect_refs_in_data(
                    v,
                    out,
                    allow_selector=allow_selector and k not in cls._NON_SELECTOR_LIST_KEYS,
                )
            return
        if isinstance(value, list):
            if allow_selector and len(value) == 2 and all(isinstance(item, str) for item in value):
                node_id, var = value[0].strip(), value[1].strip()
                if node_id and var:
                    out.add((node_id, var))
            for item in value:
                cls._collect_refs_in_data(item, out, allow_selector=allow_selector)

    @classmethod
    def _declared_outputs(cls, node: dict[str, Any]) -> list[str]:
        """Names this node exposes for ``{{#id.name#}}`` / selector references.

        Tool nodes also accept *any* name at validation time (dynamic plugin
        outputs); that exception lives in ``_declares_variable``, not here.
        Compact ``read_graph`` uses this list so the model sees the same names
        the validator grades against.
        """
        data = node.get("data") or {}
        node_type = data.get("type")
        if node_type == BuiltinNodeTypes.START:
            return [
                variable["variable"]
                for variable in (data.get("variables") or [])
                if isinstance(variable, dict) and isinstance(variable.get("variable"), str)
            ]
        if node_type == BuiltinNodeTypes.LLM:
            outputs = ["text"]
            schema = ((data.get("structured_output") or {}).get("schema") or {}).get("properties") or {}
            outputs.extend(key for key in schema if isinstance(key, str) and key != "text")
            return outputs
        if node_type == BuiltinNodeTypes.CODE:
            return [key for key in (data.get("outputs") or {}) if isinstance(key, str)]
        if node_type == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
            return ["result"]
        if node_type == BuiltinNodeTypes.PARAMETER_EXTRACTOR:
            return [
                parameter["name"]
                for parameter in (data.get("parameters") or [])
                if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
            ]
        if node_type == BuiltinNodeTypes.HTTP_REQUEST:
            return ["body", "status_code", "headers", "files"]
        if node_type == BuiltinNodeTypes.TEMPLATE_TRANSFORM:
            return ["output"]
        if node_type == BuiltinNodeTypes.TOOL:
            outputs = data.get("outputs")
            if isinstance(outputs, dict):
                return [key for key in outputs if isinstance(key, str)]
            return []
        if node_type in (BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP):
            return ["output"]
        if node_type == BuiltinNodeTypes.QUESTION_CLASSIFIER:
            return ["class_id", "class_name"]
        if node_type == BuiltinNodeTypes.DOCUMENT_EXTRACTOR:
            return ["text"]
        if node_type in (BuiltinNodeTypes.VARIABLE_AGGREGATOR, BuiltinNodeTypes.LEGACY_VARIABLE_AGGREGATOR):
            return ["output"]
        if node_type == BuiltinNodeTypes.LIST_OPERATOR:
            return ["result", "first_record", "last_record"]
        if node_type == BuiltinNodeTypes.HUMAN_INPUT:
            return [
                item["output_variable_name"]
                for item in (data.get("inputs") or [])
                if isinstance(item, dict) and isinstance(item.get("output_variable_name"), str)
            ]
        return []

    @classmethod
    def _declares_variable(cls, node: dict[str, Any], var: str) -> bool:
        """
        Does ``node`` expose a variable named ``var``? Each node type
        publishes outputs differently — start exposes ``data.variables``,
        llm exposes ``text``, code exposes ``data.outputs`` keys, etc.
        Tool parameters are validated at run time, not here.
        """
        data = node.get("data") or {}
        # Tool outputs are dynamic — validated at run time, not against a closed list.
        if data.get("type") == BuiltinNodeTypes.TOOL:
            return True
        return var in cls._declared_outputs(node)

    @classmethod
    def _sole_declared_variable(cls, node: dict[str, Any]) -> str | None:
        """Return the only output exposed by ``node``, or ``None`` when ambiguous."""
        data = node.get("data") or {}
        node_type = data.get("type")
        if node_type == BuiltinNodeTypes.LLM:
            schema = ((data.get("structured_output") or {}).get("schema") or {}).get("properties") or {}
            return "text" if not schema else None
        if node_type == BuiltinNodeTypes.CODE:
            outputs = [key for key in (data.get("outputs") or {}) if isinstance(key, str)]
            return outputs[0] if len(outputs) == 1 else None
        if node_type == BuiltinNodeTypes.PARAMETER_EXTRACTOR:
            parameters = [
                parameter.get("name")
                for parameter in (data.get("parameters") or [])
                if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
            ]
            return parameters[0] if len(parameters) == 1 else None
        if node_type == BuiltinNodeTypes.HUMAN_INPUT:
            human_outputs: list[str] = []
            for item in data.get("inputs") or []:
                if not isinstance(item, dict):
                    continue
                output_name = item.get("output_variable_name")
                if isinstance(output_name, str):
                    human_outputs.append(output_name)
            return human_outputs[0] if len(human_outputs) == 1 else None
        if not isinstance(node_type, str):
            return None
        single_output_by_type: dict[str, str] = {
            BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL: "result",
            BuiltinNodeTypes.TEMPLATE_TRANSFORM: "output",
            BuiltinNodeTypes.ITERATION: "output",
            BuiltinNodeTypes.LOOP: "output",
            BuiltinNodeTypes.DOCUMENT_EXTRACTOR: "text",
            BuiltinNodeTypes.VARIABLE_AGGREGATOR: "output",
            BuiltinNodeTypes.LEGACY_VARIABLE_AGGREGATOR: "output",
        }
        return single_output_by_type.get(node_type)

    @classmethod
    def _sanitize_node_ids(cls, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """
        Rewrite every node id to ``[a-zA-Z0-9_]`` and fix every cross-reference.

        Dify's run-time ``VARIABLE_PATTERN`` accepts only ``[a-zA-Z0-9_]`` in
        the node-id slot of ``{{#…#}}`` placeholders. The builder LLM often
        emits ``node-1`` style ids (and occasionally dots or spaces); left
        unfixed those make every placeholder silently fail at run time, the
        literal ``{{#node-1.var#}}`` survives into the prompt, and the LLM at
        run time echoes it back as the user's output — the bug we are here
        to kill.

        Approach: build a one-to-one ``old → new`` map by dropping the invalid
        characters — collision-safe: when the sanitized id is already taken
        (e.g. the builder emitted BOTH ``node-1`` and ``node1``) a numeric
        suffix keeps the two distinct instead of silently merging every
        reference onto one node. Then rewrite (a) every node ``id``, (b) every
        edge ``source`` / ``target``, (c) every ``parentId`` /
        ``start_node_id`` / ``iteration_id`` / ``loop_id`` inside ``data``,
        (d) every ``{{#…#}}`` reference in any string, (e) every
        ``["node-id", "var"]`` value-selector list. We do NOT rename variable
        names — only ids.
        """
        id_map: dict[str, str] = {}
        # Ids that are already valid are reserved up front so a sanitized id
        # can never collide with an untouched sibling.
        used: set[str] = {
            n["id"] for n in nodes if isinstance(n.get("id"), str) and not cls._INVALID_ID_CHARS_RE.search(n["id"])
        }
        fallback_seq = 0
        for node in nodes:
            old = node.get("id")
            if not isinstance(old, str) or not cls._INVALID_ID_CHARS_RE.search(old):
                continue
            base = cls._INVALID_ID_CHARS_RE.sub("", old)
            if not base:
                # Id was nothing but invalid characters (e.g. "节点", "--").
                fallback_seq += 1
                base = f"node_{fallback_seq}"
            new = base
            suffix = 2
            while new in used:
                new = f"{base}_{suffix}"
                suffix += 1
            used.add(new)
            id_map[old] = new
            node["id"] = new
        if not id_map:
            return

        # Rewrite edges' source / target.
        for edge in edges:
            for key in ("source", "target"):
                v = edge.get(key)
                if isinstance(v, str) and v in id_map:
                    edge[key] = id_map[v]
            # Also rewrite the edge id if the builder emitted one referencing
            # the old ids; the dedupe pass later recomputes it anyway, but
            # rewriting here keeps logs sane. Longest-first so an id that is
            # a substring of another (``node-1`` in ``node-12``) can't corrupt
            # the longer match.
            eid = edge.get("id")
            if isinstance(eid, str):
                for old, new in sorted(id_map.items(), key=lambda kv: -len(kv[0])):
                    eid = eid.replace(old, new)
                edge["id"] = eid

        # Rewrite every reference inside any node's data (recursively) plus
        # the wrapper-level ``parentId`` — ReactFlow stores parentId on the
        # node wrapper, but the LLM occasionally emits it inside ``data``
        # too. We cover both spots so the strip is symmetric.
        for node in nodes:
            wrapper_parent = node.get("parentId")
            if isinstance(wrapper_parent, str) and wrapper_parent in id_map:
                node["parentId"] = id_map[wrapper_parent]
            data = node.get("data")
            if isinstance(data, dict):
                cls._rewrite_refs_in_data(data, id_map)

    @classmethod
    def _rewrite_refs_in_data(cls, value: Any, id_map: dict[str, str]) -> None:
        """Recursive sibling of ``_collect_refs_in_data`` that does rewrites."""
        match value:
            case dict():
                for k, v in list(value.items()):
                    if k in cls._ID_FIELDS and isinstance(v, str):
                        # Direct id field — apply the longest matching prefix
                        # (handles ``"nodeKstart"`` where ``nodeK`` is the
                        # container's old id).
                        for old, new in sorted(id_map.items(), key=lambda kv: -len(kv[0])):
                            if old in v:
                                value[k] = v.replace(old, new)
                                v = value[k]
                    match v:
                        case str():
                            rewritten = cls._LENIENT_VAR_REF_RE.sub(lambda m: cls._rewrite_var_ref(m, id_map), v)
                            if rewritten != v:
                                value[k] = rewritten
                        case [str(v0), str(v1)] if v0 in id_map:
                            # 2-element ``["node-id", "var"]`` selector list.
                            value[k] = [id_map[v0], v1]
                        case _:
                            cls._rewrite_refs_in_data(v, id_map)
            case list():
                for item in value:
                    cls._rewrite_refs_in_data(item, id_map)

    @classmethod
    def _rewrite_var_ref(cls, m: re.Match[str], id_map: dict[str, str]) -> str:
        node_id = m.group(1)
        rest = m.group(2)
        new_id = id_map.get(node_id, node_id)
        return f"{{{{#{new_id}.{rest}#}}}}"

    @classmethod
    def _insert_multi_retrieval_context_templates(
        cls,
        *,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> None:
        """Fan multiple retrieval inputs into an LLM through one template.

        The repair is intentionally narrow: it applies only when at least two
        knowledge-retrieval nodes have direct edges into the same LLM and that
        LLM currently uses one of those results as its enabled context. This
        is enough to repair the builder's lossy single-context output without
        guessing about unrelated retrievals or mutually exclusive branches.
        """
        nodes_by_id: dict[str, dict[str, Any]] = {
            node_id: node for node in nodes if isinstance(node_id := node.get("id"), str)
        }
        used_ids = set(nodes_by_id)
        llm_nodes = [node for node in nodes if node.get("data", {}).get("type") == BuiltinNodeTypes.LLM]

        for llm_node in llm_nodes:
            llm_id = llm_node.get("id")
            if not isinstance(llm_id, str):
                continue

            incoming_retrieval_edges: list[dict[str, Any]] = []
            for edge in edges:
                source_id = edge.get("source")
                if edge.get("target") != llm_id or not isinstance(source_id, str):
                    continue
                source_node = nodes_by_id.get(source_id)
                if source_node and source_node.get("data", {}).get("type") == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
                    incoming_retrieval_edges.append(edge)
            retrieval_ids = list(
                dict.fromkeys(
                    edge["source"] for edge in incoming_retrieval_edges if isinstance(edge.get("source"), str)
                )
            )
            if len(retrieval_ids) < 2:
                continue

            llm_data = llm_node.get("data")
            if not isinstance(llm_data, dict):
                continue
            context = llm_data.get("context")
            if not isinstance(context, dict) or not context.get("enabled"):
                continue
            selector = context.get("variable_selector")
            if selector not in [[retrieval_id, "result"] for retrieval_id in retrieval_ids]:
                continue

            template_id = cls._next_generated_node_id(prefix="retrieval_context", used_ids=used_ids)
            variables = [
                {"variable": f"knowledge_{index}", "value_selector": [retrieval_id, "result"]}
                for index, retrieval_id in enumerate(retrieval_ids, start=1)
            ]
            sections = [
                (
                    f"## Knowledge source {index}\n"
                    f"{{% for item in knowledge_{index} %}}{{{{ item.content }}}}\n{{% endfor %}}"
                )
                for index in range(1, len(retrieval_ids) + 1)
            ]
            nodes.append(
                {
                    "id": template_id,
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": BuiltinNodeTypes.TEMPLATE_TRANSFORM,
                        "title": "Combine Knowledge",
                        "variables": variables,
                        "template": "\n\n".join(sections),
                    },
                }
            )

            incoming_edge_objects = {id(edge) for edge in incoming_retrieval_edges}
            edges[:] = [edge for edge in edges if id(edge) not in incoming_edge_objects]
            edges.extend(
                {"source": retrieval_id, "target": template_id, "type": "custom"} for retrieval_id in retrieval_ids
            )
            edges.append({"source": template_id, "target": llm_id, "type": "custom"})

            context["variable_selector"] = [template_id, "output"]
            cls._ensure_llm_context_placeholder(llm_data)
            logger.info(
                "Workflow generator: inserted template %s to combine retrieval inputs for LLM %s",
                template_id,
                llm_id,
            )

    @staticmethod
    def _next_generated_node_id(*, prefix: str, used_ids: set[str]) -> str:
        """Return a short runtime-safe node id and reserve it in ``used_ids``."""
        suffix = 1
        candidate = prefix
        while candidate in used_ids:
            suffix += 1
            candidate = f"{prefix}_{suffix}"
        used_ids.add(candidate)
        return candidate

    @staticmethod
    def _ensure_llm_context_placeholder(llm_data: dict[str, Any]) -> None:
        """Ensure an enabled LLM context is actually present in its prompt."""
        prompt_template = llm_data.get("prompt_template")
        if isinstance(prompt_template, list):
            messages = [message for message in prompt_template if isinstance(message, dict)]
            if any("{{#context#}}" in str(message.get("text") or "") for message in messages):
                return
            target = next((message for message in reversed(messages) if message.get("role") == "user"), None)
            if target is None:
                prompt_template.append({"role": "user", "text": "{{#context#}}"})
                return
            target["text"] = f"{target.get('text') or ''}\n\n{{{{#context#}}}}"
            return
        if isinstance(prompt_template, dict):
            text = str(prompt_template.get("text") or "")
            if "{{#context#}}" not in text:
                prompt_template["text"] = f"{text}\n\n{{{{#context#}}}}"


def reconcile_references(
    *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], mode: WorkflowGenerationMode
) -> None:
    VariableReferences._insert_multi_retrieval_context_templates(nodes=nodes, edges=edges)
    VariableReferences._normalize_sys_query_references(nodes=nodes, mode=mode)
    VariableReferences._reconcile_variable_references(nodes=nodes, mode=mode)


def collect_references(data: object) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    VariableReferences._collect_refs_in_data(data, refs)
    return refs


def declares_variable(node: dict[str, Any], variable: str) -> bool:
    return VariableReferences._declares_variable(node, variable)


def declared_outputs(node: dict[str, Any]) -> list[str]:
    """Return the output names ``node`` exposes for references and compact graphs."""
    return VariableReferences._declared_outputs(node)
