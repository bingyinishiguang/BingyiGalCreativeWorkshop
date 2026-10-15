"""One measured layout and scene renderer for previews and deterministic MP4s."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
from gal_story import StoryCancelled, ffmpeg

W, H, FPS = 1920, 1080, 30


@lru_cache(maxsize=24)
def face(size, name=False, skin="ice"):
    if skin in ("ice","violet","amber","slate"):
        from ice_story_skin import font
        return font(size,name)
    fonts = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
    candidates = [fonts / ('msyh.ttc' if name else 'simsun.ttc'), fonts / 'msyh.ttc']
    for path in candidates:
        if path.is_file(): return ImageFont.truetype(str(path),size)
    raise ValueError('缺少中文字体，请安装宋体或微软雅黑后重新预览')


def lines_for(value, size, width, skin="ice", name=False):
    import re
    if skin in ('ice','violet','amber','slate'):
        from ice_story_skin import validate_text
        validate_text(value,name)
    font=face(size,name=name,skin=skin);result=[]
    for paragraph in value.split('\n'):
        current=''
        # Keep ordinary Latin words together if the whole word fits one line.
        # Oversized identifiers may still break; every source character survives.
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'’-]*|.",paragraph):
            if len(token)>1 and current and font.getlength(token)<=width and font.getlength(current+token)>width:
                result.append(current);current=''
            for char in token:
                if current and font.getlength(current+char)>width:
                    if char in '，。！？；：、）》】”’' and len(current)>1:
                        result.append(current[:-1]);current=current[-1]+char
                    else:result.append(current);current=char
                else:current+=char
        result.append(current)
    return result or ['']


def plan(story, project, strict=False):
    from rough_cut import number
    p=story.normalize(project);segments=[];warnings=[];cursor=0
    if p['bgm']['id']:story.audio.file(p['bgm']['id'])
    for i,row in enumerate(p['clips']):
        try:
            story.asset_file(row['backgroundId'],'background')
            for actor in row['actors']:
                c=next(c for c in p['characters'] if c['id']==actor['characterId'])
                if actor['spriteId'] not in c['sprites']:raise ValueError('画面立绘尚未绑定到角色 '+c['name'])
                story.asset_file(actor['spriteId'],'sprite')
            if row['type']=='dialogue' and row['speakerId'] and not row['actors']:
                warnings.append(f'第 {i+1} 句还没有人物立绘；仍可使用背景和对白导出')
        except ValueError as error:
            if strict:raise ValueError(f'第 {i+1} 个片段：{error}') from None
            warnings.append(f'第 {i+1} 个片段：{error}')
        duration=p['settings']['narrationDuration'] if row['type'] in ('narration','thought') and row['useDefaultDuration'] else row['duration'];voice_duration=0
        if row['voiceId'] and row['voiceEnabled']:
            story.audio.file(row['voiceId'])
            voice_duration=number(story.audio.get(row['voiceId'])['duration'],'配音长度',.01,10800)
            duration=voice_duration+row['hold']
            if row['voiceText'] and row['voiceText'].replace('\r','').replace('\n','')!=row['text'].replace('\r','').replace('\n',''):
                warnings.append(f'第 {i+1} 句台词修改后与配音原文不同，请重新配音或重新绑定')
        skin=row['skin'] or p['settings']['skin']
        if skin in ('ice','violet','amber','slate'):
            from ice_story_skin import geometry,validate_text
            text_rect=geometry(row,p['settings'])
            character=next((c for c in p['characters'] if c['id']==row['speakerId']),None)
            if character:validate_text(character['name'],True)
        else:text_rect=dict(x=row['textX'],y=row['textY'],w=1800-row['textX'],h=2*(p['settings']['fontSize']+20),lines=2)
        if row['type'] in ('eyecatch','choice'):
            from ice_story_skin import validate_special
            validate_special(row)
            pages=[[]]
        else:
            width=text_rect['w'];count=text_rect['lines']
            lines=lines_for(row['text'],p['settings']['fontSize'],width,skin)
            pages=[lines[j:j+count] for j in range(0,len(lines),count)]
            if len(pages)>1:warnings.append(f'第 {i+1} 句自动分为 {len(pages)} 页，配音连续播放')
            if row['typing']:
                duration=max(duration,len(row['text'])/p['settings']['charsPerSecond']+.5)
        frames=max(len(pages),math.ceil(duration*FPS-1e-8));duration=frames/FPS
        if len(pages)>1 and duration/len(pages)<.6:
            warnings.append(f'第 {i+1} 句分页间隔不足 0.6 秒，建议拆句或延长时长')
        weights=[max(1,sum(map(len,page))) for page in pages];total_weight=sum(weights)
        page_frames=[];used=0
        for j,weight in enumerate(weights):
            end=frames if j==len(weights)-1 else max(used+1,min(frames-(len(weights)-j-1),round(frames*sum(weights[:j+1])/total_weight)))
            page_frames.append((used,end));used=end
        rects=[]
        for actor_index,actor in enumerate(row['actors']):
            try:rects.append(dict(actorIndex=actor_index,**actor_geometry(story,actor)))
            except ValueError:pass
        if row['type'] in ('narration','thought') and len(row['text'])/max(.2,duration)>12:
            warnings.append(f'第 {i+1} 段旁白较长，当前仅 {duration:.1f} 秒，可拆句或单独延长')
        segments.append(dict(clipId=row['id'],index=i,startFrame=cursor,frames=frames,start=cursor/FPS,duration=duration,
                             voiceDuration=voice_duration,pages=pages,pageFrames=page_frames,actorRects=rects,
                             textRect={k:text_rect[k] for k in ('x','y','w','h')}))
        cursor+=frames
    if cursor/FPS>7200:raise ValueError('单个剧情视频最长支持两小时，请分章节导出')
    return dict(project=p,segments=segments,frames=cursor,duration=cursor/FPS,warnings=list(dict.fromkeys(warnings)))


@lru_cache(maxsize=12)
def bitmap(path, stamp):
    with Image.open(path) as image:return image.convert('RGBA')


def load_image(path):
    path=Path(path)
    return bitmap(str(path),path.stat().st_mtime_ns).copy()


def actor_geometry(story, actor):
    image=load_image(story.asset_file(actor['spriteId'],'sprite'))
    # Keep the source canvas as the anchor: expressions in a pack share coordinates.
    height=round(H*actor['scale']);width=round(image.width*height/image.height)
    left=round(W*actor['x']-width/2);top=round(H*actor['y']-height)
    bounds=image.getchannel('A').getbbox() or (0,0,image.width,image.height)
    return dict(x=left+bounds[0]*width/image.width,y=top+bounds[1]*height/image.height,
                w=(bounds[2]-bounds[0])*width/image.width,h=(bounds[3]-bounds[1])*height/image.height,
                left=left,top=top,width=width,height=height,z=actor['z'])


SKINS={'ice':((14,46,76),(139,219,255)), 'violet':((40,21,77),(199,174,255)),
       'amber':((59,39,21),(244,207,133)), 'slate':((27,34,43),(188,207,225))}


@lru_cache(maxsize=16)
def scene_base(story, row_json, settings_json, characters_json):
    row=json.loads(row_json);settings=json.loads(settings_json);characters=json.loads(characters_json)
    canvas=ImageOps.fit(load_image(story.asset_file(row['backgroundId'],'background')),(W,H),method=Image.Resampling.LANCZOS)
    for actor in sorted(row['actors'],key=lambda a:a['z']):
        sprite=load_image(story.asset_file(actor['spriteId'],'sprite'));g=actor_geometry(story,actor)
        sprite=sprite.resize((g['width'],g['height']),Image.Resampling.LANCZOS)
        canvas.alpha_composite(sprite,(g['left'],g['top']))
    if row['type'] in ('eyecatch','choice'):return canvas
    from ice_story_skin import composite
    composite(canvas,story.kit,row,settings,characters)
    return canvas



def render(story, project, index, seconds=0, layout=None, fades=True, strict=False):
    layout=layout or plan(story,project);p=layout['project'];row=p['clips'][index];segment=layout['segments'][index]
    try:canvas=scene_base(story,json.dumps(row,sort_keys=True),json.dumps(p['settings'],sort_keys=True),json.dumps(p['characters'],sort_keys=True)).copy()
    except ValueError:
        if strict:raise
        canvas=Image.new('RGBA',(W,H),'#142a40')
    if row['type'] in ('eyecatch','choice'):
        from ice_story_skin import draw_special
        draw_special(canvas,story.kit,row,seconds,segment['duration'])
    else:
        draw=ImageDraw.Draw(canvas);accent=SKINS[row['skin'] or p['settings']['skin']][1]
        frame=min(segment['frames']-1,max(0,int(seconds*FPS)))
        page_index=next((j for j,(start,end) in enumerate(segment['pageFrames']) if start<=frame<end),len(segment['pages'])-1)
        lines=segment['pages'][page_index]
        if row['typing']:
            allowance=max(0,int((seconds-segment['pageFrames'][page_index][0]/FPS)*p['settings']['charsPerSecond']))
            shown=[]
            for line in lines:shown.append(line[:allowance]);allowance=max(0,allowance-len(line))
            lines=shown
        from ice_story_skin import draw_text
        draw_text(canvas,story.kit,row,p['settings'],p['characters'],segment,lines,page_index,seconds)
    transition=min(p['settings']['transition'],segment['duration']/2)
    if fades and row['sceneTransition'] and index>0 and transition and seconds<transition:
        canvas=Image.blend(Image.new('RGBA',(W,H),'black'),canvas,max(0,seconds/transition))
    return canvas.convert('RGB')


def at_time(layout, seconds):
    if not layout['segments']:raise ValueError('请先添加剧情')
    seconds=max(0,min(float(seconds),max(0,layout['duration']-1/FPS)))
    for seg in layout['segments']:
        if seconds<seg['start']+seg['duration']:
            return seg['index'],seconds-seg['start']
    seg=layout['segments'][-1];return seg['index'],seg['duration']-1/FPS


def run_process(args, event, logfile, stdin=None):
    with Path(logfile).open('wb') as log:
        process=subprocess.Popen(args,stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            if stdin:
                for chunk in stdin:
                    if event.is_set():raise StoryCancelled()
                    process.stdin.write(chunk)
                process.stdin.close()
            while process.poll() is None:
                if event.wait(.15):raise StoryCancelled()
            if process.returncode:raise ValueError('FFmpeg 编码失败，请检查素材或磁盘空间；诊断日志保留在任务目录')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()


def inspect_video(path):
    executable=shutil.which('ffprobe') or str(Path(ffmpeg()).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe'))
    if Path(executable).is_file():
        result=subprocess.run([executable,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('无法校验导出视频')
        info=json.loads(result.stdout);video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
        return dict(width=video['width'] if video else 0,height=video['height'] if video else 0,
                    duration=float(info['format']['duration']),audio=any(s['codec_type']=='audio' for s in info['streams']),
                    codec=video.get('codec_name','') if video else '',fps=video.get('avg_frame_rate','') if video else '')
    from pymediainfo import MediaInfo
    tracks=MediaInfo.parse(str(path));video=next(iter(tracks.video_tracks),None)
    if not video:raise ValueError('输出没有有效视频轨道')
    return dict(width=video.width,height=video.height,duration=float(video.duration)/1000,audio=bool(tracks.audio_tracks),codec=video.format,fps=str(video.frame_rate))


@lru_cache(maxsize=4)
def filter_file_option(encoder):
    help_text=subprocess.run([encoder,'-hide_banner','-h','full'],capture_output=True,timeout=20,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
    # Recent FFmpeg accepts file-backed option arguments; older versions expose
    # the dedicated filter_complex_script flag instead.
    return '-filter_complex_script' if b'-filter_complex_script' in help_text else '-/filter_complex'


def export(story, project, ident, event):
    layout=plan(story,project,strict=True);p=layout['project'];encoder=ffmpeg()
    folder=story.exports/ident;folder.mkdir()
    atomic_project=folder/'project.json'
    atomic_project.write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8')
    clips=[]
    for i,segment in enumerate(layout['segments']):
        if event.is_set():raise StoryCancelled()
        row=p['clips'][i]
        story._update(ident,progress=round(i/len(p['clips'])*75),message=f'正在渲染 {i+1}/{len(p["clips"])}')
        target=folder/f'clip-{i:04}.mp4'
        common=[encoder,'-hide_banner','-loglevel','error','-y']
        if row['type']=='choice' or row['typing'] or (row['type']!='eyecatch' and (p['settings']['indicator'] or segment['voiceDuration'])):
            args=common+['-f','rawvideo','-pixel_format','rgb24','-video_size',f'{W}x{H}','-framerate',str(FPS),'-i','pipe:0']
            chunks=(render(story,p,i,frame/FPS,layout,fades=False,strict=True).tobytes() for frame in range(segment['frames']))
        else:
            # A page is rendered once; the encoder repeats it for its exact frame span.
            page_files=[]
            for j,(start,end) in enumerate(segment['pageFrames']):
                image_path=folder/f'frame-{i:04}-{j:03}.png'
                render(story,p,i,start/FPS,layout,fades=False,strict=True).save(image_path)
                page_files.append((image_path,(end-start)/FPS))
            concat=folder/f'pages-{i:04}.txt'
            concat.write_text(''.join(f"file '{path.name}'\nduration {duration:.9f}\n" for path,duration in page_files)+f"file '{page_files[-1][0].name}'\n",'utf-8')
            args=common+['-f','concat','-safe','0','-i',str(concat)];chunks=None
        transition=min(p['settings']['transition'],segment['duration']/2) if i>0 and row['sceneTransition'] else 0
        filters=f'fps={FPS},format=yuv420p'+(f',fade=t=in:st=0:d={transition:.9f}' if transition else '')
        args+=['-vf',filters,'-frames:v',str(segment['frames']),'-an','-c:v','libx264','-preset','veryfast','-crf','19','-threads','4',str(target)]
        run_process(args,event,folder/f'encode-{i:04}.log',chunks);clips.append(target)
    concat=folder/'video-list.txt';concat.write_text(''.join(f"file '{path.name}'\n" for path in clips),'utf-8')
    story._update(ident,progress=80,message='正在对齐配音并混合背景音乐…')
    args=[encoder,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat)]
    filters=[];labels=[];input_index=1;voice_ranges=[]
    for segment in layout['segments']:
        row=p['clips'][segment['index']]
        if not row['voiceId'] or not row['voiceEnabled']:continue
        args+=['-i',str(story.audio.file(row['voiceId']))]
        start=segment['start'];voice_ranges.append((start,start+segment['voiceDuration']))
        label=f'v{input_index}'
        filters.append(f'[{input_index}:a]aresample=48000,atrim=duration={segment["voiceDuration"]:.9f},asetpts=PTS-STARTPTS,adelay={round(start*48000)}S:all=1[{label}]')
        labels.append(f'[{label}]');input_index+=1
    duration=layout['duration'];bgm=p['bgm']
    if bgm['id']:
        args+=['-stream_loop','-1','-i',str(story.audio.file(bgm['id']))]
        condition='+'.join(f'between(t,{a:.6f},{b:.6f})' for a,b in voice_ranges) or '0'
        expr=f'{bgm["volume"]}*if(gt({condition},0),{bgm["duck"]},1)'
        fade=min(bgm['fade'],duration/2)
        filters.append(f"[{input_index}:a]aresample=48000,atrim=duration={duration:.9f},asetpts=PTS-STARTPTS,volume='{expr}':eval=frame,afade=t=in:d={fade:.6f},afade=t=out:st={duration-fade:.6f}:d={fade:.6f}[music]")
        labels.append('[music]')
    temporary=folder/'unfinished.mp4'
    if labels:
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95:latency=1,apad,atrim=duration={duration:.9f}[mix]')
        # Script file avoids command-line length limits on long stories.
        script=folder/'mix-filter.txt';script.write_text(';\n'.join(filters),'utf-8')
        args+=[filter_file_option(encoder),str(script),'-map','0:v:0','-map','[mix]','-c:a','aac','-b:a','192k']
    else:args+=['-map','0:v:0','-an']
    args+=['-c:v','copy','-t',f'{duration:.9f}','-movflags','+faststart',str(temporary)]
    try:
        run_process(args,event,folder/'mix.log')
        story._update(ident,progress=95,message='正在校验分辨率、时长和音轨…')
        if event.is_set():raise StoryCancelled()
        info=inspect_video(temporary)
        if (info['width'],info['height'])!=(W,H) or abs(info['duration']-duration)>.1 or info['audio']!=bool(labels):
            raise ValueError('导出视频校验未通过，请检查编码日志')
        if event.is_set():raise StoryCancelled()
        from story_subtitles import subtitles
        label=re_safe(p['name']);subtitle=folder/(label+'.srt')
        subtitle_text=subtitles(layout)
        if subtitle_text:subtitle.write_text(subtitle_text,encoding='utf-8-sig')
        final=folder/(label+'.mp4');temporary.rename(final)
        # Keep project, final MP4 and logs; transient frames and clips are disposable.
        for pattern in ('frame-*.png','clip-*.mp4','pages-*.txt','video-list.txt','mix-filter.txt'):
            for path in folder.glob(pattern):path.unlink(missing_ok=True)
        return dict(path=str(final),url='/api/gal-story/video?id='+ident,subtitlePath=str(subtitle) if subtitle_text else '',
                    subtitleUrl=('/api/gal-story/subtitles?id='+ident) if subtitle_text else '',metadata=info,warnings=layout['warnings'])
    finally:temporary.unlink(missing_ok=True)


def re_safe(value):
    import re
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',value).strip(' .')[:70] or 'Gal剧情'
