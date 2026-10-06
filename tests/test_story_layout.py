import copy
import json
from pathlib import Path
import pytest
from test_script_plan import setup
from rough_cut import number
from script_plan import build_timeline
from text_layout import default_layout,resolve_layout
from text_layout import page_spans


def test_pagination_uses_whole_sentence_duration_and_contiguous_pages(setup):
    cut,voice,payload,_=setup;l=default_layout();l['paginate']=True;l['dialogue'].update(width=160,height=48)
    payload['scriptPlan']['layout']=l
    payload['scriptPlan']['rows'][0]['text']='这是一个需要分页显示的很长的对话，完整音频不应该被重复播放。'
    result=build_timeline(payload,cut,number)['project'];clip=result['textClips'][0]
    pages=page_spans(clip,result['fps']);assert len(pages)>1
    assert sum(p[2] for p in pages)==pytest.approx(clip['duration'])
    assert ''.join(line for lines,_,_ in pages for line in lines)==clip['text']
    assert len(result['audioClips'])==1 and result['audioClips'][0]['duration']==voice['duration']
    assert all(len(lines)==1 for lines,_,_ in pages)
    assert all(pages[i][1]+pages[i][2]==pytest.approx(pages[i+1][1]) for i in range(len(pages)-1))
    cut.export(result)
    content=json.loads(list(cut.exports.glob('*/draft_content.json'))[-1].read_text('utf-8'))
    assert sum(len(t['segments']) for t in content['tracks'] if t['type']=='audio')==1


def test_pagination_too_many_pages_rejected():
    l=default_layout();l.update(paginate=True);l['narrator'].update(width=40,height=48)
    clip={'start':0,'duration':1/30,'layout':resolve_layout(l,'旁白有很多文字','',number)}
    with pytest.raises(ValueError,match='帧数'):page_spans(clip,30)

def test_shared_left_anchor_wrapping_and_independent_name():
    l=default_layout();l['narrator']['width']=144
    a=resolve_layout(dict(l,kind='narrator'),'这是一个很长的旁白，需要换行。','',number)
    b=resolve_layout(dict(l,kind='inner'),'这是心理描写。','男主',number)
    assert len(a['lines'])>1 and a['narrator']==b['narrator']
    assert a['nameText']==b['nameText']==''
    x=resolve_layout(dict(l,kind='dialogue'),'你好。','莉莉子',number)
    y=resolve_layout(dict(l,kind='dialogue'),'你好。','很长的角色名',number)
    assert x['dialogue']==y['dialogue'] and x['nameText']=='【莉莉子】'

def test_default_timing_override_voice_and_stale_plan(setup):
    cut,voice,payload,_=setup
    rows=payload['scriptPlan']['rows']
    rows[1].update(kind='narrator',holdExplicit=False)
    rows.extend([dict(id='3',kind='inner',text='心理',voice=False,hold=99,holdExplicit=False),
                 dict(id='4',kind='dialogue',text='无声对话',voice=False,hold=99,holdExplicit=False),
                 dict(id='5',kind='inner',text='单句覆盖',voice=False,hold=1,holdExplicit=True)])
    payload['scriptPlan'].update(layout=default_layout(),timing=dict(silentHold=4,dialogueHold=2))
    result=build_timeline(payload,cut,number);p=result['project']
    assert [r['duration'] for r in result['schedule']]==[voice['duration'],4,4,2,1]
    assert p['audioClips'][0]['duration']==voice['duration']
    assert cut.normalize(p)['scriptTiming']==p['scriptTiming']
    changed=copy.deepcopy(p);changed['scriptPlan']['timing']['silentHold']=5
    with pytest.raises(ValueError,match='重新计算'):cut.export(changed)
    assert cut.save(changed)['scriptPlan']['timing']['silentHold']==5

def test_overflow_blocks_build_but_can_save_edit(setup):
    cut,_,payload,_=setup
    payload['scriptPlan']['layout']=default_layout();payload['scriptPlan']['layout']['dialogue'].update(width=40,height=48)
    with pytest.raises(ValueError,match='超出文字区域'):build_timeline(payload,cut,number)
    assert cut.save(payload)['scriptPlan']['layout']['dialogue']['width']==40

def test_export_name_and_lines_are_editable_left_aligned(setup):
    cut,_,payload,_=setup;payload['scriptPlan']['layout']=default_layout()
    payload['scriptPlan']['rows'][0]['character']='莉莉子'
    project=build_timeline(payload,cut,number)['project'];result=cut.export(project)
    files=list(cut.exports.glob('*/draft_content.json'));assert files
    content=json.loads(files[-1].read_text(encoding='utf-8'))
    texts=content['materials']['texts'];strings=[json.loads(t['content'])['text'] for t in texts]
    assert '【莉莉子】' in strings and 'Hello.' in strings
    assert all(t['type']=='text' and t['alignment']==0 for t in texts)
    assert project['textClips'][0]['layout']['dialogue']['x']==240
