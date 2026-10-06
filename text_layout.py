"""Pixel-based story text boxes shared by preview and editable draft export."""
from functools import lru_cache
import math
from pathlib import Path
from PIL import ImageFont

FONT = Path('C:/Windows/Fonts/msyh.ttc')

def default_layout():
    return {'width':1920,'height':1080,
            'narrator':dict(x=192,y=840,width=1536,height=192,size=36,lineHeight=48),
            'dialogue':dict(x=240,y=840,width=1488,height=192,size=36,lineHeight=48),
            'name':dict(x=240,y=780,width=1488,height=48,size=36,lineHeight=48,enabled=True)}

def normalize_layout(value, number):
    if not isinstance(value,dict):raise ValueError('剧情文字区域格式不正确')
    default=default_layout()
    result={k:int(number(value.get(k,default[k]),'文字参考画布'+k,320,3840)) for k in ('width','height')}
    result['paginate']=value.get('paginate',False) is True
    for key in ('narrator','dialogue','name'):
        box=value.get(key,default[key])
        if not isinstance(box,dict):raise ValueError('文字区域格式不正确')
        clean={k:int(number(box.get(k,default[key][k]),'文字区域'+k,*limits)) for k,limits in
               {'x':(0,result['width']),'y':(0,result['height']),'width':(1,result['width']),
                'height':(1,result['height']),'size':(12,240),'lineHeight':(12,480)}.items()}
        if clean['x']+clean['width']>result['width'] or clean['y']+clean['height']>result['height']:
            raise ValueError('文字区域超出参考画布，请调整起点或宽高')
        if clean['lineHeight']<clean['size']:raise ValueError('行高不能小于字号')
        if key=='name':clean['enabled']=box.get('enabled',True) is True
        result[key]=clean
    return result

@lru_cache(maxsize=64)
def font(size):
    return ImageFont.truetype(str(FONT) if FONT.exists() else 'DejaVuSans.ttf',size)

def wrap_text(text, box):
    face=font(box['size']);lines=[]
    for paragraph in text.split('\n'):
        line=''
        for char in paragraph:
            if line and face.getlength(line+char)>box['width']:
                lines.append(line);line=''
            line+=char
        lines.append(line)
    return lines

def resolve_layout(value, text, character, number):
    config=normalize_layout(value,number)
    kind=value.get('kind','narrator')
    if kind not in ('narrator','inner','dialogue','hero','heroine'):raise ValueError('文字分类不正确')
    box=config['narrator' if kind in ('narrator','inner') else 'dialogue']
    lines=wrap_text(text,box)
    name='【'+character+'】' if config['name']['enabled'] and kind not in ('narrator','inner') and character else ''
    capacity=max(1,box['height']//box['lineHeight'])
    pages=[lines[i:i+capacity] for i in range(0,len(lines),capacity)] if config['paginate'] else [lines]
    overflow=(not config['paginate'] and len(lines)*box['lineHeight']>box['height']) or box['lineHeight']>box['height'] or any(font(box['size']).getlength(line)>box['width'] for line in lines)
    if name:overflow=overflow or font(config['name']['size']).getlength(name)>config['name']['width'] or config['name']['lineHeight']>config['name']['height']
    return dict(config,kind=kind,lines=lines,pages=pages,nameText=name,overflow=bool(overflow))


def page_spans(clip, fps):
    pages=clip['layout'].get('pages',[clip['layout']['lines']]);count=len(pages)
    frames=math.floor(clip['duration']*fps+1e-7)
    if frames<count:raise ValueError('文字页数多于可播放帧数，请延长时长或扩大文字区域')
    bounds=[math.floor(i*frames/count)/fps for i in range(count)]+[clip['duration']]
    return [(pages[i],clip['start']+bounds[i],bounds[i+1]-bounds[i]) for i in range(count)]

def export_layout(script,draft,clip,project,tracks,rgb):
    """Each line and name remains ordinary editable text, with measured left anchors."""
    layout=clip['layout'];box=layout['narrator' if layout['kind'] in ('narrator','inner') else 'dialogue']
    parts=[]
    for lines,start,duration in page_spans(clip,project['fps']):
        parts.extend((str(i),line,dict(box,y=box['y']+i*box['lineHeight']),start,duration) for i,line in enumerate(lines) if line)
    if layout['nameText']:parts.append(('name',layout['nameText'],layout['name'],clip['start'],clip['duration']))
    for part,text,region,start_seconds,duration_seconds in parts:
        key=(clip['track'],part);start=round(start_seconds*1e6);duration=round((start_seconds+duration_seconds)*1e6)-start
        refs=tracks.setdefault(key,[])
        available=next((i for i,(end,_) in enumerate(refs) if end<=start),None)
        if available is None:
            available=len(refs);ref=script.append_track(draft.TrackSpec(draft.TrackType.text,f'剧情文字 {clip["track"]+1} · {part} · {available+1}'))
            refs.append((0,ref))
        ref=refs[available][1];refs[available]=(start+duration,ref)
        width=font(region['size']).getlength(text)
        settings=draft.ClipSettings(transform_x=(region['x']+width/2)/layout['width']*2-1,
                                    transform_y=1-(region['y']+region['size']/2)/layout['height']*2)
        style=clip['subtitleStyle']
        segment=draft.TextSegment(text,draft.Timerange(start,duration),
            style=draft.TextStyle(size=region['size']*108/layout['height'],color=rgb(style['color']),align=0,auto_wrapping=False),
            border=draft.TextBorder(color=rgb(style['borderColor']),width=style['borderWidth']),clip_settings=settings)
        #Use the same local font as measurement and browser preview.
        if FONT.exists():
            original=segment.export_material
            def material(original=original):
                import json
                value=original();content=json.loads(value['content'])
                content['styles'][0]['font']={'id':'','path':str(FONT),'name':'Microsoft YaHei'}
                value['content']=json.dumps(content,ensure_ascii=False);return value
            segment.export_material=material
        script.add_segment(segment,ref)
