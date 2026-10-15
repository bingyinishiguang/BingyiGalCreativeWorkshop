"""Japanese transcript repetition review and non-destructive PCM audio cuts."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import unicodedata
import uuid
import wave
from pathlib import Path


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold()
                   if not unicodedata.category(c).startswith(('P', 'Z', 'C')))


def find_repetitions(cues, manuscript):
    if not isinstance(cues, list) or not 1 <= len(cues) <= 10000:
        raise ValueError('请提供日语识别字幕')
    if not isinstance(manuscript, str) or not manuscript.strip() or len(manuscript) > 100000:
        raise ValueError('请提供日语原稿，不使用中文翻译作为删除依据')
    reference = normalized(manuscript)
    chars, times = [], []
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get('text'), str):
            raise ValueError('字幕格式错误')
        a, b = cue.get('start'), cue.get('end')
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a+b) or not 0 <= a < b:
            raise ValueError('字幕时间错误')
        words = cue.get('words')
        accurate = isinstance(words, list) and bool(words)
        parts = words if accurate else [{'text': cue['text'], 'start': a, 'end': b}]
        for part in parts:
            text = normalized(part.get('text', ''))
            wa, wb = part.get('start'), part.get('end')
            if type(wa) not in (int, float) or type(wb) not in (int, float) or not math.isfinite(wa+wb) or not a-.1 <= wa <= wb <= b+.1:
                raise ValueError('词级时间错误')
            for i, char in enumerate(text):
                chars.append(char)
                # Preserve the entire word boundary: character interpolation is
                # only a review estimate and never claimed as forced alignment.
                times.append((wa+(wb-wa)*i/len(text), wa+(wb-wa)*(i+1)/len(text), accurate))
    text = ''.join(chars)
    if len(text) > 100000:
        raise ValueError('识别文本过长，请分段检查')
    rows, covered = [], -1
    for i in range(len(text)):
        if i < covered:
            continue
        for n in range(min(80, (len(text)-i)//2), 2, -1):
            phrase = text[i:i+n]
            if phrase != text[i+n:i+2*n] or phrase not in reference:
                continue
            # Conservative: a phrase appearing twice in the author script is
            # not marked for deletion, even if spoken next to itself.
            if reference.count(phrase) > 1:
                continue
            start, end = times[i+n][0], times[i+2*n-1][1]
            first_end = times[i+n-1][1]
            if start < first_end-.05 or start-first_end > 2:
                continue
            rows.append({'id': len(rows), 'text': phrase, 'start': start, 'end': end,
                         'firstStart': times[i][0], 'firstEnd': first_end,
                         'estimated': True, 'wordTimestamps': all(t[2] for t in times[i+n:i+2*n]),
                         'note': '疑似重复的第二次朗读；时间为识别估计，试听并调整边界后再删除'})
            covered = i+2*n
            break
        if len(rows) >= 100:
            break
    return rows


class VoiceCleanup:
    def __init__(self, root, audio, assistant):
        self.root = Path(root)
        self.audio, self.assistant = audio, assistant
        self.previews = {}

    def preview(self, payload):
        audio_id = payload.get('audioId')
        path = self.audio.file(audio_id)
        cues = payload.get('cues') or self.audio.get(audio_id).get('cues', [])
        if payload.get('recognize'):
            from assistant_asr import recognize
            config = {**self.assistant._settings()['asr'], 'language': 'ja', 'includeWords': True}
            cues = recognize(path, config, threading.Event(), lambda _: None)
        rows = find_repetitions(cues, payload.get('manuscript'))
        key = uuid.uuid4().hex
        if len(self.previews) >= 16:
            self.previews.pop(next(iter(self.previews)))
        self.previews[key] = {'audioId': audio_id, 'hash': self.digest(path), 'rows': rows}
        return {'previewId': key, 'rows': rows, 'cues': cues,
                'note': '未删除音频；必须试听确认，导出后重新识别字幕'}

    @staticmethod
    def digest(path):
        h = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def save(self, payload):
        preview = self.previews.get(payload.get('previewId'))
        if not preview:
            raise ValueError('重复检查预览失效，请重新检查')
        path = self.audio.file(preview['audioId'])
        if self.digest(path) != preview['hash']:
            raise ValueError('音频已变化，请重新检查')
        cuts = payload.get('cuts')
        if not isinstance(cuts, list) or not 1 <= len(cuts) <= 100:
            raise ValueError('请勾选已试听确认的重复区间')
        directory = self.root / uuid.uuid4().hex
        directory.mkdir(parents=True)
        pcm = path
        if path.suffix.lower() != '.wav':
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise ValueError('当前支持 PCM WAV；其他格式请安装 FFmpeg 或先转换为 WAV')
            pcm = directory / 'decoded.wav'
            result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(path), '-vn', '-c:a', 'pcm_s16le', str(pcm)],
                                    capture_output=True, timeout=120,
                                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            if result.returncode:
                raise ValueError('音频解码失败')
        try:
            with wave.open(str(pcm), 'rb') as source:
                params = source.getparams()
                if params.comptype != 'NONE' or params.sampwidth not in (1, 2, 3, 4):
                    raise ValueError('请选择未压缩 PCM WAV')
                duration = params.nframes / params.framerate
                if duration > 1800 or params.nframes * params.nchannels * params.sampwidth > 256000000:
                    raise ValueError('清理支持 30 分钟、256 MB 以内的配音')
                frames = source.readframes(params.nframes)
                if len(frames) != params.nframes*params.nchannels*params.sampwidth:
                    raise ValueError('WAV 数据不完整，请重新导出')
        except (wave.Error, EOFError):
            raise ValueError('无法读取 PCM WAV，请将配音转为未压缩 WAV') from None
        intervals, ids = [], set()
        for cut in cuts:
            if not isinstance(cut, dict) or type(cut.get('id')) is not int or cut['id'] in ids or not 0 <= cut['id'] < len(preview['rows']):
                raise ValueError('重复区间编号错误')
            ids.add(cut['id'])
            a, b = cut.get('start'), cut.get('end')
            if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a+b) or not 0 <= a < b <= duration:
                raise ValueError('删除区间必须在音频时长以内')
            row = preview['rows'][cut['id']]
            if a < row['start']-1 or b > row['end']+1:
                raise ValueError('调整超出疑似重复附近一秒，请重新检查')
            intervals.append((round(a*params.framerate), round(b*params.framerate)))
        intervals.sort()
        if any(a < intervals[i-1][1] for i, (a, _) in enumerate(intervals) if i):
            raise ValueError('删除区间重叠')
        width = params.nchannels * params.sampwidth
        pieces, last = [], 0
        for a, b in intervals:
            if a < last or b <= a:
                raise ValueError('删除区间无效')
            pieces.append(frames[last*width:a*width])
            last = b
        pieces.append(frames[last*width:])
        if not any(pieces):
            raise ValueError('不能删除整段配音')
        # Short independent fades at the cut edges, without moving timing or
        # crossfading unrelated syllables. PCM16/32 are the common TTS exports.
        if params.sampwidth in (2, 4):
            import numpy as np
            dtype = '<i2' if params.sampwidth == 2 else '<i4'
            for i, piece in enumerate(pieces):
                if not piece:
                    continue
                samples = np.frombuffer(piece, dtype=dtype).reshape(-1, params.nchannels).copy()
                length = min(round(params.framerate*.005), len(samples)//2)
                if length:
                    if i:
                        samples[:length] = (samples[:length].astype(float)*np.linspace(0, 1, length)[:, None]).astype(dtype)
                    if i < len(pieces)-1:
                        samples[-length:] = (samples[-length:].astype(float)*np.linspace(1, 0, length)[:, None]).astype(dtype)
                pieces[i] = samples.tobytes()
        output = directory / '清理后配音.wav'
        with wave.open(str(output), 'wb') as target:
            target.setparams(params)
            target.writeframes(b''.join(pieces))
        if self.digest(path) != preview['hash']:
            raise ValueError('保存期间原音频已变化')
        record = {'sourceHash': preview['hash'], 'sourceUnchanged': True, 'cuts': cuts,
                  'removedSeconds': sum(b-a for a, b in intervals)/params.framerate,
                  'fadeMilliseconds': 5 if params.sampwidth in (2, 4) else 0,
                  'note': '以清理版重新识别字幕，再安排人物；已有项目时间轴未修改'}
        (directory / '配音删减记录.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf-8')
        imported = self.audio.import_file(str(output))
        return {'path': str(output), 'audioId': imported['item']['id'], **record}
