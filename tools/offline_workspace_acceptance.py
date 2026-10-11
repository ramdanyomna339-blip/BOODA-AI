"""Real local workspace exercise on disposable client data, without model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.tool_readiness import inspect_tools
from tools.teach_examples import teach_examples


def run():
    project = Path(__file__).resolve().parents[1]
    folder = project / 'outputs/offline_workspace_checks' / uuid4().hex
    folder.mkdir(parents=True)
    kb = BoodaLocalKnowledgeBase(folder / 'knowledge/local_documents.json')
    for client, token in [('a', 'عميل-101'), ('b', 'عميل-202')]:
        source = folder / (client + '.txt')
        source.write_text('رمز العقد: ' + token, encoding='utf-8')
        kb.import_file(source, client_id=client, private=True, reference_status='unverified_historical')
    teaching = teach_examples(project / 'knowledge/curriculum/booda_teacher_examples.json', root=folder)
    sequence = 'a\n\nاحسب 25% من 7000\n/بحث رمز العقد\n/مراجعي\nانشر حملة\n\n'
    result = subprocess.run([sys.executable, '-c',
        'import sys; from core.local_workspace import run_workspace; run_workspace(root=sys.argv[1])', str(folder)],
        input=sequence, capture_output=True, text=True, encoding='utf-8', timeout=30,
        env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join([
            str(project / '.desktop-deps'), str(project / '.venv/Lib/site-packages'), str(project)])))
    (folder / 'session.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    checks = {'application_exited_cleanly': result.returncode == 0,
        'decimal_result_correct': 'نتيجة الحساب: 1750' in result.stdout,
        'scoped_source_found': 'عميل-101' in result.stdout,
        'other_client_hidden': 'عميل-202' not in result.stdout,
        'historical_status_preserved': 'unverified_historical' in result.stdout,
        'unsupported_action_not_claimed': 'لم أنفذ إجراءً' in result.stdout,
        'teacher_examples_imported': len(teaching['documents']) == 12}
    report = {'checks': checks, 'passed': all(checks.values()),
        'evidence_scope': 'real local commands and example storage; not model reasoning or weight training',
        'model_called': False, 'cloud_called': False, 'tool_dependencies': inspect_tools(project)}
    path = folder / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('REPORT=' + str(path))
    if not report['passed']:
        raise RuntimeError('Offline workspace acceptance failed; inspect report.')


if __name__ == '__main__':
    run()
