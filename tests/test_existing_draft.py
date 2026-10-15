import copy
import hashlib
import json
from pathlib import Path
import pytest
from existing_draft import ExistingDraftEditor
from tools.inspect_jianying_draft import remap_styles, file_status


@pytest.fixture
def draft(tmp_path):
    root=tmp_path/'original';root.mkdir()
    body={'id':'original-id','duration':4000000,'tracks':[
        {'type':'video','segments':[{'material_id':'bg','target_timerange':{'start':0,'duration':4000000}}]},
        {'type':'text','name':'中文字幕','segments':[{'material_id':'a','target_timerange':{'start':1000000,'duration':1000000}},
            {'material_id':'b','target_timerange':{'start':2000000,'duration':1000000}}]}],
        'materials':{'texts':[{'id':i,'content':json.dumps({'text':t,'styles':[{'range':[0,len(t)],'size':8}]}),'words':{'text':['old']}}
                              for i,t in [('a','第一条，保留逗号。'),('b','第二条。')]],'videos':[{'id':'bg','path':'missing.png'}]}}
    source=root/'draft_content.json';source.write_text(json.dumps(body),'utf-8')
    (root/'keep.bin').write_bytes(b'preserve resource')
    editor=ExistingDraftEditor(tmp_path/'edits');loaded=editor.load({'path':str(root)})
    payload={'sessionId':loaded['sessionId'],'trackIndex':1}
    return source,body,editor,loaded,payload


def test_plain_copy_preserves_tracks_resources_and_source(draft):
    source,body,editor,loaded,payload=draft;original=source.read_bytes()
    result=editor.save({**payload,'rows':[{'cueIndex':1,'text':'纠正第二条。'}],'manuscript':'原稿。'})
    folder=Path(result['path']);changed=json.loads((folder/'draft_content.json').read_bytes())
    assert changed['tracks']==body['tracks']
    assert changed['materials']['videos']==body['materials']['videos']
    assert json.loads(changed['materials']['texts'][1]['content'])['text']=='纠正第二条'
    assert (folder/'keep.bin').read_bytes()==b'preserve resource'
    assert source.read_bytes()==original
    assert result['sourceUnchanged'] and result['roundTripVerified']
    assert result['changedCount']==2
    assert '00:00:02,000' in (folder/'修改后字幕.srt').read_text('utf-8-sig')
    assert editor.preview({**payload,'manuscript':'第一条，保留逗号。\n第二条。','mode':'lines'})['matchedCount']==2


def test_changed_source_blocks_save(draft):
    source,body,editor,loaded,payload=draft;source.write_text('{}','utf-8')
    with pytest.raises(ValueError,match='原草稿已变化'):editor.save(payload)
    assert not (editor.root/'copies').exists()


def test_shared_text_does_not_modify_other_track(draft):
    source,body,editor,loaded,payload=draft
    body['tracks'].append({'type':'text','segments':[body['tracks'][1]['segments'][0]]})
    source.write_text(json.dumps(body),'utf-8');loaded=editor.load({'path':str(source)})
    with pytest.raises(ValueError,match='共用素材'):editor.save({**payload,'sessionId':loaded['sessionId']})


@pytest.mark.parametrize('rows',[[{'cueIndex':True,'text':'a'}],[{'cueIndex':0,'text':'。'}],
    [{'cueIndex':9,'text':'a'}],[{'cueIndex':0,'text':'a'},{'cueIndex':0,'text':'b'}]])
def test_invalid_edits_cannot_write_copy(draft,rows):
    source,body,editor,loaded,payload=draft
    with pytest.raises(ValueError):editor.save({**payload,'rows':rows})
    assert not (editor.root/'copies').exists()


def test_style_ranges_follow_character_deletion():
    content={'styles':[{'range':[0,3]},{'range':[3,3]}]}
    remap_styles(content,'甲乙，丙丁。','甲乙，丙丁')
    assert content['styles']==[{'range':[0,3]},{'range':[3,2]}]
    with pytest.raises(ValueError):remap_styles({'styles':[{'range':[0,99]}]},'a','b')


def test_multiline_cue_normalization_uses_segments_not_lines(draft):
    _,_,editor,_,payload=draft
    result=editor.normalize({**payload,'texts':['第一行，\n第二行。','独立第二条。']})
    assert len(result['cues'])==2
    assert result['cues'][0]['text']=='第一行，\n第二行'
    assert result['cues'][0]['start']==1
    with pytest.raises(ValueError):editor.normalize({**payload,'texts':['wrong count']})


def test_unreadable_asset_is_not_reported_missing(monkeypatch):
    def denied(self):raise PermissionError('denied')
    monkeypatch.setattr(Path,'is_file',denied)
    assert file_status('fake')=='unreadable'
