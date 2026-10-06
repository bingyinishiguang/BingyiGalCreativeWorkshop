"""HTTP endpoints for the background library and rough-cut workbench."""
from __future__ import annotations

import io
import mimetypes
import os
import re
from pathlib import Path

from PIL import Image

import file_dialog
from background_library import BackgroundLibrary, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from rough_cut import RoughCut
from audio_library import AudioLibrary
from local_tts import LocalTTS
from script_voice import ScriptVoice
from subtitle_tools import read_text, parse_srt

POST_PATHS = {'/api/localtts/component-pick', '/api/localtts/component-select', '/api/backgrounds/pick', '/api/backgrounds/import', '/api/backgrounds/update',
              '/api/backgrounds/trash', '/api/backgrounds/restore', '/api/roughcut/save',
              '/api/roughcut/export', '/api/roughcut/options', '/api/audio/pick',
              '/api/audio/import','/api/audio/update','/api/audio/srt','/api/roughcut/subtitle-preset',
              '/api/roughcut/rename-sprite', '/api/composition/group-suggest', '/api/composition/group-save',
              '/api/composition/preset-save', '/api/composition/preset-apply',
              '/api/composition/preset-rename', '/api/composition/preset-delete', '/api/roughcut/build-script',
              '/api/localtts/settings', '/api/localtts/test', '/api/localtts/generate', '/api/localtts/pick', '/api/localtts/start', '/api/localtts/voice-select', '/api/localtts/voices-folder',
              '/api/timeline-voice/generate','/api/timeline-voice/preview','/api/roughcut/rebuild-preview',
              '/api/script/import','/api/script/pick','/api/script/preset','/api/script/generate','/api/script/stop','/api/script/take','/api/script/save',
'/api/roughcut/column-save','/api/roughcut/column-build','/api/roughcut/column-check','/api/roughcut/overlays-check'}


class ProductionAPI:
    def __init__(self, data_dir, output_root, sprites, recover=None):
        self.backgrounds = BackgroundLibrary(output_root / 'Backgrounds')
        self.audio = AudioLibrary(output_root / 'Audio')
        self.cut = RoughCut(data_dir / 'RoughCut', self.backgrounds, sprites, self.audio)
        from column_workflow import ColumnWorkflow
        self.columns = ColumnWorkflow(self.cut)
        self.localtts = LocalTTS(data_dir / 'LocalTTS',self.audio)
        self.scriptvoice = ScriptVoice(data_dir / 'ScriptVoice',self.localtts)
        from timeline_voice import TimelineVoice
        self.timelinevoice=TimelineVoice(self.cut,self.localtts)
        from composition_library import CompositionLibrary
        self.composition = CompositionLibrary(self.cut.root,sprites,recover)

    def post(self, handler, path, payload):
        if path == '/api/roughcut/column-check':
            handler.send_json(self.columns.preflight(payload))
        elif path == '/api/roughcut/overlays-check':
            from column_workflow import normalize_overlays
            from rough_cut import number
            handler.send_json({'overlays':normalize_overlays(payload.get('overlays'), self.backgrounds, number)})
        elif path == '/api/roughcut/column-save':
            handler.send_json(self.columns.save(payload))
        elif path == '/api/roughcut/column-build':
            handler.send_json(self.columns.build(payload))
        elif path.startswith('/api/composition/'):
            actions={'group-suggest':lambda:self.composition.suggest(payload.get('ids')),
                     'group-save':lambda:self.composition.save_group(payload),
                     'preset-save':lambda:self.composition.save_preset(payload),
                     'preset-apply':lambda:self.composition.apply_preset(payload),
                     'preset-rename':lambda:self.composition.rename_preset(payload),
                     'preset-delete':lambda:self.composition.delete_preset(payload.get('id'))}
            action=actions.get(path.rsplit('/',1)[-1])
            if not action:return False
            handler.send_json(action() or {'ok':True})
        elif path == '/api/timeline-voice/generate':
            handler.send_json(self.timelinevoice.generate(payload))
        elif path == '/api/timeline-voice/preview':
            handler.send_json(self.timelinevoice.preview(payload))
        elif path == '/api/audio/pick':
            handler.send_json({'paths':file_dialog.browse_for_images('导入配音、BGM 或音效',file_filter='音频\0*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg;*.wma\0\0')})
        elif path == '/api/audio/import':
            paths = payload.get('paths')
            if not isinstance(paths,list) or not 1 <= len(paths) <= 200:
                raise ValueError('一次请选择 1–200 个音频')
            results = []
            for source in paths:
                try:
                    results.append({'source':Path(source).name,**self.audio.import_file(source)})
                except (ValueError,OSError) as error:
                    results.append({'source':Path(source).name,'error':str(error)})
            handler.send_json({'results':results})
        elif path == '/api/audio/update':
            handler.send_json(self.audio.update(payload))
        elif path == '/api/audio/srt':
            paths = file_dialog.browse_for_images('选择对应 SRT 字幕',file_filter='字幕\0*.srt\0\0')
            handler.send_json({'cues':parse_srt(read_text(paths[0])) if paths else None})
        elif path == '/api/script/import':
            handler.send_json(self.scriptvoice.import_script(payload))
        elif path == '/api/script/save':
            handler.send_json(self.scriptvoice.save_plan(payload))
        elif path == '/api/script/pick':
            handler.send_json({'paths':file_dialog.browse_for_images('选择 TXT / DOCX 剧本',file_filter='剧本\0*.txt;*.docx\0\0')})
        elif path == '/api/script/preset':
            handler.send_json(self.scriptvoice.capture(payload))
        elif path == '/api/script/generate':
            handler.send_json(self.scriptvoice.start(payload))
        elif path == '/api/script/stop':
            handler.send_json(self.scriptvoice.cancel(payload))
        elif path == '/api/script/take':
            handler.send_json(self.scriptvoice.select_take(payload))
        elif path == '/api/localtts/component-pick':
            from app_settings import browse_for_directory
            folder=browse_for_directory('选择外置配音组件文件夹')
            handler.send_json(self.localtts.select_component(folder) if folder else {'cancelled':True})
        elif path == '/api/localtts/component-select':
            handler.send_json(self.localtts.select_component(payload.get('root')))
        elif path == '/api/localtts/voice-select':
            handler.send_json(self.localtts.select_voice(payload.get('id')))
        elif path == '/api/localtts/voices-folder':
            if os.name=='nt':os.startfile(str(self.localtts.voices.root.resolve()))
            handler.send_json({'folder':str(self.localtts.voices.root.resolve())})
        elif path == '/api/localtts/settings':
            handler.send_json(self.localtts.save(payload))
        elif path == '/api/localtts/test':
            handler.send_json(self.localtts.test())
        elif path == '/api/localtts/generate':
            handler.send_json(self.localtts.generate(payload))
        elif path == '/api/localtts/start':
            handler.send_json(self.localtts.request_start(payload))
        elif path == '/api/localtts/pick':
            handler.send_json({'paths':file_dialog.browse_for_images('选择固定参考音频',file_filter='音频\0*.wav;*.mp3;*.flac;*.ogg;*.m4a\0\0')})
        elif path == '/api/roughcut/subtitle-preset':
            from dialogue_timeline import normalize_dialogue
            from rough_cut import number, atomic_json
            style = normalize_dialogue({'subtitleStyle':payload},None,number)['subtitleStyle']
            atomic_json(self.cut.root/'subtitle-preset.json',style)
            handler.send_json(style)
        elif path == '/api/roughcut/rename-sprite':
            item = self.cut.sprites.metadata(payload.get('id'))
            if item is None:
                raise ValueError('立绘不存在')
            handler.send_json(self.cut.sprites.update(item['id'],False,payload.get('name'),item['note'],item['favorite']))
        elif path == '/api/backgrounds/pick':
            handler.send_json({'paths': file_dialog.browse_for_backgrounds()})
        elif path == '/api/backgrounds/import':
            paths = payload.get('paths')
            folder = payload.get('folder')
            if folder:
                root = Path(str(folder)).resolve()
                if not root.is_dir():
                    raise ValueError('素材文件夹不存在')
                paths = []
                for directory, dirs, files in os.walk(root, followlinks=False):
                    dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
                    for name in sorted(files):
                        p = Path(directory) / name
                        if p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                            paths.append(str(p))
                            if len(paths) > 200:
                                raise ValueError('文件夹内超过 200 个素材，请分批选择文件导入')
            if not isinstance(paths, list) or not 1 <= len(paths) <= 200:
                raise ValueError('一次请选择 1–200 个背景文件')
            results = []
            for value in paths:
                try:
                    result = self.backgrounds.import_file(Path(str(value)), payload.get('tags', []))
                    results.append({'source': Path(str(value)).name, **result})
                except (ValueError, OSError, Image.DecompressionBombError) as error:
                    results.append({'source': Path(str(value)).name, 'error': str(error)})
            handler.send_json({'results': results})
        elif path == '/api/backgrounds/update':
            handler.send_json(self.backgrounds.update(payload.get('id'), payload.get('name'),
                                                      payload.get('tags', []), payload.get('favorite')))
        elif path in ('/api/backgrounds/trash', '/api/backgrounds/restore'):
            handler.send_json(self.backgrounds.trash(payload.get('id'), path.endswith('restore')))
        elif path == '/api/roughcut/options':
            handler.send_json(self.cut.save_options(payload))
        elif path == '/api/roughcut/build-script':
            from script_plan import build_timeline
            from rough_cut import number
            handler.send_json(build_timeline(payload,self.cut,number))
        elif path == '/api/roughcut/rebuild-preview':
            from script_rebuild import preview
            handler.send_json(preview(payload,self.cut))
        elif path == '/api/roughcut/save':
            handler.send_json(self.cut.save(payload))
        elif path == '/api/roughcut/export':
            handler.send_json(self.cut.export(payload))
        else:
            return False
        return True

    def get(self, handler, path, query):
        arg = lambda name, default='': query.get(name, [default])[0]
        if path == '/api/roughcut/columns':
            handler.send_json(self.columns.list())
        elif path == '/api/composition':
            handler.send_json(self.composition.list())
        elif path == '/api/timeline-voice/history':
            handler.send_json(self.timelinevoice.history(arg('target')))
        elif path == '/api/audio':
            handler.send_json(self.audio.list(arg('search'),arg('kind'),arg('trash')=='1'))
        elif path == '/api/audio/media':
            stream_file(handler,self.audio.file(arg('id')))
        elif path == '/api/script/presets':
            handler.send_json(self.scriptvoice.presets())
        elif path == '/api/script/drafts':
            handler.send_json(self.scriptvoice.list_plans())
        elif path == '/api/script/draft':
            handler.send_json(self.scriptvoice.plan(arg('id')))
        elif path == '/api/script/jobs':
            handler.send_json(self.scriptvoice.list())
        elif path == '/api/script/job':
            handler.send_json(self.scriptvoice.job(arg('id')))
        elif path == '/api/localtts/component':
            handler.send_json(self.localtts.component_status())
        elif path == '/api/localtts/settings':
            handler.send_json(self.localtts.settings())
        elif path == '/api/localtts/devices':
            handler.send_json(self.localtts.devices())
        elif path == '/api/localtts/voices':
            handler.send_json(self.localtts.voices.scan())
        elif path == '/api/localtts/models':
            handler.send_json(self.localtts.models(arg('root') or None))
        elif path == '/api/localtts/history':
            handler.send_json(self.localtts.history())
        elif path == '/api/localtts/media':
            stream_file(handler,self.localtts.file(arg('id')))
        elif path == '/api/roughcut/subtitle-preset':
            from dialogue_timeline import DEFAULT_STYLE
            import json
            preset = self.cut.root/'subtitle-preset.json'
            handler.send_json(json.loads(preset.read_text('utf-8')) if preset.is_file() else DEFAULT_STYLE)
        elif path == '/api/backgrounds':
            handler.send_json(self.backgrounds.list(arg('search'), arg('kind'), arg('favorite')=='1', arg('trash')=='1'))
        elif path in ('/api/backgrounds/media', '/api/backgrounds/thumb'):
            item_id = arg('id')
            item = self.backgrounds.get(item_id, arg('trash')=='1')
            file = self.backgrounds.media / item['filename']
            if path.endswith('thumb'):
                file = self.backgrounds.thumbs / (item['id'] + '.jpg')
            if not file.is_file():
                handler.send_error(404)
                return True
            stream_file(handler, file)
        elif path == '/api/roughcut/options':
            handler.send_json(self.cut.options())
        elif path == '/api/roughcut/projects':
            handler.send_json(self.cut.list_projects())
        elif path == '/api/roughcut/project':
            handler.send_json(self.cut.load(arg('id')))
        elif path == '/api/roughcut/sprites':
            #Ordinary sprites only; the existing special partition stays separate.
            offset = max(0, int(arg('offset', '0')))
            handler.send_json(self.cut.sprites.list(False, search=arg('search'), limit=48, offset=offset))
        elif path == '/api/roughcut/sprite':
            file = self.cut.sprites.file(arg('id'), False)
            if not file:
                handler.send_error(404)
                return True
            with Image.open(file) as image:
                image = image.convert('RGBA')
                if arg('alignment'):
                    import json
                    from composition_library import render_aligned
                    image=render_aligned(file,json.loads(arg('alignment')))
                else:
                    box = image.getchannel('A').getbbox()
                    if box:image = image.crop(box)
                buffer = io.BytesIO()
                image.save(buffer, 'PNG')
            handler.send_bytes(buffer.getvalue(), 'image/png', cache_seconds=600)
        else:
            return False
        return True


def stream_file(handler, path):
    """Single-byte-range streaming keeps large video previews out of RAM."""
    size = path.stat().st_size
    start, end = 0, size-1
    range_header = handler.headers.get('Range', '')
    if range_header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(size-1, int(right)) if right else size-1
            else:
                suffix = int(right)
                if suffix <= 0:
                    raise ValueError()
                start = max(0, size-suffix)
            if start > end or start >= size:
                raise ValueError()
        except ValueError:
            handler.send_response(416)
            handler.send_header('Content-Range', f'bytes */{size}')
            handler.send_header('Content-Length', '0')
            handler.end_headers()
            return
    handler.send_response(206 if range_header else 200)
    handler.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
    handler.send_header('Accept-Ranges', 'bytes')
    handler.send_header('Content-Length', str(end-start+1))
    handler.send_header('Cache-Control', 'no-store')
    if range_header:
        handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
    handler.end_headers()
    with path.open('rb') as stream:
        stream.seek(start)
        remaining = end-start+1
        while remaining > 0:
            data = stream.read(min(65536, remaining))
            if not data:
                break
            handler.wfile.write(data)
            remaining -= len(data)
