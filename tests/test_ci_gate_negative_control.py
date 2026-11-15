def test_ci_gate_negative_control():
    """Intentional failure used only to verify the CI review gate."""
    assert False, "intentional negative-control failure; do not merge"
