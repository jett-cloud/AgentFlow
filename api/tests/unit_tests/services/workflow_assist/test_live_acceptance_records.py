from services.workflow_assist.live_acceptance import declined_live_graph_hash, live_grant


def test_decline_marker_is_never_a_grant() -> None:
    declined = {"declined": True, "graph_hash": "a" * 64, "candidate_revision": 2}
    grant = {"request_id": "b" * 32, "graph_hash": "a" * 64, "candidate_revision": 2, "consumed": False}

    assert live_grant(declined) is None
    assert live_grant(grant) == grant
    assert live_grant(None) is None
    assert declined_live_graph_hash(declined) == "a" * 64
    assert declined_live_graph_hash(grant) is None
    assert declined_live_graph_hash(None) is None
