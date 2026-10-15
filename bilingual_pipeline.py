"""Background one-click creation of a draft from authored bilingual scripts."""
from __future__ import annotations

import copy
import threading
import time
import uuid
import re
from PIL import Image


class BilingualPipeline:
    def __init__(self,workflow,pause,publish):
        self.workflow,self.pause,self.publish=workflow,pause,publish
        self.jobs={};self.lock=threading.RLock()

    def start(self,payload):
        from manuscript_review import validate_manuscript
        validate_manuscript(payload.get('japanese'));validate_manuscript(payload.get('chinese'))
        self.workflow.video.session(payload)
        with self.lock:
            if any(j['state'] in ('running','saving') for j in self.jobs.values()):raise ValueError('一键处理正在运行')
            if len(self.jobs)>=16:
                stale=next((k for k,v in self.jobs.items() if v['state'] in ('complete','failed','cancelled')),None)
                if not stale:raise ValueError('待保存结果较多，请先保存已有处理结果')
                self.jobs.pop(stale)
            ident=uuid.uuid4().hex
            self.jobs[ident]=dict(id=ident,state='running',stage='读取草稿素材',step=1,steps=5,started=time.monotonic(),cancel=threading.Event(),child=None)
        threading.Thread(target=self.run,args=(ident,copy.deepcopy(payload)),daemon=True).start()
        return self.job(dict(id=ident))

    def job(self,payload):
        with self.lock:
            job=self.jobs.get(payload.get('id'))
            if not job:raise ValueError('一键任务已失效')
            result=copy.deepcopy({k:v for k,v in job.items() if k not in ('cancel','child','started','finished','prepared','payload')})
            result['elapsedSeconds']=round(job.get('finished',time.monotonic())-job['started'])
            return result

    def cancel(self,payload):
        with self.lock:
            job=self.jobs.get(payload.get('id'))
            if not job:raise ValueError('一键任务已失效')
            job['cancel'].set();child=job['child']
        if child:self.workflow.cancel(dict(id=child))
        return self.job(payload)

    def prepare(self,payload):
        payload=dict(payload)
        payload.setdefault('centerX',True)
        payload['replacePortraitRange']=True
        if type(payload.get('videoTrackIndex')) is not int:
            with self.workflow.video.editor.lock:
                session=self.workflow.video.session(payload)
                materials={m['id']:m for m in session['data']['materials'].get('videos',[])}
                candidates=[]
                for ti,track in enumerate(session['data']['tracks']):
                    if track.get('type')!='video':continue
                    for si,seg in enumerate(track.get('segments',[])):
                        m=materials.get(seg.get('material_id'),{})
                        try:
                            with Image.open(m.get('path','')) as im:
                                if (im.mode in ('RGBA','LA') or 'transparency' in im.info) and im.convert('RGBA').getchannel('A').getextrema()[0]<255:
                                    candidates.append((ti,si));break
                        except (OSError,ValueError):continue
                if len(candidates)!=1:raise ValueError('无法唯一确定人物立绘，请在高级选项选择人物示例后重试')
                payload['videoTrackIndex'],payload['segmentIndex']=candidates[0]
        info=self.workflow.template(payload)
        if type(payload.get('audioTrackIndex')) is not int:
            clips=info['audioClips']
            labelled=[c for c in clips if re.search(r'自然停顿|配音|口播|narration|voice|tts',c['name'],re.I)]
            if len(clips)!=1 and len(labelled)!=1:raise ValueError('草稿有多段音频，请在高级选项选择口播配音后重试')
            audio=(labelled or clips)[0];payload.update(audioTrackIndex=audio['trackIndex'],audioSegmentIndex=audio['segmentIndex'])
        payload.setdefault('expressions',[a['id'] for a in info['assets']])
        return payload

    def run(self,ident,payload):
        job=self.jobs[ident]
        def check():
            if job['cancel'].is_set():raise ValueError('任务已取消')
        def stage(step,text):
            check()
            with self.lock:job.update(step=step,stage=text)
        try:
            payload=self.prepare(payload);check()
            stage(2,'整理长停顿，保留自然呼吸')
            removed=0
            if payload.get('cleanPauses',True):
                preview=self.pause.preview(payload);check()
                chosen=[r['id'] for r in preview['rows'] if r['selected']]
                if chosen:
                    cleaned=self.pause.save({**payload,'previewId':preview['previewId'],'selected':chosen})
                    payload['cleanAudioId']=cleaned['cleanAudioId'];removed=cleaned['removedSeconds']
            stage(3,'识别日语并安排中文字幕与人物表情')
            child=self.workflow.start(payload)
            with self.lock:job['child']=child['id']
            while child['state']=='running':
                stage(3,child['stage'])
                if job['cancel'].wait(.25):self.workflow.cancel(dict(id=child['id']));check()
                child=self.workflow.job(dict(id=child['id']))
            check()
            if child['state']!='complete':raise ValueError(child.get('error') or '双语对齐未完成')
            stage(4,'生成字幕和人物轨道')
            output=self.workflow.export(dict(id=child['id'],automatic=True,rows=[dict(chinese=r['chinese'],expression=r['expression']) for r in child['rows']]))
            with self.lock:job.update(state='awaiting_save',step=5,stage='处理完成，请选择保存方式',prepared=output,payload=payload,rows=child['rows'],expressions=child['expressions'],removedSeconds=removed,finished=time.monotonic())
        except Exception as error:
            with self.lock:job.update(state='cancelled' if job['cancel'].is_set() else 'failed',stage=str(error),error=str(error),finished=time.monotonic())

    def save(self,payload):
        with self.lock:
            job=self.jobs.get(payload.get('id'))
            if not job or job['state']!='awaiting_save':raise ValueError('请先完成一键处理；当前结果尚未准备好或已经保存')
            job.update(state='saving',step=5,stage='正在保存草稿')
            original=copy.deepcopy(job['payload']);prepared=copy.deepcopy(job['prepared'])
        try:
            choice=copy.deepcopy(payload.get('publish'))
            if isinstance(choice,dict) and choice.get('mode')=='overwrite':choice['replaceConfirmed']=True
            result=self.publish({**original,'publish':choice},prepared)
            if not result.get('published'):raise ValueError('请选择干净覆盖或新草稿保存位置')
            with self.lock:job.update(state='complete',stage='草稿已保存，可在剪映中微调',result=result)
            return self.job(dict(id=job['id']))
        except Exception:
            with self.lock:job.update(state='awaiting_save',stage='尚未保存，请修正保存位置后重试')
            raise
