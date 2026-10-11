import json
import pytest
from core.response_contract import requested_format, render_output
from core.llm_planner import OpenAICompatiblePlanner


def test_explicit_counts_are_structured_and_other_requests_remain_free():
    assert requested_format("اشرح في جملتين فقط") == ("sentences", 2)
    assert requested_format("اكتب ٤ نقاط فقط") == ("points", 4)
    assert requested_format("اشرح باختصار") is None


@pytest.mark.parametrize("data", [
    {"sentences": ["واحدة فقط"]},
    {"sentences": ["جملة. جملة زيادة", "ثانية"]},
    {"sentences": ["", "ثانية"]},
    {"sentences": ["أولى", "ثانية"], "extra": "زيادة"},
])
def test_invalid_counts_or_hidden_extra_sentences_are_not_delivered(data):
    with pytest.raises(ValueError): render_output(data, ("sentences", 2))


def test_local_response_format_is_enforced_even_if_server_ignores_schema():
    replies = iter([{"points": ["المنتج", "السعر", "الجمهور"]}, {"points": ["ناقص"]}])
    calls = []
    def transport(url, payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": json.dumps(next(replies))}}]}
    planner = OpenAICompatiblePlanner(base_url="http://localhost:8080/v1", model="local", transport=transport)
    assert planner.respond("ثلاث نقاط فقط") == "1. المنتج\n2. السعر\n3. الجمهور"
    assert calls[0]["response_format"]["json_schema"]["name"] == "booda_answer"
    with pytest.raises(ValueError): planner.respond("ثلاث نقاط فقط")
