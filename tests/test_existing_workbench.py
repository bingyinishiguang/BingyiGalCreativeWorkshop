import json
import copy
import pytest
from existing_draft import ExistingDraftEditor
import existing_draft_chat as chat
from test_existing_draft import draft


def state(payload,texts=None):
    return {'trackIndex':payload['trackIndex'],'texts':texts or ['修改第一条','第二条'],
            'manuscript':'  作者原稿。\n','mode':'auto',
            'chatHistory':[{'role':'user','text':'改第一条'}],'editLog':['手动修改第1条']}


def test_progress_survives_process_restart_and_preserves_raw_manuscript(draft):
    source,body,editor,loaded,payload=draft;raw=source.read_bytes()
    saved=editor.progress_save({**payload,'tracks':[state(payload)],'revision':None})
    restarted=ExistingDraftEditor(editor.root);loaded2=restarted.load({'path':str(source)})
    assert loaded2['progress']['tracks'][0]['texts'][0]=='修改第一条'
    assert loaded2['progress']['tracks'][0]['manuscript']=='  作者原稿。\n'
    assert loaded2['progress']['revision']==saved['revision']
    assert not loaded2['progressStale']
    assert source.read_bytes()==raw


def test_progress_source_change_and_other_window_are_detected(draft):
    source,body,editor,loaded,payload=draft
    first=editor.progress_save({**payload,'tracks':[state(payload)],'revision':None})
    with pytest.raises(ValueError,match='其他窗口'):editor.progress_save({**payload,'tracks':[state(payload)],'revision':None})
    source.write_text(json.dumps({**body,'duration':5000000}),'utf-8')
    changed=editor.load({'path':str(source)})
    assert changed['progressStale']
    with pytest.raises(ValueError,match='原草稿已变化'):editor.progress_save({**payload,'tracks':[state(payload)],'revision':first['revision']})


@pytest.mark.parametrize('broken',[b'{broken',json.dumps({'tracks':[{'trackIndex':1,'texts':[None]}],'sourceHash':'ignored','revision':'x'}).encode()])
def test_damaged_progress_never_breaks_load_and_is_backed_up(draft,broken):
    source,_,editor,_,payload=draft
    path=editor.progress_path(editor.sessions[payload['sessionId']]);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(broken)
    loaded=editor.load({'path':str(source)})
    assert loaded['progress'] is None and '损坏' in loaded['progressIssue']
    assert path.read_bytes()==broken
    editor.progress_save({**payload,'sessionId':loaded['sessionId'],'revision':None,'tracks':[state(payload)]})
    backups=list(path.parent.glob('*.damaged-*.json'))
    assert len(backups)==1 and backups[0].read_bytes()==broken
    assert editor.load({'path':str(source)})['progress']['tracks'][0]['texts'][0]=='修改第一条'


def test_conflicted_backup_does_not_overwrite_progress_and_keeps_incomplete_text(draft):
    source,_,editor,_,payload=draft
    editor.progress_save({**payload,'tracks':[state(payload)],'revision':None})
    progress=editor.progress_path(editor.sessions[payload['sessionId']]).read_bytes()
    saved=editor.progress_backup({**payload,'tracks':[{**state(payload),'texts':['','另一窗口修改']}],'path':'C:/not-allowed'})
    from pathlib import Path
    backup=Path(saved['path'])
    assert backup.is_relative_to(editor.root/'recovery-backups')
    assert json.loads(backup.read_bytes())['tracks'][0]['texts'][0]==''
    assert editor.progress_path(editor.sessions[payload['sessionId']]).read_bytes()==progress
    editor.sessions.clear()
    assert editor.progress_backup({**payload,'tracks':[state(payload)]})['path']


@pytest.mark.parametrize('invalid',[{'trackIndex':True},{'texts':[None]},{'texts':['x'*2001]},
    {'mode':'unknown'},{'chatHistory':[{'role':'system','text':'bad'}]},{'stylePatch':{'size':999}}])
def test_backup_rejects_invalid_shapes(draft,invalid):
    _,_,editor,_,payload=draft
    with pytest.raises(ValueError):editor.progress_backup({**payload,'tracks':[{**state(payload),**invalid}]})
    assert not (editor.root/'recovery-backups').exists()


@pytest.mark.parametrize('invalid',[
    {'texts':['only one']},{'texts':['', 'b']},{'texts':['a','b'],'mode':'unknown'},
    {'chatHistory':[{'role':'system','text':'execute code'}]}, {'editLog':[{}]}, {'manuscript':'a'*100001}])
def test_progress_rejects_malformed_content(draft,invalid):
    _,_,editor,_,payload=draft
    with pytest.raises(ValueError):editor.progress_save({**payload,'tracks':[{**state(payload),**invalid}],'revision':None})


def tool(name,args):
    return {'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


def mock_reply(monkeypatch,calls,content=None):
    observed=[]
    def reply(config,messages,tools):
        observed.append(messages)
        return {'content':content,'tool_calls':calls}
    monkeypatch.setattr(chat,'_request',reply)
    return observed


def test_chat_batch_replace_is_preview_only_and_omits_local_paths(draft,monkeypatch):
    source,body,editor,_,payload=draft;before=source.read_bytes()
    observed=mock_reply(monkeypatch,[tool('replace_text',{'find':'条','replacement':'段'})])
    result=editor.chat({**payload,'message':'条改成段','manuscript':'原稿。'}, {'apiKey':'secret'})
    assert result['changes'][0]['after']=='第一段，保留逗号'
    assert 'original' not in json.dumps(observed)
    assert 'secret' not in json.dumps(observed)
    assert source.read_bytes()==before
    assert not (editor.root/'copies').exists()


def test_chat_multiple_edits_keep_indices_and_timing(draft,monkeypatch):
    _,_,editor,_,payload=draft
    mock_reply(monkeypatch,[tool('edit_captions',{'edits':[{'cueIndex':1,'text':'纠正文字。'}]})])
    result=editor.chat({**payload,'message':'改第二条'}, {})
    assert result['changes']==[{'cueIndex':1,'before':'第二条。','after':'纠正文字'}]
    assert 'start' not in result['changes'][0]


def test_chat_exact_replacement_does_not_touch_unmatched_captions(draft,monkeypatch):
    _,_,editor,_,payload=draft
    mock_reply(monkeypatch,[tool('replace_text',{'find':'第二','replacement':'第贰'})])
    result=editor.chat({**payload,'message':'仅改第二条'}, {})
    assert result['changes']==[{'cueIndex':1,'before':'第二条。','after':'第贰条'}]


@pytest.mark.parametrize('calls',[
    [tool('run_python',{'code':'bad'})], [tool('edit_captions',{'edits':[{'cueIndex':True,'text':'a'}]})],
    [tool('edit_captions',{'edits':[{'cueIndex':9,'text':'a'}]})],
    [tool('edit_captions',{'edits':[{'cueIndex':0,'text':'a','start':5}]})],
    [tool('edit_captions',{'edits':[{'cueIndex':0,'text':'a'},{'cueIndex':0,'text':'b'}]})],
    [tool('replace_text',{'find':'第二条。','replacement':''})],
])
def test_invalid_model_suggestions_are_rejected_without_writes(draft,monkeypatch,calls):
    source,_,editor,_,payload=draft;before=source.read_bytes();mock_reply(monkeypatch,calls)
    with pytest.raises(ValueError):editor.chat({**payload,'message':'修正'}, {})
    assert source.read_bytes()==before


def test_manuscript_tool_does_not_auto_choose_ambiguous_lines(draft,monkeypatch):
    _,_,editor,_,payload=draft
    mock_reply(monkeypatch,[tool('compare_manuscript',{})])
    result=editor.chat({**payload,'message':'校对','texts':['再见','再见'],'manuscript':'再见。再见。'}, {})
    assert result['changes']==[] and result['warnings']
