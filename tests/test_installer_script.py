"""Installer resources must resolve even when the script is saved elsewhere."""
import json
import subprocess
import sys
from pathlib import Path


def test_custom_script_directory_keeps_resources_resolvable(tmp_path):
    root = tmp_path / 'source'
    tools = root / 'tools'
    tools.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / 'tools' / 'build_installer.py'
    script = tools / original.name
    script.write_bytes(original.read_bytes())
    (root / 'ui').mkdir()
    (root / 'ui' / 'brand.json').write_text(json.dumps({'appNameEn': 'TestApp'}))
    assets = root / 'brand-assets'
    assets.mkdir()
    for name in ('app.ico', 'inno-wizard.bmp', 'inno-wizard-small.bmp'):
        (assets / name).write_bytes(b'fixture')
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'README.md'):
        (root / name).write_text('fixture', encoding='utf-8')
    redist = root / 'installer' / 'redist'
    redist.mkdir(parents=True)
    (redist / 'MicrosoftEdgeWebview2Setup.exe').write_bytes(b'fixture')
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'TestApp.exe').write_bytes(b'fixture')
    destination = tmp_path / 'elsewhere' / 'nested' / 'setup.iss'
    result = subprocess.run([sys.executable, str(script), '--dist-dir', str(dist),
                             '--script', str(destination)], capture_output=True, text=True,
                            encoding='utf-8')
    assert result.returncode == 0, result.stderr
    content = destination.read_text(encoding='utf-8')
    assert '{#SourcePath}' not in content
    for path in [assets / 'app.ico', assets / 'inno-wizard.bmp',
                 assets / 'inno-wizard-small.bmp', root / 'LICENSE.txt',
                 root / 'README.md', redist / 'MicrosoftEdgeWebview2Setup.exe']:
        assert str(path) in content
        assert path.is_file()
    assert 'MB_YESNO or MB_DEFBUTTON2, IDNO' in content
