import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from bilingual_dialogue import BilingualDialogue, parse_groups, timed_rows
from draft_video_tools import DraftVideoTools
from tests.test_existing_draft import draft


def test_suggestion_is_plain_json_and_must_cover_both_scripts():
    ja, zh, assets = ['今日は。','明日も。'], ['今天。','明天。'], [{'id':'0'}]
    result = parse_groups({'content':'```json\n{"groups":[{"jaEnd":2,"zhIndices":[1,2],"expression":"0"}]}\n```'},ja,zh,assets)
    assert result[0]['jaStart']==result[0]['jaStart']==0
    for groups in ([dict(jaEnd=1,zhIndices=[1],expression='0')], [dict(jaEnd=2,zhIndices=[1,2],expression='invented')], [dict(jaEnd=True,zhIndices=[1,2],expression='0')]):
        with pytest.raises(ValueError):
            parse_groups({'content':json.dumps({'groups':groups})},ja,zh,assets)


def test_word_alignment_keeps_utterance_times_and_rejects_wrong_audio():
    groups=[dict(jaStart=0,jaEnd=1,zhIndices=[1],expression='0',reason='叙述'),dict(jaStart=1,jaEnd=2,zhIndices=[2],expression='0',reason='结尾')]
    cues=[dict(start=1,end=4,text='今日は明日も',words=[dict(start=1,end=2,text='今日は'),dict(start=3,end=4,text='明日も')])]
    rows,coverage=timed_rows(['今日は。','明日も。'],['今天。','明天。'],groups,cues)
    assert coverage==1 and [(r['start'],r['end']) for r in rows]==[(1,2),(3,4)]
    assert all(r['review'] for r in rows)
    with pytest.raises(ValueError):
        timed_rows(['全然違う原稿。'],['不同原稿。'],[dict(jaStart=0,jaEnd=1,zhIndices=[1],expression='0',reason='')],cues)


def test_semantic_order_can_differ_from_chinese_manuscript():
    ja=['なぜ恋愛しない。','不思議に思う。'];zh=['有人不理解。','为什么不恋爱。']
    groups=parse_groups({'content':json.dumps({'groups':[dict(jaEnd=1,zhIndices=[2],expression='0'),dict(jaEnd=2,zhIndices=[1],expression='0')]})},ja,zh,[{'id':'0'}])
    rows,coverage=timed_rows(ja,zh,groups,[dict(text=ja[0],start=1,end=3),dict(text=ja[1],start=4,end=6)])
    assert coverage==1 and [r['chinese'] for r in rows]==['为什么不恋爱','有人不理解']
    assert [(r['start'],r['end']) for r in rows]==[(1,3),(4,6)]


def test_repeated_japanese_endpoint_and_chinese_index_are_rejected():
    for second in (dict(jaEnd=1,zhIndices=[2],expression='0'),dict(jaEnd=2,zhIndices=[1],expression='0')):
        with pytest.raises(ValueError):
            parse_groups({'content':json.dumps({'groups':[dict(jaEnd=1,zhIndices=[1],expression='0'),second]})},['今日。','明日。'],['今天。','明天。'],[{'id':'0'}])


def test_interwoven_translation_merges_interval_without_repeating_text():
    groups=parse_groups({'content':json.dumps({'groups':[dict(jaEnd=1,zhIndices=[1],expression='0'),dict(jaEnd=2,zhIndices=[2],expression='0'),dict(jaEnd=3,zhIndices=[1],expression='0')]})},['続くと、','嫌で、','話さなくなる。'],['时间久了，不愿主动接触。','怕被开玩笑。'],[{'id':'0'}])
    assert len(groups)==1 and groups[0]['jaEnd']==3 and groups[0]['zhIndices']==[1,2]


def build_workflow(draft,tmp_path):
    source,body,editor,loaded,payload=draft
    for label in ('平静','微笑'):
        path=tmp_path/f'角色_制服_姿势1_{label}.png'
        Image.new('RGBA',(20,40),'blue').save(path)
    material=dict(id='portrait',path=str(tmp_path/'角色_制服_姿势1_平静.png'),width=20,height=40)
    body['materials']['videos'].append(material)
    sample=dict(id='template',material_id='portrait',clip=dict(scale=dict(x=1.1,y=1.2),transform=dict(x=.2,y=-.1),rotation=3),target_timerange=dict(start=0,duration=500000),source_timerange=dict(start=0,duration=500000),extra_material_refs=['reference'])
    body['tracks'].append(dict(type='video',segments=[sample]))
    source.write_text(json.dumps(body),'utf-8')
    loaded=editor.load({'path':str(source)})
    workflow=BilingualDialogue(tmp_path/'bilingual',DraftVideoTools(editor),SimpleNamespace())
    original=dict(payload,sessionId=loaded['sessionId'],videoTrackIndex=2,segmentIndex=0)
    rows=[dict(start=0,end=2,chinese='今天。',expression='0',japanese='今日は。',review=False),dict(start=2,end=4,chinese='明天。',expression='1',japanese='明日も。',review=False)]
    assets=[dict(id=str(i),path=str(tmp_path/f'角色_制服_姿势1_{v}.png'),width=20,height=40) for i,v in enumerate(('平静','微笑'))]
    workflow.jobs['ready']=dict(state='complete',rows=rows,assets=assets,payload=original,audioSegment=dict(target_timerange=dict(start=0,duration=4000000)),coverage=1)
    return source,body,workflow,rows


def test_full_audio_portrait_track_and_subtitle_template_preserved(draft,tmp_path):
    source,body,workflow,rows=build_workflow(draft,tmp_path)
    before=source.read_bytes()
    result=workflow.export(dict(id='ready',rows=[dict(chinese=r['chinese'],expression=r['expression'],reviewed=True) for r in rows]))
    data=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    portrait=data['tracks'][2]['segments']
    assert [s['target_timerange'] for s in portrait]==[dict(start=0,duration=2000000),dict(start=2000000,duration=2000000)]
    assert all(s['clip']==body['tracks'][2]['segments'][0]['clip'] and s['extra_material_refs']==['reference'] for s in portrait)
    assert data['tracks'][0]==body['tracks'][0]
    assert data['tracks'][1]['segments'][0]['target_timerange']==dict(start=0,duration=2000000)
    assert result['subtitleCount']==2 and source.read_bytes()==before
    assert data['materials']['texts'][0]==body['materials']['texts'][0]


def test_uncertain_alignment_or_existing_portrait_overlap_blocks_export(draft,tmp_path):
    source,body,workflow,rows=build_workflow(draft,tmp_path)
    workflow.jobs['ready']['rows'][0]['review']=True
    with pytest.raises(ValueError,match='核对'):
        workflow.export(dict(id='ready',rows=[dict(chinese=r['chinese'],expression=r['expression']) for r in rows]))
    workflow.jobs['ready']['rows'][0]['review']=False
    sid=workflow.jobs['ready']['payload']['sessionId']
    s=workflow.video.editor.sessions[sid]
    s['data']['tracks'][2]['segments'].append(copy.deepcopy(s['data']['tracks'][2]['segments'][0]))
    with pytest.raises(ValueError,match='其他片段'):
        workflow.export(dict(id='ready',rows=[dict(chinese=r['chinese'],expression=r['expression']) for r in rows]))


def test_arbitrary_filenames_use_aliases_and_each_pose_format(draft,tmp_path):
    source,body,workflow,rows=build_workflow(draft,tmp_path)
    sid=workflow.jobs['ready']['payload']['sessionId'];data=workflow.video.editor.sessions[sid]['data']
    pose=copy.deepcopy(data['tracks'][2]['segments'][0]);pose['id']='pose2';pose['clip']=dict(scale=dict(x=.8,y=.9),transform=dict(x=.7,y=-.4),rotation=4)
    data['tracks'][2]['segments'].append(pose)
    paths=[tmp_path/'holiday.png',tmp_path/'90210.webp']
    for path in paths:Image.new('RGBA',(30,50),'blue').save(path)
    data['materials']['audios']=[dict(id='audio',path=str(source))]
    data['tracks'].append(dict(type='audio',segments=[dict(material_id='audio')]))
    config=dict(workflow.jobs['ready']['payload'],portraitAssets=[dict(path=str(paths[0]),label='平静·站姿',templateSegmentIndex=0),dict(path=str(paths[1]),label='微笑·坐姿',templateSegmentIndex=1)])
    info=workflow.template(config)
    assert [a['label'] for a in info['assets']]==['平静·站姿','微笑·坐姿']
    source_image=Path(data['materials']['videos'][-1]['path']);source_image.unlink()
    assert len(workflow.template(config)['assets'])==2
    workflow.jobs['ready']['assets']=info['assets'];workflow.jobs['ready']['payload']=dict(config,centerX=True)
    result=workflow.export(dict(id='ready',automatic=True,rows=[dict(chinese=r['chinese'],expression=r['expression']) for r in rows]))
    output=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    clips=[s['clip'] for s in output['tracks'][2]['segments']]
    assert all(c['transform']['x']==0 for c in clips)
    assert [c['transform']['y'] for c in clips]==[-.1,-.4]
    assert [c['scale'] for c in clips]==[dict(x=1.1,y=1.2),dict(x=.8,y=.9)]
    assert all(path.is_file() for path in paths)


def test_automatic_reprocessing_replaces_existing_portrait_cuts_only_in_scope(draft,tmp_path):
    source,body,workflow,rows=build_workflow(draft,tmp_path)
    original=workflow.jobs['ready']['payload'];data=workflow.video.editor.sessions[original['sessionId']]['data']
    overlap=copy.deepcopy(data['tracks'][2]['segments'][0]);overlap['id']='old-cut';overlap['target_timerange']=dict(start=1000000,duration=1000000)
    outside=copy.deepcopy(overlap);outside['id']='outside';outside['target_timerange']=dict(start=4000000,duration=1000000)
    data['tracks'][2]['segments'].extend([overlap,outside])
    workflow.jobs['ready']['payload']=dict(original,replacePortraitRange=True,centerX=True)
    result=workflow.export(dict(id='ready',automatic=True,rows=[dict(chinese=r['chinese'],expression=r['expression']) for r in rows]))
    output=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    assert len(output['tracks'][2]['segments'])==3
    assert output['tracks'][2]['segments'][-1]==outside
    assert all(s['clip']['transform']['x']==0 for s in output['tracks'][2]['segments'][:2])



def test_caption_units_keep_preposition_with_next_phrase():
    from bilingual_dialogue import caption_units
    units=caption_units('今天，我想替欧尼酱，向大家说一些心里话。')
    assert units==['今天，我想替欧尼酱，','向大家说一些心里话。']
    assert all(not v.rstrip('，。').endswith('向') for v in units)


def test_phrase_timing_is_not_proportional_to_chinese_length():
    ja=['私は','皆に心を伝えます。'];zh=['我想','向大家说一些心里话。']
    groups=[dict(jaStart=0,jaEnd=1,zhIndices=[1],expression='0',reason=''),dict(jaStart=1,jaEnd=2,zhIndices=[2],expression='0',reason='')]
    cues=[dict(start=1,end=8,text='私は皆に心を伝えます。',words=[dict(start=1,end=2,text='私は'),dict(start=4,end=8,text='皆に心を伝えます。')])]
    rows,_=timed_rows(ja,zh,groups,cues)
    assert rows[0]['end']==2 and rows[1]['start']==4


@pytest.mark.parametrize('use_baidu',[False,True])
def test_baidu_reference_reaches_model_without_replacing_author_text(draft,tmp_path,monkeypatch,use_baidu):
    import threading
    import assistant_asr
    import bilingual_dialogue
    from types import SimpleNamespace
    source,body,workflow,existing_rows=build_workflow(draft,tmp_path)
    workflow.assistant=SimpleNamespace(safe_error=lambda error,settings:str(error))
    workflow.jobs['run']=dict(state='running',stage='',cancel=threading.Event())
    monkeypatch.setattr(assistant_asr,'recognize',lambda *args:[dict(text='今日は。',start=0,end=2),dict(text='明日も。',start=2,end=4)])
    translated=[]
    def references(texts,*args):
        translated.append(texts)
        return {text:{'今日は。':'今天。','明日も。':'明天也。'}[text] for text in texts}
    monkeypatch.setattr(bilingual_dialogue,'reference_translations',references)
    calls=[]
    def request(model,messages,**kwargs):
        context=json.loads(messages[1]['content']);calls.append(context)
        assert [v['referenceChinese'] for v in context['japanese']]==(['今天。','明天也。'] if use_baidu else ['',''])
        assert context['chinese'][0]['text']=='今天想说心里话。'
        return dict(content=json.dumps(dict(groups=[dict(jaEnd=1,zhIndices=[1],expression='0'),dict(jaEnd=2,zhIndices=[2],expression='0')])))
    monkeypatch.setattr(bilingual_dialogue,'_request',request)
    payload=dict(japanese='今日は。明日も。',chinese='今天想说心里话。明天也继续。',useBaidu=use_baidu)
    assets=[dict(id='0',label='平静')]
    workflow.run('run',payload,str(source),{},dict(model='mock'),['今日は。','明日も。'],['今天想说心里话。','明天也继续。'],assets,dict(target_timerange=dict(start=0,duration=4000000)),dict(appId='id',secret='secret'))
    result=workflow.job(dict(id='run'))
    assert result['state']=='complete',result.get('error')
    assert result['referenceProvider']==('baidu' if use_baidu else None) and calls
    assert bool(translated)==use_baidu
    assert result['rows'][0]['chinese']=='今天想说心里话'
    assert result['rows'][0]['referenceChinese']==('今天。' if use_baidu else '')
    assert [(r['start'],r['end']) for r in result['rows']]==[(0,2),(2,4)]
