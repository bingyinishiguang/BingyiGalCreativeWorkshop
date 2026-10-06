"""Audition first; prepare a non-destructive, validated timeline replacement."""
import copy
import json
import math
import uuid

from rough_cut import atomic_json, number


class TimelineVoice:
    def __init__(self, cut, tts):
        self.cut,self.tts=cut,tts

    def target(self, project, key):
        clip=next((c for c in project['textClips'] if c['id']==key),None)
        if clip is None:raise ValueError('这条文字已删除或更换，请重新选择')
        return clip

    def history(self, key):
        return {'items':[t for t in self.tts.history()['items'] if t.get('timelineTarget',{}).get('id')==key]}

    def generate(self, payload):
        project=self.cut.normalize(payload.get('project',{}))
        clip=self.target(project,payload.get('target'))
        preset=copy.deepcopy(self.tts.voices.get(payload.get('voiceId'))['preset'])
        preset.update(textLanguage=payload.get('language',preset['textLanguage']),speed=payload.get('speed',preset['speed']),device=payload.get('device',preset.get('device','cpu')),sampleSteps=payload.get('sampleSteps',preset.get('sampleSteps',32)),fragmentInterval=payload.get('fragmentInterval',preset.get('fragmentInterval',.3)))
        spoken=str(payload.get('text','')).strip()
        take=self.tts.generate({'text':spoken,'name':(clip['character']+' · '+clip['text'][:25]).strip(' ·')},preset=preset)
        take['timelineTarget']={'id':clip['id'],'displayText':clip['text'],'character':clip['character'],'voiceId':payload['voiceId']}
        atomic_json(self.tts.records/(take['id']+'.json'),take)
        return take

    def preview(self, payload):
        original=payload.get('project',{})
        project=self.cut.normalize(original)
        if original.get('id'):project['id']=original['id']
        clip=self.target(project,payload.get('target'))
        self.tts.file(payload.get('take'))
        take=json.loads((self.tts.records/(payload['take']+'.json')).read_text('utf-8'))
        binding=take.get('timelineTarget',{})
        row=next((r for r in project['scriptPlan']['rows'] if r['id']==clip.get('sourceRow')),None)
        if not binding and row and take['id'] in row.get('versions',[]) and take['text']==clip['text']:
            binding={'id':clip['id'],'displayText':clip['text'],'character':clip['character'],'voiceId':row.get('voicePreset','')}
        if binding.get('id')!=clip['id'] or binding.get('displayText')!=clip['text'] or binding.get('character')!=clip['character']:
            raise ValueError('文字或角色已修改，这个配音版本需要重新生成；当前时间轴保留')
        #Restore the managed library copy if it was removed, without overwriting a take.
        try:
            self.cut.audio_library.file(take['audioId']);item=self.cut.audio_library.get(take['audioId'])
        except (ValueError,OSError):
            item=self.cut.audio_library.import_file(self.tts.file(take['id']))['item']
        before=copy.deepcopy(project)
        linked=[a for a in project['audioClips'] if a.get('linkedText')==clip['id']]
        #Migrate old generated timelines only when there is a unique exact match.
        if not linked:
            legacy=[a for a in project['audioClips'] if a['kind']=='dialogue' and not a['subtitles'] and not a.get('linkedText') and abs(a['start']-clip['start'])<1e-6 and a['text']==clip['text'] and a['character']==clip['character']]
            if len(legacy)==1:linked=legacy
        if len(linked)>1:raise ValueError('这句关联了多段音频，请先在音频面板整理')
        old=linked[0] if linked else None
        mode=payload.get('mode','ripple')
        if mode not in ('ripple','keep'):raise ValueError('请选择时长安排方式')
        fps=project['fps'];start=clip['start'];end=start+clip['duration']
        pause=number(payload.get('pause',0),'配音后停顿',0,10)
        span=math.ceil((take['duration']+pause)*fps-1e-8)/fps
        if span>3600:raise ValueError('单句音频过长，请拆分台词')
        if mode=='keep':
            if take['duration']>clip['duration']+1e-6:raise ValueError('完整音频长于当前文字，请选择联动后续内容')
            span=clip['duration']
        delta=span-clip['duration'];new_end=start+span
        if abs(delta)>1e-8:
            #Preserve every internal visual change; never squash it onto the next sentence.
            cursor=0
            for scene in project['scenes']:
                cursor+=scene['duration']
                if start+1e-6<cursor<end-1e-6 and cursor>=new_end-1e-6:
                    raise ValueError(f'缩短后会挤掉 {cursor-start:.2f} 秒的人物或背景变化，请调整变化时间或保留原时长')
            for other in project['textClips']:
                if other is clip:continue
                if other['start']>=end-1e-6:other['start']+=delta
                elif other['start']+other['duration']>end+1e-6:
                    raise ValueError('有其他文字跨过本句末尾，请先调整该文字或保留原时长')
            for other in project['audioClips']:
                if other is old or other['kind']!='dialogue':continue
                if other['start']>=end-1e-6:other['start']+=delta
                elif other['start']+other['duration']>end+1e-6:
                    raise ValueError('有其他对白跨过本句末尾，请先调整或保留原时长')
            cursor=0
            for scene in project['scenes']:
                left=cursor;right=cursor+scene['duration'];cursor=right
                #A scene spanning the old end grows/shrinks; later scenes retain duration.
                if left<end-1e-6 and right>=end-1e-6:scene['duration']+=delta
            clip['duration']=span
        total=sum(s['duration'] for s in project['scenes'])
        if new_end>total+1e-6:project['scenes'][-1]['duration']+=math.ceil((new_end-total)*fps-1e-8)/fps
        track=old['track'] if old else 0
        others=[a for a in project['audioClips'] if a is not old]
        while track<16 and any(a['kind']=='dialogue' and a['track']==track and start<a['start']+a['duration']-1e-6 and start+take['duration']>a['start']+1e-6 for a in others):track+=1
        if track>=16:raise ValueError('没有空闲对白轨，请先整理音频轨道')
        audio={'id':old['id'] if old else uuid.uuid4().hex,'linkedText':clip['id'],'audio':item['id'],'start':start,'sourceStart':0,'duration':take['duration'],'track':track,'kind':'dialogue','volume':old['volume'] if old else 1,'character':clip['character'],'text':clip['text'],'cues':[],'subtitles':False}
        if clip.get('sourceRow'):audio['sourceRow']=clip['sourceRow']
        if old:project['audioClips'][project['audioClips'].index(old)]=audio
        else:project['audioClips'].append(audio)
        versions=list(dict.fromkeys(clip.get('voice',{}).get('versions',[])+[take['id']]))
        clip['voice']={'take':take['id'],'versions':versions,'spokenText':take['text'],'displayText':clip['text'],'character':clip['character'],'voiceId':binding['voiceId'],'language':take['preset']['textLanguage'],'speed':take['preset']['speed'],'sampleSteps':take['preset'].get('sampleSteps',32),'fragmentInterval':take['preset'].get('fragmentInterval',.3)}
        #Synchronize the originating row only when the plan marker is still current.
        marker=project.get('scriptTiming')
        if row and row['text']==clip['text'] and (not marker or marker['plan']==before['scriptPlan']):
            if any(e['offset']>=take['duration']-1e-8 for e in row.get('actorEvents',[])) and mode!='keep':
                raise ValueError('人物变化晚于新配音结束，请先调整变化时间或保留原时长')
            row.update(voice=True,voiceExplicit=True,audio=item['id'],take=take['id'],versions=versions,voicePreset=binding['voiceId'],language=take['preset']['textLanguage'],pause=pause)
            row['audioBinding']={'id':item['id'],'text':row['text'],'character':row['character']}
            row['spokenText']=take['text']
            if marker:marker['plan']=copy.deepcopy(project['scriptPlan'])
        result=self.cut.normalize(project)
        if original.get('id'):result['id']=original['id']
        changed=sum(abs(a['start']-b['start'])>1e-6 for a,b in zip(before['textClips'],result['textClips']))
        return {'project':result,'summary':{'oldDuration':before['textClips'][project['textClips'].index(clip)]['duration'],'duration':span,'audioDuration':take['duration'],'delta':delta,'shiftedTexts':changed,'mode':mode,'bgm':'BGM 和音效保持原时间'}}
