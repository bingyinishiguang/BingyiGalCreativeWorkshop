"""Strict SRT import and editable, audio-relative subtitle cues."""
from __future__ import annotations

import re
from pathlib import Path


def read_text(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError('字幕文件超过 2 MB')
    encodings = ('utf-16',) if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else ('utf-8-sig','gb18030')
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError('无法识别字幕编码，请保存为 UTF-8')


def parse_srt(text):
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError('字幕内容过大或格式不正确')
    stamp = r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})'
    timing = re.compile(r'^' + stamp + r'\s*-->\s*' + stamp + r'\s*$')
    cues = []
    def seconds(parts):
        h, m, s, ms = map(int, parts)
        if m >= 60 or s >= 60:
            raise ValueError('字幕时间格式不正确')
        return h*3600 + m*60 + s + ms/1000
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip().lstrip('\ufeff')):
        if not block.strip():
            continue
        lines = block.splitlines()
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            raise ValueError('字幕缺少时间轴')
        match = timing.fullmatch(lines[0].strip())
        if not match or len(lines) < 2:
            raise ValueError(f'第 {len(cues)+1} 条字幕格式不正确')
        start, end = seconds(match.groups()[:4]), seconds(match.groups()[4:])
        content = '\n'.join(lines[1:]).strip()
        if end <= start or not content or len(content) > 2000:
            raise ValueError('字幕须有文字且结束时间大于开始时间')
        cues.append({'start': start, 'end': end, 'text': content})
        if len(cues) > 10000:
            raise ValueError('每个音频最多一万条字幕')
    return cues


def validate_cues(cues, duration):
    if not isinstance(cues, list) or len(cues) > 10000:
        raise ValueError('字幕数量或格式不正确')
    clean = []
    for cue in cues:
        try:
            start, end = float(cue['start']), float(cue['end'])
            text = str(cue['text']).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('字幕格式不正确') from error
        if not (0 <= start < end <= duration+.05) or not text or len(text) > 2000:
            raise ValueError('字幕时间须位于音频内，且文字不能为空')
        clean.append({'start': start, 'end': min(end, duration), 'text': text})
    return sorted(clean, key=lambda c: c['start'])
