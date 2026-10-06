import copy
import json
from pathlib import Path
import pytest
from test_script_plan import setup
from script_plan import build_timeline
from rough_cut import number

def member_event(payload,action,offset,slot=0):
    e=dict(action=action,offset=offset,slot=slot)
    if action!='hide':e.update(payload['scriptPlan']['rows'][0]['expression']);e.pop('action',None);e['action']=action;e['offset']=offset
    return e

def test_sentence_changes_preserve_full_voice_and_position(setup):
    cut,voice,payload,_=setup;row=payload['scriptPlan']['rows'][0]
    row['actorEvents']=[member_event(payload,'change',.61),dict(action='hide',offset=1.1,slot=0)]
    row.pop('expression');payload['scriptPlan']['rows'][1]['actorEvents']=[dict(action='show',offset=0,slot=0,id=payload['scenes'][0]['actors'][0]['id'],alignment=payload['scenes'][0]['actors'][0]['alignment'])]
    result=build_timeline(payload,cut,number);project=result['project'];scenes=project['scenes']
    assert len(scenes)==4 and scenes[0]['duration']==pytest.approx(19/30)
    assert scenes[0]['actors'][0]['id']==payload['scenes'][0]['actors'][0]['id']
    assert scenes[1]['actors'][0]['id']!=scenes[0]['actors'][0]['id'] and not scenes[2]['actors']
    assert scenes[3]['actors'][0]['transform']==scenes[0]['actors'][0]['transform']
    assert len(project['audioClips'])==1 and project['audioClips'][0]['duration']==voice['duration']
    assert len(project['textClips'])==2
    repeated=build_timeline(dict(project,reviewed=True),cut,number)['project']
    assert repeated['scenes']==scenes

def test_hide_at_start_keeps_templates_across_save_and_rebuild(setup):
    cut,_,payload,_=setup;payload['scriptPlan']['rows'][0].pop('expression')
    payload['scriptPlan']['rows'][0]['actorEvents']=[dict(action='hide',slot=0,offset=0)]
    base=payload['scenes'][0]['actors'][0]
    payload['scriptPlan']['rows'][1]['actorEvents']=[dict(action='show',slot=0,offset=.5,id=base['id'],alignment=base['alignment'])]
    built=build_timeline(payload,cut,number)['project'];saved=cut.save(built)
    assert not built['scenes'][0]['actors']
    rebuilt=build_timeline(dict(cut.load(saved['id']),reviewed=True),cut,number)['project']
    assert rebuilt['scenes']==built['scenes'] and rebuilt['scenes'][-1]['actors']
    modified=copy.deepcopy(saved);modified['scriptBase']['actors'][0]['transform']['x']+=20
    with pytest.raises(ValueError,match='重新计算'):cut.export(modified)

@pytest.mark.parametrize('events',[[dict(action='hide',slot=0,offset=50)],
 [dict(action='hide',slot=0,offset=.01),dict(action='hide',slot=0,offset=.02)],
 [dict(action='show',slot=1,offset=0,id='missing')]])
def test_invalid_changes_never_replace_timeline(setup,events):
    cut,_,payload,_=setup;payload['scriptPlan']['rows'][0]['actorEvents']=events
    original=copy.deepcopy(payload)
    with pytest.raises(ValueError):build_timeline(payload,cut,number)
    assert payload==original and cut.list_projects()['items']==[]

def test_calibrated_unused_candidates_registered_without_timeline_segments(setup):
    cut,_,payload,_=setup;payload['scriptPlan']['rows'][0].pop('expression')
    result=cut.export(build_timeline(payload,cut,number)['project']);folder=Path(result['path'])
    meta=json.loads((folder/'draft_meta_info.json').read_text('utf-8'));content=json.loads((folder/'draft_content.json').read_text('utf-8'))
    pack=json.loads((folder/'bingyi-actor-assets.json').read_text('utf-8'))
    assert len(pack['items'])==2 and sum(i['used'] for i in pack['items'])==1
    registry=next(g['value'] for g in meta['draft_materials'] if g['type']==0)
    assert len(registry)==len(content['materials']['videos'])+len(content['materials']['audios'])
    assert all(Path(m['file_Path']).is_file() for m in registry)
    assert all(m['local_material_id'] in {i['id'] for i in registry} for m in content['materials']['videos'])
    refs={s['material_id'] for t in content['tracks'] for s in t['segments']}
    assert next(i['materialId'] for i in pack['items'] if not i['used']) not in refs
    assert meta['draft_timeline_materials_size']>0
