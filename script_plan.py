"""Reviewed sentence plans and frame-aligned Galgame-style timeline generation."""
from __future__ import annotations
import copy
import math
import uuid
from composition_library import alignment

KINDS = ('narrator', 'heroine', 'inner', 'hero', 'dialogue')

def normalize_plan(value, number):
    if value is None:return {'rows':[], 'gap':.3}
    if not isinstance(value,dict):raise ValueError('台词校对表格式不正确')
    rows=value.get('rows',[])
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('台词校对表最多五百句')
    result=[];seen=set()
    for index,row in enumerate(rows):
        if not isinstance(row,dict):raise ValueError('台词行格式不正确')
        key=str(row.get('id',''))
        if not key or len(key)>64 or key in seen:raise ValueError('台词编号为空或重复')
        seen.add(key)
        kind=row.get('kind','narrator')
        if kind not in KINDS:raise ValueError('台词分类不正确')
        text=str(row.get('text','')).strip()
        if not text or len(text)>2000:raise ValueError(f'第 {index+1} 句文字不能为空且最多两千字')
        voice=row.get('voice',kind in ('heroine','inner'))
        if not isinstance(voice,bool):raise ValueError('配音开关格式不正确')
        voice_explicit=row.get('voiceExplicit',True)
        if not isinstance(voice_explicit,bool):raise ValueError('配音选择来源格式不正确')
        item={'id':key,'kind':kind,'text':text,'character':str(row.get('character',''))[:100],
              'voice':voice,'voiceExplicit':voice_explicit,'audio':str(row.get('audio',''))[:64],
              'hold':number(row.get('hold',3),'无声文字停留',.1,3590),
              'pause':None if row.get('pause') is None else number(row['pause'],'句间停顿',0,10)}
        if 'holdExplicit' in row:item['holdExplicit']=row['holdExplicit'] is True
        if item['audio']:
            binding=row.get('audioBinding')
            if binding is None:binding={'id':item['audio'],'text':text,'character':item['character']}
            if not isinstance(binding,dict) or not all(isinstance(binding.get(k),str) for k in ('id','text','character')):
                raise ValueError('音频核对记录格式不正确')
            if len(binding['id'])>64 or len(binding['text'])>2000 or len(binding['character'])>100:
                raise ValueError('音频核对记录过长')
            item['audioBinding']={k:binding[k].strip() for k in ('id','text','character')}
        for field in ('voicePreset','language','take'):
            if field in row:item[field]=str(row[field])[:64]
        if 'spokenText' in row:
            spoken=row['spokenText']
            if not isinstance(spoken,str) or not 1<=len(spoken.strip())<=1000:raise ValueError('实际配音文字应为 1–1000 字')
            item['spokenText']=spoken.strip()
        if 'sceneKey' in row:
            if not isinstance(row['sceneKey'],str) or len(row['sceneKey'])>64:raise ValueError('场景关联编号格式不正确')
            item['sceneKey']=row['sceneKey']
        if 'versions' in row:
            if not isinstance(row['versions'],list) or len(row['versions'])>500:raise ValueError('单句配音版本最多五百个')
            item['versions']=[str(v)[:64] for v in row['versions']]
        if 'warnings' in row:
            if not isinstance(row['warnings'],list) or len(row['warnings'])>20:raise ValueError('台词提示格式不正确')
            item['warnings']=[str(v)[:200] for v in row['warnings']]
            item['reviewed']=row.get('reviewed') is True
        if 'source' in row:
            source=row['source']
            if not isinstance(source,dict):raise ValueError('剧本来源格式不正确')
            item['source']={k:str(source.get(k,''))[:2000] for k in ('file','line','raw')}
        if 'actorEvents' in row:
            from actor_timeline import normalize_events
            item['actorEvents']=normalize_events(row['actorEvents'],number)
        expression=row.get('expression')
        if expression is not None:
            if not isinstance(expression,dict) or not isinstance(expression.get('id'),str):raise ValueError('台词表情格式不正确')
            item['expression']={'id':expression['id'][:64],'slot':int(number(expression.get('slot',0),'表情角色槽位',0,1))}
            if 'alignment' in expression:item['expression']['alignment']=alignment(expression['alignment'])
        result.append(item)
    plan={'rows':result,'gap':number(value.get('gap',.3),'默认句间停顿',0,10)}
    if 'directives' in value:
        if not isinstance(value['directives'],list) or len(value['directives'])>1000:raise ValueError('场景说明格式不正确')
        plan['directives']=[{k:str(v.get(k,''))[:(64 if k=='id' else 2000)] for k in ('line','type','value','raw','id')} for v in value['directives'] if isinstance(v,dict)]
    if 'sceneBindings' in value:
        bindings=value['sceneBindings']
        if not isinstance(bindings,dict) or len(bindings)>1000 or any(not isinstance(k,str) or not 1<=len(k)<=64 or not isinstance(v,str) or len(v)>64 for k,v in bindings.items()):raise ValueError('场景素材绑定格式不正确')
        plan['sceneBindings']=dict(bindings)
    if 'layout' in value:
        from text_layout import normalize_layout
        plan['layout']=normalize_layout(value['layout'],number)
    if 'timing' in value:
        if not isinstance(value['timing'],dict):raise ValueError('默认文字时长格式不正确')
        plan['timing']={k:number(value['timing'].get(k,3),'默认文字时长',.1,3590) for k in ('silentHold','dialogueHold')}
    return plan

def build_timeline(payload, cut, number):
    plan=normalize_plan(payload.get('scriptPlan'),number)
    if not plan['rows']:raise ValueError('请先添加台词并确认分类、配音和表情')
    if payload.get('reviewed') is not True:raise ValueError('请先确认台词分类与素材绑定')
    #Validate the original project before constructing a replacement in memory.
    project=cut.normalize(payload)
    base_index=int(number(payload.get('baseScene',0),'基础镜头',0,len(project['scenes'])-1))
    base=copy.deepcopy(project.get('scriptBase') or project['scenes'][base_index]);fps=project['fps']
    scenes=[];voices=[];texts=[];schedule=[];frame=0
    for index,row in enumerate(plan['rows']):
        if row.get('warnings') and not row.get('reviewed'):raise ValueError(f'第 {index+1} 句有待确认的解析提示')
        item=None
        if row['voice']:
            if not row['audio']:raise ValueError(f'第 {index+1} 句已开启配音，请绑定音频或关闭配音')
            if row['audioBinding']!={'id':row['audio'],'text':row['text'],'character':row['character'].strip()}:
                raise ValueError(f'第 {index+1} 句文字或角色已变更，请试听并核对旧音频')
            item=cut.audio_library.get(row['audio']);cut.audio_library.file(item['id'])
            duration=item['duration']
            if duration>3590:raise ValueError('单句音频过长，请先拆分音频文件再导入')
        else:
            timing=plan.get('timing')
            duration=timing['silentHold' if row['kind'] in ('narrator','inner') else 'dialogueHold'] if timing and row.get('holdExplicit') is False else row['hold']
        pause=0 if index==len(plan['rows'])-1 else (plan['gap'] if row['pause'] is None else row['pause'])
        frames=math.ceil((duration+pause)*fps-1e-8);span=frames/fps;start=frame/fps
        scene=copy.deepcopy(base);
        if scenes:scene['background']=scenes[-1]['background']
        bound=plan.get('sceneBindings',{}).get(row.get('sceneKey',''))
        if row.get('sceneKey') and not bound:raise ValueError(f'第 {index+1} 句的场景尚未确认具体背景，请在场景素材中选图')
        if bound:
            cut.backgrounds.get(bound);cut.backgrounds.file(bound)
            scene['background']=bound
        if scenes:scene['actors']=copy.deepcopy(scenes[-1]['actors'])
        scene.update(duration=span,restart=base.get('restart',False) if index==0 else False)
        expression=row.get('expression')
        if expression:
            actor=next((a for a in scene['actors'] if a['slot']==expression['slot']),None)
            if actor is None:raise ValueError(f'第 {index+1} 句对应人物槽位为空，请先放好人物')
            if expression['id']!=actor['id']:
                old=cut.sprites.metadata(actor['id']);new=cut.sprites.metadata(expression['id'])
                if not new or (old['game'],old['character'],old['body'])!=(new['game'],new['character'],new['body']):raise ValueError('换表情需要同一角色和姿势')
                if 'alignment' not in expression:raise ValueError('换表情请先建立并绑定表情组')
                if expression['alignment']['groupId']!=actor.get('alignment',{}).get('groupId'):raise ValueError('表情组与基础人物不匹配，请重新校对')
            if 'alignment' in expression and 'alignment' in actor:
                if any(expression['alignment'][k]!=actor['alignment'][k] for k in ('groupId','version','width','height')):
                    raise ValueError('表情组校准版本与基础人物不同，请重新选择表情')
            actor['id']=expression['id']
            if 'alignment' in expression:actor['alignment']=copy.deepcopy(expression['alignment'])
        from actor_timeline import expand
        pieces=expand(scene,base['actors'],row.get('actorEvents',[]),duration,span,fps,cut)
        for part,piece in enumerate(pieces):piece.update(id=uuid.uuid5(uuid.NAMESPACE_URL,'scene:'+row['id']+':'+str(part)).hex,sourceRow=row['id'])
        scenes.extend(pieces)
        character=row['character'] or {'narrator':'旁白','heroine':'女主','inner':'心理描写','hero':'男主','dialogue':'对话'}[row['kind']]
        texts.append(dict(id=uuid.uuid5(uuid.NAMESPACE_URL,'text:'+row['id']).hex,sourceRow=row['id'],text=row['text'],character=character,start=start,duration=span,track=0,subtitleStyle=copy.deepcopy(project['subtitleStyle'])))
        if 'layout' in plan:
            from text_layout import resolve_layout
            texts[-1]['layout']=resolve_layout(dict(plan['layout'],kind=row['kind']),row['text'],row['character'],number)
            if texts[-1]['layout']['overflow']:raise ValueError(f'第 {index+1} 句超出文字区域，请扩大区域或拆分台词')
        if item:voices.append(dict(id=uuid.uuid5(uuid.NAMESPACE_URL,'audio:'+row['id']).hex,sourceRow=row['id'],linkedText=texts[-1]['id'],audio=item['id'],start=start,sourceStart=0,duration=duration,track=0,kind='dialogue',volume=1,character=character,text=row['text'],cues=[],subtitles=False))
        schedule.append(dict(id=row['id'],start=start,duration=duration,pause=pause,end=(frame+frames)/fps))
        frame+=frames
    result=copy.deepcopy(project);result.update(scenes=scenes,textClips=texts,audioClips=[c for c in project['audioClips'] if c['kind']!='dialogue']+voices,scriptPlan=plan,gap=plan['gap'])
    if 'layout' in plan or 'timing' in plan:result['scriptTiming']={'plan':copy.deepcopy(plan)}
    if 'scriptBase' in project or any('actorEvents' in row for row in plan['rows']):
        result['scriptBase']=base
        result['scriptTiming']={'plan':copy.deepcopy(plan)}
    result=cut.normalize(result)
    result['scriptBaseline']={k:copy.deepcopy(result[k]) for k in ('scenes','textClips','audioClips')}
    if 'scriptBase' in result:result['scriptTiming']['base']=copy.deepcopy(result['scriptBase'])
    if payload.get('id'):result['id']=payload['id']
    return {'project':result,'schedule':schedule}
