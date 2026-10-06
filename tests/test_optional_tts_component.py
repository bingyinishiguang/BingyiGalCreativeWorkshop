import json
from pathlib import Path

import pytest
import tts_bundle
from audio_library import AudioLibrary
from local_tts import LocalTTS


def component(root):
    files = ['service/api_v2.py', 'service/runtime/python.exe',
             'service/GPT_SoVITS/TTS_infer_pack/TTS.py',
             'service/GPT_SoVITS/pretrained_models/chinese-hubert-base/pytorch_model.bin',
             'service/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/pytorch_model.bin']
    for name in files:
        p = root/name;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(b'fixture')
    voice = root/'voices/角色';voice.mkdir(parents=True)
    for name in ('model.ckpt', 'model.pth', 'reference.wav'):(voice/name).write_bytes(b'fixture')
    (voice/'voice.json').write_text(json.dumps(dict(id='stable',name='角色',gpt='@tts/voices/角色/model.ckpt',sovits='@tts/voices/角色/model.pth',reference='@tts/voices/角色/reference.wav',prompt='你好',serviceRoot='@tts/service')),encoding='utf-8')
    (root/'component.json').write_text(json.dumps(dict(schemaVersion=1,componentId='bingyi-gpt-sovits',componentVersion='1.0-test',adapter='api_v2',serviceRoot='service',voicesRoot='voices')),encoding='utf-8')
    return root


def test_select_persist_disconnect_and_missing_no_fallback(tmp_path, monkeypatch):
    legacy=component(tmp_path/'legacy/tts_bundle')
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:legacy)
    t=LocalTTS(tmp_path/'data/LocalTTS',AudioLibrary(tmp_path/'audio'))
    voice=t.voices.scan()['items'][0];stable=voice['id']
    t.save({'name':'我的预设','speed':1.3})
    user_voice=t.voices.root/'角色/voice.json'
    raw=json.loads(user_voice.read_text('utf-8'));raw['name']='我的角色'
    user_voice.write_text(json.dumps(raw),encoding='utf-8')
    selected=component(tmp_path/'中文 外置组件')
    assert t.select_component(selected)['connected']
    assert Path(t.settings()['gpt']).is_relative_to(selected)
    assert t.settings()['name']=='我的预设' and t.settings()['speed']==1.3
    assert t.voices.scan()['items'][0]['id']==stable
    assert t.voices.scan()['items'][0]['name']=='我的角色'
    restored=LocalTTS(t.root,t.library)
    assert restored.component.root()==selected.resolve()
    before=t.component.state.read_bytes()
    with pytest.raises(ValueError):t.select_component(tmp_path/'broken')
    assert t.component.state.read_bytes()==before
    selected.rename(tmp_path/'moved')
    assert not t.component_status()['connected']
    assert Path(t.settings()['gpt']).is_relative_to(selected)  #No hidden fallback to legacy.
    t.select_component(None)
    assert not t.component_status()['connected']
    assert 'component-not-connected' in t.settings()['gpt']


def test_manifest_and_path_validation(tmp_path):
    root=component(tmp_path/'valid')
    manifest=root/'component.json';info=json.loads(manifest.read_text())
    info['schemaVersion']=2;manifest.write_text(json.dumps(info))
    with pytest.raises(ValueError,match='版本'):tts_bundle.Component.inspect(root)
    info.update(schemaVersion=1,serviceRoot='../other');manifest.write_text(json.dumps(info))
    with pytest.raises(ValueError):tts_bundle.Component.inspect(root)
    with pytest.raises(ValueError):tts_bundle.resolve('@tts/../outside',root)


def test_verified_upgrade_failure_preserves_previous_and_can_roll_back(tmp_path):
    import hashlib
    old=component(tmp_path/'旧版本 中文')
    new=component(tmp_path/'新版本 中文')
    index=new/'component-files.json'
    model=new/'service/api_v2.py'
    index.write_text(json.dumps({'files':[dict(path='service/api_v2.py',bytes=model.stat().st_size,sha256=hashlib.sha256(model.read_bytes()).hexdigest())]}))
    manifest=new/'component.json';info=json.loads(manifest.read_text())
    info.update(inventory=index.name,inventorySha256=hashlib.sha256(index.read_bytes()).hexdigest())
    manifest.write_text(json.dumps(info))
    selection=tts_bundle.Component(tmp_path/'data/location.json')
    selection.select(old);before=selection.state.read_bytes()
    model.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='校验失败'):selection.select(new)
    assert selection.state.read_bytes()==before
    model.write_bytes(b'fixture');selection.select(new)
    assert selection.root()==new.resolve()
    selection.select(old);assert selection.root()==old.resolve()
    moved=tmp_path/'移动后的 中文组件';old.rename(moved)
    assert not selection.status()['connected']
    selection.select(moved);assert selection.status()['connected']


def test_no_author_machine_default_and_no_host_model_import(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:tmp_path/'absent')
    t=LocalTTS(tmp_path/'data/LocalTTS',AudioLibrary(tmp_path/'audio'))
    assert t.settings()['serviceRoot']==''
    assert not t.component_status()['connected'] and not t.voices.items
    assert 'torch' not in sys.modules
    assert t.history()=={'items':[]}


def test_occupied_service_is_not_adopted_and_port_lease_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:tmp_path/'absent')
    a=LocalTTS(tmp_path/'a',AudioLibrary(tmp_path/'audio'))
    b=LocalTTS(tmp_path/'b',a.library)
    a.probe=lambda base:None
    with pytest.raises(ValueError,match='其他推理服务'):a.start()
    assert a.process is None
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    try:
        a.claim_service(base)
        with pytest.raises(ValueError,match='另一个'):b.claim_service(base)
        a.close();b.claim_service(base)
    finally:a.close();b.close()


def test_busy_switch_preserves_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:tmp_path/'absent')
    t=LocalTTS(tmp_path/'data/LocalTTS',AudioLibrary(tmp_path/'audio'))
    t.lock.acquire()
    try:
        with pytest.raises(ValueError,match='完成后'):t.select_component(None)
        assert not t.component.state.exists()
    finally:t.lock.release()


def test_relative_data_root_keeps_child_cache_out_of_component(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:tmp_path/'absent')
    t=LocalTTS(Path('data/LocalTTS'),AudioLibrary(tmp_path/'audio'))
    selected=component(tmp_path/'readonly-component')
    t.select_component(selected)
    def unavailable(base):raise ConnectionError()
    monkeypatch.setattr(t,'probe',unavailable)
    captured={}
    class Process:
        stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self,timeout=None):return 0
    def spawn(args,**kwargs):captured.update(kwargs);return Process()
    monkeypatch.setattr('local_tts.subprocess.Popen',spawn)
    try:
        t.start()
        cache=Path(captured['env']['MPLCONFIGDIR'])
        assert cache.is_absolute() and cache.is_relative_to(tmp_path/'data')
        assert not cache.is_relative_to(selected)
        assert captured['cwd']==selected/'service'
    finally:t.close()
