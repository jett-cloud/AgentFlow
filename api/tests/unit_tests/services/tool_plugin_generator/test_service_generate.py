from services.tool_plugin_generator import service


def test_generate_uses_llm_and_validates():
    class FakeLLM:
        def complete(self, prompt: str) -> dict:
            return {
                "provider_label": "Demo",
                "tool_label": "Echo",
                "tool_description": "echo text",
                "parameters": [{"name": "text", "type": "string", "required": True, "label": "Text"}],
                "credentials": [],
                "invoke_python_body": 'yield self.create_text_message(tool_parameters.get("text", ""))',
                "readme": "# Demo",
            }

    result = service.generate_tool_plugin(
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        user_prompt="echo tool",
        api_doc="POST /echo {text}",
        llm_client=FakeLLM(),
    )
    assert "manifest.yaml" in result.files
    assert result.preview_tool["tool_name"] == "echo"


def test_generate_forwards_llm_event_callback():
    seen: list[str] = []

    class FakeLLM:
        def complete(self, prompt: str, on_event=None) -> dict:
            if on_event:
                on_event("thinking")
            return {
                "provider_label": "Demo",
                "tool_label": "Echo",
                "tool_description": "echo text",
                "parameters": [],
                "credentials": [],
                "invoke_python_body": "yield self.create_text_message('ok')",
                "readme": "# Demo",
            }

    service.generate_tool_plugin(
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        user_prompt="echo tool",
        api_doc="",
        llm_client=FakeLLM(),
        on_llm_event=seen.append,
    )

    assert seen == ["thinking"]
