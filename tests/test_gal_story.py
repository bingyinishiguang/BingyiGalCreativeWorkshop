"""Story-specific validation, real encoding and AI/voice contract checks."""
import copy
import json
import math
import shutil
import struct
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from sprite_library import SpriteLibrary
from gal_story import GalStory, StoryCancelled
from gal_story_render import plan, render, export, inspect_video, at_time


@pytest.fixture
def story(tmp_path):
    audio=AudioLibrary(tmp_path/'audio')
    tts=SimpleNamespace(settings=lambda:{},voices=SimpleNamespace(get=lambda _:dict(preset={})))
    assistant=SimpleNamespace(settings=lambda:dict(models=[],activeModelId=''),model=lambda _:dict(baseUrl='https://example.com/v1',model='test'))
    return GalStory(tmp_path/'story',BackgroundLibrary(tmp_path/'backgrounds'),SpriteLibrary(tmp_path/'sprites'),audio,tts,assistant)


def tone(path, duration=.6):
    with wave.open(str(path),'wb') as stream:
        stream.setparams((1,2,48000,0,'NONE','not compressed'))
        stream.writeframes(b''.join(struct.pack('<h',int(math.sin(i/48000*440*2*math.pi)*1500)) for i in range(round(duration*48000))))
    return path


def test_parse_preserves_unmarked_lines_and_unknown_speaker(story):
    p=story.parse({'text':'冰翼：你好！\n没有角色的段落。\n【访客】我来了。\n旁白：钟响了。'})
    assert [r['text'] for r in p['clips']]==['你好！','没有角色的段落。','我来了。','钟响了。']
    assert p['clips'][1]['type']=='narration'
    assert p['characters'][-1]['name']=='访客'
    assert p['clips'][2]['actors']==p['clips'][0]['actors']  # Existing cast remains on stage.
    assert p['originalText'].endswith('钟响了。')


def test_save_load_and_asset_type_boundaries(story):
    p=story.demo();story.save({'project':p});assert story.load(p['id'])==story.normalize(p)
    assert len(story.list()['items'])==1
    with pytest.raises(ValueError):story.load('../outside')
    with pytest.raises(ValueError):story.asset_file('kit:sprite-1','background')
    with pytest.raises(ValueError):story.asset_file('local:../anything')


def test_plan_audio_end_pagination_and_typing(story,tmp_path):
    item=story.audio.import_file(tone(tmp_path/'voice.wav',2.13))['item']
    p=story.parse({'text':'冰翼：'+('我们一起把故事写下去。'*16)})
    p['clips'][0].update(voiceId=item['id'],voiceText=p['clips'][0]['text'],hold=.2,duration=.5)
    layout=plan(story,p,True);s=layout['segments'][0]
    assert len(s['pages'])>1
    assert s['duration']>=2.33 and s['duration']<2.37
    assert s['pageFrames'][0][0]==0 and s['pageFrames'][-1][1]==s['frames']
    p['clips'][0]['typing']=True
    assert plan(story,p)['duration']>s['duration']
    assert render(story,p,0,1).size==(1920,1080)


def test_invalid_refs_and_nonfinite_values(story):
    p=story.demo();p['clips'][0]['backgroundId']='kit:missing'
    assert plan(story,p)['warnings']
    with pytest.raises(ValueError):plan(story,p,True)
    with pytest.raises(ValueError):story.normalize({**story.demo(),'settings':[]})
    with pytest.raises(ValueError):story.normalize({**story.demo(),'bgm':[]})
    p=story.demo();p['clips'][0]['duration']=float('nan')
    with pytest.raises(ValueError):story.normalize(p)
    p=story.demo();p['clips'][1]['actors'][0]['spriteId']='kit:studio-day'
    with pytest.raises(ValueError):plan(story,p,True)


def test_chat_suggestions_validate_bindings_and_do_not_mutate(story,monkeypatch):
    import assistant_model
    p=story.parse({'text':'冰翼：你号。'});before=copy.deepcopy(p)
    response={'tool_calls':[{'function':{'name':'propose_story_edits','arguments':json.dumps({'message':'修正一处错字','changes':[{'id':p['clips'][0]['id'],'text':'你好。','spriteId':'kit:sprite-2'}]})}}]}
    calls=[]
    def request(*args,**kwargs):calls.append((args,kwargs));return response
    monkeypatch.setattr(assistant_model,'_request',request)
    result=story.chat({'project':p,'message':'修正错字','operation':'proofread'})
    assert p==before and result['changes'][0]['after']['text']=='你好。'
    assert calls[0][1]['tool_choice']['function']['name']=='propose_story_edits'
    assert 'measuredLines' in calls[0][0][1][1]['content']
    response['tool_calls'][0]['function']['arguments']=json.dumps({'changes':[{'id':p['clips'][0]['id'],'spriteId':'kit:studio-day'}]})
    with pytest.raises(ValueError):story.chat({'project':p,'message':'安排表情'})


def test_voice_job_returns_bindings_without_changing_project(story,tmp_path):
    item=story.audio.import_file(tone(tmp_path/'voice.wav'))['item']
    seen=[]
    def generate(payload,preset):seen.append(preset);return {'audioId':item['id']}
    story.tts.generate=generate
    p=story.parse({'text':'冰翼：明天见。'});before=copy.deepcopy(p)
    job=story.start({'project':p},'voice')
    for _ in range(100):
        result=story.job(job['id'])
        if result['state']!='running':break
        time.sleep(.01)
    assert result['state']=='complete' and result['outputs'][0]['voiceText']=='明天见。'
    assert p==before and seen[0]['textLanguage']=='zh'


def test_completed_export_record_survives_restart(story,tmp_path):
    p=story.demo();ident='previous_export';folder=story.exports/ident;folder.mkdir()
    video=folder/'story.mp4';video.write_bytes(b'fixture')
    result=dict(id=ident,state='complete',kind='export',projectId=p['id'],path=str(video),metadata={'duration':1})
    (folder/'result.json').write_text(json.dumps(result),'utf-8')
    assert story.job(ident)==result
    assert story.output_file(ident)==video
    assert story.outputs(p['id'])['items'][0]['id']==ident
    with pytest.raises(ValueError):story.job('../outside')


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='real encoder unavailable')
def test_real_mp4_with_voice_music_and_typing(story,tmp_path):
    voice=story.audio.import_file(tone(tmp_path/'voice.wav',.7))['item']
    music=story.audio.import_file(tone(tmp_path/'music.wav',1))['item']
    p=story.parse({'text':'冰翼：明天见。\n旁白：窗外起风了。'})
    p['clips'][0].update(voiceId=voice['id'],voiceText='明天见。',hold=.1,typing=True)
    p['clips'][1].update(duration=.7)
    p['bgm']['id']=music['id'];p['settings']['transition']=.1
    ident='test_export';story.jobs[ident]={}
    result=export(story,p,ident,threading.Event())
    info=inspect_video(Path(result['path']))
    assert (info['width'],info['height'],info['audio'])==(1920,1080,True)
    assert abs(info['duration']-plan(story,p)['duration'])<.1
    assert info['fps']=='30/1'
    assert not list(Path(result['path']).parent.glob('frame-*.png'))


def test_cancel_before_encoding_never_publishes(story):
    event=threading.Event();event.set();ident='cancelled_export';story.jobs[ident]={}
    with pytest.raises(StoryCancelled):export(story,story.demo(),ident,event)
    assert not list((story.exports/ident).glob('*.mp4'))


def test_narration_is_silent_and_keeps_stage_with_global_and_local_timing(story,tmp_path):
    audio=story.audio.import_file(tone(tmp_path/'old-narration.wav',4))['item']
    p=story.parse({'text':'冰翼：你好。\n旁白：夜色安静。\n冰翼（心声）：明天会更好。'})
    assert p['clips'][1]['actors']==p['clips'][0]['actors']
    assert p['clips'][2]['type']=='thought' and p['clips'][2]['speakerId']=='bingyi'
    p['clips'][1]['voiceId']=audio['id'];p['settings']['narrationDuration']=1.5
    layout=plan(story,p)
    assert layout['segments'][1]['voiceDuration']==0
    assert layout['segments'][1]['duration']==layout['segments'][2]['duration']==1.5
    p['clips'][1].update(duration=3,useDefaultDuration=False)
    assert plan(story,p)['segments'][1]['duration']==3
    p['clips'][1]['voiceEnabled']=True
    assert plan(story,p)['segments'][1]['voiceDuration']==4


def test_continuous_text_change_preserves_background_logo_and_animation(story):
    from PIL import ImageChops
    p=story.parse({'text':'冰翼：你好。\n旁白：安静。'})
    a=render(story,p,0,0);b=render(story,p,1,0);later=render(story,p,1,.3)
    assert ImageChops.difference(a.crop((0,0,1920,730)),b.crop((0,0,1920,730))).getbbox() is None
    assert ImageChops.difference(a.crop((0,1005,340,1080)),b.crop((0,1005,340,1080))).getbbox() is None
    assert ImageChops.difference(b.crop((1588,998,1620,1030)),later.crop((1588,998,1620,1030))).getbbox()
    p['clips'][1]['sceneTransition']=True
    assert render(story,p,1,0).getbbox() is None  # Black appears only when explicitly requested.


def test_actor_order_matches_visible_pixels_and_geometry(story,tmp_path):
    from PIL import Image
    p=story.parse({'text':'冰翼：图层验收。'})
    ids=[]
    for color in ('red','blue'):
        path=tmp_path/(color+'.png');image=Image.new('RGBA',(200,400),color);image.putpixel((0,0),(0,0,0,0));image.save(path)
        ids.append(story.import_asset({'path':str(path),'kind':'sprite'})['id'])
    p['characters'][0]['sprites']+=ids
    p['clips'][0]['actors']=[dict(characterId='bingyi',spriteId=ids[0],x=.5,y=.8,scale=.6,z=2),
                            dict(characterId='bingyi',spriteId=ids[1],x=.5,y=.8,scale=.6,z=1)]
    assert render(story,p,0).getpixel((960,400))==(255,0,0)
    p['clips'][0]['actors'][1]['z']=3
    assert render(story,p,0).getpixel((960,400))==(0,0,255)
    rects=plan(story,p)['segments'][0]['actorRects']
    assert rects[0]['width']==324 and rects[0]['height']==648


def test_deepseek_chat_uses_fat_fish_identity_without_changing_story(story,monkeypatch):
    import assistant_model
    from gal_story import chat_identity
    models=[dict(id='ds',name='自定义服务',model='deepseek-chat',baseUrl='https://example.com/v1',apiKey='secret'),dict(id='other',name='其他模型',model='test',baseUrl='https://example.com/v1')]
    story.assistant.settings=lambda:dict(models=models,activeModelId='ds')
    story.assistant.model=lambda _:models[0]
    captured=[]
    def request(config,messages,*args,**kwargs):
        captured.append(messages[0]['content'])
        return {'content':'你好，我是大肥鱼。'}
    monkeypatch.setattr(assistant_model,'_request',request)
    p=story.demo();before=copy.deepcopy(p)
    assert story.chat(dict(project=p,message='你好',modelId='ds'))['message']=='你好，我是大肥鱼。'
    assert '你是大肥鱼，' in captured[0] and '你是冰翼，' not in captured[0]
    assert p==before and p['characters'][0]['name']=='冰翼'
    public=story.status()['models']
    assert public[0]['identity']['name']=='大肥鱼'
    assert 'apiKey' not in public[0] and 'baseUrl' not in public[0]
    assert public[1]['identity']['name']=='冰翼'
    assert chat_identity(dict(name='DeepSeek 中转',model='custom'))['name']=='大肥鱼'
    assert chat_identity(dict(baseUrl='https://api.deepseek.com/v1'))['name']=='大肥鱼'

