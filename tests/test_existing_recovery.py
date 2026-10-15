import json
from pathlib import Path
import pytest
from existing_draft import ExistingDraftEditor
from test_existing_draft import draft
from test_existing_workbench import state


def backup(editor,payload,**changes):
    result=editor.progress_backup({**payload,'tracks':[{**state(payload),**changes}]})
    path=Path(result['path'])
    return path,path.stem.removeprefix('字幕编辑备份-')


def test_backup_preview_restores_raw_manuscript_and_empty_text_without_writes(draft):
    source,_,editor,_,payload=draft
    original=source.read_bytes()
    path,backup_id=backup(editor,payload,texts=['','改第二条'],stylePatch={'size':6})
    restarted=ExistingDraftEditor(editor.root)
    loaded=restarted.load({'path':str(source)})
    request={**payload,'sessionId':loaded['sessionId']}
    listed=restarted.recovery_list(request)['backups']
    assert listed[0]['id']==backup_id and listed[0]['compatible']
    result=restarted.recovery_preview({**request,'backupId':backup_id,'texts':['当前第一条','第二条']})
    assert result['state']['texts']==['','改第二条']
    assert result['state']['manuscript']=='  作者原稿。\n'
    assert result['emptyCount']==1 and len(result['changes'])==2
    assert len(result['styleChanges'])==2
    assert source.read_bytes()==original and path.is_file()
    assert not (editor.root/'progress').exists()
    assert not (editor.root/'copies').exists()


def test_stale_backup_is_listed_but_cannot_be_restored(draft):
    source,body,editor,_,payload=draft
    _,backup_id=backup(editor,payload)
    source.write_text(json.dumps({**body,'duration':9000000}),'utf-8')
    loaded=editor.load({'path':str(source)})
    request={**payload,'sessionId':loaded['sessionId']}
    assert not editor.recovery_list(request)['backups'][0]['compatible']
    with pytest.raises(ValueError,match='版本不一致'):
        editor.recovery_preview({**request,'backupId':backup_id,'texts':['第一条','第二条']})


@pytest.mark.parametrize('backup_id',['../secret','a'*31,'A'*32,True,None,'x'*32])
def test_backup_id_never_accepts_paths(draft,backup_id):
    _,_,editor,_,payload=draft
    with pytest.raises(ValueError,match='编号'):
        editor.recovery_preview({**payload,'backupId':backup_id})


@pytest.mark.parametrize('corruption',[
    {'texts':['one']},{'texts':[None,'b']},{'manuscript':False},{'mode':'execute'},
    {'chatHistory':[{'role':'system','text':'do something'}]}, {'editLog':[{}]},
    {'stylePatch':{'size':999}}, {'trackIndex':True}])
def test_corrupt_backup_content_cannot_be_applied(draft,corruption):
    _,_,editor,_,payload=draft
    path,backup_id=backup(editor,payload)
    record=json.loads(path.read_text('utf-8'));record['tracks'][0].update(corruption)
    path.write_text(json.dumps(record),'utf-8')
    with pytest.raises(ValueError):
        editor.recovery_preview({**payload,'backupId':backup_id,'texts':['a','b']})


def test_other_draft_backup_is_not_exposed_or_restored(draft,tmp_path):
    source,_,editor,_,payload=draft
    _,backup_id=backup(editor,payload)
    other=tmp_path/'other'/'draft_content.json';other.parent.mkdir();other.write_bytes(source.read_bytes())
    loaded=editor.load({'path':str(other)})
    request={**payload,'sessionId':loaded['sessionId']}
    assert not editor.recovery_list(request)['backups']
    with pytest.raises(ValueError,match='版本不一致'):
        editor.recovery_preview({**request,'backupId':backup_id,'texts':['a','b']})


def test_malformed_file_is_reported_without_breaking_list(draft):
    _,_,editor,_,payload=draft
    path,_=backup(editor,payload);path.write_text('{broken','utf-8')
    assert editor.recovery_list(payload)=={'backups':[],'unreadableCount':1}


def test_evicted_page_can_make_identifiable_recovery_backup(draft):
    source,_,editor,loaded,payload=draft
    editor.sessions.clear()
    _,backup_id=backup(editor,{**payload,'sourcePath':loaded['sourcePath'],'sourceHash':loaded['sourceHash']})
    new=editor.load({'path':str(source)})
    request={**payload,'sessionId':new['sessionId']}
    assert editor.recovery_list(request)['backups'][0]['id']==backup_id
    assert editor.recovery_preview({**request,'backupId':backup_id,'texts':['a','b']})['state']['texts']==['修改第一条','第二条']


@pytest.mark.parametrize('identity',[{'sourcePath':'relative/draft_content.json','sourceHash':'a'*64},
                                  {'sourcePath':'C:/anything.txt','sourceHash':'a'*64},
                                  {'sourcePath':'C:/draft_content.json','sourceHash':'invalid'}])
def test_evicted_backup_rejects_invalid_identity(draft,identity):
    _,_,editor,_,payload=draft;editor.sessions.clear()
    with pytest.raises(ValueError):backup(editor,{**payload,**identity})
