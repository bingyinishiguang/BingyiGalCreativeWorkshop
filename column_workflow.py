"""Reusable local column recipes and full-length image overlays."""
from __future__ import annotations

import json
import math
import re
import copy
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def normalize_overlays(raw, backgrounds, number, check_media=True):
    if not isinstance(raw, list) or len(raw) > 16:
        raise ValueError('全片叠加图片最多 16 个')
    result = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError('全片叠加图片格式不正确')
        image = str(row.get('image', ''))
        item = backgrounds.get(image) if check_media else {'name':'全片图片'}
        if check_media:
            backgrounds.file(image)
            if item['kind'] != 'image':
                raise ValueError('全片叠加层请选择静态图片')
        if not isinstance(image,str) or not image:
            raise ValueError('全片图片引用为空')
        result.append(dict(image=image, name=str(row.get('name') or item['name'])[:100],
                           left=number(row.get('left', 2), '图片距左边百分比', -100, 100),
                           top=number(row.get('top', 2), '图片距上边百分比', -100, 100),
                           width=number(row.get('width', 12), '图片宽度百分比', .1, 200),
                           rotation=number(row.get('rotation', 0), '图片旋转', -360, 360)))
        if 'slotId' in row:
            result[-1]['slotId']=ColumnWorkflow.key(row['slotId'])
            if result[-1]['slotId'] in ('background','openingBackground','bgm','voice') or result[-1]['slotId'].startswith('voice-'):
                raise ValueError('全片图片组件编号与内置组件冲突')
    ids=[r['slotId'] for r in result if 'slotId' in r]
    if len(set(ids))!=len(ids):raise ValueError('全片图片组件编号重复')
    return result


def overlay_transform(row, width, height, source_width, source_height):
    shown_width = width * row['width'] / 100
    shown_height = shown_width * source_height / source_width
    fit = min(width / source_width, height / source_height)
    scale = shown_width / source_width / fit * 100
    return dict(x=width * row['left'] / 100 + shown_width / 2 - width / 2,
                y=height / 2 - height * row['top'] / 100 - shown_height / 2,
                scaleX=scale, scaleY=scale, rotation=row['rotation'], uniform=True)


def normalize_destinations(raw):
    if not isinstance(raw, dict):
        raise ValueError('栏目输出目录格式不正确')
    result = {}
    for key, label in [('episodeDirectory', '作品目录'), ('draftDirectory', '剪映草稿目录'), ('materialDirectory', '素材目录')]:
        value = str(raw.get(key) or '').strip()
        if value and not Path(value).is_dir():
            raise ValueError(label + '不存在，请选择已有文件夹')
        result[key] = value
    result['presetName'] = str(raw.get('presetName') or '')[:100]
    if raw.get('presetId'):
        result['presetId'] = ColumnWorkflow.key(raw['presetId'])
    return result


def normalize_generation(raw):
    if not isinstance(raw,dict) or type(raw.get('schemaVersion')) is not int or raw.get('schemaVersion')!=1:
        raise ValueError('生成记录格式版本不支持')
    required=('generator','createdAt','source','effectiveConfig','voices','episode','resolved')
    if any(key not in raw for key in required):raise ValueError('生成记录不完整')
    try:
        encoded=json.dumps(raw,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError) as error:raise ValueError('生成记录包含无效数据') from error
    if len(encoded.encode('utf-8'))>4_000_000:raise ValueError('生成记录过大')
    return {key:copy.deepcopy(raw[key]) for key in ('schemaVersion',)+required+('requestId','requestDigest','assets') if key in raw}


class ColumnWorkflow:
    def __init__(self, cut):
        self.cut = cut
        self.root = cut.root / 'column-presets'
        self.root.mkdir(exist_ok=True)
        self.lock=threading.RLock()

    @staticmethod
    def key(value):
        value = str(value or 'ifgal')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
            raise ValueError('栏目配置编号不正确')
        return value

    def list(self):
        items,errors=[],[]
        for p in sorted(self.root.glob('*.json')):
            try:
                value=json.loads(p.read_text('utf-8'))
                if value.get('schemaVersion',1)!=1:raise ValueError('配置格式版本不支持')
                items.append(value)
            except (ValueError,AttributeError,OSError) as error:
                errors.append({'file':p.name,'message':str(error)})
        #Older recipes stored an episode directory. Never reuse it for a new episode.
        for item in items:
            item.pop('episodeDirectory', None)
        return {'items': items, 'errors':errors}

    def normalize(self, payload, check_media=True):
        from rough_cut import number
        if not isinstance(payload, dict):
            raise ValueError('栏目配置格式不正确')
        if type(payload.get('schemaVersion',1)) is not int or payload.get('schemaVersion',1)!=1:raise ValueError('配置格式版本不支持')
        background = str(payload.get('background') or '')
        visual_mode=payload.get('visualMode','cover')
        if visual_mode not in ('cover','sequence'):raise ValueError('主画面组合方式不支持')
        duration_policy=payload.get('durationPolicy','voice')
        if duration_policy not in ('voice','timeline'):raise ValueError('总时长规则不支持')
        from column_sequence import normalize_sequence
        sequence=normalize_sequence(payload.get('sequence',[]))
        if check_media and visual_mode=='cover':self.cut.backgrounds.file(background)
        opening = str(payload.get('openingBackground') or '')
        if opening and check_media:
            self.cut.backgrounds.file(opening)
        bgm = str(payload.get('bgm') or '')
        if bgm and check_media:
            self.cut.audio_library.file(bgm)
        fps = int(number(payload.get('fps', 30), '帧率', 24, 60))
        if fps not in (24, 25, 30, 60):
            raise ValueError('帧率支持 24、25、30、60')
        permissions={}
        if not isinstance(payload.get('permissions',{}),dict):raise ValueError('画面规则格式不正确')
        for field in ('background','openingBackground'):
            raw=payload.get('permissions',{}).get(field,{})
            if not isinstance(raw,dict):raise ValueError('画面规则格式不正确')
            mode=raw.get('mode','ask')
            if mode not in ('ask','trim','loop'):raise ValueError('画面时长规则不支持')
            permissions[field]={'asset':str(payload.get(field) or ''),'mode':mode if raw.get('asset')==payload.get(field) else 'ask'}
        overlays=normalize_overlays(payload.get('overlays', []),self.cut.backgrounds,number,check_media)
        for row in overlays:row.setdefault('slotId',uuid.uuid4().hex)
        return dict(schemaVersion=1,id=self.key(payload.get('id')), name=str(payload.get('name') or 'IfGal')[:100],
                    background=background, openingBackground=opening, bgm=bgm,
                    bgmVolume=number(payload.get('bgmVolume', 1), 'BGM 音量', 0, 2),
                    bgmLoop=payload.get('bgmLoop') is True,
                    width=int(number(payload.get('width', 1920), '画布宽度', 320, 3840)),
                    height=int(number(payload.get('height', 1080), '画布高度', 320, 3840)), fps=fps,
                    overlays=overlays,permissions=permissions,visualMode=visual_mode,sequence=sequence,durationPolicy=duration_policy,
                    draftDirectory=str(payload.get('draftDirectory') or '').strip())

    def save(self, payload):
        from rough_cut import atomic_json
        with self.lock:
            result = self.normalize(payload,check_media=False)
            path=self.root/(result['id']+'.json')
            previous=json.loads(path.read_text('utf-8')) if path.exists() else None
            if previous and previous.get('schemaVersion',1)!=1:raise ValueError('旧配置格式版本不支持')
            if previous and 'revision' in payload and payload['revision']!=previous.get('revision'):
                raise ValueError('配置已被更新，请重新打开后保存；本次编辑未覆盖旧配置')
            history=self.root/'revisions'/result['id'];history.mkdir(parents=True,exist_ok=True)
            if previous and not (history/(str(previous.get('revision',0))+'.json')).exists():
                atomic_json(history/(str(previous.get('revision',0))+'.json'),previous)
            revision=max([int(p.stem) for p in history.glob('*.json')]+[0])+1
            result.update(revision=revision,savedAt=datetime.now(timezone.utc).isoformat())
            atomic_json(history/(str(revision)+'.json'),result)
            atomic_json(path,result)
            return result

    def revision(self, preset_id, revision):
        if isinstance(revision,bool) or not isinstance(revision,int) or revision<0:raise ValueError('配置修订号不正确')
        path=self.root/'revisions'/self.key(preset_id)/(str(revision)+'.json')
        if not path.exists():raise ValueError('配置修订不存在，请重新打开配置')
        return json.loads(path.read_text('utf-8'))

    def preflight(self,payload):
        issues=[]
        try:config=self.normalize(payload.get('config',{}),check_media=False)
        except (ValueError,TypeError,AttributeError) as error:
            return {'state':'invalid','issues':[{'slotId':'configuration','message':str(error)}]}
        if payload.get('config',{}).get('revision') is not None:
            try:self.revision(config['id'],payload['config']['revision'])
            except ValueError as error:
                return {'state':'invalid','issues':[{'slotId':'configuration','message':str(error)}]}
        refs=[('主画面','background',config['background'],self.cut.backgrounds),
              ('背景音乐','bgm',config['bgm'],self.cut.audio_library)]
        if config['visualMode']=='sequence':
            refs=refs[1:]
            refs += [('顺序画面 '+str(i+1),row['itemId'],row['background'],self.cut.backgrounds) for i,row in enumerate(config['sequence'])]
        voices=payload.get('voices',[])
        if not isinstance(voices,list) or not 1<=len(voices)<=100:
            issues.append({'slotId':'voice','message':'请选择 1–100 段配音'})
            voices=[]
        for index,voice in enumerate(voices):
            if not isinstance(voice,dict):issues.append({'slotId':'voice','message':'配音格式不正确'});continue
            refs.append((f'第{index+1}段配音','voice-'+str(index),voice.get('audio',''),self.cut.audio_library))
        if voices and isinstance(voices[0],dict) and voices[0].get('opening') is True:
            refs.append(('开场画面','openingBackground',config['openingBackground'],self.cut.backgrounds))
        for row in config['overlays']:refs.append((row['name'],row['slotId'],row['image'],self.cut.backgrounds))
        for label,slot,ref,library in refs:
            if not ref and slot not in ('background',) and not slot.startswith('voice-') and not any(r['itemId']==slot for r in config['sequence']):continue
            try:
                if not ref:raise ValueError('尚未选择素材')
                library.file(ref)
                if any(r['slotId']==slot for r in config['overlays']) and library.get(ref)['kind']!='image':raise ValueError('需要静态图片')
            except (ValueError,OSError) as error:
                issues.append({'slotId':slot,'asset':ref,'message':label+'：'+str(error)})
        arrangement=None
        if not issues:
            try:
                assembled=self._assemble(payload,config)
                normalized=self.cut.normalize(assembled)
                arrangement={'durationUs':normalized['durationUs'],
                             'sequence':assembled.get('sequenceResolved',[])}
            except ValueError as error:issues.append({'slotId':'timing','message':str(error)})
        return {'state':'needsInput' if issues else 'ready','issues':issues,'arrangement':arrangement}

    def build(self, payload):
        with self.lock:
            request_id=payload.get('requestId')
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
            project_id=None
            if request_id:
                request_id=self.key(request_id)
                project_id=uuid.uuid5(uuid.NAMESPACE_URL,'column-request:'+request_id).hex
                if self.cut.project_path(project_id).exists():
                    existing=self.cut.load(project_id)
                    if existing.get('generation',{}).get('requestDigest')!=digest:raise ValueError('同一次生成请求内容已改变，请重新生成')
                    return existing
            checked=self.preflight(payload)
            if checked['state']!='ready':raise ValueError('；'.join(i['message'] for i in checked['issues']))
            config = self.normalize(payload.get('config', {}),check_media=False)
            assembled=self._assemble(payload,config)
            sequence_resolved=assembled.pop('sequenceResolved',[])
            project=self.cut.normalize(assembled)
            source={'kind':'unsaved','id':config['id'],'revision':None}
            if payload.get('config',{}).get('revision') is not None:
                base=self.revision(config['id'],payload['config']['revision'])
                source={'kind':'saved','id':config['id'],'revision':base['revision'],'snapshot':base}
            project['generation']={'schemaVersion':1,'generator':'column-basic/1','createdAt':datetime.now(timezone.utc).isoformat(),
                'source':source,'effectiveConfig':config,'voices':copy.deepcopy(payload['voices']),
                'episode':{'name':project['name'],'episodeDirectory':project['workflow']['episodeDirectory']},
                'resolved':{'scenes':copy.deepcopy(project['scenes']),'audioClips':copy.deepcopy(project['audioClips']),
                            'durationUs':project['durationUs'],'overlays':copy.deepcopy(project['overlays'])}}
            if sequence_resolved:project['generation']['resolved']['sequence']=sequence_resolved
            refs=[('backgrounds',config['background']),('backgrounds',config['openingBackground']),('audio',config['bgm'])]
            refs += [('backgrounds',r['image']) for r in config['overlays']]+[('audio',v['audio']) for v in payload['voices']]
            refs += [('backgrounds',r['background']) for r in config['sequence']]
            assets=[]
            for library,ref in dict.fromkeys(refs):
                if not ref:continue
                try:info=(self.cut.backgrounds if library=='backgrounds' else self.cut.audio_library).get(ref)
                except ValueError:continue
                assets.append({'library':library,**{key:info[key] for key in ('id','name','kind','duration','width','height','hash') if key in info}})
            project['generation']['assets']=assets
            if project_id:
                project['id']=project_id
                project['generation'].update(requestId=request_id,requestDigest=digest)
            return self.cut.save(project)

    def _assemble(self,payload,config):
        destinations = normalize_destinations({'episodeDirectory':payload.get('episodeDirectory'),
                                               'draftDirectory':config['draftDirectory']})
        voices = payload.get('voices')
        if not isinstance(voices, list) or not 1 <= len(voices) <= 100:
            raise ValueError('请选择 1–100 段配音，按播放顺序排列')
        scenes, audio, cursor = [], [], 0.0
        visual_segments=0
        fps = config['fps']
        main_start_frame=0
        for index, voice in enumerate(voices):
            if not isinstance(voice, dict):
                raise ValueError('配音片段格式不正确')
            item = self.cut.audio_library.get(voice.get('audio'))
            self.cut.audio_library.file(item['id'])
            duration = item['duration']
            if cursor + duration > 10800:
                raise ValueError('总配音时长超过三小时')
            audio.append(dict(audio=item['id'], start=cursor, sourceStart=0, duration=duration,
                              kind='dialogue', track=0, volume=1, character=item['character'],
                              cues=item['cues'], subtitles=bool(item['cues']), text=item['text']))
            end = math.ceil((cursor + duration) * fps - 1e-8) / fps
            dedicated_opening=index==0 and voice.get('opening') is True and config['openingBackground']
            if config['visualMode']=='sequence' and not dedicated_opening:
                cursor=end
                continue
            if dedicated_opening:main_start_frame=round(end*fps)
            field='openingBackground' if index == 0 and voice.get('opening') is True and config['openingBackground'] else 'background'
            background=config[field]
            info=self.cut.backgrounds.get(background)
            mode=config['permissions'][field]['mode']
            if info['kind']=='video':
                difference=round((end-cursor-info['duration'])*1_000_000)
                if difference>0 and mode!='loop':raise ValueError(f"{('开场' if field=='openingBackground' else '主')}画面还差 {difference/1e6:.3f} 秒，请明确允许循环或更换画面")
                if difference<0 and mode not in ('trim','loop'):raise ValueError('画面长于配音，请明确允许截取至配音结束或更换画面')
                visual_segments+=math.ceil((end-cursor)/info['duration'])
                if visual_segments>10000:raise ValueError('画面循环片段过多，请换用更长的铺底画面')
            remaining = end - cursor
            restart=True
            while remaining > 1e-8:
                amount = min(3600, remaining)
                scenes.append(dict(id=uuid.uuid4().hex,background=background, duration=amount, loop=mode=='loop',restart=restart,actors=[]))
                restart=False
                remaining -= amount
            cursor = end
        if cursor > 10800:
            raise ValueError('帧对齐后的总时长超过三小时')
        sequence_resolved=[]
        if config['visualMode']=='sequence':
            from column_sequence import compile_sequence
            if config['durationPolicy']=='timeline':
                _,extent=compile_sequence(config['sequence'],self.cut.backgrounds,fps,main_start_frame,None)
                end_frame=max(round(cursor*fps),extent[-1]['endFrame'])
                if end_frame/fps>10800:raise ValueError('时间轴总时长超过三小时')
                cursor=end_frame/fps
            compiled,sequence_resolved=compile_sequence(config['sequence'],self.cut.backgrounds,fps,main_start_frame,round(cursor*fps))
            scenes+=compiled
        if len(scenes)>500:raise ValueError('生成镜头超过500个，请减少配音片段')
        if config['bgm']:
            item = self.cut.audio_library.get(config['bgm'])
            start = 0.0
            while start < cursor - 1e-8:
                if len(audio) >= 1000:
                    raise ValueError('BGM 循环片段过多，请选择更长的音乐')
                amount = min(item['duration'], cursor - start)
                audio.append(dict(audio=item['id'], start=start, sourceStart=0, duration=amount,
                                  kind='bgm', track=0, volume=config['bgmVolume'], subtitles=False))
                start += amount
                if not config['bgmLoop']:
                    break
        project = dict(name=str(payload.get('name') or '新一期草稿'), width=config['width'],
                       height=config['height'], fps=fps, scenes=scenes, audioClips=audio,
                       overlays=config['overlays'], workflow=dict(presetName=config['name'], presetId=config['id'],
                       episodeDirectory=destinations['episodeDirectory'],draftDirectory=destinations['draftDirectory']))
        if sequence_resolved:project['sequenceResolved']=sequence_resolved
        return project
