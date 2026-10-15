"""Local subtitle tools and cancellable jobs; project changes are returned for UI undo."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from rough_cut import atomic_json
from subtitle_tools import validate_cues


class Cancelled(Exception):
    pass


class SubtitleAssistant:
    def __init__(self, root, cut, audio):
        self.root = Path(root)
        self.cut, self.audio = cut, audio
        self.lock = threading.RLock()
        self.jobs = {}
        self.events = {}

    def _settings(self):
        path = self.root / 'settings.json'
        return json.loads(path.read_text('utf-8')) if path.exists() else {
            'models': [], 'activeModelId': '',
            'asr': {'modelPath': '', 'pythonPath': '', 'device': 'cpu', 'computeType': 'int8'},
            'translation': {'provider': 'baidu', 'appId': '', 'secret': ''}}

    def settings(self):
        with self.lock:
            value = self._settings()
        for model in value['models']:
            model['hasApiKey'] = bool(model.pop('apiKey', ''))
        value['translation']['hasSecret'] = bool(value['translation'].pop('secret', ''))
        return value

    def save_settings(self, payload):
        with self.lock:
            previous = self._settings()
            models = payload.get('models', previous['models'])
            if not isinstance(models, list) or len(models) > 20:
                raise ValueError('最多配置 20 个模型')
            old = {m['id']: m for m in previous['models']}
            clean = []
            for model in models:
                key = str(model.get('id') or uuid.uuid4().hex)
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key) or any(m['id'] == key for m in clean):
                    raise ValueError('模型编号重复或格式不正确')
                url = str(model.get('baseUrl', '')).strip().rstrip('/')
                if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
                    raise ValueError('API 地址须以 http:// 或 https:// 开头')
                clean.append({'id': key, 'name': str(model.get('name', '自定义模型'))[:100],
                              'baseUrl': url, 'model': str(model.get('model', '')).strip()[:200],
                              'apiKey': str(model.get('apiKey') or old.get(key, {}).get('apiKey', ''))})
            active = str(payload.get('activeModelId', previous['activeModelId']))
            if active and active not in [m['id'] for m in clean]:
                raise ValueError('请选择已配置的模型')
            asr = {**previous['asr'], **payload.get('asr', {})}
            if asr.get('device') not in ('cpu', 'cuda', 'auto'):
                raise ValueError('识别设备支持 cpu、cuda 或 auto')
            translation = {**previous['translation'], **payload.get('translation', {})}
            translation['secret'] = str(translation.get('secret') or previous['translation'].get('secret', ''))
            translation.pop('hasSecret', None)
            translation['provider'] = 'baidu'
            atomic_json(self.root / 'settings.json', {'models': clean, 'activeModelId': active,
                                                       'asr': asr, 'translation': translation})
        return self.settings()

    def model(self, model_id=None):
        settings = self._settings()
        model = next((m for m in settings['models'] if m['id'] == (model_id or settings['activeModelId'])), None)
        if not model:
            raise ValueError('请先配置并选择聊天模型')
        return model

    def test(self, payload):
        from assistant_model import test_connection
        return test_connection(self.model(payload.get('modelId')))

    def manuscript_preview(self, payload):
        from manuscript_review import compare
        project = self.validate_project(payload.get('project', {}))
        clip = self.clip(project, payload.get('clipId'))
        return compare(clip['cues'], payload.get('manuscript'), payload.get('mode', 'auto'))

    def manuscript_apply(self, payload):
        from manuscript_review import apply_review
        project = self.validate_project(payload.get('project', {}))
        clip = self.clip(project, payload.get('clipId'))
        result = apply_review(project, clip['id'], payload.get('rows'),
                              payload.get('manuscript'), payload.get('name', ''))
        return {'project': self.validate_project(result)}

    def normalize_subtitles(self, payload):
        project = self.validate_project(payload.get('project', {}))
        return {'project': project, 'message': '已规范字幕：句间保留逗号，片段末尾去掉句末标点'}

    @staticmethod
    def clip(project, clip_id=None):
        clips = project.get('audioClips', [])
        selected = next((c for c in clips if c.get('id') == clip_id), None) if clip_id else None
        if selected is None and not clip_id and len(clips) == 1:
            selected = clips[0]
        if selected is None:
            raise ValueError('请明确选择一个配音片段')
        return selected

    def validate_project(self, project):
        project = copy.deepcopy(project)
        end = max((c.get('start', 0) + c.get('duration', 0) for c in project.get('audioClips', [])), default=1)
        if not project.get('scenes'):
            project['scenes'] = [{'blank': True, 'duration': min(3600, max(1, end)), 'actors': []}]
            remaining = end - 3600
            while remaining > 0:
                project['scenes'].append({'blank': True, 'duration': min(3600, remaining), 'actors': []})
                remaining -= 3600
        clean = self.cut.normalize(project)
        if project.get('id'):
            clean['id'] = project['id']
        return clean

    def pipeline(self, payload):
        source, target = payload.get('sourceLanguage', 'ja'), payload.get('targetLanguage', 'zh')
        languages = ('auto', 'ja', 'jp', 'en', 'zh', 'zh-CN', 'ko', 'kor', 'fr', 'fra', 'es', 'spa', 'de', 'ru')
        if source not in languages or target not in languages or target == 'auto':
            raise ValueError('识别或翻译语言不支持，请选择助手提供的语言')
        if payload.get('recognize', True) and source in ('jp', 'kor', 'fra', 'spa', 'zh-CN'):
            payload = {**payload, 'sourceLanguage': {'jp': 'ja', 'kor': 'ko', 'fra': 'fr', 'spa': 'es', 'zh-CN': 'zh'}[source]}
        project = self.validate_project(payload.get('project', {}))
        self.clip(project, payload.get('clipId'))
        if not payload.get('recognize', True) and not payload.get('translate', True):
            raise ValueError('请选择识别或翻译步骤')
        with self.lock:
            if any(j['status'] in ('queued', 'running') for j in self.jobs.values()):
                raise ValueError('已有字幕任务运行，请等待完成或取消')
            job_id = uuid.uuid4().hex
            job = {'id': job_id, 'status': 'queued', 'stage': '等待执行', 'logs': []}
            self.jobs[job_id] = job
            self.events[job_id] = threading.Event()
            # Keep a bounded in-memory history without saving audio or secrets in logs.
            completed = [key for key, value in self.jobs.items() if value['status'] not in ('queued', 'running')]
            for key in completed[:-30]:
                self.jobs.pop(key, None); self.events.pop(key, None)
        thread = threading.Thread(target=self._run, args=(job_id, project, copy.deepcopy(payload), self._settings()), daemon=True)
        thread.start()
        return {'job': self.job(job_id)}

    def job(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('字幕任务不存在或已过期')
            return copy.deepcopy(self.jobs[job_id])

    def cancel(self, payload):
        job_id = payload.get('id')
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('字幕任务不存在')
            if self.jobs[job_id]['status'] in ('queued', 'running'):
                if self.jobs[job_id].get('committing'):
                    return self.job(job_id)
                self.events[job_id].set()
                self.jobs[job_id]['stage'] = '正在取消；当前识别或请求结束后停止'
        return self.job(job_id)

    def _check(self, job_id):
        if self.events[job_id].is_set():
            raise Cancelled()

    def _stage(self, job_id, message):
        self._check(job_id)
        with self.lock:
            self.jobs[job_id]['stage'] = message
            self.jobs[job_id]['logs'].append(message)
            self.jobs[job_id]['logs'] = self.jobs[job_id]['logs'][-100:]

    def recognize(self, path, settings, language, job_id):
        from assistant_asr import recognize
        try:
            return recognize(path, {**settings, 'language': language}, self.events[job_id],
                             lambda message: self._stage(job_id, message))
        except Exception:
            self._check(job_id)
            raise

    def translate(self, cues, settings, source, target, job_id):
        from baidu_translation import translate_text
        app_id, secret = settings.get('appId'), settings.get('secret')
        if not app_id or not secret:
            raise ValueError('请先配置百度翻译 APP ID 和密钥')
        result = []
        for index, cue in enumerate(cues):
            self._stage(job_id, f'翻译字幕 {index + 1}/{len(cues)}')
            text=translate_text(cue['text'],settings,source,target)
            self._check(job_id)
            result.append({**cue, 'text': text})
            if index + 1 < len(cues) and self.events[job_id].wait(1.05):
                raise Cancelled()
        return result

    def _run(self, job_id, project, payload, settings):
        try:
            with self.lock:
                self.jobs[job_id]['status'] = 'running'
            clip = self.clip(project, payload.get('clipId'))
            item = self.audio.get(clip['audio'])
            cues = clip.get('cues', [])
            source, target = payload.get('sourceLanguage', 'ja'), payload.get('targetLanguage', 'zh')
            if payload.get('recognize', True):
                self._stage(job_id, '识别配音（本地模型）')
                cues = self.recognize(self.audio.file(clip['audio']), settings['asr'], source, job_id)
            if payload.get('translate', True):
                if not cues:
                    raise ValueError('没有可翻译的字幕，请先识别或导入 SRT')
                cues = self.translate(cues, settings['translation'], source, target, job_id)
            self._stage(job_id, '校验字幕与项目')
            clip['cues'] = validate_cues(cues, item['duration'])
            clip['text'] = '\n'.join(c['text'] for c in clip['cues'])
            clip['subtitles'] = True
            project = self.validate_project(project)
            result = {'project': project}
            if payload.get('export'):
                self._stage(job_id, '输出剪映草稿')
                with self.lock:
                    self._check(job_id)
                    self.jobs[job_id]['committing'] = True
                result['exportResult'] = self.cut.export(project)
            with self.lock:
                self._check(job_id)
                self.jobs[job_id].update(status='completed', stage='完成', result=result, **result)
        except Cancelled:
            with self.lock:
                self.jobs[job_id].update(status='cancelled', stage='已取消')
        except Exception as error:
            with self.lock:
                self.jobs[job_id].update(status='failed', stage='失败', error=self.safe_error(error, settings))

    @staticmethod
    def safe_error(error, settings):
        message = str(error)
        secrets = [m.get('apiKey', '') for m in settings.get('models', [])]
        secrets.append(settings.get('translation', {}).get('secret', ''))
        for secret in secrets:
            if secret:
                message = message.replace(secret, '[密钥]')
        return message[:1000]

    def chat(self, payload):
        from assistant_model import plan_message
        project = self.validate_project(payload.get('project', {}))
        plan = plan_message(self.model(payload.get('modelId')), {**payload, 'project': project})
        actions = plan.get('actions', [])
        if not isinstance(actions, list) or len(actions) > 16:
            raise ValueError('模型返回的操作数量或格式不正确')
        result = {'message': str(plan.get('message', ''))[:10000], 'actions': actions}
        deferred = None
        export = False
        for action in actions:
            tool, args = action.get('tool'), action.get('arguments', {})
            if tool == 'undo':
                if len(actions) != 1:
                    raise ValueError('撤销须作为独立操作执行')
                result['undo'] = True
            elif tool in ('generate_subtitles', 'recognize_subtitles', 'translate_subtitles'):
                if deferred:
                    raise ValueError('请将识别和翻译合并为一次生成字幕操作')
                deferred = {**args, 'clipId': args.get('clipId') or payload.get('clipId')}
                if tool == 'recognize_subtitles':
                    deferred.update(recognize=True, translate=False, sourceLanguage=args.get('language', 'auto'))
                elif tool == 'translate_subtitles':
                    deferred.update(recognize=False, translate=True)
            elif tool == 'replace_subtitle':
                clip = self.clip(project, args.get('clipId') or payload.get('clipId'))
                index = args.get('cueIndex')
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(clip['cues']):
                    raise ValueError('字幕序号不存在')
                clip['cues'][index]['text'] = str(args.get('text', '')).strip()
                clip['text'] = '\n'.join(c['text'] for c in clip['cues'])
            elif tool == 'set_subtitle_style':
                target = self.clip(project, args.get('clipId') or payload.get('clipId'))
                target['subtitleStyle'] = {**target.get('subtitleStyle', project.get('subtitleStyle', {})), **args.get('style', {})}
            elif tool == 'remove_subtitle_punctuation':
                clip = self.clip(project, args.get('clipId') or payload.get('clipId'))
                import unicodedata
                for cue in clip['cues']:
                    cue['text'] = ''.join(c for c in cue['text'] if not unicodedata.category(c).startswith('P')).strip()
                clip['text'] = '\n'.join(c['text'] for c in clip['cues'])
            elif tool == 'export_draft':
                export = True
            else:
                raise ValueError('模型请求了未支持的工具：' + str(tool))
        project = self.validate_project(project)
        if deferred:
            result.update(self.pipeline({**deferred, 'project': project, 'export': export or deferred.get('export', False)}))
            result['message'] = '已启动字幕任务，请查看实际执行进度；完成后可应用到时间轴。'
        elif not result.get('undo') and actions:
            result['project'] = project
            result['message'] = '字幕操作已通过项目校验，可应用到时间轴并撤销。'
            if export:
                result['exportResult'] = self.cut.export(project)
                result['message'] = '剪映草稿已输出，请查看输出目录。'
        elif result.get('undo'):
            result['message'] = '正在撤销上一次项目修改。'
        return result
