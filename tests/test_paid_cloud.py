import json
import pytest
from core.llm_planner import OpenAICompatiblePlanner


def test_paid_cloud_cannot_be_created_without_explicit_approval():
    with pytest.raises(PermissionError):
        OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only")


def test_no_payment_preference_blocks_even_previously_approved_paid_mode(tmp_path, monkeypatch):
    import core.cost_policy as policy
    path = tmp_path / "policy.json"
    path.write_text('{"allow_paid_ai": false}', encoding="utf-8")
    monkeypatch.setattr(policy, "COST_POLICY_PATH", path)
    with pytest.raises(PermissionError, match="مقفول"):
        OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only", allow_paid=True)


def test_paid_cloud_uses_native_chat_payload_and_has_bounded_requests():
    calls = []
    def transport(url, payload):
        calls.append((url, payload))
        return {"choices": [{"message": {"content": "رد تجريبي"}}]}
    planner = OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only", allow_paid=True, transport=transport)
    for _ in range(20): assert planner.respond("سؤال خيالي") == "رد تجريبي"
    with pytest.raises(RuntimeError, match="20"):
        planner.respond("طلب زائد")
    assert len(calls) == 20
    url, payload = calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert "messages" not in payload and "contents" in payload
    assert payload["generationConfig"]["maxOutputTokens"] == 1024


def test_large_paid_request_is_not_sent_or_silently_truncated():
    calls = []
    planner = OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only", allow_paid=True,
        transport=lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="حد البيانات"):
        planner.respond("ك" * 24001)
    assert calls == [] and planner.cloud_requests == 0


def test_reference_consent_never_shares_private_history_or_full_memory():
    source = {"private": True, "document_id": "d", "chunk_id": "c", "text": "مقتطف مسموح",
              "source": "C:/private/customer/file.txt", "reference_status": "unverified_historical"}
    memory = {"local_sources": [source], "structured_memory": {"secret": "خاص"},
              "conversation_history": {"private": True, "turns": ["كلام خاص"]},
              "result": {"private": True, "sources": [source]}}
    planner = OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only", allow_paid=True, transport=lambda *args: {})
    assert "مقتطف مسموح" not in json.dumps(planner._memory_for_planner(memory), ensure_ascii=False)
    planner.share_local_references = True
    filtered = planner._memory_for_planner(memory)
    text = json.dumps(filtered, ensure_ascii=False)
    assert "مقتطف مسموح" in text and "unverified_historical" in text
    assert "كلام خاص" not in text and "C:/private" not in text and "structured_memory" not in filtered
    assert planner._memory_for_planner([{"private": True, "text": "private root list"}]) == []


def test_native_gemini_truncation_and_thought_parts_are_preserved_safely(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [
                {"text": "hidden reasoning", "thought": True}, {"text": "incomplete"}]}}],
                "usageMetadata": {"totalTokenCount": 12}}).encode()
    monkeypatch.setattr("core.llm_planner.urlopen", lambda *args, **kwargs: Response())
    planner = OpenAICompatiblePlanner.from_gemini_paid(api_key="fixture-only", allow_paid=True)
    response = planner._send_request(planner._endpoint(), {"contents": []})
    assert response["choices"][0]["finish_reason"] == "length"
    assert response["choices"][0]["message"]["content"] == "incomplete"
    with pytest.raises(ValueError, match="مبتورة"):
        planner.respond("سؤال")


def test_declining_paid_service_in_application_never_asks_key_or_calls_provider(tmp_path, monkeypatch, capsys):
    import core.main as app
    from core.permission_manager import BoodaPermissionManager
    from core.approval_manager import BoodaApprovalManager
    from core.task_manager import BoodaTaskManager
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "gemini-paid")
    monkeypatch.setattr("builtins.input", lambda prompt: "لا")
    monkeypatch.setattr(app, "getpass", lambda *args: pytest.fail("Key requested before service consent"))
    monkeypatch.setattr(OpenAICompatiblePlanner, "from_gemini_paid", lambda **kwargs: pytest.fail("Paid provider activated without consent"))
    app.run_ai_agent(None, BoodaPermissionManager(), BoodaApprovalManager(), BoodaTaskManager(), initial_goal="مثال خيالي")
    assert "لم يتم تفعيل الاتصال المدفوع" in capsys.readouterr().out
