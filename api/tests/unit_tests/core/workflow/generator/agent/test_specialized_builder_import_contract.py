def test_specialized_builder_modules_import_from_tracked_tree() -> None:
    from core.workflow.generator.agent.loop import iter_agent_events
    from core.workflow.generator.agent.tools.tool_build_agent import build_agent_node
    from core.workflow.generator.agent.tools.tool_build_container import build_iteration, build_loop
    from core.workflow.generator.agent.tools.tool_build_tool import build_tool_node

    assert callable(iter_agent_events)
    assert callable(build_agent_node)
    assert callable(build_iteration)
    assert callable(build_loop)
    assert callable(build_tool_node)
