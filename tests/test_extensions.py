from ccr_xva.engines.extensions import extension_status


def test_phase_seven_hooks_are_explicit():
    status = extension_status()
    assert status["european_option"] == "not_implemented"
    assert status["wrong_way_risk"] == "protocol_only"
    assert status["revaluation_surrogate"] == "protocol_only"
