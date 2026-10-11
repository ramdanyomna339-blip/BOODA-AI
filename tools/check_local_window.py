"""Hidden-window integration check; no microphone, model, browser or network."""
import json
from pathlib import Path
import tkinter as tk
from uuid import uuid4
from tools.local_workspace_gui import LocalWorkspaceWindow
from core.knowledge_base import BoodaLocalKnowledgeBase


def run():
    project = Path(__file__).resolve().parents[1]
    folder = project / 'outputs/local_window_checks' / uuid4().hex
    folder.mkdir(parents=True)
    kb = BoodaLocalKnowledgeBase(folder / 'knowledge/local_documents.json')
    source = folder / 'client.txt'
    source.write_text('رمز العميل: نافذة-303', encoding='utf-8')
    kb.import_file(source, client_id='a', private=True, reference_status='unverified_historical')
    window = tk.Tk()
    window.withdraw()
    try:
        app = LocalWorkspaceWindow(window, root=folder)
        app.submit('احسب 25% من 7000')
        arithmetic = '1750' in app.output.get('1.0', 'end')
        app.client.set('a')
        cleared = '1750' not in app.output.get('1.0', 'end')
        app.submit('/بحث رمز العميل')
        source_found = 'نافذة-303' in app.output.get('1.0', 'end')
        app.client.set('b')
        app.submit('/بحث رمز العميل')
        other_scope_hidden = 'نافذة-303' not in app.output.get('1.0', 'end')
        window.update_idletasks()
        checks = dict(arithmetic=arithmetic, scope_change_clears_output=cleared,
                      source_found=source_found, other_scope_hidden=other_scope_hidden)
        report = {'checks': checks, 'passed': all(checks.values()),
                  'test': 'hidden Tk window and actual callbacks; visual user acceptance still needed',
                  'cloud_called': False, 'model_called': False}
        destination = folder / 'report.json'
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REPORT=' + str(destination))
        if not report['passed']:
            raise RuntimeError('Local window check failed.')
    finally:
        window.destroy()


if __name__ == '__main__':
    run()
