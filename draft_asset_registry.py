"""填充剪映草稿的本地素材列表，独立于时间轴片段。

字段参考：border1px/JianYingProDraft 的 .draftDemo/Normal/draft_meta_info.json。"""
from pathlib import Path
import time
import json

def register(script,meta,media_root):
    now=int(time.time()*1_000_000);items=[]
    for media in list(script.materials.videos)+list(script.materials.audios):
        if hasattr(media,'local_material_id'):media.local_material_id=media.material_id
        kind=getattr(media,'material_type','music')
        items.append(dict(id=media.material_id,file_Path=media.path,extra_info=Path(media.path).name,
            metetype=kind,type=0,duration=5_000_000 if kind=='photo' else media.duration,
            width=getattr(media,'width',0),height=getattr(media,'height',0),create_time=now//1_000_000,
            import_time=now//1_000_000,import_time_ms=now,item_source=1,md5='',
            roughcut_time_range=dict(duration=-1,start=-1),sub_time_range=dict(duration=-1,start=-1)))
    groups=meta.setdefault('draft_materials',[])
    group=next((g for g in groups if g['type']==0),None)
    if group is None:group=dict(type=0,value=[]);groups.append(group)
    group['value']=items
    meta['draft_timeline_materials_size']=sum((media_root/Path(m.path).name).stat().st_size for m in list(script.materials.videos)+list(script.materials.audios) if (media_root/Path(m.path).name).is_file())
    return items

def actor_pack(materials,project,used):
    items=[]
    actors=[a for s in project['scenes']+[project.get('scriptBase',{'actors':[]})] for a in s['actors']]
    for key,value in materials.items():
        if key[0]!='sprite':continue
        placement=json.loads(key[2]) if key[2] else None
        placements=[];seen=set()
        for actor in actors:
            match=actor['id']==key[1] if not placement else all(actor.get('alignment',{}).get(k)==placement[k] for k in ('groupId','version','width','height'))
            identity=(actor['slot'],json.dumps(actor['transform'],sort_keys=True))
            if match and identity not in seen:
                seen.add(identity);placements.append(dict(slot=actor['slot'],transform=actor['transform']))
        items.append(dict(sourceId=key[1],alignment=placement,path=value.path,materialId=value.material_id,
                          used=value.material_id in used,placements=placements))
    return dict(canvas={k:project[k] for k in ('width','height')},items=items)
