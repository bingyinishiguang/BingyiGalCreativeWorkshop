"""Verified publication to a draft directory, with recoverable clean replacement."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path


def snapshot(directory):
    result={}
    for path in directory.rglob('*'):
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
            raise ValueError('草稿中存在链接目录，不能干净覆盖')
        if path.is_file():
            result[str(path.relative_to(directory))]=(path.stat().st_size,path.stat().st_mtime_ns)
    return result


def safe_name(value):
    if not isinstance(value,str) or not value.strip() or len(value)>100 or value in ('.','..') or any(c in value for c in '\\/:*?"<>|') or any(ord(c)<32 for c in value) or value.rstrip(' .')!=value or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',value,re.I):
        raise ValueError('草稿名称不能为空或含有路径字符')
    return value


class DraftPublisher:
    def __init__(self, root, editor):
        self.root=Path(root).resolve();self.editor=editor
        self.root.mkdir(parents=True,exist_ok=True)

    def options(self,payload):
        source=self.editor.sessions.get(payload.get('sessionId'))
        path=self.root/'options.json'
        try:saved=json.loads(path.read_text('utf-8')) if path.is_file() else {}
        except (ValueError,OSError):saved={}
        if not isinstance(saved,dict):saved={}
        return dict(directory=saved.get('directory') or str(source['source'].parent.parent) if source else saved.get('directory',''))

    def read_json(self,path,session,work):
        try:return json.loads(path.read_bytes()),False
        except (ValueError,UnicodeError):
            decoded=work/(path.name+'.decoded')
            self.editor.codec('dec',path,decoded,session['install'],session['python'])
            return json.loads(decoded.read_bytes()),True

    def write_json(self,path,value,encrypted,session,work):
        temporary=work/(path.name+'.plain')
        temporary.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),'utf-8')
        if encrypted:
            self.editor.codec('enc',temporary,path,session['install'],session['python'])
            decoded=work/(path.name+'.check')
            self.editor.codec('dec',path,decoded,session['install'],session['python'])
            if json.loads(decoded.read_bytes())!=value:
                raise ValueError('发布草稿加密校验失败')
        else:shutil.copy2(temporary,path)

    def publish(self,payload,result):
        choice=payload.get('publish')
        if not choice:return result
        if not isinstance(choice,dict) or choice.get('mode') not in ('new','overwrite'):
            raise ValueError('请选择新建草稿或干净覆盖当前草稿')
        session=self.editor.sessions.get(payload.get('sessionId'))
        if not session:
            raise ValueError('草稿会话已失效')
        source=session['source'].resolve();original=source.parent
        replacing=choice['mode']=='overwrite'
        expected_digest=hashlib.sha256(source.read_bytes()).hexdigest() if replacing and choice.get('replaceConfirmed') is True else session['digest']
        if replacing and hashlib.sha256(source.read_bytes()).hexdigest()!=expected_digest:
            raise ValueError('原草稿已变化，请重新载入后再保存')
        root=Path(choice.get('directory') or original.parent).resolve()
        if not root.is_dir() or root==Path(root.anchor) or root==original or root.is_relative_to(original):
            raise ValueError('请选择剪映草稿根目录，不能选择草稿自身或磁盘根目录')
        if root.is_symlink() or getattr(root,'is_junction',lambda:False)():
            raise ValueError('草稿输出目录不能是链接目录')
        replacing=choice['mode']=='overwrite'
        if replacing and root!=original.parent:
            raise ValueError('干净覆盖须使用当前草稿所在的根目录')
        name=original.name if replacing else safe_name(choice.get('name',original.name+'·修改版'))
        target=(root/name).resolve();target.relative_to(root)
        if target.parent!=root:raise ValueError('草稿目标必须直接位于选定根目录下')
        if not replacing:
            index=2
            while target.exists():
                target=root/f'{name}-{index}';index+=1
                if index>1000:raise ValueError('同名草稿过多，请修改名称')
            name=target.name
        elif target!=original:
            raise ValueError('只能干净覆盖本次载入的草稿目录')
        prepared=Path(result['path']).resolve()
        if not prepared.is_relative_to(self.editor.root) or prepared==original or not (prepared/'draft_content.json').is_file():
            raise ValueError('待发布草稿不是已校验的工作台输出')
        before=snapshot(original) if replacing else None
        operation=uuid.uuid4().hex
        stage=(root/('.bingyi-stage-'+operation)).resolve();stage.relative_to(root)
        quarantine=(root/('.bingyi-old-'+operation)).resolve();quarantine.relative_to(root)
        work=self.root/'operations'/operation;work.mkdir(parents=True)
        backup=None;warnings=[]
        try:
            shutil.copytree(prepared,stage)
            data,encrypted=self.read_json(stage/'draft_content.json',session,work)
            meta_file=stage/'draft_meta_info.json'
            meta,meta_encrypted=self.read_json(meta_file,session,work) if meta_file.is_file() else ({},False)
            ident=meta.get('draft_id') or data.get('id') or str(uuid.uuid4()).upper()
            if not replacing:ident=str(uuid.uuid4()).upper()
            data['id']=ident
            if 'name' in data:data['name']=name
            # Package assets owned by the editor or the replaced source directory.
            assets=stage/'素材'
            for group,items in data.get('materials',{}).items():
                if not isinstance(items,list):continue
                for material in items:
                    if not isinstance(material,dict) or not material.get('path'):continue
                    path=Path(material['path'])
                    if not path.is_absolute():path=original/path
                    path=path.resolve()
                    if path.is_relative_to(original):
                        captured=prepared/path.relative_to(original)
                        if captured.is_file():path=captured
                    if (path.is_relative_to(self.root.parent) or path.is_relative_to(original) or path.is_relative_to(prepared)) and path.is_file():
                        assets.mkdir(exist_ok=True)
                        filename=uuid.uuid4().hex[:8]+'-'+path.name
                        shutil.copy2(path,assets/filename)
                        material['path']=str(target/'素材'/filename)
            now=int(time.time()*1000000)
            meta.update(draft_id=ident,draft_name=name,draft_fold_path=str(target),draft_root_path=str(root),tm_draft_modified=now,tm_duration=data.get('duration',0))
            if not replacing:meta['tm_draft_create']=now
            self.write_json(stage/'draft_content.json',data,encrypted,session,work)
            self.write_json(meta_file,meta,meta_encrypted,session,work)
            # Old autosave copies can resurrect obsolete tracks; the published tree is clean.
            for filename in ('draft_content.json.bak','template.tmp','template-2.tmp','draft_content.json.tmp','保存未通过.txt'):
                stale=stage/filename
                if stale.is_file():stale.unlink()
            native_files={'draft_content.json','draft_meta_info.json','draft_cover.jpg','draft_settings','draft.extra','key_value.json','attachment_pc_common.json','draft_agency_config.json','draft_biz_config.json','draft_virtual_store.json'}
            for path in stage.iterdir():
                inherited=original/path.name
                if path.is_file() and path.name not in native_files and inherited.is_file() and path.read_bytes()==inherited.read_bytes():
                    path.unlink()
            if replacing and (snapshot(original)!=before or hashlib.sha256(source.read_bytes()).hexdigest()!=expected_digest):
                raise ValueError('准备发布期间原草稿变化，请在剪映保存并关闭当前草稿后重试')
            if replacing:
                self.assert_unlocked(original)
                backup=self.root/'backups'/(original.name+'-'+operation+'.zip');backup.parent.mkdir(exist_ok=True)
                with zipfile.ZipFile(backup,'w',zipfile.ZIP_DEFLATED) as archive:
                    for path in original.rglob('*'):
                        if path.is_file() or path.is_dir():archive.write(path,str(path.relative_to(original)))
                with zipfile.ZipFile(backup) as archive:
                    if archive.testzip():raise ValueError('原草稿备份校验失败')
                if snapshot(original)!=before:raise ValueError('备份期间原草稿变化，请关闭剪映当前草稿后重试')
                original.rename(quarantine)
            try:stage.rename(target)
            except OSError:
                if replacing and quarantine.exists() and not original.exists():quarantine.rename(original)
                raise ValueError('草稿目录被占用，发布未完成，原草稿已保留') from None
            if quarantine.exists():
                quarantine.resolve().relative_to(root)
                if quarantine.parent!=root or quarantine.name!='.bingyi-old-'+operation:
                    raise ValueError('旧目录清理范围校验失败')
                try:shutil.rmtree(quarantine)
                except OSError:warnings.append('新草稿已保存，旧目录暂被占用，保留在 '+str(quarantine))
            try:(self.root/'options.json').write_text(json.dumps(dict(directory=str(root)),ensure_ascii=False),'utf-8')
            except OSError:warnings.append('草稿已保存，但未能记住输出目录')
            return {**result,'path':str(target),'sourceUnchanged':not replacing,'published':True,'overwritten':replacing,'backup':str(backup) if backup else None,'draftName':name,'warnings':warnings}
        except PermissionError:
            if replacing and quarantine.exists() and not original.exists():quarantine.rename(original)
            raise ValueError('剪映草稿被占用，请保存并关闭该草稿后重试') from None
        finally:
            if stage.exists():
                stage.resolve().relative_to(root)
                if stage.parent==root and stage.name=='.bingyi-stage-'+operation:shutil.rmtree(stage)

    @staticmethod
    def assert_unlocked(directory):
        if os.name!='nt':return
        import ctypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        api.CreateFileW.restype=ctypes.c_void_p;api.CloseHandle.argtypes=[ctypes.c_void_p]
        for path in directory.rglob('*'):
            if not path.is_file():continue
            handle=api.CreateFileW(str(path),0x40000000,0,None,3,0,None)
            if handle==ctypes.c_void_p(-1).value:
                raise ValueError('原草稿文件被占用，请保存并关闭剪映中的该草稿后重试')
            api.CloseHandle(handle)
