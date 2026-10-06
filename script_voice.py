"""Durable, sequential voice jobs with frozen sentence and preset bindings."""
import copy
import json
import threading
import uuid
from datetime import datetime,timezone
from pathlib import Path
from rough_cut import atomic_json, number
from script_plan import normalize_plan
from script_import import document_text, parse_script


class ScriptVoice:
    def __init__(self,root,tts):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.jobs=self.root/'jobs';self.jobs.mkdir(exist_ok=True)
        self.drafts=self.root/'drafts';self.drafts.mkdir(exist_ok=True)
        self.profiles=self.root/'profiles.json';self.tts=tts;self.lock=threading.RLock()
        self.active=None
        for p in self.jobs.glob('*.json'):
            value=json.loads(p.read_text('utf-8'))
            if value['state'] in ('queued','running','stopping'):
                value.update(state='interrupted',message='工坊重启，已完成的音频保留，可应用结果后继续生成');atomic_json(p,value)

    def presets(self):
        saved=json.loads(self.profiles.read_text('utf-8')) if self.profiles.is_file() else []
        voices=self.tts.voices.scan()['items']
        for item in saved:
            match=next((v for v in voices if v['ready'] and all(Path(v['preset'][k]).resolve()==Path(item['preset'][k]).resolve() for k in ('gpt','sovits'))),None)
            if match:item['name']=match['name']
        return {'items':saved+[dict(id=v['id'],name=v['name'],work=v['work'],preset=v['preset']) for v in voices if v['ready']]}

    def capture(self,payload):
        with self.lock:
            config=self.tts.validate(payload.get('preset') or self.tts.settings())
            item=dict(id=uuid.uuid4().hex,name=config['name'],preset=config)
            values=json.loads(self.profiles.read_text('utf-8')) if self.profiles.is_file() else []
            if len(values)>=100:raise ValueError('声音预设最多一百个')
            values.append(item);atomic_json(self.profiles,values);return item

    def import_script(self,payload):
        if payload.get('path'):
            path=Path(payload['path']);return parse_script(document_text(path),path.name)
        return parse_script(payload.get('text',''))

    def save_plan(self,payload):
        plan=normalize_plan(payload.get('scriptPlan'),number)
        if not plan['rows']:raise ValueError('请先导入或添加台词')
        draft_id=payload.get('id') or uuid.uuid4().hex
        self.path(draft_id)  #same strict identifier validation
        draft=dict(id=draft_id,name=str(payload.get('name') or '未命名剧本')[:100],plan=plan,updated=datetime.now(timezone.utc).isoformat())
        with self.lock:atomic_json(self.drafts/(draft_id+'.json'),draft)
        return draft

    def list_plans(self):
        with self.lock:
            values=[json.loads(p.read_text('utf-8')) for p in self.drafts.glob('*.json')]
            return {'items':[{k:v[k] for k in ('id','name','updated')} for v in sorted(values,key=lambda v:v['updated'],reverse=True)]}

    def plan(self,draft_id):
        self.path(draft_id)
        with self.lock:
            path=self.drafts/(draft_id+'.json')
            if not path.is_file():raise ValueError('保存的剧本不存在')
            return json.loads(path.read_text('utf-8'))

    def path(self,job_id):
        if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):raise ValueError('任务编号不正确')
        return self.jobs/(job_id+'.json')

    def job(self,job_id):
        with self.lock:
            path=self.path(job_id)
            if not path.is_file():raise ValueError('配音任务不存在')
            return json.loads(path.read_text('utf-8'))

    def list(self):
        with self.lock:
            values=[json.loads(p.read_text('utf-8')) for p in self.jobs.glob('*.json')]
            return {'items':[{k:v[k] for k in ('id','name','created','state','completed','total','message')} for v in sorted(values,key=lambda v:v['created'],reverse=True)]}

    def start(self,payload):
        with self.lock:
            if self.active:raise ValueError('已有批量配音正在进行，请等待完成或停止')
            plan=normalize_plan(payload.get('scriptPlan'),number)
            requested=payload.get('rowIds')
            if requested is not None and (not isinstance(requested,list) or any(not isinstance(v,str) for v in requested)):
                raise ValueError('台词选择格式不正确')
            if requested is not None and set(requested)-{r['id'] for r in plan['rows']}:raise ValueError('选择的台词不存在')
            selected=[r for r in plan['rows'] if r['voice'] and (r['id'] in requested if requested is not None else not r['audio'])]
            if not selected:raise ValueError('没有需要生成的台词；已有音频可在单句操作中重新生成')
            profiles={p['id']:p['preset'] for p in self.presets()['items']};presets={}
            for row in selected:
                if len(row.get('versions',[]))>=500:raise ValueError('单句版本已达到五百个，请分开保存剧本')
                if row.get('warnings') and not row.get('reviewed'):raise ValueError('请先确认台词解析提示')
                if len(row.get('spokenText',row['text']))>1000:raise ValueError('配音单句最多一千字，请拆分长句')
                preset=profiles.get(row.get('voicePreset'))
                if not preset:raise ValueError(f'请为「{row["character"] or row["text"][:12]}」选择声音预设')
                config=copy.deepcopy(preset);config['character']=row['character']
                config['textLanguage']=row.get('language') or config['textLanguage']
                presets[row['id']]=self.tts.validate(config)
            job=dict(id=uuid.uuid4().hex,name=str(payload.get('name') or '剧本配音')[:100],created=datetime.now(timezone.utc).isoformat(),
                     state='queued',completed=0,total=len(selected),message='等待生成',plan=plan,
                     rowIds=[r['id'] for r in selected],presets=presets,results=[],cancel=False)
            atomic_json(self.path(job['id']),job);self.active=job['id']
            threading.Thread(target=self.run,args=(job['id'],),daemon=True).start()
            return copy.deepcopy(job)

    def cancel(self,payload):
        with self.lock:
            job=self.job(payload.get('id'))
            if job['state'] in ('queued','running','stopping'):
                job.update(cancel=True,state='stopping',message='当前句完成后停止，已生成音频会保留');atomic_json(self.path(job['id']),job)
            return job

    def run(self,job_id):
        try:
            job=self.job(job_id)
            for row_id in job['rowIds']:
                with self.lock:
                    job=self.job(job_id)
                    if job['cancel']:break
                    job.update(state='running',message=f'正在生成 {job["completed"]+1}/{job["total"]}')
                    atomic_json(self.path(job_id),job)
                row=next(r for r in job['plan']['rows'] if r['id']==row_id)
                try:
                    take=self.tts.generate({'text':row.get('spokenText',row['text']),'name':(row['character']+' · '+row['text'][:25]).strip(' ·')},preset=job['presets'][row_id])
                    row.setdefault('versions',[]).append(take['id']);row.update(take=take['id'],audio=take['audioId'])
                    row['audioBinding']={'id':take['audioId'],'text':row['text'],'character':row['character'].strip()}
                    result={'rowId':row_id,'state':'success','take':take['id']}
                except Exception as error:
                    result={'rowId':row_id,'state':'failed','message':str(error)[:500]}
                with self.lock:
                    latest=self.job(job_id);job['cancel']=latest['cancel']
                    job['results'].append(result);job['completed']+=1;atomic_json(self.path(job_id),job)
            with self.lock:
                job=self.job(job_id);failed=sum(r['state']=='failed' for r in job['results'])
                succeeded=job['completed']-failed
                job.update(state='stopped' if job['cancel'] else ('failed' if failed==job['total'] else 'partial' if failed else 'complete'),
                           message=f'已处理 {job["completed"]}/{job["total"]}，成功 {succeeded} 句，失败 {failed} 句；已有音频保留')
                atomic_json(self.path(job_id),job)
        except Exception as error:
            with self.lock:
                job=self.job(job_id);job.update(state='failed',message=str(error)[:500]);atomic_json(self.path(job_id),job)
        finally:
            with self.lock:self.active=None

    def select_take(self,payload):
        #Bind the recording to its original text and speaker, never to edited words.
        take_id=payload.get('id');path=self.tts.file(take_id)
        take=json.loads((self.tts.records/(take_id+'.json')).read_text('utf-8'))
        audio_id=take['audioId']
        try:self.tts.library.file(audio_id)
        except ValueError:
            imported=self.tts.library.import_file(path);audio_id=imported['item']['id']
            if not imported['duplicate']:
                self.tts.library.update({'id':audio_id,'name':take['name'],'text':take['text'],'character':take['character']})
        return {'audio':audio_id,'take':take_id,'audioBinding':{'id':audio_id,'text':take['text'],'character':take['character']}}
