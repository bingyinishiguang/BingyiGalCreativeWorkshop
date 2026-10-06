import copy
import wave
import pytest
from PIL import Image
from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from sprite_library import SpriteLibrary
from rough_cut import RoughCut, number
from composition_library import CompositionLibrary
from script_plan import build_timeline, normalize_plan

@pytest.fixture
def setup(tmp_path):
    audio=AudioLibrary(tmp_path/'audio');wav=tmp_path/'voice.wav'
    with wave.open(str(wav),'wb') as out:
        out.setparams((1,2,8000,0,'NONE','not compressed'));out.writeframes(bytes(2*16296))
    voice=audio.import_file(wav)['item']
    bg=BackgroundLibrary(tmp_path/'bg');png=tmp_path/'bg.png';Image.new('RGB',(960,540),'blue').save(png);background=bg.import_file(png)['item']
    sprites=SpriteLibrary(tmp_path/'sprites');ids=[sprites.save('Test','Heroine','pose',str(i),'normal',Image.new('RGBA',(200,400),c))['id'] for i,c in enumerate(['red','green'])]
    groups=CompositionLibrary(tmp_path/'cut',sprites);group=groups.save_group(groups.suggest(ids))
    cut=RoughCut(tmp_path/'cut',bg,sprites,audio)
    transform=dict(scaleX=180,scaleY=180,x=50,y=-260,rotation=0,uniform=True)
    base=dict(background=background['id'],duration=10,actors=[dict(id=ids[0],slot=0,alignment=group['members'][0],transform=transform)])
    rows=[dict(id='1',kind='heroine',text='Hello.',audio=voice['id'],pause=.55,expression=dict(id=ids[1],slot=0,alignment=group['members'][1])),dict(id='2',kind='hero',text='Hi.',hold=2)]
    payload=dict(name='English',fps=30,scenes=[base],reviewed=True,scriptPlan=dict(rows=rows,gap=.3))
    return cut,voice,payload,tmp_path

def test_full_voice_frame_ceil_inherited_expression_and_pause(setup):
    cut,voice,payload,_=setup;original=copy.deepcopy(payload);result=build_timeline(payload,cut,number);p=result['project'];first,second=result['schedule']
    assert p['audioClips'][0]['duration']==voice['duration']==2.037
    assert p['audioClips'][0]['sourceStart']==0 and not p['audioClips'][0]['subtitles']
    assert first['pause']==.55 and first['end']==pytest.approx(78/30)
    assert second['start']==first['end'] and second['pause']==0
    assert len(p['audioClips'])==1 and len(p['textClips'])==2
    assert p['textClips'][0]['duration']==p['scenes'][0]['duration']
    assert p['scenes'][0]['actors']==p['scenes'][1]['actors']
    assert p['scenes'][0]['actors'][0]['transform']==payload['scenes'][0]['actors'][0]['transform']
    assert payload==original

def test_default_pause_and_voice_override_and_bgm_preserved(setup):
    cut,voice,payload,_=setup;payload['scriptPlan']['rows'][0]['pause']=None
    payload['scriptPlan']['rows'][1].update(voice=True,audio=voice['id'])
    payload['audioClips']=[dict(audio=voice['id'],kind='bgm')]
    result=build_timeline(payload,cut,number)
    assert result['schedule'][0]['pause']==.3
    assert [c['kind'] for c in result['project']['audioClips']]==['bgm','dialogue','dialogue']
    assert normalize_plan({'rows':[dict(id='x',kind='inner',text='thought')]},number)['rows'][0]['voice']

def test_review_and_missing_audio_block_generation_without_saving(setup):
    cut,_,payload,_=setup
    for reviewed in (False,True):
        payload['reviewed']=reviewed;payload['scriptPlan']['rows'][0]['audio']=''
        with pytest.raises(ValueError,match='确认|绑定'):build_timeline(payload,cut,number)
    assert cut.list_projects()['items']==[]

def test_plan_round_trip_export_and_repeated_generation(setup):
    cut,_,payload,_=setup;p=build_timeline(payload,cut,number)['project'];saved=cut.save(p)
    assert cut.load(saved['id'])['scriptPlan']==p['scriptPlan']
    repeated=build_timeline(dict(saved,reviewed=True),cut,number)['project']
    assert repeated['audioClips']==p['audioClips'] and repeated['textClips']==p['textClips']
    exported=cut.export(saved)
    assert exported['duration']>=sum(s['duration'] for s in p['scenes'])-.001

def test_invalid_rows_and_timeline_limit(setup):
    cut,_,payload,_=setup
    with pytest.raises(ValueError):normalize_plan({'rows':[dict(id='x',text='a'),dict(id='x',text='b')]},number)
    with pytest.raises(ValueError):normalize_plan({'rows':[dict(id='x',kind='unknown',text='a')]},number)
    payload['scriptPlan']['rows']=[dict(id=str(i),text='long',hold=3590) for i in range(4)]
    with pytest.raises(ValueError,match='三小时'):build_timeline(payload,cut,number)


def test_stale_expression_calibration_requires_review(setup):
    cut,_,payload,_=setup
    payload['scenes'][0]['actors'][0]['alignment']['version']='new-version'
    with pytest.raises(ValueError,match='校准版本'):build_timeline(payload,cut,number)


def test_manual_voice_and_audio_binding_survive_save_reopen(setup):
    cut,voice,payload,_=setup
    row=payload['scriptPlan']['rows'][0]
    row.update(voice=False,voiceExplicit=True,
               audioBinding=dict(id=voice['id'],text=row['text'],character=''))
    saved=cut.save(build_timeline(payload,cut,number)['project'])
    restored=cut.load(saved['id'])['scriptPlan']['rows'][0]
    assert restored['voice'] is False and restored['voiceExplicit'] is True
    assert restored['audio']==voice['id'] and restored['audioBinding']==row['audioBinding']


@pytest.mark.parametrize('change', [{'text':'New words.'},{'character':'Another speaker'}])
def test_changed_sentence_requires_audio_review_without_deleting_recording(setup,change):
    cut,voice,payload,_=setup
    payload['scriptPlan']=normalize_plan(payload['scriptPlan'],number)
    row=payload['scriptPlan']['rows'][0];row.update(change)
    original=copy.deepcopy(payload)
    with pytest.raises(ValueError,match='核对旧音频'):build_timeline(payload,cut,number)
    assert payload==original and cut.audio_library.file(voice['id']).is_file()
    #Save the unresolved plan, then reopen; the warning must not disappear.
    saved=cut.save(payload);reopened=cut.load(saved['id'])
    with pytest.raises(ValueError,match='核对旧音频'):build_timeline(dict(reopened,reviewed=True),cut,number)
    reopened['scriptPlan']['rows'][0]['audioBinding']={'id':voice['id'],'text':row['text'],'character':row['character']}
    assert build_timeline(dict(reopened,reviewed=True),cut,number)['project']['audioClips'][0]['audio']==voice['id']


def test_legacy_plan_keeps_voice_decision_and_establishes_binding(setup):
    _,voice,payload,_=setup
    row=normalize_plan(payload['scriptPlan'],number)['rows'][0]
    assert row['voiceExplicit'] is True
    assert row['audioBinding']==dict(id=voice['id'],text='Hello.',character='')
