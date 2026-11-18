"""Static verification that runs without external third-party packages."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
excluded = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.suffix.lower() in {'.html','.css','.js','.jsx'})
assert not excluded, f'Unexpected frontend sources: {excluded}'
required = [
    'nicegui_app.py','manage.py','requirements.txt','db.sqlite3',
    'accounting/models.py','accounting/forms.py','accounting/services.py',
    'accounting/journal_rules.py','accounting/exports.py','accounting/vouchers.py',
    'config/settings.py',
]
for name in required:
    assert (ROOT/name).exists(), f'Missing: {name}'
for py in ROOT.rglob('*.py'):
    ast.parse(py.read_text(encoding='utf-8-sig'), filename=str(py))
ui_source=(ROOT/'nicegui_app.py').read_text()
assert 'ui.run_javascript' not in ui_source
assert 'ui.html(' not in ui_source
assert ui_source.count('@ui.page(')>=20
print(f'OK: {len(required)} core files, {ui_source.count("@ui.page(")} NiceGUI pages, syntax valid, no .html/.css/.js files')
