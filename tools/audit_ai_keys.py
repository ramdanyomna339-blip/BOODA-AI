"""Inspect first-party text files without printing credentials or contacting providers."""
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.venv', '.silma-venv', '.desktop-deps', '.local-ai-runtime', '.git', '__pycache__', 'node_modules'}
KEY = re.compile(r'AIza[0-9A-Za-z_-]{35}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}')
ERROR = re.compile(r'API_KEY_INVALID|RESOURCE_EXHAUSTED|quota.{0,40}exceed|HTTP(?: Error| endpoint returned HTTP)?\s*(?:401|403|404|429)', re.I)

def run():
    matches, diagnostics, count = [], [], 0
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('torchinductor')
                   and not d.startswith('.pytest') and not os.path.isjunction(Path(folder) / d)
                   and not (Path(folder) == ROOT / 'outputs' and not (
                       d.startswith('brain_') or d in {'project_review', 'research', 'system_checks'}))]
        for name in files:
            path = Path(folder) / name
            if path.suffix.lower() not in {'.json', '.jsonl', '.txt', '.log', '.md', '.env', '.ps1', '.cmd', '.py', '.yaml', '.toml'} and name != '.env':
                continue
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                content = path.read_text(encoding='utf-8-sig')
            except (OSError, UnicodeError):
                continue
            count += 1
            if KEY.search(content):
                matches.append(str(path.relative_to(ROOT)))
            if ROOT / 'outputs' in path.parents and ERROR.search(content):
                diagnostics.append(str(path.relative_to(ROOT)))
    result = {'scanned_text_files': count, 'credential_pattern_files': matches,
              'possible_error_record_files': diagnostics, 'external_requests_sent': False,
              'scope': 'first-party text files up to 5MB and brain evidence outputs; excludes dependencies, models, junctions and generated test trees'}
    dest = ROOT / 'outputs/brain_acceptance_20261011/KEY_AUDIT.json'
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))

if __name__ == '__main__':
    run()
