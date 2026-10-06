import io
import json
import wave
from pathlib import Path

import pytest
from audio_library import AudioLibrary
from local_tts import LocalTTS, endpoint


@pytest.fixture
def studio(tmp_path, monkeypatch):
    import tts_bundle
    monkeypatch.setattr(tts_bundle,'bundle_root',lambda:tmp_path/'no-bundled-voices')
    t=LocalTTS(tmp_path/'tts',AudioLibrary(tmp_path/'audio'))
    files={}
    for key,suffix in [('gpt','.ckpt'),('sovits','.pth'),('reference','.wav')]:
        p=tmp_path/(key+suffix);p.write_bytes(b'fixture');files[key]=str(p)
    t.save(dict(**files,prompt='参考台词',promptLanguage='ja',character='测试角色',serviceMode='external'))
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000)
    calls=[]
    def call(base,route,payload=None,limit=None):
        calls.append((route,payload))
        if route=='/openapi.json':return json.dumps({'paths':{p:{} for p in ['/tts','/set_gpt_weights','/set_sovits_weights']}}).encode()
        if route=='/tts':return stream.getvalue()
        return b'{"message":"success"}'
    t.call=call
    return t,calls


def test_connection_does_not_switch_or_generate(studio):
    t,calls=studio;t.test();assert [r for r,p in calls]==['/openapi.json']


def test_versions_and_duplicate_keep_previous_metadata(studio):
    t,calls=studio
    a=t.generate({'text':'第一句','name':'第一版'})
    b=t.generate({'text':'第二句','name':'第二版'})
    assert a['id']!=b['id'] and a['audioId']==b['audioId']
    assert t.library.file(a['audioId']).is_file()
    assert t.file(a['id']).is_file() and len(t.history()['items'])==2
    assert t.library.list()['items'][0]['text']=='第一句'
    request=[p for r,p in calls if r=='/tts'][0]
    assert request['streaming_mode'] is False and request['prompt_lang']=='ja'
    assert request['sample_steps']==32 and request['fragment_interval']==.3
    assert calls[1][0].startswith('/set_gpt_weights?') and calls[2][0].startswith('/set_sovits_weights?')


def test_failed_generation_preserves_history(studio):
    t,_=studio;a=t.generate({'text':'旧台词'})
    original=t.call
    t.call=lambda base,route,payload=None,limit=None: b'bad audio' if route=='/tts' else original(base,route,payload,limit)
    with pytest.raises(ValueError):t.generate({'text':'新台词'})
    assert len(t.history()['items'])==1 and t.file(a['id']).is_file()
    assert len(list(t.records.glob('*.wav')))==1
    assert not t.lock.locked()


def test_busy_and_invalid_preset(studio):
    t,_=studio;t.lock.acquire()
    try:
        with pytest.raises(ValueError,match='等待'):t.generate({'text':'你好'})
    finally:t.lock.release()
    with pytest.raises(ValueError):t.save({'speed':'nan'})
    with pytest.raises(ValueError):endpoint('https://example.com')
    with pytest.raises(ValueError):t.file('../preset')
    t.save({'reference':''})
    with pytest.raises(ValueError,match='参考音频'):t.generate({'text':'你好'})


def test_sampling_speed_pause_are_saved_and_frozen(studio):
    t,calls=studio
    t.save({'sampleSteps':16,'fragmentInterval':.8,'speed':1.2})
    take=t.generate({'text':'第一句。第二句。'})
    request=next(p for r,p in calls if r=='/tts')
    assert request['sample_steps']==16 and request['fragment_interval']==.8 and request['speed_factor']==1.2
    assert take['preset']['sampleSteps']==16 and take['preset']['fragmentInterval']==.8
    assert t.settings()['sampleSteps']==16
    t.save({'sampleSteps':32,'fragmentInterval':0})
    assert t.history()['items'][0]['preset']['fragmentInterval']==.8
    for value in (8,4,True,16.5,'unknown'):
        with pytest.raises(ValueError,match='16 或 32'):t.save({'sampleSteps':value})
    for value in (-1,4,float('nan'),float('inf'),'unknown'):
        with pytest.raises(ValueError):t.save({'fragmentInterval':value})
