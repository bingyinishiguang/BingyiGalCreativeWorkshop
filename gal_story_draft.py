"""Export GalStory as an editable Jianying timeline, with durable local media."""
import json
import math
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageChops
from draft_media import MediaPack, readable_name
from rough_cut import atomic_json, publish_directory


def export(story, project, ident, event):
    import pyJianYingDraft as d
    from gal_story import StoryCancelled
    from gal_story_render import plan, actor_geometry, render, SKINS, face
    from ice_story_skin import composite, geometry, special_lines, THEMES, themed_read
    from draft_asset_registry import register
    layout = plan(story, project, strict=True)
    p = layout['project']; settings = p['settings']; width, height = 1920, 1080
    defaults = getattr(story, 'output_options', lambda: {})()
    options = p.get('output', {})
    directory = options.get('draftDirectory') or defaults.get('draftDirectory')
    destination = (Path(directory) if directory else story.root/'drafts').resolve()
    destination.mkdir(parents=True, exist_ok=True)
    name = readable_name(p['name']) + ' · 生成稿'
    final = destination/name
    version = 2
    while final.exists():
        final = destination/f'{name}_版本{version}'; version += 1
    name = final.name
    staging = destination/('.bingyi-building-' + uuid.uuid4().hex[:12])
    pack = None
    asset_names = {a['id']:a['name'] for a in story.catalog()}
    try:
        script = d.DraftFolder(str(destination)).create_draft(staging.name, width, height, 30, maintrack_adsorb=False)
        script.content.update(id=str(uuid.uuid4()).upper(), name=name)
        media = staging/'media'; media.mkdir()
        pack = MediaPack(media, final/'media', options.get('materialDirectory') or defaults.get('materialDirectory', ''))
        tracks = {}; materials = {}; text_count = 0
        manifest = []

        def track(name, kind=d.TrackType.video):
            if name not in tracks:
                tracks[name] = script.append_track(d.TrackSpec(kind, name, mute=kind==d.TrackType.video))
            return tracks[name]

        def check():
            if event.is_set():
                raise StoryCancelled()

        def image_material(key, label, source=None, image=None):
            if key in materials:
                return materials[key]
            target = pack.copy(source, label) if source else pack.allocate(label, '.png')
            if image is not None:
                image.save(target)
            material = d.VideoMaterial(str(target)); material.path = pack.path(target)
            materials[key] = material
            return material

        def picture(material, start, duration, name, box=None):
            if box is None:
                # Backgrounds fill the frame; crop rather than stretch.
                scale = max(width/material.width, height/material.height)/min(width/material.width, height/material.height)
                clip = d.ClipSettings(scale_x=scale, scale_y=scale)
            else:
                x,y,w,h = box; fit = min(width/material.width, height/material.height)
                clip = d.ClipSettings(scale_x=w/material.width/fit, scale_y=h/material.height/fit,
                    transform_x=(x+w/2)/width*2-1, transform_y=1-(y+h/2)/height*2)
            segment=d.VideoSegment(material, d.Timerange(start,duration), clip_settings=clip, volume=0)
            script.add_segment(segment, track(name))
            return segment

        def text(value, x, y, size, start, duration, name='对白 · 可编辑', color='#1f4688', outline='#ffffff', bold=False, skin='ice'):
            nonlocal text_count
            if not value:
                return
            font = face(size, name=bold or name=='人物名 · 可编辑', skin=skin)
            rgb = lambda c:tuple(int(c[i:i+2],16)/255 for i in (1,3,5))
            segment = d.TextSegment(value, d.Timerange(start,duration),
                style=d.TextStyle(size=size/10, color=rgb(color), bold=bold, align=0, auto_wrapping=False),
                border=d.TextBorder(color=rgb(outline), width=1/size) if outline else None,
                clip_settings=d.ClipSettings(transform_x=(x+font.getlength(value)/2)/width*2-1,
                    transform_y=1-(y+size/2)/height*2))
            original = segment.export_material
            font_path = font.path
            def export_material():
                result = original()
                content = json.loads(result['content'])
                content['styles'][0]['font'] = {'id':'', 'path':str(font_path), 'name':Path(font_path).stem}
                result['content'] = json.dumps(content, ensure_ascii=False)
                return result
            segment.export_material = export_material
            script.add_segment(segment, track(name,d.TrackType.text)); text_count += 1

        # Append the visual tracks in a fixed painter order before adding content.
        track('背景')
        z_values = sorted({a['z'] for row in p['clips'] for a in row['actors']})
        max_at_z = {z:max(sum(a['z']==z for a in row['actors']) for row in p['clips']) for z in z_values}
        for z in z_values:
            for slot in range(max_at_z[z]):track(f'人物图层 {z} · {slot+1}')
        for name_ in ('对话框底板','说话者头像','继续提示','语音进度底','语音进度','底部快捷菜单','选项框 1','选项框 2','选项框 3'):track(name_)
        for name_ in ('人物名 · 可编辑','对白 · 可编辑','选项 · 可编辑','过场文字 · 可编辑'):track(name_,d.TrackType.text)

        for i, (row, seg) in enumerate(zip(p['clips'],layout['segments'])):
            check(); story._update(ident, progress=round(i/max(1,len(p['clips']))*85), message=f'正在铺轨 {i+1}/{len(p["clips"])}')
            start = round(seg['startFrame']/30*1e6)
            duration = round((seg['startFrame']+seg['frames'])/30*1e6)-start
            bg = image_material(('bg',row['backgroundId']), '背景_'+asset_names.get(row['backgroundId'],'场景'),
                                source=story.asset_file(row['backgroundId'],'background'))
            picture(bg,start,duration,'背景')
            counters = {}
            for actor in sorted(row['actors'],key=lambda a:a['z']):
                c = next(c for c in p['characters'] if c['id']==actor['characterId'])
                sprite_path = story.asset_file(actor['spriteId'],'sprite')
                sprite = image_material(('sprite',actor['spriteId']), asset_names.get(actor['spriteId'],c['name']+'_立绘'), source=sprite_path)
                g = actor_geometry(story,actor); z=actor['z'];slot=counters.get(z,0);counters[z]=slot+1
                picture(sprite,start,duration,f'人物图层 {z} · {slot+1}',(g['left'],g['top'],g['width'],g['height']))
            skin = row['skin'] or settings['skin']
            if row['type'] not in ('choice','eyecatch'):
                panelkey = ('panel',skin,row['type'],bool(row['speakerId']),settings['fontSize'],settings['dialogueLayout'],settings['panelOpacity'])
                panel = Image.new('RGBA',(width,height))
                composite(panel,story.kit,row,settings,p['characters'])
                g = geometry(row,settings); namex,namey,namesize = g['nameX'],g['nameY'],27
                picture(image_material(panelkey,'对话框_'+{'ice':'冰蓝','violet':'紫色','amber':'暖棕','slate':'灰蓝'}[skin],image=panel),start,duration,'对话框底板',(0,0,width,height))
                c=next((c for c in p['characters'] if c['id']==row['speakerId']),None)
                label=c['name'] if c and row['type'] in ('dialogue','thought') else ''
                if row['type']=='thought':label=(label+' · ' if label else '')+'心声'
                text(label,namex,namey,namesize,start,duration,'人物名 · 可编辑',color='#ffffff',outline=None,skin=skin)
                for page,(left,right) in zip(seg['pages'],seg['pageFrames']):
                    for line_index,line in enumerate(page):
                        text(line,seg['textRect']['x'],seg['textRect']['y']+line_index*max(62,settings['fontSize']+20),
                             settings['fontSize'],round((seg['startFrame']+left)/30*1e6),round((seg['startFrame']+right)/30*1e6)-round((seg['startFrame']+left)/30*1e6),skin=skin,
                             name=f'对白 · 可编辑 {line_index+1}',color=THEMES[skin]['ink'],outline=None)
                from game_hud import quick_menu, voice_track, voice_fill, next_icon, MENU_BOX, VOICE_BOX, NEXT_BOX
                menu=image_material(('quick-menu',),'底部菜单_SAVE_LOAD',image=quick_menu())
                picture(menu,start,duration,'底部快捷菜单',MENU_BOX)
                if settings['indicator']:
                    icon=image_material(('next-hud',),'雪花循环继续提示',image=next_icon())
                    indicator=picture(icon,start,duration,'继续提示',NEXT_BOX)
                    indicator.add_keyframe(d.KeyframeProperty.rotation,0,0)
                    indicator.add_keyframe(d.KeyframeProperty.rotation,duration-1,seg['duration']*300)
                if seg['voiceDuration']:
                    voice_us=round(seg['voiceDuration']*1e6)
                    bar=image_material(('voice-track-hud',),'VOICE_语音进度框',image=voice_track())
                    fill=image_material(('voice-fill-hud',),'VOICE_冰晶渐变进度',image=voice_fill())
                    picture(bar,start,voice_us,'语音进度底',VOICE_BOX)
                    progress=picture(fill,start,voice_us,'语音进度',(1678,1009,202,8))
                    full_scale=202/fill.width/min(width/fill.width,height/fill.height)
                    for offset,fraction in ((0,.001),(max(1,voice_us-1),1)):
                        progress.add_keyframe(d.KeyframeProperty.scale_x,offset,full_scale*fraction)
                        progress.add_keyframe(d.KeyframeProperty.position_x,offset,(1678+101*fraction)/width*2-1)
            elif row['type']=='eyecatch' and row['captionEnabled']:
                lines=special_lines(row['captionText'],48,850,3,'过场文字')
                for j,line in enumerate(lines):text(line,960-face(48).getlength(line)/2,540-len(lines)*34+j*68,48,start,duration,'过场文字 · 可编辑')
            elif row['type']=='choice':
                options=[special_lines(v,30,870,2,'选项',True) for v in row['options']]
                tall=any(len(lines)>1 for lines in options); bh,step=(148,174) if tall else (100,126)
                top=round(445-(bh+(len(options)-1)*step)/2)
                for j,lines in enumerate(options):
                    panel=image_material(('choice',tall),'选项框',source=story.kit/('choice-'+('tall-' if tall else '')+'idle.png'))
                    picture(panel,start,duration,f'选项框 {j+1}',(440,top+j*step,panel.width,panel.height))
                    for k,line in enumerate(lines):text(line,535,top+j*step+(34 if tall else 32)+k*40,30,start,duration,f'选项 · 可编辑 {j+1} · {k+1}',bold=True)
                for j,line in enumerate(special_lines(row['text'],30,1040,2,'选择提示')):
                    text(line,960-face(30).getlength(line)/2,max(50,top-110)+j*42,30,start,duration,'选择提示 · 可编辑')
            if seg['voiceDuration']:
                source=story.audio.file(row['voiceId']); item=story.audio.get(row['voiceId'])
                key=('audio',row['voiceId'])
                if key not in materials:
                    target=pack.copy(source,'配音_'+item['name']); materials[key]=d.AudioMaterial(str(target));materials[key].path=pack.path(target)
                value=materials[key]; voice_us=min(value.duration,round(seg['voiceDuration']*1e6))
                script.add_segment(d.AudioSegment(value,d.Timerange(start,voice_us),source_timerange=d.Timerange(0,voice_us),volume=row.get('volume',1)),track('角色配音',d.TrackType.audio))
            manifest.append({'clipId':row['id'],'type':row['type'],'startUs':start,'durationUs':duration,'text':row['text']})

        if p['bgm']['id']:
            check(); source=story.audio.file(p['bgm']['id']); target=pack.copy(source,'BGM_'+story.audio.get(p['bgm']['id'])['name'])
            music=d.AudioMaterial(str(target));music.path=pack.path(target)
            # Split at dialogue boundaries for editable ducking, looping the source.
            cursor=0
            for seg in layout['segments']:
                target_start=round(seg['startFrame']/30*1e6)
                remaining=round((seg['startFrame']+seg['frames'])/30*1e6)-target_start
                while remaining:
                    amount=min(remaining,music.duration-cursor)
                    volume=p['bgm']['volume']*(p['bgm']['duck'] if seg['voiceDuration'] else 1)
                    audio=d.AudioSegment(music,d.Timerange(target_start,amount),source_timerange=d.Timerange(cursor,amount),volume=volume)
                    fade=min(p['bgm']['fade'],layout['duration']/2)*1e6
                    total=round(layout['duration']*1e6)
                    if fade:
                        points={0,amount-1}
                        for boundary in (round(fade),round(total-fade)):
                            if target_start<boundary<target_start+amount:points.add(boundary-target_start)
                        for offset in sorted(points):
                            absolute=target_start+offset
                            gain=min(1,absolute/fade,max(0,(total-absolute)/fade))
                            audio.add_keyframe(offset,volume*gain)
                    script.add_segment(audio,track('BGM',d.TrackType.audio))
                    remaining-=amount;target_start+=amount;cursor=(cursor+amount)%music.duration
        check()
        for name_ in list(script.tracks):
            if not script.tracks[name_].segments:
                del script.tracks[name_]
        meta_path=staging/'draft_meta_info.json';meta=json.loads(meta_path.read_text('utf-8'))
        register(script,meta,media);script.save()
        now=int(datetime.now().timestamp()*1e6)
        meta.update(draft_id=script.content['id'],draft_name=name,draft_fold_path=str(final),draft_root_path=str(destination),
                    tm_draft_create=now,tm_draft_modified=now,tm_duration=round(layout['duration']*1e6),draft_cover=str(final/'draft_cover.jpg'))
        atomic_json(meta_path,meta)
        render(story,p,0,layout=layout,fades=False,strict=True).convert('RGB').save(staging/'draft_cover.jpg',quality=90)
        atomic_json(staging/'bingyi-story.json',p)
        atomic_json(staging/'bingyi-generation.json',dict(version=1,projectId=p['id'],jobId=ident,clips=manifest,
                    materialDirectory=str(pack.final),note='原始生成稿；请在剪映复制为精剪稿后调整，保留此稿用于比较。'))
        notes=list(layout['warnings'])
        if any(r['typing'] for r in p['clips']):notes.append('剪映草稿使用整句可编辑文字；逐字效果可在剪映添加文字动画。')
        notes.append('生成成功与素材引用检查不等于已通过目标剪映版本的打开、播放、保存重开验收。')
        atomic_json(staging/'compatibility.json',dict(adapter='pyJianYingDraft 0.3.0',verifiedVersions=[],notes=notes))
        check();pack.publish()
        try:publish_directory(staging,final)
        except Exception:pack.rollback();raise
        return dict(path=str(final),materialDirectory=str(pack.final),name=name,metadata=dict(width=width,height=height,duration=layout['duration'],textSegments=text_count),warnings=notes)
    finally:
        if staging.is_dir():shutil.rmtree(staging)
