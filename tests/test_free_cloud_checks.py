import json
import pytest
from core.cloud_diagnostics import diagnose_cloud_error
from core.llm_planner import OpenAICompatiblePlanner
from tools.check_free_gemini import check


@pytest.mark.parametrize('error,category', [
    ('Model endpoint returned HTTP 401.', 'authentication'),
    ('Model endpoint returned HTTP 400. API_KEY_INVALID', 'authentication'),
    ('Model endpoint returned HTTP 429. RESOURCE_EXHAUSTED', 'quota'),
    ('Model endpoint returned HTTP 404.', 'model_unavailable'),
    ('Model endpoint returned HTTP 403.', 'permission'),
    ('Could not reach the configured model endpoint.', 'network')])
def test_diagnostics_do_not_assume_every_failure_is_geographic(error, category):
    assert diagnose_cloud_error(RuntimeError(error))['category'] == category


def test_free_probe_requires_confirmation_and_never_saves_key_or_provider_body(tmp_path):
    calls = []
    def transport(endpoint, payload):
        calls.append(payload)
        raise RuntimeError('Model endpoint returned HTTP 429. secret-fixture-only')
    with pytest.raises(PermissionError):
        check(api_key='secret-fixture-only', transport=transport, root=tmp_path)
    assert not calls
    report, path = check(api_key='secret-fixture-only', confirmed_unbilled=True, transport=transport, root=tmp_path)
    assert len(calls) == 1 and report['requests_attempted'] == 1
    assert report['diagnosis']['category'] == 'quota'
    assert 'secret-fixture-only' not in path.read_text(encoding='utf-8')
    assert 'conversation_history' not in json.dumps(calls)


def test_free_probe_checks_actual_response_and_no_retry(tmp_path):
    calls = []
    def transport(endpoint, payload):
        calls.append(endpoint)
        return {'choices': [{'message': {'content': 'جاهز'}}]}
    report, _ = check(api_key='fixture-only', confirmed_unbilled=True, transport=transport, root=tmp_path)
    assert report['status'] == 'passed' and len(calls) == 1
    report, _ = check(api_key='fixture-only', confirmed_unbilled=True,
        transport=lambda *args: {'choices': [{'message': {'content': 'something else'}}]}, root=tmp_path)
    assert report['status'] == 'unexpected_answer'


def test_explicit_dialogue_sharing_is_bounded_and_keeps_other_private_data_hidden():
    calls = []
    planner = OpenAICompatiblePlanner.from_gemini_free_tier(api_key='fixture-only',
        share_conversation_history=True, transport=lambda url, payload: calls.append(payload) or
            {'choices': [{'message': {'content': 'متابعة'}}]})
    context = {'conversation_history': {'private': True, 'turns': [
        {'message': 'سؤال' + str(i), 'answer': 'جواب' + str(i), 'secret': 'hidden'} for i in range(5)]},
        'other': {'private': True, 'text': 'private document'}}
    planner.respond('كمل', context=context)
    body = calls[0]['contents'][0]['parts'][0]['text']
    assert 'سؤال4' in body and 'سؤال0' not in body
    assert 'hidden' not in body and 'private document' not in body
    planner.share_conversation_history = False
    planner.respond('كمل', context=context)
    assert 'سؤال4' not in calls[-1]['contents'][0]['parts'][0]['text']


def test_free_calls_stop_at_session_cap_and_oversize_never_sent():
    calls = []
    planner = OpenAICompatiblePlanner.from_gemini_free_tier(api_key='fixture-only',
        transport=lambda *args: calls.append(1) or {})
    assert planner.enable_local_reasoning_tools is True
    with pytest.raises(ValueError):
        planner.transport(planner._endpoint(), {'contents': 'a' * 24001})
    assert planner.cloud_requests == 0
    for _ in range(20):
        planner.transport(planner._endpoint(), {'contents': []})
    with pytest.raises(RuntimeError, match='20'):
        planner.transport(planner._endpoint(), {'contents': []})
    assert len(calls) == 20


def test_free_source_opt_in_is_explicit_and_strips_paths():
    source = {'private': True, 'sources': [{'document_id': 'd1', 'title': 'عنوان',
        'text': 'مقتطف', 'reference_status': 'unverified_historical', 'path': 'C:/private/secret'}]}
    planner = OpenAICompatiblePlanner.from_gemini_free_tier(api_key='fixture-only', transport=lambda *args: {})
    assert 'مقتطف' not in json.dumps(planner._memory_for_planner(source), ensure_ascii=False)
    planner.share_local_references = True
    result = json.dumps(planner._memory_for_planner(source), ensure_ascii=False)
    assert 'مقتطف' in result and 'unverified_historical' in result
    assert 'C:/private' not in result
