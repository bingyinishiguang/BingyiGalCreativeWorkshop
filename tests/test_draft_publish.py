import json
import shutil
import zipfile
from pathlib import Path

import pytest
from draft_publish import DraftPublisher
from tests.test_existing_draft import draft


def prepared(draft):
    source,body,editor,loaded,payload=draft
    result=editor.save({**payload,'rows':[{'cueIndex':0,'text':'新的字幕'}]})
    (Path(result['path'])/'draft_content.json.bak').write_text('stale','utf-8')
    return source,body,editor,payload,result


def test_new_draft_direct_to_selected_directory_has_own_identity(draft,tmp_path):
    source,body,editor,payload,result=prepared(draft)
    root=tmp_path/'drafts';root.mkdir()
    published=DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='new',directory=str(root),name='口播修改版')},result)
    folder=Path(published['path'])
    assert folder.parent==root and folder.name=='口播修改版' and source.exists()
    data=json.loads((folder/'draft_content.json').read_text('utf-8'))
    meta=json.loads((folder/'draft_meta_info.json').read_text('utf-8'))
    assert data['id']!=body['id'] and meta['draft_id']==data['id']
    assert meta['draft_fold_path']==str(folder) and not (folder/'draft_content.json.bak').exists()


def test_clean_overwrite_replaces_tree_and_backup_is_external(draft,tmp_path):
    source,body,editor,payload,result=prepared(draft)
    original=source.read_bytes();(source.parent/'obsolete.bin').write_bytes(b'old')
    publisher=DraftPublisher(tmp_path/'publisher',editor)
    r=publisher.publish({**payload,'publish':dict(mode='overwrite',directory=str(source.parent.parent))},result)
    assert r['overwritten'] and Path(r['path'])==source.parent
    assert not (source.parent/'obsolete.bin').exists() and not (source.parent/'draft_content.json.bak').exists()
    assert json.loads(source.read_text('utf-8'))['id']==body['id']
    with zipfile.ZipFile(r['backup']) as z:
        assert z.read('draft_content.json')==original and z.read('obsolete.bin')==b'old'
    assert not Path(r['backup']).is_relative_to(source.parent)


def test_changed_source_blocks_publication_before_modification(draft,tmp_path):
    source,body,editor,payload,result=prepared(draft)
    source.write_text('changed','utf-8')
    with pytest.raises(ValueError,match='变化'):
        DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='overwrite')},result)
    assert source.read_text('utf-8')=='changed'


def test_deferred_new_save_keeps_current_source_changes(draft,tmp_path):
    source,body,editor,payload,result=prepared(draft)
    source.write_text('changed','utf-8');root=tmp_path/'new';root.mkdir()
    r=DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='new',directory=str(root),name='新结果')},result)
    assert r['published'] and source.read_text('utf-8')=='changed'


def test_explicit_finished_result_overwrite_backs_up_latest_source(draft,tmp_path):
    source,body,editor,payload,result=prepared(draft)
    changed=dict(body,name='剪映里刚保存的版本');source.write_text(json.dumps(changed),'utf-8')
    r=DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='overwrite',replaceConfirmed=True)},result)
    with zipfile.ZipFile(r['backup']) as archive:assert json.loads(archive.read('draft_content.json'))['name']==changed['name']
    assert r['overwritten']


def test_replace_failure_restores_original_directory(draft,tmp_path,monkeypatch):
    source,body,editor,payload,result=prepared(draft);original=source.read_bytes()
    rename=Path.rename
    def blocked(path,target):
        if path.name.startswith('.bingyi-stage-'):raise PermissionError('busy')
        return rename(path,target)
    monkeypatch.setattr(Path,'rename',blocked)
    with pytest.raises(ValueError,match='原草稿已保留'):
        DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='overwrite')},result)
    assert source.read_bytes()==original and (source.parent/'keep.bin').is_file()


@pytest.mark.parametrize('name',['../x','a/b','a\\b','', '..','CON','nul.txt','LPT1','bad\x01name'])
def test_unsafe_output_names_rejected(draft,tmp_path,name):
    source,body,editor,payload,result=prepared(draft)
    with pytest.raises(ValueError):DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='new',directory=str(tmp_path),name=name)},result)


def test_cleanup_failure_reports_published_result(draft,tmp_path,monkeypatch):
    source,body,editor,payload,result=prepared(draft)
    cleanup=shutil.rmtree
    def blocked(path,*args,**kwargs):
        if Path(path).name.startswith('.bingyi-old-'):raise PermissionError('busy')
        return cleanup(path,*args,**kwargs)
    monkeypatch.setattr(shutil,'rmtree',blocked)
    r=DraftPublisher(tmp_path/'publisher',editor).publish({**payload,'publish':dict(mode='overwrite')},result)
    assert r['published'] and r['overwritten'] and r['warnings']
    assert json.loads(source.read_text('utf-8'))['id']==body['id']
    assert Path(r['backup']).is_file()
