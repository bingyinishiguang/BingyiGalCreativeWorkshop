import copy
import json
from pathlib import Path
import pytest
from existing_draft import ExistingDraftEditor
from draft_video_tools import DraftVideoTools
from tests.test_existing_draft import draft


@pytest.mark.parametrize('root', ['', '   ', None])
def test_relink_requires_explicit_directory(draft, root):
    source, body, editor, loaded, payload = draft
    with pytest.raises(ValueError, match='请填写'):
        DraftVideoTools(editor).relink_preview({**payload, 'root': root})


def test_relink_candidates_are_explicit_and_preserve_other_data(draft, tmp_path):
    source, body, editor, loaded, payload = draft
    assets = tmp_path/'assets'; assets.mkdir()
    (assets/'missing.png').write_bytes(b'one')
    (assets/'sub').mkdir(); (assets/'sub/missing.png').write_bytes(b'two')
    tools = DraftVideoTools(editor)
    before = source.read_bytes()
    review = tools.relink_preview({**payload, 'root': str(assets)})
    assert review['rows'][0]['status'] == 'ambiguous'
    assert review['rows'][0]['selected'] == ''
    with pytest.raises(ValueError): tools.relink_save({**payload, 'previewId': review['previewId'], 'choices': {}})
    with pytest.raises(ValueError): tools.relink_save({**payload, 'previewId': review['previewId'], 'choices': {'videos:0': str(source)}})
    chosen = review['rows'][0]['candidates'][0]['path']
    result = tools.relink_save({**payload, 'previewId': review['previewId'], 'choices': {'videos:0': chosen}})
    modified = json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    expected = copy.deepcopy(body); expected['materials']['videos'][0]['path'] = chosen
    assert modified == expected and source.read_bytes() == before


def test_relink_changed_candidate_and_source_rejected(draft, tmp_path):
    source, body, editor, loaded, payload = draft
    assets=tmp_path/'assets'; assets.mkdir(); candidate=assets/'missing.png'; candidate.write_bytes(b'x')
    tools=DraftVideoTools(editor); review=tools.relink_preview({**payload,'root':str(assets)})
    candidate.write_bytes(b'changed')
    with pytest.raises(ValueError,match='变化'):
        tools.relink_save({**payload,'previewId':review['previewId'],'choices':{'videos:0':str(candidate)}})
    source.write_text('{}')
    with pytest.raises(ValueError,match='变化'): tools.character_info(payload)


def test_identical_candidates_content_hash_and_same_size_change(draft,tmp_path):
    source,body,editor,loaded,payload=draft
    assets=tmp_path/'assets';assets.mkdir();(assets/'sub').mkdir()
    for path in (assets/'missing.png',assets/'sub/missing.png'):path.write_bytes(b'one')
    tools=DraftVideoTools(editor);preview=tools.relink_preview({**payload,'root':str(assets)})
    assert preview['rows'][0]['status']=='identical'
    candidate=preview['rows'][0]['candidates'][0]
    Path(candidate['path']).write_bytes(b'two')
    with pytest.raises(ValueError,match='变化'):
        tools.relink_save({**payload,'previewId':preview['previewId'],'choices':{'videos:0':candidate['path']}})


def character_fixture(draft, tmp_path):
    source, body, editor, loaded, payload=draft
    for name in ('neutral.png','smile.png'):
        (tmp_path/name).write_bytes(b'image')
    body['materials']['videos'] += [{'id':name,'path':str(tmp_path/name)} for name in ('neutral.png','smile.png')]
    body['tracks'].append({'type':'video','segments':[{'id':'example','material_id':'neutral.png','clip':{'scale':{'x':1.1,'y':1.1},'transform':{'x':.2,'y':-.1}},'speed':1,'target_timerange':{'start':0,'duration':4000000},'source_timerange':{'start':0,'duration':4000000}}]})
    source.write_text(json.dumps(body),'utf-8')
    loaded=editor.load({'path':str(source)})
    return source,body,DraftVideoTools(editor),{**payload,'sessionId':loaded['sessionId']}


def test_character_model_plan_manual_edit_and_boundary(draft,tmp_path,monkeypatch):
    source,body,tools,payload=character_fixture(draft,tmp_path)
    before=source.read_bytes()
    switches=[{'cueIndex':0,'materialId':'neutral.png','reason':'叙述'},{'cueIndex':1,'materialId':'smile.png','reason':'轻松'}]
    def model(config,messages,tool):
        assert str(tmp_path) not in json.dumps(messages)
        return {'tool_calls':[{'function':{'name':'plan_expressions','arguments':json.dumps({'switches':switches})}}]}
    monkeypatch.setattr('draft_video_tools._request',model)
    plan=tools.character_plan({**payload,'assets':[{'materialId':'neutral.png','label':'默认'},{'materialId':'smile.png','label':'微笑'}]}, {})
    assert source.read_bytes()==before
    info=tools.character_info(payload); assert len(info['tracks'])==2
    result=tools.character_save({**payload,'previewId':plan['previewId'],'videoTrackIndex':2,'segmentIndex':0})
    modified=json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    assert modified['tracks'][:2]==body['tracks'][:2]
    assert modified['materials']==body['materials']
    segments=modified['tracks'][2]['segments']
    assert [s['target_timerange'] for s in segments]==[{'start':0,'duration':2000000},{'start':2000000,'duration':2000000}]
    assert all(s['clip']==body['tracks'][2]['segments'][0]['clip'] for s in segments)
    assert source.read_bytes()==before
    with pytest.raises(ValueError):tools.character_save({**payload,'previewId':plan['previewId'],'videoTrackIndex':1,'segmentIndex':0})


@pytest.mark.parametrize('switches',[[{'cueIndex':1,'materialId':'neutral.png'}],[{'cueIndex':True,'materialId':'neutral.png'}],[{'cueIndex':0,'materialId':'invented'}],[{'cueIndex':0,'materialId':'neutral.png'},{'cueIndex':0,'materialId':'smile.png'}]])
def test_model_invalid_plans_cannot_export(draft,tmp_path,monkeypatch,switches):
    source,body,tools,payload=character_fixture(draft,tmp_path)
    monkeypatch.setattr('draft_video_tools._request',lambda *args:{'tool_calls':[{'function':{'name':'plan_expressions','arguments':json.dumps({'switches':switches})}}]})
    with pytest.raises(ValueError):tools.character_plan({**payload,'assets':[{'materialId':'neutral.png','label':'默认'}]}, {})
    assert not (tools.editor.root/'copies').exists()
