"""Copied local audio assets with optional same-name SRT and stable IDs."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import threading
import uuid
from pathlib import Path

from rough_cut import atomic_json
from subtitle_tools import parse_srt, read_text, validate_cues

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma'}


class AudioLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.media = self.root / 'media'
        self.records = self.root / 'records'
        self.media.mkdir(parents=True, exist_ok=True)
        self.records.mkdir(exist_ok=True)
        self.lock = threading.RLock()

    def record_path(self, item_id):
        import re
        if not re.fullmatch('[a-f0-9]{32}', str(item_id)):
            raise ValueError('音频编号不正确')
        return self.records / (str(item_id)+'.json')

    def get(self, item_id, trash=False):
        path = self.record_path(item_id)
        if not path.is_file():
            raise ValueError('音频不存在')
        try:
            item = self._read_record(path)
        except (OSError, UnicodeError, ValueError, TypeError):
            raise ValueError('音频资料无法读取，请检查或恢复原资料文件') from None
        if item.get('deleted', False) != bool(trash):
            raise ValueError('音频已移入回收站或不存在')
        item['missing'] = not (self.media / item['filename']).is_file()
        return item

    def _read_record(self, path):
        item=json.loads(path.read_text('utf-8'))
        if not isinstance(item,dict) or item.get('id')!=path.stem or self.record_path(item.get('id'))!=path:
            raise ValueError('音频资料编号不正确')
        filename=item.get('filename')
        if not isinstance(filename,str) or Path(filename).suffix.lower() not in AUDIO_EXTENSIONS or filename!=item['id']+Path(filename).suffix:
            raise ValueError('音频资料文件名不正确')
        duration=item.get('duration')
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 0<duration<=10800:
            raise ValueError('音频资料时长不正确')
        if not isinstance(item.get('name'),str) or not item['name'].strip() or item.get('kind') not in ('dialogue','bgm','effect'):
            raise ValueError('音频资料名称或分类不正确')
        if any(not isinstance(item.get(field,''),str) for field in ('character','text','work')):
            raise ValueError('音频文字资料格式不正确')
        if not isinstance(item.get('tags',[]),list) or any(not isinstance(tag,str) for tag in item.get('tags',[])):
            raise ValueError('音频标签资料格式不正确')
        cues=item.get('cues')
        if not isinstance(cues,list) or len(cues)>10000:
            raise ValueError('音频字幕资料格式不正确')
        for cue in cues:
            if not isinstance(cue,dict) or not isinstance(cue.get('text'),str) or not cue['text'].strip():
                raise ValueError('音频字幕资料格式不正确')
            start,end=cue.get('start'),cue.get('end')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,end)) or not 0<=start<end<=duration+.05:
                raise ValueError('音频字幕时间不正确')
        return item

    def file(self, item_id):
        item = self.get(item_id)
        path = self.media / item['filename']
        if not path.is_file():
            raise ValueError('音频文件丢失，请重新导入')
        return path

    def list(self, search='', kind='', trash=False):
        items,warnings = [],[]
        with self.lock:
            for path in self.records.glob('*.json'):
                try:
                    item=self._read_record(path)
                    if bool(item.get('deleted')) != bool(trash):
                        continue
                    item['missing']=not (self.media/item['filename']).is_file()
                    if (not kind or item['kind'] == kind) and str(search).casefold() in (
                            item['name']+' '+item.get('character','')+' '+item.get('text','')+' '+
                            item.get('work','')+' '+' '.join(item.get('tags',[]))).casefold():
                        items.append(item)
                except (OSError,UnicodeError,ValueError,TypeError):
                    warnings.append({'record':path.name,'message':'音频资料无法读取，原资料文件已保留。'})
        return {'items': sorted(items, key=lambda x: x['name']), 'total': len(items), 'warnings':warnings}

    def import_file(self, source):
        source = Path(source).resolve()
        if not source.is_file() or source.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError('请选择 MP3/WAV/M4A/AAC/FLAC/OGG/WMA 音频')
        from pymediainfo import MediaInfo
        tracks = MediaInfo.parse(str(source)).audio_tracks
        if not tracks or not tracks[0].duration:
            raise ValueError('无法读取音频时长')
        duration = float(tracks[0].duration)/1000
        if not 0 < duration <= 10800:
            raise ValueError('音频时长须在三小时以内')
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        sha = digest.hexdigest()
        with self.lock:
            previous=None
            for path in self.records.glob('*.json'):
                try:
                    record=self._read_record(path)
                except (OSError,UnicodeError,ValueError,TypeError):
                    continue
                if record.get('hash')==sha:
                    previous=record
                    break
            item = previous or {'id': uuid.uuid4().hex, 'name': source.stem.strip()[:100] or '音频', 'hash': sha,
                                'kind':'dialogue', 'character':'', 'text':'', 'cues':[]}
            item.update(duration=duration, deleted=False, filename=item['id']+source.suffix.lower())
            target = self.media / item['filename']
            if not target.is_file():
                temporary = target.with_suffix(target.suffix+'.tmp')
                try:
                    shutil.copyfile(source, temporary)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            warning = ''
            srt = source.with_suffix('.srt')
            if srt.is_file() and not item['cues']:
                try:
                    item['cues'] = validate_cues(parse_srt(read_text(srt)), duration)
                    item['text'] = '\n'.join(c['text'] for c in item['cues'])
                except ValueError as error:
                    warning = '音频已导入，同名字幕未导入：'+str(error)
            atomic_json(self.record_path(item['id']), item)
            return {'item': self.get(item['id']), 'duplicate': bool(previous), 'warning': warning}

    def update(self, payload):
        with self.lock:
            item = self.get(payload.get('id'), bool(payload.get('restore')))
            for field in ('name', 'character', 'text', 'work'):
                if field in payload:
                    item[field] = str(payload[field]).strip()[:20000 if field == 'text' else 100]
            if not item['name']:
                raise ValueError('音频名称不能为空')
            if 'tags' in payload:
                tags = payload['tags']
                if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                    raise ValueError('音频标签必须是文字列表')
                item['tags'] = list(dict.fromkeys(tag.strip()[:60] for tag in tags if tag.strip()))[:30]
            if 'kind' in payload:
                if payload['kind'] not in ('dialogue','bgm','effect'):
                    raise ValueError('音频分类不正确')
                item['kind'] = payload['kind']
            if 'srt' in payload:
                item['cues'] = validate_cues(parse_srt(payload['srt']), item['duration'])
            elif 'cues' in payload:
                item['cues'] = validate_cues(payload['cues'], item['duration'])
            if 'deleted' in payload:
                item['deleted'] = bool(payload['deleted'])
            item.pop('missing', None)
            atomic_json(self.record_path(item['id']), item)
            return self.get(item['id'], item.get('deleted', False))
