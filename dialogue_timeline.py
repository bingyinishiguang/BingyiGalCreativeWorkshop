"""Validated independent audio clips, subtitle styling and draft export."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from subtitle_tools import validate_cues

DEFAULT_STYLE = {'x':0, 'y':-.8, 'size':8, 'color':'#ffffff', 'borderColor':'#000000',
                 'borderWidth':40, 'showCharacter':False}


def safe_name(name, item_id, suffix):
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:45] or '素材'
    return label+'-'+item_id[:8]+suffix


def normalize_dialogue(payload, audio_library, number):
    raw = payload.get('audioClips', [])
    if not isinstance(raw, list) or len(raw) > 1000:
        raise ValueError('音频片段最多一千个')
    clips = []
    occupied = {}
    for entry in raw:
        if not isinstance(entry, dict) or audio_library is None:
            raise ValueError('音频片段格式不正确')
        item = audio_library.get(entry.get('audio'))
        audio_library.file(item['id'])
        source = number(entry.get('sourceStart',0), '音频裁切起点', 0, item['duration'])
        duration = number(entry.get('duration',item['duration']-source), '音频时长', .001, item['duration'])
        if source+duration > item['duration']+.001:
            raise ValueError('音频裁切范围超过原文件')
        start = number(entry.get('start',0), '音频开始时间', 0, 10800)
        if start+duration > 10800:
            raise ValueError('音频结束时间超过三小时')
        track = int(number(entry.get('track',0), '音频轨道', 0, 15))
        kind = entry.get('kind', item['kind'])
        if kind not in ('dialogue','bgm','effect'):
            raise ValueError('音频类别不正确')
        key = (kind, track)
        if any(start < b-1e-6 and start+duration > a+1e-6 for a,b in occupied.get(key, [])):
            raise ValueError('同一音频轨道的片段不能重叠，请放到另一个轨道')
        occupied.setdefault(key,[]).append((start,start+duration))
        cues = validate_cues(entry.get('cues', item['cues']), item['duration'])
        clip_style = normalize_dialogue({'subtitleStyle':entry['subtitleStyle']},None,number)['subtitleStyle'] if isinstance(entry.get('subtitleStyle'),dict) else None
        clips.append({'audio':item['id'], 'start':start, 'sourceStart':source, 'duration':duration,
                      'track':track, 'kind':kind, 'volume':number(entry.get('volume',1), '音量', 0, 2),
                      'character':str(entry.get('character',item['character']))[:100],
                      'text':str(entry.get('text',item['text']))[:20000], 'cues':cues,
                      'subtitles':entry.get('subtitles', kind=='dialogue') is True,
                      **({'subtitleStyle':clip_style} if clip_style else {})})
        if 'manuscript' in entry:
            from manuscript_review import review_record
            clips[-1]['manuscript'] = review_record(entry['manuscript'])
        from timeline_identity import metadata
        metadata(entry,clips[-1])
    style = dict(DEFAULT_STYLE)
    raw_style = payload.get('subtitleStyle', {})
    if not isinstance(raw_style, dict):
        raise ValueError('字幕样式格式不正确')
    for key, limits in {'x':(-1,1),'y':(-1,1),'size':(2,50),'borderWidth':(0,100)}.items():
        style[key] = number(raw_style.get(key, style[key]), '字幕'+key, *limits)
    for key in ('color','borderColor'):
        value = str(raw_style.get(key,style[key]))
        if not re.fullmatch(r'#[a-fA-F0-9]{6}', value):
            raise ValueError('字幕颜色格式不正确')
        style[key] = value
    style['showCharacter'] = raw_style.get('showCharacter',False) is True
    order = payload.get('roleOrder',[0,1])
    if order not in ([0,1],[1,0]):
        raise ValueError('人物图层顺序不正确')
    texts = payload.get('textClips', [])
    if not isinstance(texts,list) or len(texts)>2000:
        raise ValueError('独立文字最多两千个片段')
    clean_texts=[]
    for entry in texts:
        if not isinstance(entry,dict):
            raise ValueError('独立文字格式不正确')
        text=str(entry.get('text','')).strip()
        if not text or len(text)>2000:
            raise ValueError('独立文字不能为空且每段最多两千字')
        start=number(entry.get('start',0),'文字开始时间',0,10800)
        duration=number(entry.get('duration',3),'文字时长',.001,3600)
        if start+duration>10800:
            raise ValueError('文字结束时间超过三小时')
        text_style=normalize_dialogue({'subtitleStyle':entry.get('subtitleStyle',style)},None,number)['subtitleStyle']
        clean_texts.append({'text':text,'start':start,'duration':duration,
                            'character':str(entry.get('character','旁白'))[:100],
                            'track':int(number(entry.get('track',0),'文字轨道',0,15)),
                            'subtitleStyle':text_style})
        if 'layout' in entry:
            from text_layout import resolve_layout
            clean_texts[-1]['layout']=resolve_layout(entry['layout'],text,clean_texts[-1]['character'],number)
            from text_layout import page_spans
            if not clean_texts[-1]['layout']['overflow']:page_spans(clean_texts[-1],int(payload.get('fps',30)))
        from timeline_identity import metadata
        metadata(entry,clean_texts[-1])
    from timeline_identity import identify
    identify(clips,'audio');identify(clean_texts,'text')
    return {'audioClips':clips, 'textClips':clean_texts, 'subtitleStyle':style, 'roleOrder':order,
            'gap':number(payload.get('gap',.3),'默认间隔',0,10)}


def export_dialogue(script, draft, project, library, media, final, pack=None):
    from draft_media import MediaPack
    pack = pack or MediaPack(media, final/'media')
    audio_tracks, subtitle_tracks, materials = {}, {}, {}
    style = project['subtitleStyle']
    rgb = lambda value: tuple(int(value[i:i+2],16)/255 for i in (1,3,5))
    cue_intervals = []
    #Put sound below visual tracks; subtitles are appended after all sound tracks.
    for clip_index,clip in enumerate(sorted(project['audioClips'],key=lambda c:(c['kind'],c['track'],c['start']))):
        item_id = clip['audio']
        if item_id not in materials:
            item = library.get(item_id)
            source = library.file(item_id)
            target = pack.copy(source, item['name'])
            material = draft.AudioMaterial(str(target))
            material.path = pack.path(target)
            materials[item_id] = material
        material = materials[item_id]
        key = (clip['kind'],clip['track'])
        if key not in audio_tracks:
            name = {'dialogue':'对白','bgm':'BGM','effect':'音效'}[clip['kind']]+f" {clip['track']+1}"
            audio_tracks[key] = script.append_track(draft.TrackSpec(draft.TrackType.audio,name))
        source_us = round(clip['sourceStart']*1_000_000)
        duration_us = min(round(clip['duration']*1_000_000),material.duration-source_us)
        if duration_us <= 0:
            raise ValueError('音频裁切后没有有效内容')
        start_us = round(clip['start']*1_000_000)
        script.add_segment(draft.AudioSegment(material,draft.Timerange(start_us,duration_us),
                           source_timerange=draft.Timerange(source_us,duration_us),volume=clip['volume']),audio_tracks[key])
        if clip['subtitles']:
            for cue in clip['cues']:
                left = max(cue['start'],clip['sourceStart'])
                right = min(cue['end'],clip['sourceStart']+clip['duration'])
                if right <= left:
                    continue
                text = cue['text']
                cue_style = clip.get('subtitleStyle',style)
                if cue_style['showCharacter'] and clip['character']:
                    text = clip['character']+'：'+text
                cue_intervals.append((round((clip['start']+left-clip['sourceStart'])*1_000_000),
                                      round((clip['start']+right-clip['sourceStart'])*1_000_000),text,cue_style,
                                      clip['character'] or f'对白组 {clip_index+1}'))
    layout_tracks={}
    for clip in project.get('textClips',[]):
        if 'layout' in clip:
            from text_layout import export_layout
            if clip['layout']['overflow']:raise ValueError('文字超出剧情区域，请调整排版或拆分台词')
            export_layout(script,draft,clip,project,layout_tracks,rgb)
            continue
        text=clip['text'];text_style=clip['subtitleStyle']
        if text_style['showCharacter'] and clip['character']:
            text=clip['character']+'：'+text
        cue_intervals.append((round(clip['start']*1_000_000),round((clip['start']+clip['duration'])*1_000_000),
                              text,text_style,f"文字 {clip['track']+1} · {clip['character'] or '旁白'}"))
    #Interval partitioning also handles overlapping captions from different audio tracks.
    for start,end,text,style,group in sorted(cue_intervals,key=lambda c:c[0]):
        if end <= start:
            continue
        group_tracks = subtitle_tracks.setdefault(group,[])
        available = next((i for i,(last,_) in enumerate(group_tracks) if last <= start),None)
        if available is None:
            available = len(group_tracks)
            #Include a global counter to keep track names unique even when role names collide.
            count = sum(len(tracks) for tracks in subtitle_tracks.values())+1
            ref = script.append_track(draft.TrackSpec(draft.TrackType.text,f'字幕 {count} · {group[:40]}'))
            group_tracks.append((0,ref))
        ref = group_tracks[available][1]
        group_tracks[available] = (end,ref)
        settings = draft.ClipSettings(transform_x=style['x'], transform_y=style['y'])
        #Ordinary independent text avoids Jianying's recognized-caption style linkage.
        #Wrap locally rather than setting auto_wrapping, which exports type="subtitle".
        text = '\n'.join('\n'.join(line[i:i+22] for i in range(0,len(line),22))
                         for line in text.split('\n'))
        text_style = draft.TextStyle(size=style['size'], color=rgb(style['color']),align=1,
                                     auto_wrapping=False)
        border = draft.TextBorder(color=rgb(style['borderColor']),width=style['borderWidth'])
        script.add_segment(draft.TextSegment(text,draft.Timerange(start,end-start),style=text_style,
                                            border=border,clip_settings=settings),ref)
