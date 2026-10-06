"""Stable timeline identities and bounded, persisted voice links."""
import json
import re
import uuid


def identify(clips, kind):
    seen=set()
    for index, clip in enumerate(clips):
        key=clip.get('id')
        if key is None:
            key=uuid.uuid5(uuid.NAMESPACE_URL,kind+':'+str(index)+':'+json.dumps(clip,sort_keys=True,ensure_ascii=False)).hex
        if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',key) or key in seen:
            raise ValueError('时间轴片段编号为空、重复或格式不正确')
        seen.add(key);clip['id']=key
    return clips


def metadata(source, target):
    for key in ('id','sourceRow','linkedText'):
        if key in source:
            value=source[key]
            if not isinstance(value,str) or not 1<=len(value)<=64 or (key!='sourceRow' and not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',value)):
                raise ValueError('时间轴关联编号格式不正确')
            target[key]=value
    if 'voice' in source:
        value=source['voice']
        if not isinstance(value,dict):raise ValueError('配音记录格式不正确')
        versions=value.get('versions',[])
        if not isinstance(versions,list) or len(versions)>500 or any(not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{32}',v) for v in versions):
            raise ValueError('单句配音版本格式不正确或超过五百个')
        clean={'versions':list(dict.fromkeys(versions))}
        for key,limit in (('take',64),('voiceId',64),('spokenText',1000),('displayText',2000),('character',100),('language',16)):
            if key in value:
                if not isinstance(value[key],str) or len(value[key])>limit:raise ValueError('配音记录字段格式不正确')
                clean[key]=value[key]
        if 'speed' in value:
            from rough_cut import number
            clean['speed']=number(value['speed'],'配音语速',.5,2)
        target['voice']=clean
