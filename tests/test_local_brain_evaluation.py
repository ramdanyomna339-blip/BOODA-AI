from tools.evaluate_local_brain import exact_fixture_retrieval


def test_retrieval_score_rejects_extra_claims_even_when_expected_facts_are_present():
    assert exact_fixture_retrieval("رمز المشروع: مرجع-742\n\nلون الهوية: تركواز")
    assert not exact_fixture_retrieval("الرمز: مرجع-742، اللون: تركواز. 25% من 7000 = 175")
    assert not exact_fixture_retrieval("مرجع-742 تركواز، وتم تنفيذ الحملة")
