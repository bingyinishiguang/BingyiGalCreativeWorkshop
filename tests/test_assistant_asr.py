"""ASR process lifecycle tests without downloading or loading a speech model."""
import json
import sys
import threading
import types
from pathlib import Path

import pytest

import assistant_asr as host
import assistant_asr_worker as worker


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    audio = tmp_path / 'voice.wav'
    audio.write_bytes(b'fake audio')
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'model.bin').write_bytes(b'fake model')
    temporary = host.tempfile.TemporaryDirectory
    monkeypatch.setattr(host.tempfile, 'TemporaryDirectory', lambda **kwargs: temporary(dir=tmp_path, **kwargs))
    return audio, {'modelPath': str(model), 'pythonPath': sys.executable}, tmp_path


def fake_process(monkeypatch, mode, cancel=None):
    created = []
    class Process:
        def __init__(self, args, **kwargs):
            self.args, self.options, self.killed, self.waited = args, kwargs, False, False
            self.returncode = None if mode == 'running' else (1 if mode == 'failed' else 0)
            self.polls = 0
            if mode == 'success':
                Path(args[3]).write_text(json.dumps({'cues': [{'start': 0, 'end': 1, 'text': 'ok'}]}), 'utf-8')
            if mode == 'failed':
                Path(args[3]).write_text(json.dumps({'error': 'Model initialization failed'}), 'utf-8')
            created.append(self)
        def poll(self):
            self.polls += 1
            return self.returncode
        def kill(self):
            self.killed = True
            self.returncode = -1
        def wait(self, timeout):
            self.waited = True
            return self.returncode
    monkeypatch.setattr(host.subprocess, 'Popen', Process)
    return created


def test_cancel_kills_and_reaps_child_then_removes_temporary_files(inputs, monkeypatch):
    audio, config, root = inputs
    cancelled = threading.Event()
    cancelled.set()
    created = fake_process(monkeypatch, 'running')
    with pytest.raises(ValueError, match='取消'):
        host.recognize(audio, config, cancelled, lambda message: None)
    process = created[0]
    assert process.killed and process.waited
    assert not Path(process.options['cwd']).exists()
    assert process.options['creationflags'] == host.subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize('mode,match', [('failed', 'Model initialization'), ('missing', '意外退出')])
def test_child_failures_are_reported_and_reaped(inputs, monkeypatch, mode, match):
    audio, config, root = inputs
    created = fake_process(monkeypatch, mode)
    with pytest.raises(ValueError, match=match):
        host.recognize(audio, config, threading.Event(), lambda message: None)
    assert created[0].waited and not created[0].killed
    assert not Path(created[0].options['cwd']).exists()


def test_success_returns_worker_cues_and_removes_temporary_files(inputs, monkeypatch):
    audio, config, root = inputs
    created = fake_process(monkeypatch, 'success')
    assert host.recognize(audio, config, threading.Event(), lambda message: None) == [{'start': 0, 'end': 1, 'text': 'ok'}]
    assert created[0].waited and not created[0].killed
    assert not Path(created[0].options['cwd']).exists()


@pytest.mark.parametrize('failure', [False, True])
def test_worker_main_writes_atomic_success_or_error_without_real_model(tmp_path, monkeypatch, failure):
    request, result, progress = (tmp_path / name for name in ('request.json', 'result.json', 'progress.json'))
    request.write_text(json.dumps({'audio': 'fake.wav', 'config': {'modelPath': 'fake-model', 'language': 'auto'}}), 'utf-8')
    calls = []
    class Model:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))
            if failure:
                raise ValueError('incompatible model')
        def transcribe(self, audio, **kwargs):
            calls.append((audio, kwargs))
            return iter([types.SimpleNamespace(start=0, end=1, text=' hello ')]), object()
    monkeypatch.setitem(sys.modules, 'faster_whisper', types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(sys, 'argv', ['worker', str(request), str(result), str(progress)])
    monkeypatch.setenv('PATH', worker.os.environ.get('PATH', ''))
    code = worker.main()
    data = json.loads(result.read_text('utf-8'))
    assert calls[0][1]['local_files_only'] is True
    if failure:
        assert code == 1 and 'incompatible model' in data['error']
    else:
        assert code == 0 and data['cues'] == [{'start': 0, 'end': 1, 'text': 'hello'}]
        assert calls[1][1]['language'] is None
    assert not list(tmp_path.glob('*.tmp'))


def test_atomic_progress_retries_brief_windows_read_lock(tmp_path,monkeypatch):
    target=tmp_path/'progress.json';replace=Path.replace;attempts=[]
    def locked_once(path,destination):
        attempts.append(destination)
        if len(attempts)==1:raise PermissionError('file in use')
        return replace(path,destination)
    monkeypatch.setattr(Path,'replace',locked_once)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    worker.write(target,{'message':'已识别'})
    assert len(attempts)==2 and json.loads(target.read_text('utf-8'))['message']=='已识别'
