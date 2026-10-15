"""Caption-only edits of existing drafts, saved as independent workspace copies."""
from __future__ import annotations
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import app_paths
from manuscript_review import compare
from subtitle_tools import format_subtitle
from tools.inspect_jianying_draft import remap_styles
import draft_subtitle_style as subtitle_style


class ExistingDraftEditor:
    def __init__(self, root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.sessions={};self.lock=threading.RLock()

    def codec(self, operation, source, target, install, python):
        worker=app_paths.resource_root()/'draft_codec_worker.py'
        if not install or not (Path(install)/'videoeditor.dll').is_file():
            raise ValueError('请展开加密草稿适配设置，填写包含 videoeditor.dll 的剪映安装目录')
        if not python:
            command = ([sys.executable, '--draft-codec-worker'] if getattr(sys,'frozen',False)
                       else [sys.executable, str(worker)])
        else:
            command = [python, str(worker)]
        result=subprocess.run([*command,operation,install,str(source),str(target)],capture_output=True,timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        if result.returncode or not target.is_file():raise ValueError('编解码失败：请核对剪映版本、安装目录和 Python；目前已验证 7.2.2.53989')

    def load(self, payload):
        source=Path(payload.get('path','')).resolve()
        if source.is_dir():source=source/'draft_content.json'
        if source.name!='draft_content.json' or not source.is_file():raise ValueError('请选择草稿目录或 draft_content.json')
        if source.is_relative_to(self.root):raise ValueError('请选择原草稿，不能把输出目录作为输入')
        if source.stat().st_size>50_000_000:raise ValueError('草稿超过 50 MB')
        install=str(payload.get('installPath','')).strip();python=str(payload.get('pythonPath','')).strip()
        raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest();sid=uuid.uuid4().hex
        work=self.root/'sessions'/sid;work.mkdir(parents=True)
        try:
            data=json.loads(raw);encrypted=False
        except (UnicodeError,ValueError):
            # The native codec never receives the writable original path.
            src=work/'input.encrypted';src.write_bytes(raw);decoded=work/'decoded.json'
            self.codec('dec',src,decoded,install,python);data=json.loads(decoded.read_bytes());encrypted=True
        if not isinstance(data,dict) or not isinstance(data.get('tracks'),list):raise ValueError('草稿结构不受支持')
        texts={m['id']:m for m in data.get('materials',{}).get('texts',[])}
        tracks=[]
        for index,track in enumerate(data['tracks']):
            if track.get('type')!='text':continue
            cues=[]
            for seg in track.get('segments',[]):
                item=texts.get(seg.get('material_id'))
                if not item:raise ValueError('文字素材引用缺失')
                content=json.loads(item['content']);timer=seg['target_timerange']
                cues.append({'start':timer['start']/1e6,'end':(timer['start']+timer['duration'])/1e6,'text':content['text']})
            if cues:tracks.append({'index':index,'name':track.get('name') or f'文字轨道 {index+1}','cues':cues})
        if not tracks:raise ValueError('草稿没有可编辑的字幕文字轨道')
        session={'source':source,'digest':digest,'data':data,'tracks':tracks,'encrypted':encrypted,'install':install,'python':python,'work':work}
        with self.lock:
            if len(self.sessions)>=8:self.sessions.pop(next(iter(self.sessions)))
            self.sessions[sid]=session
        cached=self.read_progress(session)
        return {'sessionId':sid,'name':source.parent.name,'sourcePath':str(source),'encrypted':encrypted,'tracks':tracks,'sourceHash':digest,
                'progress':cached,'progressStale':bool(cached and cached.get('sourceHash')!=digest),
                'progressIssue':session.get('progressIssue','')}

    def progress_path(self,session):
        key=hashlib.sha256(str(session['source']).casefold().encode('utf-8')).hexdigest()
        return self.root/'progress'/(key+'.json')

    def read_progress(self,session):
        path=self.progress_path(session)
        if not path.is_file():return None
        try:
            if path.stat().st_size>10_000_000:raise ValueError()
            value=json.loads(path.read_bytes())
            if (not isinstance(value,dict) or not isinstance(value.get('tracks'),list) or
                not 1<=len(value['tracks'])<=100 or not isinstance(value.get('revision'),str) or
                not isinstance(value.get('sourceHash'),str)):raise ValueError()
            seen=set()
            for row in value['tracks']:
                if not isinstance(row,dict):raise ValueError()
                index=row.get('trackIndex')
                if isinstance(index,bool) or not isinstance(index,int) or index in seen:raise ValueError()
                seen.add(index);texts=row.get('texts')
                if not isinstance(texts,list) or len(texts)>1000 or any(not isinstance(t,str) or not t.strip() or len(t)>2000 for t in texts):raise ValueError()
                if value['sourceHash']==session['digest']:
                    track=next((t for t in session['tracks'] if t['index']==index),None)
                    if not track or len(track['cues'])!=len(texts):raise ValueError()
                if not isinstance(row.get('manuscript',''),str) or len(row.get('manuscript',''))>100000 or row.get('mode','auto') not in ('auto','lines'):raise ValueError()
                chat=row.get('chatHistory',[]);log=row.get('editLog',[])
                if not isinstance(chat,list) or len(chat)>20 or not isinstance(log,list) or len(log)>100:raise ValueError()
                if any(not isinstance(h,dict) or h.get('role') not in ('user','assistant') or not isinstance(h.get('text'),str) or len(h['text'])>10000 for h in chat):raise ValueError()
                if any(not isinstance(h,str) or len(h)>300 for h in log):raise ValueError()
                subtitle_style.validate_patch(row.get('stylePatch',{}))
            session.pop('progressIssue',None)
            return value
        except (OSError,ValueError):
            session['progressIssue']='旧编辑进度损坏，未套用；下次保存会先备份旧文件'
            return None

    def presets(self):
        path=self.root/'style-presets.json'
        if not path.is_file():return []
        try:
            value=json.loads(path.read_bytes())
            if not isinstance(value,list) or len(value)>100:raise ValueError()
            for row in value:
                if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not isinstance(row.get('name'),str):raise ValueError()
                subtitle_style.validate_patch(row['stylePatch'])
                font=row.get('font')
                if font and subtitle_style.font_id(font)!=row['stylePatch'].get('fontId'):raise ValueError()
            return value
        except (OSError,ValueError,KeyError,TypeError):
            raise ValueError('样式预设文件损坏，请保留文件并检查，未覆盖已有预设') from None

    def style_fonts(self,session):
        fonts=subtitle_style.font_catalog(session['data'])
        for p in self.presets():
            if p.get('font'):fonts[subtitle_style.font_id(p['font'])]=p['font']
        return fonts

    def style_info(self,payload,*,allow_missing_font=False):
        with self.lock:
            session,track=self.selected(payload)
            fonts=self.style_fonts(session)
            patch=subtitle_style.validate_patch(payload.get('stylePatch',{}))
            data=copy.deepcopy(session['data'])
            segments=data['tracks'][track['index']]['segments']
            items={m['id']:m for m in data['materials']['texts']}
            for seg in segments:
                subtitle_style.apply_style(items[seg['material_id']],seg,patch,fonts,allow_missing_font=allow_missing_font)
            styles=[subtitle_style.describe(items[s['material_id']],s) for s in segments]
            identities={json.dumps(f['richFont'],sort_keys=True,ensure_ascii=False):key for key,f in fonts.items()}
            for style,seg in zip(styles,segments):
                font=subtitle_style.font_descriptor(items[seg['material_id']])
                if font:style['fontId']=identities.get(json.dumps(font['richFont'],sort_keys=True,ensure_ascii=False),style['fontId'])
            return {'styles':styles,'fonts':[{'id':key,'name':subtitle_style.font_label(f),'available':subtitle_style.available_font(f)} for key,f in fonts.items()],
                    'presets':[{'id':p['id'],'name':p['name'],'stylePatch':p['stylePatch']} for p in self.presets()]}

    def style_preview(self,payload):
        with self.lock:
            patch=subtitle_style.validate_patch(payload.get('stylePatch',{}))
            before=self.style_info({**payload,'stylePatch':payload.get('currentStylePatch',{})},allow_missing_font=True)
            after=self.style_info({**payload,'stylePatch':patch})
            changes=[{'cueIndex':i,'before':a,'after':b} for i,(a,b) in enumerate(zip(before['styles'],after['styles'])) if a!=b]
            return {'stylePatch':patch,'styleChanges':changes,'styles':after['styles']}

    def preset_save(self,payload):
        with self.lock:
            session,_=self.selected(payload)
            name=payload.get('name')
            if not isinstance(name,str) or not name.strip() or len(name)>60:raise ValueError('请填写不超过 60 字的预设名称')
            patch=subtitle_style.validate_patch(payload.get('stylePatch',{}))
            if not patch:raise ValueError('请先应用至少一项样式调整')
            self.style_info({**payload,'stylePatch':patch})
            rows=self.presets()
            if any(p['name']==name.strip() for p in rows):raise ValueError('已有同名预设，请使用另一个名称')
            if len(rows)>=100:raise ValueError('最多保存 100 个样式预设')
            item={'id':uuid.uuid4().hex,'name':name.strip(),'stylePatch':patch}
            if 'fontId' in patch:item['font']=copy.deepcopy(self.style_fonts(session)[patch['fontId']])
            rows.append(item)
            path=self.root/'style-presets.json';temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf-8');temp.replace(path)
            return {'id':item['id'],'name':item['name']}

    def progress_save(self,payload):
        with self.lock:
            session,_=self.selected(payload)
            if hashlib.sha256(session['source'].read_bytes()).hexdigest()!=session['digest']:raise ValueError('原草稿已变化，请重新载入后保存进度')
            previous=self.read_progress(session)
            if payload.get('revision')!=(previous or {}).get('revision'):raise ValueError('其他窗口已保存更新的进度，请重新载入后核对')
            states=payload.get('tracks')
            if not isinstance(states,list) or not 1<=len(states)<=100:raise ValueError('编辑进度轨道数量不正确')
            clean=[];seen=set()
            for state in states:
                if not isinstance(state,dict):raise ValueError('编辑进度格式不正确')
                index=state.get('trackIndex')
                _,track=self.selected({**payload,'trackIndex':index})
                if index in seen:raise ValueError('编辑进度轨道重复')
                seen.add(index);cues=self.current_cues(track,{'texts':state.get('texts')})
                if len(cues)>1000 or state.get('texts') is None:raise ValueError('编辑进度最多保存每轨 1000 条字幕')
                manuscript=state.get('manuscript','')
                if not isinstance(manuscript,str) or len(manuscript)>100000:raise ValueError('作者原稿格式不正确')
                mode=state.get('mode','auto')
                if mode not in ('auto','lines'):raise ValueError('原稿对照方式不正确')
                chat=state.get('chatHistory',[]);log=state.get('editLog',[])
                if not isinstance(chat,list) or len(chat)>20 or not isinstance(log,list) or len(log)>100:raise ValueError('编辑记录数量不正确')
                normalized_chat=[]
                for h in chat:
                    if not isinstance(h,dict) or h.get('role') not in ('user','assistant') or not isinstance(h.get('text'),str) or len(h['text'])>10000:raise ValueError('聊天记录格式不正确')
                    normalized_chat.append({'role':h['role'],'text':h['text']})
                if any(not isinstance(h,str) or len(h)>300 for h in log):raise ValueError('修改记录格式不正确')
                patch=subtitle_style.validate_patch(state.get('stylePatch',{}))
                self.style_info({**payload,'trackIndex':index,'stylePatch':patch})
                clean.append({'trackIndex':index,'texts':[c['text'] for c in cues],'manuscript':manuscript,'mode':mode,'chatHistory':normalized_chat,'editLog':log,'stylePatch':patch})
            result={'sourceHash':session['digest'],'revision':uuid.uuid4().hex,'savedAt':datetime.now(timezone.utc).isoformat(),'tracks':clean}
            path=self.progress_path(session);path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(result,ensure_ascii=False),'utf-8')
            if session.get('progressIssue') and path.is_file():
                shutil.copyfile(path,path.with_suffix('.damaged-'+uuid.uuid4().hex+'.json'))
            temporary.replace(path);session.pop('progressIssue',None)
            return {'revision':result['revision'],'savedAt':result['savedAt']}

    def progress_backup(self,payload):
        """Preserve an unsaved/conflicted page without replacing shared progress.

        This also works for evicted sessions and incomplete text while typing.
        It accepts no output path, and the backup is never silently reapplied.
        """
        with self.lock:
            rows=payload.get('tracks')
            if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('备份轨道数量不正确')
            clean=[];seen=set()
            for row in rows:
                if not isinstance(row,dict):raise ValueError('备份格式不正确')
                index=row.get('trackIndex');texts=row.get('texts');manuscript=row.get('manuscript','')
                if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<=9999 or index in seen:raise ValueError('备份轨道序号不正确')
                seen.add(index)
                if not isinstance(texts,list) or len(texts)>1000 or any(not isinstance(t,str) or len(t)>2000 for t in texts):raise ValueError('备份字幕格式不正确')
                if not isinstance(manuscript,str) or len(manuscript)>100000:raise ValueError('备份原稿格式不正确')
                mode=row.get('mode','auto')
                if mode not in ('auto','lines'):raise ValueError('备份对照方式不正确')
                chat=row.get('chatHistory',[]);log=row.get('editLog',[])
                if not isinstance(chat,list) or len(chat)>20 or not isinstance(log,list) or len(log)>100:raise ValueError('备份记录数量不正确')
                if any(not isinstance(h,dict) or h.get('role') not in ('user','assistant') or not isinstance(h.get('text'),str) or len(h['text'])>10000 for h in chat):raise ValueError('备份聊天记录不正确')
                if any(not isinstance(h,str) or len(h)>300 for h in log):raise ValueError('备份修改记录不正确')
                clean.append({'trackIndex':index,'texts':texts,'manuscript':manuscript,'mode':mode,
                              'chatHistory':[{'role':h['role'],'text':h['text']} for h in chat],'editLog':log,
                              'stylePatch':subtitle_style.validate_patch(row.get('stylePatch',{}))})
            session=self.sessions.get(payload.get('sessionId'))
            source=str(session['source']) if session else None;digest=session['digest'] if session else None
            # Expired pages can label a backup for later version-checked recovery.
            # These values are metadata only; they never become an output path.
            if not session and payload.get('sourcePath') is not None:
                import re
                supplied=payload.get('sourcePath');supplied_hash=payload.get('sourceHash')
                if not isinstance(supplied,str) or not 1<=len(supplied)<=4096 or not Path(supplied).is_absolute() or Path(supplied).name!='draft_content.json':raise ValueError('备份原草稿标识不正确')
                if not isinstance(supplied_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',supplied_hash):raise ValueError('备份原草稿版本不正确')
                source=str(Path(supplied).resolve());digest=supplied_hash
            record={'source':source,'sourceHash':digest,
                    'savedAt':datetime.now(timezone.utc).isoformat(),'tracks':clean,
                    'note':'冲突恢复备份，未覆盖共享进度；空字幕需修正后才能输出'}
            folder=self.root/'recovery-backups';folder.mkdir(parents=True,exist_ok=True)
            path=folder/('字幕编辑备份-'+uuid.uuid4().hex+'.json')
            path.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
            return {'path':str(path)}

    def recovery_record(self, backup_id):
        """Read only an app-created backup ID, never a client-supplied path."""
        import re
        if not isinstance(backup_id,str) or not re.fullmatch(r'[0-9a-f]{32}',backup_id):
            raise ValueError('备份编号不正确')
        folder=(self.root/'recovery-backups').resolve()
        path=folder/('字幕编辑备份-'+backup_id+'.json')
        if path.is_symlink() or path.resolve().parent!=folder or not path.is_file():
            raise ValueError('备份不存在或不可读取')
        if path.stat().st_size>10*1024*1024:raise ValueError('备份文件过大')
        try:
            record=json.loads(path.read_text('utf-8'))
        except (UnicodeError,json.JSONDecodeError):raise ValueError('备份文件损坏') from None
        if not isinstance(record,dict):raise ValueError('备份格式不正确')
        return record

    def recovery_list(self,payload):
        with self.lock:
            session,_=self.selected(payload)
            folder=self.root/'recovery-backups';items=[];unreadable=0
            paths=sorted(folder.glob('字幕编辑备份-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100] if folder.exists() else []
            for path in paths:
                backup_id=path.stem.removeprefix('字幕编辑备份-')
                try:
                    record=self.recovery_record(backup_id)
                    if record.get('source')!=str(session['source']):continue
                    rows=record.get('tracks')
                    if not isinstance(rows,list):raise ValueError('备份轨道格式不正确')
                    matching=next((r for r in rows if isinstance(r,dict) and r.get('trackIndex')==payload['trackIndex']),None)
                    if not matching:continue
                    compatible=record.get('sourceHash')==session['digest']
                    items.append({'id':backup_id,'savedAt':record.get('savedAt','未知时间'),
                                  'cueCount':len(matching.get('texts',[])) if isinstance(matching.get('texts'),list) else 0,
                                  'compatible':compatible,'reason':'' if compatible else '原草稿版本已变化，不能自动恢复'})
                except (ValueError,OSError):unreadable+=1
                if len(items)>=50:break
            return {'backups':items,'unreadableCount':unreadable}

    def recovery_preview(self,payload):
        """Validate and return one track for explicit, undoable browser restoration."""
        with self.lock:
            session,track=self.selected(payload)
            record=self.recovery_record(payload.get('backupId'))
            if record.get('source')!=str(session['source']) or record.get('sourceHash')!=session['digest']:
                raise ValueError('备份与当前草稿版本不一致，请保留备份并人工核对')
            if hashlib.sha256(session['source'].read_bytes()).hexdigest()!=session['digest']:
                raise ValueError('原草稿已变化，请重新载入后核对备份')
            rows=record.get('tracks')
            if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('备份轨道格式不正确')
            matches=[r for r in rows if isinstance(r,dict) and type(r.get('trackIndex')) is int and r['trackIndex']==track['index']]
            if len(matches)!=1:raise ValueError('备份中没有唯一对应的字幕轨道')
            state=matches[0];texts=state.get('texts');current=payload.get('texts')
            for values in (texts,current):
                if not isinstance(values,list) or len(values)!=len(track['cues']) or len(values)>1000 or any(not isinstance(t,str) or len(t)>2000 for t in values):
                    raise ValueError('备份字幕数量或内容不正确')
            manuscript=state.get('manuscript','');mode=state.get('mode','auto');chat=state.get('chatHistory',[]);log=state.get('editLog',[])
            if not isinstance(manuscript,str) or len(manuscript)>100000 or mode not in ('auto','lines'):raise ValueError('备份原稿格式不正确')
            if not isinstance(chat,list) or len(chat)>20 or any(not isinstance(h,dict) or h.get('role') not in ('user','assistant') or not isinstance(h.get('text'),str) or len(h['text'])>10000 for h in chat):raise ValueError('备份聊天记录不正确')
            if not isinstance(log,list) or len(log)>100 or any(not isinstance(h,str) or len(h)>300 for h in log):raise ValueError('备份修改记录不正确')
            patch=subtitle_style.validate_patch(state.get('stylePatch',{}))
            styling=self.style_preview({**payload,'currentStylePatch':payload.get('stylePatch',{}),'stylePatch':patch})
            return {'state':{'texts':texts,'manuscript':manuscript,'mode':mode,
                             'chatHistory':[{'role':h['role'],'text':h['text']} for h in chat],'editLog':log,'stylePatch':patch},
                    'changes':[{'cueIndex':i,'before':before,'after':after} for i,(before,after) in enumerate(zip(current,texts)) if before!=after],
                    'styleChanges':styling['styleChanges'],'savedAt':record.get('savedAt','未知时间'),
                    'emptyCount':sum(not t.strip() for t in texts)}

    def chat(self,payload,config):
        with self.lock:
            _,track=self.selected(payload)
            cues=self.current_cues(track,payload)
            info=self.style_info(payload)
        from existing_draft_chat import propose
        result=propose(config,payload,cues,info)
        if 'stylePatch' in result:
            result.update(self.style_preview({**payload,'currentStylePatch':payload.get('stylePatch',{}),'stylePatch':result['stylePatch']}))
        return result

    def selected(self,payload):
        session=self.sessions.get(payload.get('sessionId'))
        if not session:raise ValueError('草稿会话已失效，请重新载入')
        index=payload.get('trackIndex')
        if isinstance(index,bool) or not isinstance(index,int):raise ValueError('请选择字幕轨道')
        track=next((t for t in session['tracks'] if t['index']==index),None)
        if not track:raise ValueError('字幕轨道不存在')
        return session,track

    def preview(self,payload):
        with self.lock:
            _,track=self.selected(payload)
            return compare(self.current_cues(track,payload),payload.get('manuscript'),payload.get('mode','auto'))

    def current_cues(self,track,payload):
        cues=copy.deepcopy(track['cues']);texts=payload.get('texts')
        if texts is not None:
            if not isinstance(texts,list) or len(texts)!=len(cues):raise ValueError('当前字幕数量不正确')
            for cue,text in zip(cues,texts):
                if not isinstance(text,str) or len(text)>2000 or not text.strip():raise ValueError('当前字幕内容不正确')
                cue['text']=text
        return cues

    def normalize(self,payload):
        with self.lock:
            _,track=self.selected(payload)
            cues=self.current_cues(track,payload)
            for cue in cues:
                cue['text']=format_subtitle(cue['text'])
                if not cue['text']:raise ValueError('规范后字幕为空，请手动修正')
            return {'cues':cues}

    def save(self,payload):
        with self.lock:
            session,track=self.selected(payload)
            source=session['source']
            if hashlib.sha256(source.read_bytes()).hexdigest()!=session['digest']:raise ValueError('原草稿已变化，请重新载入后校对')
            rows=payload.get('rows',[])
            if not isinstance(rows,list) or len(rows)>1000:raise ValueError('字幕修改数量不正确')
            edits={}
            for row in rows:
                if not isinstance(row,dict):raise ValueError('字幕修改格式不正确')
                i=row.get('cueIndex');text=row.get('text')
                if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(track['cues']) or i in edits:raise ValueError('字幕序号不存在或重复')
                if not isinstance(text,str) or len(text)>2000 or not format_subtitle(text):raise ValueError('字幕不能为空或超过两千字')
                edits[i]=format_subtitle(text)
            if payload.get('normalize',True):
                for i,c in enumerate(track['cues']):edits.setdefault(i,format_subtitle(c['text']))
            data=copy.deepcopy(session['data']);segments=data['tracks'][track['index']]['segments']
            other={s.get('material_id') for i,t in enumerate(data['tracks']) if i!=track['index'] for s in t.get('segments',[])}
            refs={}
            for i,seg in enumerate(segments):
                mid=seg['material_id'];new=edits.get(i,track['cues'][i]['text'])
                if mid in refs and refs[mid]!=new:raise ValueError('同一文字素材被重复引用且修改不同，需专项处理')
                refs[mid]=new
            changed=[]
            for item in data['materials']['texts']:
                mid=item['id']
                if mid not in refs:continue
                content=json.loads(item['content']);old=content['text'];new=refs[mid]
                if new==old:continue
                if not new:raise ValueError('规范后字幕为空，请手动修正')
                if mid in other:raise ValueError('字幕与其他轨道共用素材，当前版本无法修改')
                remap_styles(content,old,new);content['text']=new;item['content']=json.dumps(content,ensure_ascii=False,separators=(',',':'))
                if 'words' in item:item['words']={'start_time':[],'end_time':[],'text':[]}
                changed.append({'id':mid,'before':old,'after':new})
            # All non-caption fields, including tracks and time ranges, stay exact.
            changed_ids={c['id'] for c in changed}
            a,b=copy.deepcopy(session['data']),copy.deepcopy(data)
            for d in (a,b):d['materials']['texts']=[m for m in d['materials']['texts'] if m['id'] not in changed_ids]
            if a!=b:raise ValueError('非字幕数据校验失败')
            patch=subtitle_style.validate_patch(payload.get('stylePatch',{}))
            styled=[]
            if patch:
                before_style=copy.deepcopy(data);fonts=self.style_fonts(session)
                items={m['id']:m for m in data['materials']['texts']}
                for i,seg in enumerate(segments):
                    mid=seg['material_id']
                    if mid in other:raise ValueError('字幕与其他轨道共用素材，当前版本无法修改样式')
                    before=subtitle_style.describe(items[mid],seg)
                    subtitle_style.apply_style(items[mid],seg,patch,fonts)
                    after=subtitle_style.describe(items[mid],seg)
                    if before!=after:styled.append({'cueIndex':i,'before':before,'after':after})
                subtitle_style.verify_boundary(before_style,data,track['index'],set(refs))
            files=list(source.parent.rglob('*'))
            if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in files):raise ValueError('草稿含链接目录，请使用普通草稿目录')
            if len(files)>10000 or sum(p.stat().st_size for p in files if p.is_file())>512_000_000:raise ValueError('草稿资源过大，当前副本功能支持 512 MB 以内')
            output=self.root/'copies'/(source.parent.name+'-字幕修改-'+uuid.uuid4().hex[:8])
            output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(source.parent,output)
            try:
                plain=session['work']/'modified.json';plain.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),'utf-8')
                target=output/'draft_content.json'
                if session['encrypted']:
                    self.codec('enc',plain,target,session['install'],session['python'])
                    check=session['work']/'readback.json';self.codec('dec',target,check,session['install'],session['python'])
                    if json.loads(check.read_bytes())!=data:raise ValueError('加密往返校验失败')
                else:shutil.copyfile(plain,target)
                if hashlib.sha256(source.read_bytes()).hexdigest()!=session['digest']:raise ValueError('保存期间原草稿已变化，请重新载入')
                # Stale generated subtitle export would misrepresent the edited copy.
                from subtitle_tools import to_srt
                edited_cues=[{**c,'text':refs[segments[i]['material_id']]} for i,c in enumerate(track['cues'])]
                (output/'修改后字幕.srt').write_text(to_srt(edited_cues),'utf-8-sig')
                record={'source':str(source),'sourceHash':session['digest'],'sourceUnchanged':True,'roundTripVerified':True,
                        'track':track['name'],'changes':changed,'manuscript':payload.get('manuscript',''),
                        'stylePatch':patch,'styleChanges':styled,
                        'note':'独立副本，未注册剪映项目；打开、播放、保存重开需人工验收'}
                (output/'字幕修改记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
            except Exception:
                # Retain failed copy for diagnostics, never report it as successful.
                (output/'保存未通过.txt').write_text('副本验证失败，请勿导入此目录','utf-8')
                raise
            return {'path':str(output),'changedCount':len(changed),'styledCount':len(styled),'styleChanges':styled,'sourceUnchanged':True,'roundTripVerified':True,'cues':edited_cues,
                    'changes':[{'cueIndex':i,'before':c['text'],'after':edited_cues[i]['text']} for i,c in enumerate(track['cues']) if c['text']!=edited_cues[i]['text']]}
