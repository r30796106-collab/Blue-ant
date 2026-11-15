def test_pr_review_gate_negative_control():
    """Intentional failure to verify the dependent review job is skipped."""
    assert False, "intentional negative-control failure; do not merge"
