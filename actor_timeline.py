"""Explicit, frame-aligned actor changes; no inferred emotion or speaker coupling."""
import copy
import math
from composition_library import alignment

def normalize_events(events,number):
    if not isinstance(events,list) or len(events)>20:raise ValueError('每句最多二十个人物变化')
    clean=[]
    for event in events:
        if not isinstance(event,dict) or event.get('action') not in ('show','hide','change'):
            raise ValueError('人物变化类型不正确')
        slot=number(event.get('slot',0),'人物槽位',0,1)
        if slot!=int(slot):raise ValueError('人物槽位必须为整数')
        e=dict(slot=int(slot),action=event['action'],offset=number(event.get('offset',0),'人物变化时间',0,3590))
        if e['action']!='hide':
            if not isinstance(event.get('id'),str) or not event['id'] or len(event['id'])>64:raise ValueError('请选择人物立绘')
            e['id']=event['id']
            if 'alignment' in event:e['alignment']=alignment(event['alignment'])
        clean.append(e)
    return sorted(clean,key=lambda e:e['offset'])

def switch(actor,event,cut):
    old=cut.sprites.metadata(actor['id']);new=cut.sprites.metadata(event['id'])
    if not new or not cut.sprites.file(event['id'],False):raise ValueError('人物变化的立绘丢失或已删除')
    if (old['game'],old['character'],old['body'])!=(new['game'],new['character'],new['body']):
        raise ValueError('换表情需要同一角色和姿势，请先建立对应表情组')
    saved=actor.get('alignment');incoming=event.get('alignment')
    if event['id']!=actor['id'] and (not saved or not incoming):raise ValueError('换表情请先绑定校准表情组')
    if incoming:
        if not saved or any(saved[k]!=incoming[k] for k in ('groupId','version','width','height')):
            raise ValueError('人物变化的表情组或校准版本不匹配，请重新核对')
        actor['alignment']=copy.deepcopy(incoming)
    actor['id']=event['id']

def expand(scene,templates,events,duration,span,fps,cut):
    end=round(span*fps);changes={};seen=set()
    for e in events:
        if e['offset']>=duration:raise ValueError('人物变化时间必须小于该句实际播放或停留时长')
        frame=math.ceil(e['offset']*fps-1e-8)
        if frame>=end:raise ValueError('人物变化太靠近句尾，请提前至少一帧')
        if (frame,e['slot']) in seen:raise ValueError('同一帧同一人物只能有一个变化')
        seen.add((frame,e['slot']));changes.setdefault(frame,[]).append(e)
    actors=copy.deepcopy(scene['actors']);result=[];left=0
    for frame in sorted(set(changes)|{end}):
        if frame>left:result.append(dict(copy.deepcopy(scene),actors=copy.deepcopy(actors),duration=(frame-left)/fps))
        for e in changes.get(frame,[]):
            actor=next((a for a in actors if a['slot']==e['slot']),None)
            if e['action']=='hide':actors=[a for a in actors if a['slot']!=e['slot']]
            elif e['action']=='show':
                if actor is None:
                    template=next((a for a in templates if a['slot']==e['slot']),None)
                    if template is None:raise ValueError('请先给该人物槽位放好基础立绘和构图')
                    actor=copy.deepcopy(template);actors.append(actor)
                switch(actor,e,cut)
            else:
                if actor is None:raise ValueError('人物尚未出场，请先添加出场变化')
                switch(actor,e,cut)
        left=frame
    for i,s in enumerate(result):
        if i:s['restart']=False
    return result
