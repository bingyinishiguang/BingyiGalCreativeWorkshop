import copy
import json
from pathlib import Path

import pytest

from test_existing_draft import draft
from test_existing_workbench import tool, mock_reply, state
import draft_subtitle_style as styles
from existing_draft import ExistingDraftEditor


@pytest.fixture
def styled_draft(draft, tmp_path):
    source, body, editor, _, payload = draft
    font = tmp_path/'测试字体.ttf';font.write_bytes(b'font placeholder for file availability')
    for i, item in enumerate(body['materials']['texts']):
        content=json.loads(item['content'])
        content['styles'][0].update(fill={'content':{'solid':{'color':[1,1,1]}}},
            strokes=[{'content':{'solid':{'color':[0,0,0]}},'width':.08}],
            font={'id':'font-existing','path':str(font)},bold=True)
        item['content']=json.dumps(content)
        item.update(font_size=8,text_color='#ffffff',border_color='#000000',border_width=.08,
                    font_path=str(font),font_resource_id='font-existing',fonts=[{'path':str(font),'title':'测试字体'}])
    for seg in body['tracks'][1]['segments']:
        seg.update(clip={'transform':{'x':0,'y':-.73},'scale':{'x':1.2,'y':1.2},'rotation':5},
                   common_keyframes=[],keyframe_refs=[])
    source.write_text(json.dumps(body),'utf-8')
    loaded=editor.load({'path':str(source)})
    return source,body,editor,loaded,{**payload,'sessionId':loaded['sessionId']}


def test_style_preview_and_export_preserve_every_other_field(styled_draft):
    source,body,editor,_,payload=styled_draft;raw=source.read_bytes()
    patch={'size':6,'color':'#ffee33','borderColor':'#112233','borderWidth':.1,'x':.2,'y':-.6}
    preview=editor.style_preview({**payload,'stylePatch':patch})
    assert len(preview['styleChanges'])==2
    assert source.read_bytes()==raw and not (editor.root/'copies').exists()
    result=editor.save({**payload,'stylePatch':patch,'normalize':False})
    changed=json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    assert result['styledCount']==2 and result['changedCount']==0
    assert changed['tracks'][0]==body['tracks'][0]
    assert changed['materials']['videos']==body['materials']['videos']
    for a,b in zip(body['tracks'][1]['segments'],changed['tracks'][1]['segments']):
        assert a['target_timerange']==b['target_timerange']
        assert b['clip']['transform']=={'x':.2,'y':-.6}
        assert b['clip']['scale']==a['clip']['scale'] and b['clip']['rotation']==5
    for a,b in zip(body['materials']['texts'],changed['materials']['texts']):
        old,new=json.loads(a['content']),json.loads(b['content'])
        assert new['text']==old['text']
        assert new['styles'][0]['range']==old['styles'][0]['range']
        assert new['styles'][0]['font']==old['styles'][0]['font']
        assert new['styles'][0]['bold'] is True
        assert new['styles'][0]['fill']['content']['solid']['color']==styles.rgb('#ffee33')
        assert b['words']==a['words']
    record=json.loads((Path(result['path'])/'字幕修改记录.json').read_bytes())
    assert record['stylePatch']==patch and len(record['styleChanges'])==2
    assert source.read_bytes()==raw


def test_reset_preview_returns_original_style(styled_draft):
    _,_,editor,_,payload=styled_draft
    result=editor.style_preview({**payload,'currentStylePatch':{'size':6},'stylePatch':{}})
    assert result['stylePatch']=={}
    assert result['styleChanges'][0]['before']['size']==6
    assert result['styleChanges'][0]['after']['size']==8


@pytest.mark.parametrize('patch',[{'size':True},{'size':float('nan')},{'size':51},{'size':1},
    {'color':'red'},{'borderWidth':.31},{'x':1.01},{'font_path':'C:/fake.ttf'},
    {'shadow':True},{'fontId':'made-up'},{'size':None},{'y':float('inf')}])
def test_invalid_style_never_writes_copy(styled_draft,patch):
    source,_,editor,_,payload=styled_draft;before=source.read_bytes()
    with pytest.raises(ValueError):editor.style_preview({**payload,'stylePatch':patch})
    with pytest.raises(ValueError):editor.save({**payload,'stylePatch':patch})
    assert source.read_bytes()==before and not (editor.root/'copies').exists()


def test_position_with_keyframes_is_rejected_but_size_allowed(styled_draft):
    source,body,editor,_,payload=styled_draft
    body['tracks'][1]['segments'][0]['common_keyframes']=[{'property':'position_y','values':[-.7,-.5]}]
    source.write_text(json.dumps(body),'utf-8');loaded=editor.load({'path':str(source)})
    p={**payload,'sessionId':loaded['sessionId']}
    with pytest.raises(ValueError,match='关键帧'):editor.style_preview({**p,'stylePatch':{'y':-.5}})
    result=editor.save({**p,'stylePatch':{'size':6},'normalize':False})
    data=json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    assert data['tracks']==body['tracks']


def test_complex_fill_is_preserved_when_not_requested(styled_draft):
    source,body,editor,_,payload=styled_draft
    content=json.loads(body['materials']['texts'][0]['content'])
    content['styles'][0]['fill']={'content':{'gradient':{'stops':[1,2]}}}
    content['styles'][0]['strokes'].append(copy.deepcopy(content['styles'][0]['strokes'][0]))
    body['materials']['texts'][0]['content']=json.dumps(content)
    source.write_text(json.dumps(body),'utf-8');loaded=editor.load({'path':str(source)})
    p={**payload,'sessionId':loaded['sessionId']}
    with pytest.raises(ValueError,match='渐变'):editor.style_preview({**p,'stylePatch':{'color':'#ffffff'}})
    with pytest.raises(ValueError,match='多层'):editor.style_preview({**p,'stylePatch':{'borderWidth':.1}})
    result=editor.save({**p,'stylePatch':{'size':6},'normalize':False})
    changed=json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    style=json.loads(changed['materials']['texts'][0]['content'])['styles'][0]
    assert style['fill']==content['styles'][0]['fill'] and style['strokes']==content['styles'][0]['strokes']


def test_style_progress_and_preset_survive_restart(styled_draft):
    source,_,editor,_,payload=styled_draft
    info=editor.style_info(payload);font=info['fonts'][0]
    patch={'size':6,'fontId':font['id']}
    saved=editor.preset_save({**payload,'name':'栏目字幕','stylePatch':patch})
    progress=editor.progress_save({**payload,'revision':None,'tracks':[{**state(payload),'stylePatch':patch}]})
    fresh=ExistingDraftEditor(editor.root);loaded=fresh.load({'path':str(source)})
    assert loaded['progress']['tracks'][0]['stylePatch']==patch
    assert loaded['progress']['revision']==progress['revision']
    info2=fresh.style_info({'sessionId':loaded['sessionId'],'trackIndex':1})
    assert info2['presets']==[{'id':saved['id'],'name':'栏目字幕','stylePatch':patch}]
    assert 'path' not in json.dumps(info2['fonts'])
    with pytest.raises(ValueError,match='同名'):fresh.preset_save({'sessionId':loaded['sessionId'],'trackIndex':1,'name':'栏目字幕','stylePatch':patch})


def test_preset_font_is_available_in_other_draft_and_checks_file(styled_draft,tmp_path):
    source,body,editor,_,payload=styled_draft
    info=editor.style_info(payload);font_id=info['fonts'][0]['id']
    editor.preset_save({**payload,'name':'复用字体','stylePatch':{'fontId':font_id}})
    other=tmp_path/'other';other.mkdir()
    for item in body['materials']['texts']:
        content=json.loads(item['content']);content['styles'][0].pop('font')
        item['content']=json.dumps(content)
        for k in styles.FONT_FIELDS:item.pop(k,None)
    (other/'draft_content.json').write_text(json.dumps(body),'utf-8')
    loaded=editor.load({'path':str(other)});p={'sessionId':loaded['sessionId'],'trackIndex':1}
    result=editor.save({**p,'stylePatch':{'fontId':font_id},'normalize':False})
    changed=json.loads((Path(result['path'])/'draft_content.json').read_bytes())
    path=json.loads(changed['materials']['texts'][0]['content'])['styles'][0]['font']['path']
    Path(path).unlink()
    with pytest.raises(ValueError,match='字体文件不可用'):editor.style_preview({**p,'stylePatch':{'fontId':font_id}})
    # Missing fonts can still be inspected and reset; export remains protected.
    info=editor.style_info({**p,'stylePatch':{'fontId':font_id}},allow_missing_font=True)
    assert not info['fonts'][0]['available']
    reset=editor.style_preview({**p,'currentStylePatch':{'fontId':font_id},'stylePatch':{}})
    assert reset['styleChanges']


def test_unknown_native_style_does_not_block_caption_chat(styled_draft,monkeypatch):
    source,body,editor,_,payload=styled_draft
    content=json.loads(body['materials']['texts'][0]['content']);content['styles']=None
    body['materials']['texts'][0]['content']=json.dumps(content)
    source.write_text(json.dumps(body),'utf-8');loaded=editor.load({'path':str(source)})
    p={**payload,'sessionId':loaded['sessionId']}
    mock_reply(monkeypatch,[tool('edit_captions',{'edits':[{'cueIndex':1,'text':'只改第二条'}]})])
    assert editor.chat({**p,'message':'改第二条'}, {})['changes'][0]['after']=='只改第二条'
    with pytest.raises(ValueError,match='样式结构'):editor.style_preview({**p,'stylePatch':{'size':6}})


def test_chat_style_is_preview_only_and_validated(styled_draft,monkeypatch):
    source,_,editor,_,payload=styled_draft;raw=source.read_bytes()
    observed=mock_reply(monkeypatch,[tool('set_caption_style',{'style':{'size':6,'color':'#ffffff','borderWidth':.08}})])
    result=editor.chat({**payload,'message':'字号6白字黑边'}, {})
    assert result['changes']==[] and len(result['styleChanges'])==2
    assert result['stylePatch']['size']==6 and source.read_bytes()==raw
    assert str(source.parent) not in json.dumps(observed)
    assert '测试字体.ttf' not in json.dumps(observed,ensure_ascii=False)  # only font label, no path
    assert not (editor.root/'copies').exists()


@pytest.mark.parametrize('call',[tool('set_caption_style',{'style':{'size':999}}),
    tool('set_caption_style',{'style':{'fontId':'f'*64}}),tool('set_caption_style',{'style':{}}),
    tool('apply_style_preset',{'presetId':'invented'})])
def test_chat_rejects_invented_or_invalid_style(styled_draft,monkeypatch,call):
    _,_,editor,_,payload=styled_draft;mock_reply(monkeypatch,[call])
    with pytest.raises(ValueError):editor.chat({**payload,'message':'调整样式'}, {})


def test_chat_preset_merges_only_its_fields(styled_draft,monkeypatch):
    _,_,editor,_,payload=styled_draft
    saved=editor.preset_save({**payload,'name':'节目字号','stylePatch':{'size':6}})
    mock_reply(monkeypatch,[tool('apply_style_preset',{'presetId':saved['id']})])
    result=editor.chat({**payload,'message':'套用节目字号','stylePatch':{'color':'#ffff00'}}, {})
    assert result['stylePatch']=={'color':'#ffff00','size':6}


def test_identical_fonts_with_different_native_metadata_are_one_choice(styled_draft):
    source,body,editor,_,payload=styled_draft
    for i,item in enumerate(body['materials']['texts']):item['fonts'][0]['id']=f'per-material-font-{i}'
    source.write_text(json.dumps(body),'utf-8');loaded=editor.load({'path':str(source)})
    p={**payload,'sessionId':loaded['sessionId']}
    info=editor.style_info(p)
    assert len(info['fonts'])==1
    assert info['styles'][0]['fontId']==info['styles'][1]['fontId']
    assert editor.style_preview({**p,'stylePatch':{'fontId':info['fonts'][0]['id']}})['styleChanges']==[]
