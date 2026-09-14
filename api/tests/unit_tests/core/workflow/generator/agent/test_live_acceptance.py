from core.workflow.generator.acceptance.authorization import LiveAcceptanceRequest, build_live_acceptance_request


def test_request_binds_graph_and_lists_nested_agent_capabilities():
    graph = {
        "nodes": [
            {
                "id": "agent",
                "data": {
                    "type": "agent",
                    "title": "Research",
                    "dify_tools": [{"tool_name": "search"}],
                    "mcp_tools": [{"name": "fetch"}],
                },
            }
        ],
        "edges": [],
    }
    request = build_live_acceptance_request(graph, revision=3)
    assert request.candidate_revision == 3
    assert len(request.graph_hash) == 64
    assert request.nodes[0].node_id == "agent"
    assert request.nodes[0].may_have_side_effects is True
    assert request.max_executions == 1
    assert request.request_id != build_live_acceptance_request(graph, revision=3).request_id
    assert LiveAcceptanceRequest.model_validate(request.model_dump()) == request
