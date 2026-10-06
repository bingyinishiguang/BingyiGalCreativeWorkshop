import json
from pathlib import Path
import pytest
import tts_bundle
from local_tts import LocalTTS
from audio_library import AudioLibrary


def test_portable_paths_and_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_bundle,'resource_root',lambda:tmp_path)
    file=tmp_path/'tts_bundle/voices/model.pth'
    assert tts_bundle.portable(str(file))=='@tts/voices/model.pth'
    assert tts_bundle.resolve('@tts/voices/model.pth')==str(file.resolve())
    with pytest.raises(ValueError):tts_bundle.resolve('@tts/../../outside')


def test_seed_keeps_author_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_bundle,'resource_root',lambda:tmp_path)
    source=tmp_path/'tts_bundle/voices/角色/voice.json'
    source.parent.mkdir(parents=True);source.write_text('{}')
    output=tmp_path/'user/角色/voice.json'
    tts_bundle.seed_voices(output.parents[1]);output.write_text('{"name":"自定义"}',encoding='utf-8')
    tts_bundle.seed_voices(output.parents[1])
    assert json.loads(output.read_text('utf-8'))['name']=='自定义'


def test_waits_for_startup_and_reports_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_bundle,'resource_root',lambda:tmp_path)
    t=LocalTTS(tmp_path/'tts',AudioLibrary(tmp_path/'audio'))
    t.test=lambda base:(_ for _ in ()).throw(ValueError('offline'))
    calls=[]
    t.start=lambda config:calls.append('start')
    t.probe=lambda base:calls.append('probe')
    t.ensure_ready(t.settings());assert calls==['start','probe']
    t.process=type('Failed',(),{'poll':lambda self:1})()
    with pytest.raises(ValueError,match='启动失败'):t.ensure_ready(t.settings())


def test_cpu_default_idle_release_and_busy_protection(tmp_path,monkeypatch):
    monkeypatch.setattr(tts_bundle,'resource_root',lambda:tmp_path)
    t=LocalTTS(tmp_path/'tts',AudioLibrary(tmp_path/'audio'))
    assert t.settings()['device']=='cpu'
    class Owned:
        alive=True
        def poll(self):return None if self.alive else 0
        def terminate(self):self.alive=False
        def wait(self,timeout):return 0
    proc=Owned();t.process=proc;t.last_used=0
    t.lock.acquire();t.release_idle();assert proc.alive;t.lock.release()
    t.last_used=0;t.release_idle();assert not proc.alive
    with pytest.raises(ValueError):t.save({'device':'unknown'})
