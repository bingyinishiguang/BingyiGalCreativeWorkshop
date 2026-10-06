"""Storyboard persistence and a version-pinned Jianying draft adapter."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image
from cut_geometry import default_transform, normalize_transform, clip_values


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_directory(source: Path, destination: Path):
    """Retry transient Windows sharing/access failures without overwriting a draft."""
    for attempt in range(5):
        if destination.exists():raise FileExistsError('草稿目标目录已存在')
        try:
            source.rename(destination)
            return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33) or attempt==4:raise
            time.sleep(.1*(attempt+1))


def number(value, label, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(label + '必须是数值')
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(label + '必须是数值') from error
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{label}应在 {minimum}–{maximum} 之间')
    return result


class RoughCut:
    def __init__(self, root: Path, backgrounds, sprites, audio_library=None):
        self.root = Path(root)
        self.projects = self.root / 'projects'
        self.exports = self.root / 'drafts'
        self.projects.mkdir(parents=True, exist_ok=True)
        self.exports.mkdir(exist_ok=True)
        self.backgrounds = backgrounds
        self.sprites = sprites
        self.audio_library = audio_library
        self.lock = threading.Lock()

    def options(self):
        path = self.root / 'options.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'draftDirectory': ''}

    def save_options(self, payload):
        directory = str(payload.get('draftDirectory', '')).strip()
        if directory and not Path(directory).is_dir():
            raise ValueError('剪映草稿目录不存在，请选择实际的 JianyingPro Drafts 文件夹')
        atomic_json(self.root / 'options.json', {'draftDirectory': directory})
        return self.options()

    def project_path(self, project_id):
        if not re.fullmatch(r'[a-f0-9]{32}', str(project_id)):
            raise ValueError('粗剪项目编号不正确')
        return self.projects / (project_id + '.json')

    def list_projects(self):
        items = []
        for path in self.projects.glob('*.json'):
            try:
                p = json.loads(path.read_text(encoding='utf-8'))
                items.append({'id': p['id'], 'name': p['name'], 'updated': p['updated']})
            except (OSError, ValueError, KeyError):
                continue
        return {'items': sorted(items, key=lambda i: i['updated'], reverse=True)}

    def load(self, project_id):
        path = self.project_path(project_id)
        if not path.is_file():
            raise ValueError('粗剪项目不存在')
        return json.loads(path.read_text(encoding='utf-8'))

    def normalize(self, payload):
        fps = int(number(payload.get('fps', 30), '帧率', 24, 60))
        if fps not in (24, 25, 30, 60):
            raise ValueError('帧率支持 24、25、30、60')
        width = int(number(payload.get('width', 1920), '画布宽度', 320, 3840))
        height = int(number(payload.get('height', 1080), '画布高度', 320, 3840))
        scenes = payload.get('scenes')
        if not isinstance(scenes, list) or not 1 <= len(scenes) <= 500:
            raise ValueError('请添加 1–500 个镜头')
        clean = []
        last_bg = ''
        video_cursor = 0
        frame = 0
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise ValueError('镜头格式不正确')
            frames = max(1, round(number(scene.get('duration', 4), f'第 {index+1} 镜时长', 1/fps, 3600) * fps))
            bg = str(scene.get('background') or '')
            if scene.get('blank') is True:
                if bg or scene.get('actors'):raise ValueError('空白镜头不能携带背景或角色')
                start=round(frame*1_000_000/fps);end=round((frame+frames)*1_000_000/fps)
                clean.append({'blank':True,'background':'','duration':frames/fps,'start':start,'durationUs':end-start,
                              'videoStart':0,'restart':True,'loop':False,'actors':[]})
                from timeline_identity import metadata
                metadata(scene,clean[-1]);frame+=frames;last_bg='';video_cursor=0
                continue
            if not bg:
                raise ValueError(f'第 {index+1} 镜请选择背景')
            info = self.backgrounds.get(bg)
            self.backgrounds.file(bg)
            if bg != last_bg or scene.get('restart') is True:
                video_cursor = round(number(scene.get('videoStart', 0), '视频起点', 0, 86400) * 1_000_000)
            if info['kind'] == 'video' and video_cursor >= round(info['duration'] * 1_000_000):
                if scene.get('loop') is True:
                    video_cursor %= round(info['duration'] * 1_000_000)
                else:
                    raise ValueError(f'第 {index+1} 镜背景视频已播放完，请勾选循环或重新开始')
            actors = []
            raw_actors = scene.get('actors', [])
            if not isinstance(raw_actors, list) or len(raw_actors) > 2:
                raise ValueError('每个镜头最多两个角色')
            for actor in raw_actors:
                if not isinstance(actor, dict):
                    raise ValueError('角色格式不正确')
                actor_id = str(actor.get('id') or '')
                if not self.sprites.file(actor_id, False):
                    raise ValueError(f'第 {index+1} 镜立绘不存在、丢失或不在普通立绘库')
                slot = int(number(actor.get('slot', len(actors)), '角色轨道', 0, 1))
                if any(a['slot'] == slot for a in actors):
                    raise ValueError('同一镜头的角色轨道不能重复')
                clean_actor = {'id': actor_id, 'slot': slot,
                               'x': number(actor.get('x', 0), '人物水平位置', -1, 1),
                               'height': number(actor.get('height', .9), '人物高度比例', .1, 2)}
                with Image.open(self.sprites.file(actor_id, False)) as image:
                    box = image.convert('RGBA').getchannel('A').getbbox()
                if not box:
                    raise ValueError('立绘完全透明')
                sw,sh=box[2]-box[0],box[3]-box[1]
                if 'alignment' in actor:
                    from composition_library import alignment
                    clean_actor['alignment']=alignment(actor['alignment'])
                    sw,sh=clean_actor['alignment']['width'],clean_actor['alignment']['height']
                fallback = default_transform(width, height, sw, sh, clean_actor)
                clean_actor['transform'] = normalize_transform(actor.get('transform'), fallback, number, width, height)
                actors.append(clean_actor)
            start = round(frame * 1_000_000 / fps)
            end = round((frame + frames) * 1_000_000 / fps)
            if info['kind'] == 'video' and not scene.get('loop') and video_cursor + end-start > round(info['duration']*1_000_000):
                raise ValueError(f'第 {index+1} 镜背景视频长度不足，请缩短镜头或勾选循环')
            clean.append({'background': bg, 'duration': frames/fps, 'start': start, 'durationUs': end-start,
                          'videoStart': video_cursor/1_000_000, 'restart': scene.get('restart') is True,
                          'loop': scene.get('loop') is True, 'actors': actors,
                          'backgroundTransform': normalize_transform(scene.get('backgroundTransform'),
                              default_transform(width, height, info['width'], info['height']), number, width, height)})
            from timeline_identity import metadata
            metadata(scene,clean[-1])
            video_cursor += end-start
            last_bg = bg
            frame += frames
        if frame/fps > 10800:
            raise ValueError('粗剪总时长最多三小时')
        name = str(payload.get('name') or '未命名粗剪').strip()[:100] or '未命名粗剪'
        from dialogue_timeline import normalize_dialogue
        dialogue = normalize_dialogue(payload, self.audio_library, number)
        from script_plan import normalize_plan
        plan = normalize_plan(payload.get('scriptPlan'),number)
        script_base={}
        if isinstance(payload.get('scriptBase'),dict):
            base_payload=dict(payload,scenes=[payload['scriptBase']]);base_payload.pop('scriptBase');base_payload.pop('scriptTiming',None)
            script_base={'scriptBase':self.normalize(base_payload)['scenes'][0]}
        timing={}
        if isinstance(payload.get('scriptTiming'),dict):
            marker={'plan':normalize_plan(payload['scriptTiming'].get('plan'),number)}
            if isinstance(payload['scriptTiming'].get('base'),dict):
                bp=dict(payload,scenes=[payload['scriptTiming']['base']]);bp.pop('scriptBase',None);bp.pop('scriptTiming',None)
                marker['base']=self.normalize(bp)['scenes'][0]
            timing={'scriptTiming':marker}
        baseline={}
        if isinstance(payload.get('scriptBaseline'),dict):
            bp=dict(payload,**payload['scriptBaseline']);bp.pop('scriptBaseline');bp.pop('scriptBase',None);bp.pop('scriptTiming',None);bp['scriptPlan']=None
            normalized=self.normalize(bp)
            baseline={'scriptBaseline':{k:normalized[k] for k in ('scenes','textClips','audioClips')}}
        from column_workflow import normalize_overlays, normalize_destinations
        extras = {}
        if 'overlays' in payload:
            extras['overlays'] = normalize_overlays(payload['overlays'], self.backgrounds, number)
        if 'workflow' in payload:
            extras['workflow'] = normalize_destinations(payload['workflow'])
        if 'generation' in payload:
            from column_workflow import normalize_generation
            extras['generation']=normalize_generation(payload['generation'])
        return {'schema': 3, 'name': name, 'width': width, 'height': height, 'fps': fps,
                'scenes': clean, 'durationUs': max(round(frame*1_000_000/fps),
                    max((round((c['start']+c['duration'])*1_000_000) for c in dialogue['audioClips']+dialogue['textClips']),default=0)),
                **dialogue, 'scriptPlan':plan, **script_base,
                **timing, **baseline, **extras}

    def save(self, payload):
        project = self.normalize(payload)
        project_id = payload.get('id') or uuid.uuid4().hex
        path = self.project_path(project_id)
        project.update(id=project_id, updated=datetime.now().isoformat(timespec='seconds'))
        atomic_json(path, project)
        return project

    def export(self, payload):
        #Serialize copy-heavy exports; every run gets a fresh folder and IDs.
        with self.lock:
            project = self.save(payload)
            if project.get('scriptTiming') and (project['scriptTiming']['plan']!=project['scriptPlan'] or ('base' in project['scriptTiming'] and project['scriptTiming']['base']!=project.get('scriptBase'))):
                raise ValueError('台词、配音或排版已修改，请在台词校对中重新计算并铺轨')
            timed_clips=project['audioClips']+project['textClips']
            if timed_clips and max(c['start']+c['duration'] for c in timed_clips) > sum(s['duration'] for s in project['scenes'])+.001:
                raise ValueError('音频或文字超出画面时间，请点击「延长末镜至内容结束」或按对白生成镜头')
            try:
                import pyJianYingDraft as draft
            except ImportError as error:
                raise ValueError('缺少粗剪依赖，请按 requirements.txt 安装 pyJianYingDraft') from error
            label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project['name']).strip(' .')[:60] or 'roughcut'
            name = f'冰翼粗剪-{label}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}'
            directory = str(project.get('workflow', {}).get('draftDirectory') or self.options().get('draftDirectory') or '')
            destination = Path(directory) if directory else self.exports
            if not destination.is_dir():
                raise ValueError('草稿输出目录已不存在，请重新设置')
            #Stage within the destination so the final rename is atomic; material paths use final location.
            final = destination / name
            #Keep the staging layout flat: nesting draft-name/media under another
            #UUID directory can exceed Win32 path limits in a frozen application.
            staging = destination / ('.bingyi-building-' + uuid.uuid4().hex[:12])
            try:
                script = draft.DraftFolder(str(destination)).create_draft(staging.name, project['width'], project['height'], project['fps'], maintrack_adsorb=False)
                draft_id = str(uuid.uuid4()).upper()
                script.content['id'] = draft_id
                script.content['name'] = name
                folder = staging
                media = folder / 'media'
                media.mkdir()
                tracks = {0:script.append_track(draft.TrackSpec(draft.TrackType.video,'背景',mute=True))}
                for slot in project['roleOrder']:
                    #New layer-aware projects only need actor tracks that contain actors.
                    #Preserve historical track layout for existing legacy projects.
                    if 'overlays' in project and not any(a['slot'] == slot for s in project['scenes'] for a in s['actors']):
                        continue
                    tracks[slot+1] = script.append_track(draft.TrackSpec(draft.TrackType.video,f'角色 {slot+1}',mute=True))
                materials = {}
                def material(kind, item_id, placement=None):
                    key = (kind, item_id, json.dumps(placement,sort_keys=True) if placement else '')
                    if key in materials:
                        return materials[key]
                    if kind in ('background', 'overlay'):
                        from dialogue_timeline import safe_name
                        source = self.backgrounds.file(item_id)
                        target = media / safe_name(self.backgrounds.get(item_id)['name'],item_id,source.suffix)
                        shutil.copy2(source, target)
                    else:
                        source = self.sprites.file(item_id, False)
                        if not source:
                            raise ValueError('立绘文件丢失')
                        from dialogue_timeline import safe_name
                        info = self.sprites.metadata(item_id)
                        if info is None:
                            raise ValueError('立绘已移入回收站')
                        display = info.get('displayName') or '_'.join(str(info.get(k) or '') for k in ('character','body','face')).strip('_') or '人物'
                        target = media / safe_name(display,item_id,'.png')
                        if placement:target=target.with_name(target.stem+'-'+uuid.uuid4().hex[:8]+'.png')
                        with Image.open(source) as image:
                            image = image.convert('RGBA')
                            box = image.getchannel('A').getbbox()
                            if not box:
                                raise ValueError('立绘完全透明')
                            if placement:
                                from composition_library import render_aligned
                                render_aligned(source,placement).save(target)
                            else:image.crop(box).save(target)
                    value = draft.VideoMaterial(str(target))
                    #Files are staged, but serialized references point to their durable final paths.
                    value.path = str(final / 'media' / target.name)
                    materials[key] = value
                    return value
                w, h = project['width'], project['height']
                for scene in project['scenes']:
                    if scene.get('blank'):continue
                    bg = material('background', scene['background'])
                    clip = draft.ClipSettings(**clip_values(scene['backgroundTransform'], w, h))
                    remaining = scene['durationUs']
                    cursor = round(scene['videoStart']*1_000_000)
                    target_start = scene['start']
                    while remaining:
                        amount = remaining if bg.material_type == 'photo' else min(remaining, bg.duration-cursor)
                        if amount <= 0:
                            raise ValueError('背景视频没有足够的有效时长')
                        if len(script.tracks['背景'].segments) > 10000:
                            raise ValueError('视频循环片段过多，请改用更长的视频')
                        segment = draft.VideoSegment(bg, draft.Timerange(target_start, amount),
                            source_timerange=draft.Timerange(0 if bg.material_type == 'photo' else cursor, amount),
                            clip_settings=clip, volume=0)
                        script.add_segment(segment, tracks[0])
                        remaining -= amount
                        target_start += amount
                        cursor = 0
                    for actor in scene['actors']:
                        value = material('sprite', actor['id'], actor.get('alignment'))
                        settings = draft.ClipSettings(**clip_values(actor['transform'], w, h))
                        script.add_segment(draft.VideoSegment(value, draft.Timerange(scene['start'], scene['durationUs']),
                                           clip_settings=settings), tracks[actor['slot']+1])
                from column_workflow import overlay_transform
                for index, overlay in enumerate(project.get('overlays', [])):
                    value = material('overlay', overlay['image'])
                    info = self.backgrounds.get(overlay['image'])
                    transform = overlay_transform(overlay, w, h, info['width'], info['height'])
                    ref = script.append_track(draft.TrackSpec(draft.TrackType.video,
                        f"全片图片 {index+1} · {overlay['name']}", mute=True))
                    script.add_segment(draft.VideoSegment(value, draft.Timerange(0, project['durationUs']),
                        clip_settings=draft.ClipSettings(**clip_values(transform, w, h)), volume=0), ref)
                used_ids={m.material_id for m in script.materials.videos}
                #Package calibrated alternatives without placing them on any timeline track.
                from composition_library import CompositionLibrary
                groups=CompositionLibrary(self.root,self.sprites).list()['groups']
                candidate_sets=set()
                for source_scene in project['scenes']+[project.get('scriptBase',{'actors':[]})]:
                    for actor in source_scene['actors']:
                        placement=actor.get('alignment')
                        if not placement:continue
                        group=next((g for g in groups if g['id']==placement['groupId'] and g['version']==placement['version']),None)
                        if not group or (group['id'],group['version']) in candidate_sets:continue
                        candidate_sets.add((group['id'],group['version']))
                        for member in group['members']:
                            p={k:member[k] for k in ('width','height','left','top','scale','groupId','version')}
                            value=material('sprite',member['id'],p)
                            if value not in script.materials:script.materials.videos.append(value)
                from dialogue_timeline import export_dialogue
                export_dialogue(script,draft,project,self.audio_library,media,final)
                meta_path = folder / 'draft_meta_info.json'
                meta = json.loads(meta_path.read_text(encoding='utf-8'))
                from draft_asset_registry import register, actor_pack
                registered=register(script,meta,media)
                script.save()
                #Empty background ranges are real timeline time, including a
                #trailing gap beyond the last material/audio segment.
                if any(scene.get('blank') for scene in project['scenes']):
                    content_path=folder/'draft_content.json'
                    content=json.loads(content_path.read_text(encoding='utf-8'))
                    content['duration']=project['durationUs']
                    atomic_json(content_path,content)
                atomic_json(folder/'bingyi-actor-assets.json',actor_pack(materials,project,used_ids))
                now = int(datetime.now().timestamp()*1_000_000)
                meta.update(draft_id=draft_id, draft_name=name, draft_fold_path=str(final),
                            draft_root_path=str(destination),
                            tm_draft_create=now, tm_draft_modified=now, tm_duration=project['durationUs'])
                atomic_json(meta_path, meta)
                atomic_json(folder / 'bingyi-storyboard.json', project)
                atomic_json(folder / 'compatibility.json', {'adapter':'pyJianYingDraft 0.3.0',
                    'features':['local_media','import_registry','calibrated_actor_candidates','audio','editable_text','track_order'],
                    'verifiedVersions':[], 'note':'请在目标剪映版本验证打开、播放、保存重开；生成成功不代表已通过版本验收。'})
                self._cover(project, folder / 'draft_cover.jpg')
                meta['draft_cover'] = str(final / 'draft_cover.jpg')
                atomic_json(meta_path, meta)
                publish_directory(folder,final)
                return {'project': project, 'name': name, 'path': str(final),
                        'inJianyingDirectory': bool(directory), 'duration': project['durationUs']/1_000_000}
            finally:
                #Only the freshly-created staging directory is owned by this operation.
                shutil.rmtree(staging, ignore_errors=True)

    def _cover(self, project, path):
        canvas = Image.new('RGB', (480, round(480*project['height']/project['width'])), '#102a42')
        scene = project['scenes'][0]
        if not scene.get('blank'):
            bg = self.backgrounds.file(scene['background'])
            thumb = self.backgrounds.thumbs / (scene['background'] + '.jpg')
            if bg.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp') or thumb.is_file():
                with Image.open(bg if bg.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp') else thumb) as image:
                    self._paste_transform(canvas, image.convert('RGBA'), scene['backgroundTransform'], project)
        for actor in sorted(scene['actors'], key=lambda a: project['roleOrder'].index(a['slot'])):
            with Image.open(self.sprites.file(actor['id'], False)) as image:
                image = image.convert('RGBA')
                box = image.getchannel('A').getbbox()
                if not box:
                    continue
                if actor.get('alignment'):
                    from composition_library import render_aligned
                    image=render_aligned(self.sprites.file(actor['id'],False),actor['alignment'])
                else:image = image.crop(box)
                self._paste_transform(canvas, image, actor['transform'], project)
        from column_workflow import overlay_transform
        for overlay in project.get('overlays', []):
            with Image.open(self.backgrounds.file(overlay['image'])) as image:
                image = image.convert('RGBA')
                transform = overlay_transform(overlay, project['width'], project['height'], image.width, image.height)
                self._paste_transform(canvas, image, transform, project)
        canvas.save(path, quality=85)

    @staticmethod
    def _paste_transform(canvas, image, transform, project):
        fit = min(canvas.width/image.width, canvas.height/image.height)
        sx, sy = fit*transform['scaleX']/100, fit*transform['scaleY']/100
        cx = canvas.width/2 + transform['x']*canvas.width/project['width']
        cy = canvas.height/2 - transform['y']*canvas.height/project['height']
        angle = math.radians(transform['rotation'])
        cos, sin = math.cos(angle), math.sin(angle)
        inverse = (cos/sx, sin/sx, image.width/2-(cos*cx+sin*cy)/sx,
                   -sin/sy, cos/sy, image.height/2+(sin*cx-cos*cy)/sy)
        #Render only the visible canvas; large zoom must not allocate giant thumbnails.
        layer = image.transform(canvas.size, Image.Transform.AFFINE, inverse,
                                resample=Image.Resampling.BICUBIC)
        canvas.paste(layer, (0, 0), layer)
