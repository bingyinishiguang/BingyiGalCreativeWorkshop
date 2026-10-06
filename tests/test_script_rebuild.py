import copy
import pytest
from test_script_plan import setup
from rough_cut import number
from script_plan import build_timeline
from script_rebuild import preview
from script_import import parse_script


def test_rebuild_preserves_manual_positions_and_text_style(setup):
    cut,_,payload,_=setup;p=build_timeline(payload,cut,number)['project'];p['reviewed']=True
    p['scenes'][0]['actors'][0]['transform']['x']=213
    p['textClips'][0]['subtitleStyle']['color']='#123456'
    original=copy.deepcopy(p);result=preview(p,cut)
    assert p==original
    assert result['summary']['manualFields']==2
    kept=result['preservedProject'];assert kept['scenes'][0]['actors'][0]['transform']['x']==213
    assert kept['textClips'][0]['subtitleStyle']['color']=='#123456'
    assert kept['scriptBaseline']['textClips'][0]['subtitleStyle']['color']=='#ffffff'
    assert cut.save(kept)['scriptBaseline']==kept['scriptBaseline']


def test_conflicting_word_changes_cannot_silently_merge(setup):
    cut,_,payload,_=setup;p=build_timeline(payload,cut,number)['project'];p['reviewed']=True
    p['textClips'][1]['text']='时间轴手改';p['scriptPlan']['rows'][1]['text']='校对表手改'
    result=preview(p,cut)
    assert result['preservedProject'] is None and result['summary']['conflicts']
    assert result['project']['textClips'][1]['text']=='校对表手改'


def test_manual_timing_and_deleted_clips_cannot_claim_preserved(setup):
    cut,_,payload,_=setup;p=build_timeline(payload,cut,number)['project'];p['reviewed']=True
    p['textClips'][1]['start']+=.2
    assert preview(p,cut)['preservedProject'] is None
    p['textClips'].pop()
    assert any('删除' in t for t in preview(p,cut)['summary']['conflicts'])


def test_scene_binding_requires_explicit_id_and_persists_with_duplicate_names(setup):
    cut,_,payload,_=setup
    plan=parse_script('【场景】教室\n【背景】同名背景\n【旁白】第一句\n【场景】走廊\n【旁白】第二句')
    payload['scriptPlan']=plan
    with pytest.raises(ValueError,match='尚未确认'):build_timeline(payload,cut,number)
    keys=[r['sceneKey'] for r in plan['rows']];assert keys[0]!=keys[1]
    plan['sceneBindings']={key:payload['scenes'][0]['background'] for key in keys}
    result=build_timeline(payload,cut,number)['project']
    assert all(s['background']==plan['sceneBindings'][keys[0]] for s in result['scenes'])
    assert cut.save(result)['scriptPlan']['sceneBindings']==plan['sceneBindings']
