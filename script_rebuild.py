"""Compare a fresh build to its generated baseline before keeping manual edits."""
import copy
from rough_cut import number
from script_plan import build_timeline


FIELDS={'scenes':('background','backgroundTransform','actors','loop','restart'),
        'textClips':('text','character','subtitleStyle','layout'),
        'audioClips':('volume','subtitleStyle','subtitles','cues')}


def preview(payload, cut):
    current=cut.normalize(payload)
    result=build_timeline(payload,cut,number)
    fresh=result['project'];baseline=current.get('scriptBaseline')
    kept=copy.deepcopy(fresh);count=0;conflicts=[]
    if baseline:
        for kind,fields in FIELDS.items():
            originals={c.get('id'):c for c in baseline[kind] if c.get('id')}
            generated={c.get('id'):c for c in fresh[kind] if c.get('id')}
            edited_ids={c.get('id') for c in current[kind]}
            if any(key not in edited_ids and key in generated for key in originals):
                conflicts.append('有人工删除的片段，重新铺轨会恢复；请先另存精修项目再决定')
            for edited in current[kind]:
                if edited.get('id') not in originals and edited.get('id') not in generated:
                    conflicts.append('有人工新增的片段，无法自动合并；请先另存精修项目再决定')
            for edited in current[kind]:
                key=edited.get('id');base=originals.get(key);new=generated.get(key)
                if not base:continue
                if new and any(edited.get(f)!=base.get(f) and edited.get(f)!=new.get(f) for f in ('start','duration','sourceStart')):
                    conflicts.append('有人工移动或裁切的片段，无法安全重排；请先另存精修项目再决定')
                modified=[f for f in fields if edited.get(f)!=base.get(f)]
                if not modified:continue
                if not new:
                    conflicts.append('已删除或拆分的句子有人工修改，请从原项目核对');continue
                target=next(c for c in kept[kind] if c.get('id')==key)
                for field in modified:
                    if new.get(field)!=base.get(field) and new.get(field)!=edited.get(field):
                        conflicts.append(f'{edited.get("character") or "镜头"}的 {field} 同时在校对表和时间轴修改，需要手动核对')
                    else:
                        if field in edited:target[field]=copy.deepcopy(edited[field])
                        else:target.pop(field,None)
                        count+=1
        if not conflicts:
            try:kept=cut.normalize(kept)
            except ValueError as error:conflicts.append(str(error))
    if payload.get('id'):
        fresh['id']=payload['id'];kept['id']=payload['id']
    return {'project':fresh,'preservedProject':kept if baseline and not conflicts else None,
            'schedule':result['schedule'],'summary':{'manualFields':count,'hasBaseline':bool(baseline),
            'conflicts':list(dict.fromkeys(conflicts)),'oldScenes':len(current['scenes']),'scenes':len(fresh['scenes']),
            'oldDuration':sum(s['duration'] for s in current['scenes']),'duration':sum(s['duration'] for s in fresh['scenes']),
            'note':'开始时间、手动裁切和新增/删除的片段不自动合并；原项目可先另存，应用可撤销。'}}
