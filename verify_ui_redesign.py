"""Pemeriksaan struktur tanpa membutuhkan NiceGUI/Django terinstal."""
from pathlib import Path
import ast

root = Path(__file__).resolve().parent
source = (root / 'nicegui_app.py').read_text(encoding='utf-8')
mod = ast.parse(source)
routes = []
for node in mod.body:
    if isinstance(node, ast.FunctionDef):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'page':
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    routes.append(dec.args[0].value)
assert len(routes) == 27, f'Expected 27 routes, got {len(routes)}'
assert len(routes) == len(set(routes)), 'Duplicate route'
for name in ('shell', 'metric', 'datatable', 'period_bar', 'form_widgets', 'show_export_dialog'):
    assert any(isinstance(node, ast.FunctionDef) and node.name == name for node in mod.body), name
for forbidden in ('ui.html(', 'ui.add_head_html(', 'ui.run_javascript('):
    assert forbidden not in source, forbidden
for ext in ('.html', '.css', '.js'):
    assert not any(root.rglob('*' + ext)), f'Found frontend artifact {ext}'
print(f'OK: {len(routes)} NiceGUI pages, reusable UI components, no custom HTML/CSS/JS files.')
