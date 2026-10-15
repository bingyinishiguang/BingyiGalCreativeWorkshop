"""Reference-style visual quick menu and voice HUD for preview and draft layers."""
import math
import os
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app_paths import resource_root

MENU_BOX=(480,1034,1380,34)
VOICE_BOX=(1670,981,220,55)
NEXT_BOX=(1588,998,32,32)

@lru_cache(maxsize=1)
def ui_font():
    return ImageFont.truetype(str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts' / 'arialbd.ttf'),24)

@lru_cache(maxsize=1)
def quick_menu():
    image=Image.new('RGBA',(1380,34));draw=ImageDraw.Draw(image);white='#ffffff';x=0
    def icon(name,left):
        with Image.open(resource_root()/'ui/assets/story-kit/hud-icons'/(name+'.png')) as source:
            glyph=source.convert('RGBA').resize((26,26),Image.Resampling.LANCZOS)
        alpha=glyph.getchannel('A')
        glyph=Image.new('RGBA',glyph.size,'white');glyph.putalpha(alpha)
        image.alpha_composite(glyph,(left,3))
    icon('lock',0);icon('settings',40);x=85
    for label in ('SAVE','LOAD','Q.SAVE','Q.LOAD','SYSTEM'):
        draw.text((x,4),label,font=ui_font(),fill=white)
        x+=round(ui_font().getlength(label))+22
    x+=8
    # History, previous/next, play, fast-forward and auto controls.
    for action in ('first','rewind','previous','play','next','forward','last','auto'):
        center=x+12
        def triangle(cx,forward=True):
            direction=1 if forward else -1
            draw.polygon([(cx-direction*7,8),(cx-direction*7,24),(cx+direction*7,16)],fill=white)
        if action in ('rewind','forward'):
            triangle(center-7,action=='forward');triangle(center+7,action=='forward')
        else:
            triangle(center,action not in ('first','previous'))
            if action in ('first','last','auto'):
                bx=center-12 if action=='first' else center+12
                draw.rectangle((bx,8,bx+3,24),fill=white)
        x+=48
    for name in ('history','voice','auto','star','close','fullscreen'):
        icon(name,x);x+=48
    return image

@lru_cache(maxsize=1)
def voice_track():
    image=Image.new('RGBA',(220,55));draw=ImageDraw.Draw(image)
    draw.polygon([(6,3),(12,10),(6,17),(0,10)],fill='#a9edff',outline='white')
    draw.text((20,0),'VOICE',font=ImageFont.truetype(str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts' / 'arialbd.ttf'),17),fill='white',stroke_width=1,stroke_fill='#173a58')
    draw.rounded_rectangle((0,23,219,43),radius=10,fill='#18384bcc',outline='#b4edff',width=2)
    draw.rounded_rectangle((6,27,213,39),radius=5,fill='#0e283dcf')
    draw.polygon([(212,22),(219,33),(212,44),(205,33)],fill='#d5f6ff',outline='#67c8f4')
    return image

@lru_cache(maxsize=1)
def voice_fill():
    image=Image.new('RGBA',(202,8));draw=ImageDraw.Draw(image)
    for x in range(202):
        t=x/201
        draw.line((x,0,x,7),fill=(round(50+140*t),round(170+68*t),255,255))
    draw.line((0,0,201,0),fill='#effcff',width=2)
    for x in (40,80,120,160,196):
        draw.polygon([(x,2),(x+2,4),(x,6),(x-2,4)],fill='#e5fbff')
    return image

@lru_cache(maxsize=1)
def next_icon():
    image=Image.new('RGBA',(128,128));draw=ImageDraw.Draw(image)
    for i in range(6):
        angle=i*math.tau/6-math.pi/2
        ux,uy=math.cos(angle),math.sin(angle)
        draw.line((64,64,64+52*ux,64+52*uy),fill='#ffffff',width=8)
        for radius in (27,41):
            x,y=64+radius*ux,64+radius*uy
            for side in (-1,1):
                branch=angle+side*math.pi/3
                draw.line((x,y,x-15*math.cos(branch),y-15*math.sin(branch)),fill='#d9f5ff',width=6)
    draw.ellipse((57,57,71,71),fill='white')
    return image.resize((32,32),Image.Resampling.LANCZOS)

def draw_hud(canvas, seconds, voice_duration, indicator=True):
    canvas.alpha_composite(quick_menu(),MENU_BOX[:2])
    if indicator:
        canvas.alpha_composite(next_icon().rotate(-seconds*300,resample=Image.Resampling.BICUBIC),NEXT_BOX[:2])
    if voice_duration and seconds<voice_duration:
        canvas.alpha_composite(voice_track(),VOICE_BOX[:2])
        width=round(202*max(0,min(1,seconds/voice_duration)))
        if width:canvas.alpha_composite(voice_fill().crop((0,0,width,8)),(1678,1009))
