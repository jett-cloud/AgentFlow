from models.tools import ToolPluginPublishJob


def test_publish_job_is_durable_and_keeps_credentials_encrypted() -> None:
    columns = ToolPluginPublishJob.__table__.columns
    assert "encrypted_credentials_json" in columns
    assert "credentials_json" not in columns
    durable_columns = {"status", "attempt_id", "candidate_id", "lease_expires_at", "trace_json", "result_json"}
    assert durable_columns <= set(columns.keys())


def test_publish_job_has_session_and_lease_cleanup_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in ToolPluginPublishJob.__table__.indexes
    }
    assert indexes["tool_plugin_publish_job_session_created_idx"] == ("session_id", "created_at")
    assert indexes["tool_plugin_publish_job_status_lease_idx"] == ("status", "lease_expires_at")
