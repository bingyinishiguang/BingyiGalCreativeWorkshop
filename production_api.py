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
              '/api/timeline-voice/generate','/api/timeline-voice/preview','/api/timeline-voice/jobs','/api/timeline-voice/job-resume','/api/timeline-voice/job-stop','/api/roughcut/rebuild-preview',
              '/api/script/import','/api/script/pick','/api/script/preset','/api/script/generate','/api/script/stop','/api/script/take','/api/script/save',
'/api/roughcut/column-save','/api/roughcut/column-build','/api/roughcut/column-check','/api/roughcut/overlays-check'}

POST_PATHS.update('/api/assistant/' + action for action in ('settings', 'test', 'chat', 'pipeline', 'cancel'))
POST_PATHS.update(('/api/localtts/trash', '/api/localtts/restore'))
POST_PATHS.update('/api/assistant/' + action for action in ('manuscript-pick', 'manuscript-preview', 'manuscript-apply', 'normalize-subtitles'))
POST_PATHS.update('/api/existing-draft/' + action for action in ('pick', 'load', 'preview', 'normalize', 'save', 'chat', 'progress-save', 'progress-backup', 'recovery-list', 'recovery-preview', 'style-info', 'style-preview', 'preset-save'))
POST_PATHS.update('/api/existing-draft/' + action for action in ('relink-preview', 'relink-save', 'character-info', 'character-plan', 'character-save'))
POST_PATHS.update(('/api/voice-cleanup/preview', '/api/voice-cleanup/save'))
POST_PATHS.update('/api/bilingual-dialogue/' + action for action in ('template', 'start', 'job', 'cancel', 'export'))
POST_PATHS.update('/api/bilingual-pipeline/' + action for action in ('start','job','cancel','save'))
POST_PATHS.add('/api/bilingual-dialogue/pick-portraits')
POST_PATHS.update('/api/pause-cleanup/' + action for action in ('preview', 'save'))
POST_PATHS.update('/api/draft-publishing/' + action for action in ('options', 'pick-directory'))
POST_PATHS.update('/api/gal-story/' + action for action in ('new', 'demo', 'parse', 'save', 'preview', 'plan', 'chat', 'export', 'draft', 'voice', 'cancel', 'pick-asset', 'pick-text'))


class ProductionAPI:
    def __init__(self, data_dir, output_root, sprites, recover=None):
        self.backgrounds = BackgroundLibrary(output_root / 'Backgrounds')
        self.audio = AudioLibrary(output_root / 'Audio')
        self.cut = RoughCut(data_dir / 'RoughCut', self.backgrounds, sprites, self.audio)
        from ai_subtitle_assistant import SubtitleAssistant
        self.assistant = SubtitleAssistant(data_dir / 'SubtitleAssistant', self.cut, self.audio)
        from existing_draft import ExistingDraftEditor
        self.existing_drafts = ExistingDraftEditor(data_dir / 'ExistingDraftEdits')
        from draft_publish import DraftPublisher
        self.draft_publisher = DraftPublisher(data_dir / 'DraftPublishing',self.existing_drafts)
        from draft_video_tools import DraftVideoTools
        from voice_cleanup import VoiceCleanup
        self.draft_video = DraftVideoTools(self.existing_drafts)
        from bilingual_dialogue import BilingualDialogue
        self.bilingual_dialogue = BilingualDialogue(data_dir / 'BilingualDialogue', self.draft_video, self.assistant)
        from pause_cleanup import PauseCleanup
        self.pause_cleanup = PauseCleanup(data_dir / 'PauseCleanup', self.draft_video)
        self.bilingual_dialogue.pause_cleanup = self.pause_cleanup
        from bilingual_pipeline import BilingualPipeline
        self.bilingual_pipeline=BilingualPipeline(self.bilingual_dialogue,self.pause_cleanup,self.publish_draft)
        self.voice_cleanup = VoiceCleanup(data_dir / 'VoiceCleanup', self.audio, self.assistant)
        from column_workflow import ColumnWorkflow
        self.columns = ColumnWorkflow(self.cut)
        self.localtts = LocalTTS(data_dir / 'LocalTTS',self.audio)
        self.scriptvoice = ScriptVoice(data_dir / 'ScriptVoice',self.localtts)
        from timeline_voice import TimelineVoice
        self.timelinevoice=TimelineVoice(self.cut,self.localtts)
        from timeline_voice_jobs import TimelineVoiceJobs
        self.timelinevoicejobs=TimelineVoiceJobs(data_dir / 'TimelineVoiceJobs',self.timelinevoice)
        from composition_library import CompositionLibrary
        self.composition = CompositionLibrary(self.cut.root,sprites,recover)
        from gal_story import GalStory
        self.gal_story = GalStory(data_dir / 'GalStory', self.backgrounds, sprites, self.audio, self.localtts, self.assistant)
        self.gal_story.output_options = self.cut.options

    def post(self, handler, path, payload):
        if path.startswith('/api/gal-story/'):
            action = path.rsplit('/', 1)[-1]
            story = self.gal_story
            if action == 'preview':
                from gal_story_render import plan, render, at_time
                layout = plan(story, payload.get('project'))
                index, seconds = at_time(layout, payload.get('time', 0))
                image = render(story, layout['project'], index, seconds, layout, fades=payload.get('playing') is True)
                image.thumbnail((960, 540), Image.Resampling.LANCZOS)
                buffer = io.BytesIO(); image.save(buffer, 'JPEG', quality=88)
                handler.send_bytes(buffer.getvalue(), 'image/jpeg')
            elif action == 'plan':
                from gal_story_render import plan
                result = plan(story, payload.get('project'))
                result.pop('project', None)
                handler.send_json(result)
            elif action == 'pick-asset':
                paths = file_dialog.browse_for_images('选择剧情背景或透明立绘', file_filter='图片\0*.png;*.jpg;*.jpeg;*.webp\0\0')
                handler.send_json({'item': story.import_asset({**payload, 'path': paths[0]}) if paths else None})
            elif action == 'pick-text':
                from script_import import document_text
                paths = file_dialog.browse_for_images('导入剧情 TXT / DOCX', file_filter='剧情文本\0*.txt;*.docx\0\0')
                handler.send_json({'text': document_text(Path(paths[0])) if paths else None})
            else:
                actions = {'new':lambda _:story.new(), 'demo':lambda _:story.demo(), 'parse':story.parse, 'save':story.save,
                           'chat':story.chat, 'export':lambda p:story.start(p), 'draft':lambda p:story.start(p,'draft'), 'voice':lambda p:story.start(p,'voice'), 'cancel':story.cancel}
                if action not in actions:return False
                handler.send_json(actions[action](payload))
        elif path.startswith('/api/draft-publishing/'):
            if path.endswith('/options'):handler.send_json(self.draft_publisher.options(payload))
            else:
                from app_settings import browse_for_directory
                handler.send_json(dict(directory=browse_for_directory('选择剪映草稿根目录',payload.get('directory')) or None))
        elif path.startswith('/api/pause-cleanup/'):
            action = {'preview':self.pause_cleanup.preview, 'save':self.pause_cleanup.save}.get(path.rsplit('/',1)[-1])
            if action is None: return False
            handler.send_json(action(payload))
        elif path.startswith('/api/bilingual-pipeline/'):
            action={'start':self.bilingual_pipeline.start,'job':self.bilingual_pipeline.job,'cancel':self.bilingual_pipeline.cancel,'save':self.bilingual_pipeline.save}.get(path.rsplit('/',1)[-1])
            if action is None:return False
            handler.send_json(action(payload))
        elif path.startswith('/api/bilingual-dialogue/'):
            if path.endswith('/pick-portraits'):
                paths=file_dialog.browse_for_images('选择人物表情图片，无需重命名',file_filter='人物图片\0*.png;*.webp;*.jpg;*.jpeg\0\0')
                handler.send_json(dict(paths=paths));return True
            action = getattr(self.bilingual_dialogue, path.rsplit('/', 1)[-1], None)
            if action is None: return False
            result=action(payload)
            if path.endswith('/export'):
                original=self.bilingual_dialogue.jobs[payload['id']]['payload']
                result=self.publish_draft({**original,'publish':payload.get('publish')},result)
            handler.send_json(result)
        elif path.startswith('/api/voice-cleanup/'):
            action = {'preview': self.voice_cleanup.preview, 'save': self.voice_cleanup.save}.get(path.rsplit('/', 1)[-1])
            if action is None: return False
            handler.send_json(action(payload))
        elif path == '/api/existing-draft/pick':
            paths = file_dialog.browse_for_images('选择已有剪映草稿 draft_content.json', file_filter='剪映草稿\0draft_content.json\0\0')
            handler.send_json({'path': paths[0] if paths else None})
        elif path.startswith('/api/existing-draft/'):
            actions = {'load':self.existing_drafts.load,'preview':self.existing_drafts.preview,'normalize':self.existing_drafts.normalize,'save':self.existing_drafts.save,
                       'relink-preview': self.draft_video.relink_preview, 'relink-save': self.draft_video.relink_save,
                       'character-info': self.draft_video.character_info,
                       'character-plan': lambda value: self.draft_video.character_plan(value, self.assistant.model(value.get('modelId'))),
                       'character-save': self.draft_video.character_save,
                       'progress-save':self.existing_drafts.progress_save,
                       'progress-backup':self.existing_drafts.progress_backup,
                       'recovery-list':self.existing_drafts.recovery_list,'recovery-preview':self.existing_drafts.recovery_preview,
                       'style-info':lambda value:self.existing_drafts.style_info(value,allow_missing_font=True),'style-preview':self.existing_drafts.style_preview,'preset-save':self.existing_drafts.preset_save,
                       'chat':lambda value:self.existing_drafts.chat(value,self.assistant.model(value.get('modelId')))}
            action = actions.get(path.rsplit('/',1)[-1])
            if action is None:return False
            result=action(payload)
            if path.rsplit('/',1)[-1] in ('save','relink-save','character-save'):
                result=self.publish_draft(payload,result)
            handler.send_json(result)
        elif path == '/api/assistant/manuscript-pick':
            paths = file_dialog.browse_for_images('选择作者原稿 TXT', file_filter='作者原稿\0*.txt\0\0')
            if paths:
                from manuscript_review import validate_manuscript
                source = Path(paths[0])
                if source.suffix.lower() != '.txt':
                    raise ValueError('请选择 TXT 原稿文件')
                handler.send_json({'text': validate_manuscript(read_text(source)), 'name': source.name})
            else:
                handler.send_json({'text': None})
        elif path.startswith('/api/assistant/'):
            actions = {'settings': self.assistant.save_settings, 'test': self.assistant.test,
                       'chat': self.assistant.chat, 'pipeline': self.assistant.pipeline,
                       'cancel': self.assistant.cancel,
                       'manuscript-preview': self.assistant.manuscript_preview,
                       'manuscript-apply': self.assistant.manuscript_apply,
                       'normalize-subtitles': self.assistant.normalize_subtitles}
            action = actions.get(path.rsplit('/', 1)[-1])
            if action is None:
                return False
            handler.send_json(action(payload))
        elif path == '/api/roughcut/column-check':
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
        elif path == '/api/timeline-voice/jobs':
            handler.send_json(self.timelinevoicejobs.start(payload))
        elif path == '/api/timeline-voice/job-resume':
            handler.send_json(self.timelinevoicejobs.resume(payload))
        elif path == '/api/timeline-voice/job-stop':
            handler.send_json(self.timelinevoicejobs.stop(payload))
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
        elif path in ('/api/localtts/trash', '/api/localtts/restore'):
            handler.send_json(self.localtts.trash_take(payload.get('id'), path.endswith('restore')))
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

    def publish_draft(self,payload,result):
        result=self.draft_publisher.publish(payload,result)
        if result.get('published'):
            self.cut.save_options(dict(draftDirectory=str(Path(result['path']).parent)))
        return result

    def get(self, handler, path, query):
        arg = lambda name, default='': query.get(name, [default])[0]
        if path == '/api/bilingual-dialogue/portrait':
            image=self.bilingual_dialogue.portrait_preview(arg('token'),arg('sessionId'),arg('id'))
            buffer=io.BytesIO();image.save(buffer,'PNG');handler.send_bytes(buffer.getvalue(),'image/png')
        elif path == '/api/pause-cleanup/audio':
            if arg('id'):
                output = self.pause_cleanup.outputs.get(arg('id'))
                if not output or output['sessionId'] != arg('sessionId'):
                    raise ValueError('音频预览已失效')
                source = Path(output['path'])
            else:
                source, _, _ = self.pause_cleanup.source(dict(sessionId=arg('sessionId'), audioTrackIndex=int(arg('audioTrackIndex')),audioSegmentIndex=int(arg('audioSegmentIndex'))))
            stream_file(handler,source)
        elif path.startswith('/api/gal-story/'):
            action = path.rsplit('/', 1)[-1]
            story = self.gal_story
            if action == 'video': stream_file(handler, story.output_file(arg('id')))
            elif action == 'subtitles': handler.send_bytes(story.subtitle_file(arg('id')).read_bytes(),'application/x-subrip; charset=utf-8')
            elif action == 'asset':
                image = Image.open(story.asset_file(arg('id'))).convert('RGBA')
                image.thumbnail((480, 480), Image.Resampling.LANCZOS)
                buffer = io.BytesIO(); image.save(buffer, 'PNG')
                handler.send_bytes(buffer.getvalue(), 'image/png')
            else:
                actions = {'status':story.status, 'catalog':lambda: {'items':story.catalog()}, 'projects':story.list, 'last':story.last, 'outputs':lambda:story.outputs(arg('projectId')),
                           'project':lambda:story.load(arg('id')), 'job':lambda:story.job(arg('id'))}
                if action not in actions:return False
                handler.send_json(actions[action]())
        elif path == '/api/assistant/settings':
            handler.send_json(self.assistant.settings())
        elif path == '/api/assistant/job':
            handler.send_json(self.assistant.job(arg('id')))
        elif path == '/api/roughcut/columns':
            handler.send_json(self.columns.list())
        elif path == '/api/composition':
            handler.send_json(self.composition.list())
        elif path == '/api/timeline-voice/jobs':
            handler.send_json(self.timelinevoicejobs.list())
        elif path == '/api/timeline-voice/job':
            handler.send_json(self.timelinevoicejobs.job(arg('id')))
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
            handler.send_json(self.localtts.history(arg('trash')=='1'))
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
