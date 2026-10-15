"""The frozen draft adapter runs in a child process and never opens a window."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import app_launcher
import draft_codec_worker
import existing_draft


def test_frozen_codec_uses_application_worker(tmp_path, monkeypatch):
    install = tmp_path / 'editor'
    install.mkdir()
    (install / 'videoeditor.dll').write_bytes(b'fixture')
    target = tmp_path / 'decoded.json'
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        target.write_text('{}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(existing_draft.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(existing_draft.subprocess, 'run', run)
    editor = existing_draft.ExistingDraftEditor(tmp_path / 'work')
    editor.codec('dec', tmp_path / 'input', target, str(install), '')
    assert commands[0][:3] == [existing_draft.sys.executable, '--draft-codec-worker', 'dec']


def test_worker_dispatch_does_not_launch_ui(monkeypatch):
    received = []
    monkeypatch.setattr(app_launcher.sys, 'argv', ['app.exe', '--draft-codec-worker', 'dec', 'editor', 'input', 'output'])
    monkeypatch.setattr(draft_codec_worker, 'main', lambda args: received.append(args))
    monkeypatch.setattr(app_launcher, '_run', lambda: pytest.fail('worker opened a window'))
    assert app_launcher.main() == 0
    assert received == [['dec', 'editor', 'input', 'output']]


def test_worker_failure_returns_nonzero_without_dialog(monkeypatch):
    monkeypatch.setattr(app_launcher.sys, 'argv', ['app.exe', '--draft-codec-worker'])
    monkeypatch.setattr(app_launcher, '_notify_user', lambda *args: pytest.fail('worker showed a dialog'))
    assert app_launcher.main() == 1


def test_missing_install_has_actionable_error(tmp_path):
    editor = existing_draft.ExistingDraftEditor(tmp_path / 'work')
    with pytest.raises(ValueError, match='videoeditor.dll'):
        editor.codec('dec', tmp_path / 'input', tmp_path / 'output', '', '')
