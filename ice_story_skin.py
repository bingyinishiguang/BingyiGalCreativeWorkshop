"""Approved ice artwork, with a single measured contract for preview and export."""
import math
import os
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

THEMES = {
    'ice': dict(hue=0, saturation=1, ink='#1f4688'),
    'violet': dict(hue=37, saturation=.85, ink='#583477'),
    'amber': dict(hue=-132, saturation=.8, ink='#70502b'),
    'slate': dict(hue=-8, saturation=.35, ink='#354d65'),
}

def theme(row, settings):
    return row.get('skin') or settings.get('skin','ice')

def themed_read(kit, name, skin):
    image=read(kit,name)
    if skin=='ice':return image
    palette=THEMES[skin]
    hue,saturation,value=image.convert('RGB').convert('HSV').split()
    hue=hue.point([(i+palette['hue'])%256 for i in range(256)])
    saturation=saturation.point([round(i*palette['saturation']) for i in range(256)])
    colored=Image.merge('HSV',(hue,saturation,value)).convert('RGB').convert('RGBA')
    colored.putalpha(image.getchannel('A'))
    return colored

@lru_cache(maxsize=48)
def font(size, name=False):
    default_fonts = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
    preferred=Path(os.environ.get('BINGYI_FONT_DIR',str(default_fonts)))
    candidates=[preferred/('NotoSansSC-VF.ttf' if name else 'NotoSerifSC-VF.ttf'),
                default_fonts/('msyh.ttc' if name else 'simsun.ttc'),default_fonts/'msyh.ttc']
    for path in candidates:
        if not path.is_file():
            continue
        try:
            result=ImageFont.truetype(str(path),size)
        except OSError:
            continue
        try:
            result.set_variation_by_axes([400])
        except OSError:
            pass  # Static Windows fonts have no variation axes.
        return result
    raise ValueError('缺少中文字体，请安装宋体、微软雅黑或思源字体后重新预览')

@lru_cache(maxsize=4096)
def glyph_signature(char,name=False):
    mask=font(34,name).getmask(char)
    return mask.size,bytes(mask)

def validate_text(value,name=False):
    missing=glyph_signature('\U0010ffff',name)
    unsupported=[c for c in dict.fromkeys(value) if not c.isspace() and glyph_signature(c,name)==missing]
    if unsupported:
        raise ValueError('冰翼字体缺少这些字符：'+', '.join(f'U+{ord(c):04X}' for c in unsupported[:8])+'，请替换这些字符后重试')

def geometry(row, settings):
    size=settings['fontSize']
    mode=settings.get('dialogueLayout','auto')
    extended=mode=='extended' or size>40
    top,bottom=(798,1008) if extended else (885,1000)
    line_height=max(62,size+20)
    count=min(3 if extended else 2,max(1,1+(bottom-top-size-8)//line_height))
    x=max(425,min(1500,row['textX']))
    preferred_y=798 if extended and row['textY']==885 else row['textY']
    y=max(top,min(bottom-(count-1)*line_height-size-8,preferred_y))
    return dict(x=x,y=y,w=1720-x,h=(count-1)*line_height+size+8,
                lines=count,lineHeight=line_height,extended=extended,nameX=540,plateX=480,nameY=733 if extended else 816)

def read(kit, name):
    path=kit/name
    if not path.is_file():raise ValueError('冰翼皮肤素材缺失：'+name+'，请重新准备 story-kit')
    return cached_image(str(path),path.stat().st_mtime_ns).copy()

@lru_cache(maxsize=16)
def cached_image(path, stamp):
    with Image.open(path) as image:return image.convert('RGBA')

def has_label(row, characters):
    return row['type']=='thought' or (row['type']=='dialogue' and any(c['id']==row['speakerId'] and c['name'] for c in characters))

def composite(canvas, kit, row, settings, characters):
    g=geometry(row,settings);named=has_label(row,characters)
    def read_panel(name):
        panel=themed_read(kit,name,theme(row,settings))
        original_alpha=panel.getchannel('A')
        alpha=original_alpha.point(lambda value:round(value*settings.get('panelOpacity',.62)))
        # Fade the plate while keeping the logo and nameplate legible.
        if name in ('dialogue.png','extended.png','extended-no-nameplate.png'):
            offset=660 if name.startswith('extended') else 720
            logo_y=259 if name.startswith('extended') else 199
            logo=(34,logo_y,382,logo_y+134)
            logo_mask=read(kit,'brand-logo.png').getchannel('A').resize((348,134),Image.Resampling.LANCZOS)
            alpha.paste(original_alpha.crop(logo),logo,logo_mask)
        panel.putalpha(alpha)
        return panel
    if g['extended']:
        panel=read_panel('extended-no-nameplate.png')
        canvas.alpha_composite(panel,(0,660))
    else:
        # Keep the exact approved composite everywhere except the absent nameplate.
        # Separately compositing the old source layers changes their alpha blend.
        box=(419,799,719,865)
        patch=canvas.crop(box)
        for filename in ('dialogue-base.png','dialogue-decoration.png'):
            patch.alpha_composite(read_panel(filename).crop((419,79,719,145)))
        canvas.alpha_composite(read_panel('dialogue.png'),(0,720))
        canvas.paste(patch,(419,799))
    if named:
        plate=themed_read(kit,'nameplate.png',theme(row,settings))
        canvas.alpha_composite(plate,(g['plateX'],g['nameY']-17))

def draw_text(canvas, kit, row, settings, characters, segment, lines, page_index, seconds):
    g=geometry(row,settings);draw=ImageDraw.Draw(canvas)
    ink=THEMES[theme(row,settings)]['ink']
    for j,line in enumerate(lines):
        draw.text((g['x'],g['y']+j*g['lineHeight']),line,font=font(settings['fontSize']),
                  fill=ink,anchor='lt')
    c=next((c for c in characters if c['id']==row['speakerId']),None)
    label=c['name'] if c and row['type'] in ('dialogue','thought') else ''
    if row['type']=='thought':label=(label+' · ' if label else '')+'心声'
    namefont=font(27,True)
    if namefont.getlength(label)>185:
        while label and namefont.getlength(label+'…')>185:label=label[:-1]
        label+='…'
    if label:draw.text((g['nameX'],g['nameY']),label,font=namefont,fill='#ffffff',anchor='lt')
    if len(segment['pages'])>1:
        draw.text((1700,1032),f'{page_index+1}/{len(segment["pages"])}',font=font(18,True),fill=ink,anchor='rm')
    from game_hud import draw_hud
    draw_hud(canvas,seconds,segment['voiceDuration'],settings['indicator'])



def special_lines(value,size,width,limit,label,name=False):
    from gal_story_render import lines_for
    lines=lines_for(value,size,width,name=name)
    if len(lines)>limit:raise ValueError(label+'过长，请缩短文字或增加片段；不会截掉内容')
    return lines

def validate_special(row):
    if row['type']=='choice':
        for option in row['options']:special_lines(option,30,870,2,'选项',True)
        if row['text']:special_lines(row['text'],30,1040,2,'选择提示')
    elif row['captionEnabled'] and row['captionText']:
        special_lines(row['captionText'],48,850,3,'过场文字')

def draw_special(canvas,kit,row,seconds,duration):
    draw=ImageDraw.Draw(canvas)
    if row['type']=='eyecatch':
        if not row['captionEnabled'] or not row['captionText']:return
        lines=special_lines(row['captionText'],48,850,3,'过场文字')
        height=len(lines)*68
        if not row['backgroundId'].startswith('kit:time-card-'):
            overlay=Image.new('RGBA',canvas.size)
            ImageDraw.Draw(overlay).rounded_rectangle((475,390,1445,690),radius=28,fill=(239,249,255,215),outline=(57,124,194,220),width=3)
            canvas.alpha_composite(overlay);draw=ImageDraw.Draw(canvas)
        for j,line in enumerate(lines):
            night=row['backgroundId']=='kit:time-card-night'
            draw.text((960,540-height/2+j*68),line,font=font(48),fill='#f9feff' if night else '#1f4688',
                      stroke_width=1,stroke_fill='#1f4688' if night else 'white',anchor='mt')
        return
    options=[special_lines(v,30,870,2,'选项',True) for v in row['options']]
    tall=any(len(lines)>1 for lines in options)
    height,step=(148,174) if tall else (100,126)
    top=round(445-(height+(len(options)-1)*step)/2)
    if row['text']:
        for j,line in enumerate(special_lines(row['text'],30,1040,2,'选择提示')):
            draw.text((960,max(50,top-110)+j*42),line,font=font(30),fill='white',stroke_width=2,stroke_fill='#1f4688',anchor='mt')
    for i,lines in enumerate(options):
        selected=seconds>=duration*.6 and i==row['selectedOption']
        state='selected' if selected else 'idle'
        panel=read(kit,'choice-'+('tall-' if tall else '')+state+'.png')
        y=top+i*step;canvas.alpha_composite(panel,(440,y))
        draw=ImageDraw.Draw(canvas)
        for j,line in enumerate(lines):
            draw.text((535,y+(34 if tall else 32)+j*40),line,font=font(30,True),
                      fill='white' if selected else '#1f4688',anchor='lt')
