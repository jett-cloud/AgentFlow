from core.workflow.generator.prompts.output_language import (
    detect_output_language,
    localized_generator_message,
    resolve_output_language,
    text_matches_output_language,
)


def test_detect_output_language_follows_chinese_instruction():
    assert detect_output_language("请生成一个客服工作流") == "zh-Hans"


def test_detect_output_language_follows_english_instruction():
    assert detect_output_language("Build a customer support workflow") == "en"


def test_detect_output_language_uses_majority_for_mixed_instruction():
    assert detect_output_language("请 build 一个客服 workflow，并返回中文结果") == "zh-Hans"


def test_localized_generator_message_preserves_event_shape_values():
    assert localized_generator_message("planning", "zh-Hans") == "正在规划工作流"
    assert localized_generator_message("planning", "en") == "Planning workflow"
    assert localized_generator_message("plan_ready", "zh-Hans", count=3) == "已规划 3 个节点"
    assert localized_generator_message("node_done", "en", label="Answer") == "Node Answer completed"


def test_language_match_ignores_dify_placeholders_and_urls():
    assert text_matches_output_language("请总结 {{#node2.text#}}，来源：https://example.com", "zh-Hans")
    assert text_matches_output_language("Summarize {{#node2.text#}} from https://example.com", "en")


def test_conversation_language_survives_model_names_and_explicit_switches():
    history = ["请生成抠图工作流", "deepseek-v4-pro 深度求索\ndoubao-seedream-3-0-t2i-250415"]
    assert resolve_output_language(history) == "zh-Hans"
    assert resolve_output_language([*history, "请改用英文回答", "continue"]) == "en"
    assert resolve_output_language(["Build a workflow", "请用中文回答", "v2.0"]) == "zh-Hans"
    assert resolve_output_language([*history, "不要用英文回答"]) == "zh-Hans"
