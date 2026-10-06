import copy
import io
import json
import wave

import pytest
from test_local_tts import studio
from test_script_plan import setup
from timeline_voice import TimelineVoice
from rough_cut import number
from script_plan import build_timeline


def prepare(setup,studio):
    cut,_,payload,_=setup;tts,calls=studio
    tts.library=cut.audio_library
    folder=tts.voices.root/'测试';folder.mkdir()
    (folder/'voice.json').write_text(json.dumps(dict(id='test',name='中文音色',**{k:tts.settings()[k] for k in ('gpt','sovits','reference','prompt','promptLanguage')})),encoding='utf-8')
    voice_id=tts.voices.scan()['items'][0]['id']
    project=build_timeline(payload,cut,number)['project'];project['id']='a'*32
    service=TimelineVoice(cut,tts);target=project['textClips'][0]['id']
    take=service.generate(dict(project=project,target=target,voiceId=voice_id,text='实际发音',language='zh',speed=1))
    return service,project,target,take,tts,calls


def test_generate_does_not_edit_or_save_project_and_frozen_voice(setup,studio):
    service,p,key,take,tts,calls=prepare(setup,studio)
    assert service.cut.list_projects()['items']==[]
    assert p['audioClips'][0]['duration']==2.037
    assert take['text']=='实际发音' and take['preset']['name']=='中文音色'
    assert take['timelineTarget']['id']==key
    assert service.history(key)['items'][0]['id']==take['id']
    assert service.history('other')['items']==[]
    assert [payload for route,payload in calls if route=='/tts'][0]['text_lang']=='zh'


def test_preview_ripple_retains_transforms_binding_and_undo_input(setup,studio):
    service,p,key,take,tts,_=prepare(setup,studio);old=copy.deepcopy(p)
    response=service.preview(dict(project=p,target=key,take=take['id'],mode='ripple',pause=.55));out=response['project']
    assert p==old and out['id']==p['id']
    assert out['textClips'][1]['start']==pytest.approx(47/30)
    assert out['audioClips'][0]['duration']==1
    assert out['audioClips'][0]['linkedText']==key
    assert out['scenes'][0]['actors']==p['scenes'][0]['actors']
    assert out['textClips'][0]['text']=='Hello.'
    assert out['textClips'][0]['voice']['spokenText']=='实际发音'
    assert out['scriptPlan']['rows'][0]['spokenText']=='实际发音'
    assert out['scriptTiming']['plan']==out['scriptPlan'] if 'scriptTiming' in out else True
    saved=service.cut.save(out);assert saved['textClips'][0]['voice']['take']==take['id']
    assert service.cut.load(saved['id'])['audioClips'][0]['id']==p['audioClips'][0]['id']
    assert tts.file(take['id']).is_file()


def test_stale_take_and_ambiguous_links_reject_without_mutation(setup,studio):
    service,p,key,take,_,_=prepare(setup,studio)
    p['textClips'][0]['text']='改词'
    original=copy.deepcopy(p)
    with pytest.raises(ValueError,match='文字或角色'):service.preview(dict(project=p,target=key,take=take['id']))
    assert p==original


def test_shorter_voice_preserves_internal_changes_or_blocks(setup,studio):
    service,p,key,take,_,_=prepare(setup,studio)
    scene=copy.deepcopy(p['scenes'][0]);scene['duration']=.8
    second=copy.deepcopy(scene);second['duration']=p['scenes'][0]['duration']-.8;second['actors'][0]['transform']['x']=150
    p['scenes']=[scene,second,p['scenes'][1]]
    out=service.preview(dict(project=p,target=key,take=take['id'],pause=0))['project']
    assert out['scenes'][0]['duration']==.8
    assert out['scenes'][1]['duration']==pytest.approx(.2)
    assert out['scenes'][1]['actors'][0]['transform']['x']==150
    p['scenes'][0]['duration']=1.5;p['scenes'][1]['duration']=1.1
    with pytest.raises(ValueError,match='挤掉'):service.preview(dict(project=p,target=key,take=take['id']))
    assert service.preview(dict(project=p,target=key,take=take['id'],mode='keep'))['summary']['delta']==0


def test_longer_take_keep_rejects_bgm_stays_and_later_text_shifts(setup,studio):
    service,p,key,take,tts,_=prepare(setup,studio)
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(2*16000*4))
    original=tts.call;tts.call=lambda base,route,payload=None,limit=None:stream.getvalue() if route=='/tts' else original(base,route,payload,limit)
    take2=service.generate(dict(project=p,target=key,voiceId=take['timelineTarget']['voiceId'],text='第二版'))
    with pytest.raises(ValueError,match='长于'):service.preview(dict(project=p,target=key,take=take2['id'],mode='keep'))
    p['audioClips'].append(dict(audio=take2['audioId'],start=0,duration=4,kind='bgm'))
    out=service.preview(dict(project=p,target=key,take=take2['id']))['project']
    assert next(a for a in out['audioClips'] if a['kind']=='bgm')['start']==0
    assert out['textClips'][1]['start']==4
    assert len(tts.history()['items'])==2 and tts.file(take['id']).exists()


def test_legacy_identity_stable_and_duplicate_rejected(setup):
    cut,_,payload,_=setup;payload['textClips']=[dict(text='文字')]
    a=cut.normalize(payload);b=cut.normalize(payload)
    assert a['textClips'][0]['id']==b['textClips'][0]['id']
    payload['textClips']=[dict(id='same',text='一'),dict(id='same',text='二')]
    with pytest.raises(ValueError,match='重复'):cut.normalize(payload)
