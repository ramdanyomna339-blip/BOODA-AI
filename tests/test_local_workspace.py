from core.knowledge_base import BoodaLocalKnowledgeBase
from core.local_workspace import local_reply, run_workspace
from core.local_workspace import review_teacher_import
import json
import pytest
from pathlib import Path


def test_workspace_search_and_inventory_do_not_leak_clients(tmp_path):
    kb = BoodaLocalKnowledgeBase(tmp_path / 'knowledge/local_documents.json')
    for client, text in [('a', 'رمز العميل ألف-111'), ('b', 'رمز العميل باء-222')]:
        path = tmp_path / (client + '.txt')
        path.write_text(text, encoding='utf-8')
        kb.import_file(path, private=True, client_id=client, reference_status='unverified_historical')
    answer = local_reply('/بحث رمز العميل', knowledge_base=kb, scope={'client_id': 'a'})
    assert 'ألف-111' in answer and 'باء-222' not in answer and 'unverified_historical' in answer
    assert 'المراجع المتاحة في النطاق الحالي: 0' in local_reply('/مراجعي', knowledge_base=kb)
    assert 'عدم وجود' in local_reply('/بحث غيرموجود', knowledge_base=kb)


def test_local_workspace_without_model_or_key_honestly_refuses_unknown(tmp_path, monkeypatch, capsys):
    messages = iter(['', '', 'احسب 25% من 7000', 'انشر إعلانًا', ''])
    monkeypatch.setattr('builtins.input', lambda _: next(messages))
    run_workspace(root=tmp_path)
    output = capsys.readouterr().out
    assert '1750' in output and 'لم أنفذ إجراءً' in output


def test_workspace_does_not_claim_readiness_from_installed_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr('core.local_workspace.inspect_tools', lambda _: {
        'message': 'التثبيت لا يثبت نجاح الاستخدام الحي',
        'tools': [{'tool': 'الصوت', 'installed': True}]})
    answer = local_reply('/جاهزية', knowledge_base=None, root=tmp_path)
    assert 'الاستخدام الحي غير مثبت' in answer


def test_teacher_review_cannot_promote_global_lessons_to_a_client_or_import_without_review(tmp_path):
    pack = json.loads((Path(__file__).resolve().parents[1] / 'knowledge/curriculum/booda_teacher_examples.json').read_text(encoding='utf-8'))
    path = tmp_path / 'teacher.json'
    path.write_text(json.dumps(pack), encoding='utf-8')
    with pytest.raises(ValueError, match='نطاق'):
        review_teacher_import(path, scope={'client_id': 'a'}, root=tmp_path, confirm=lambda _: 'نعم')
    assert 'لم تُستورد' in review_teacher_import(path, scope={}, root=tmp_path, confirm=lambda _: 'لا')
    assert not (tmp_path / 'knowledge/local_documents.json').exists()
    result = review_teacher_import(path, scope={}, root=tmp_path, confirm=lambda _: 'نعم')
    assert '12' in result and 'غير مثبت' in result


def test_teacher_file_change_after_review_cannot_change_scope(tmp_path):
    path = tmp_path / 'teacher.json'
    pack = json.loads((Path(__file__).resolve().parents[1] / 'knowledge/curriculum/booda_teacher_examples.json').read_text(encoding='utf-8'))
    path.write_text(json.dumps(pack), encoding='utf-8')
    def change_then_confirm(_):
        pack['scope'] = {'client_id': 'other'}
        path.write_text(json.dumps(pack), encoding='utf-8')
        return 'نعم'
    with pytest.raises(ValueError, match='تغيرت'):
        review_teacher_import(path, scope={}, root=tmp_path, confirm=change_then_confirm)
    assert not (tmp_path / 'knowledge/local_documents.json').exists()
