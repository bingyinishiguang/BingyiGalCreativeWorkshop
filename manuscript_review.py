"""Local, conservative manuscript comparisons; no model calls or timing guesses."""
from __future__ import annotations

import copy
import difflib
import hashlib
import re
import unicodedata

from subtitle_tools import format_subtitle

LIMIT = 100_000


def text_key(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def validate_manuscript(value):
    if not isinstance(value, str) or not value.strip() or len(value) > LIMIT:
        raise ValueError('请提供不超过十万字的作者原稿')
    return value


def compare(cues, manuscript, mode='auto'):
    raw = validate_manuscript(manuscript)
    if not isinstance(cues, list) or not 1 <= len(cues) <= 1000:
        raise ValueError('原稿校对一次支持 1–1000 条字幕，请先生成或导入字幕')
    if mode not in ('auto', 'lines'):
        raise ValueError('原稿对照方式不正确')
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if mode == 'lines':
        if len(lines) != len(cues):
            raise ValueError(f'逐行对应需要 {len(cues)} 行原稿，当前为 {len(lines)} 行')
        pairs = {i: (i, 1.0) for i in range(len(cues))}
        parts = lines
    else:
        # Sentence/paragraph units may differ from ASR segments. Never interpolate
        # arbitrary boundaries or shift every later cue after one unmatched line.
        parts = [p.strip() for p in re.split(r'[\n。！？!?；;]+', raw) if p.strip()]
        if len(parts) > 2000:
            raise ValueError('原稿段落太多，请分段校对')
        cue_keys = [text_key(c['text']) for c in cues]
        part_keys = [text_key(p) for p in parts]
        pairs, used, after = {}, set(), -1
        for i, key in enumerate(cue_keys):
            if not key:
                continue
            # Nearby monotonic matching bounds work and rejects repeated ambiguity.
            begin = max(0, after + 1, i - 4)
            window = range(begin, min(len(parts), begin + 16))
            scores = []
            for j in window:
                if j in used or not part_keys[j]:
                    continue
                a, b = key[:2000], part_keys[j][:2000]
                if min(len(a), len(b))/max(len(a), len(b)) < .45:
                    continue
                score = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
                if score >= .60:
                    scores.append((score, j))
            scores.sort(reverse=True)
            if scores and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .12):
                score, j = scores[0]
                # Repeated identical manuscript lines have no unique automatic mapping.
                if part_keys.count(part_keys[j]) > 1:
                    continue
                pairs[i] = (j, score); used.add(j); after = j
    rows = []
    for i, cue in enumerate(cues):
        match = pairs.get(i)
        reference = parts[match[0]] if match else ''
        score = match[1] if match else 0
        rows.append({'cueIndex': i, 'start': cue['start'], 'end': cue['end'],
                     'recognized': cue['text'], 'reference': reference,
                     'suggested': format_subtitle(reference or cue['text']),
                     'confidence': round(score, 3),
                     'status': 'matched' if match else 'review',
                     'selected': bool(match and (mode == 'lines' or score >= .82))})
    matched = {j for j, _ in pairs.values()}
    return {'rows': rows, 'unmatched': [p for j, p in enumerate(parts) if j not in matched],
            'manuscript': raw, 'mode': mode, 'hash': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'matchedCount': len(pairs), 'reviewCount': sum(not r['selected'] for r in rows)}


def review_record(value):
    if not isinstance(value, dict):
        raise ValueError('作者原稿记录格式不正确')
    raw = validate_manuscript(value.get('text'))
    name = value.get('name', '')
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError('原稿文件名格式不正确')
    return {'text': raw, 'name': name, 'hash': hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def apply_review(project, clip_id, rows, manuscript, name=''):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('校对字幕数量不正确')
    result = copy.deepcopy(project)
    clip = next((c for c in result.get('audioClips', []) if c.get('id') == clip_id), None)
    if not clip:
        raise ValueError('请明确选择一个配音片段')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('校对结果格式不正确')
        index = row.get('cueIndex')
        if isinstance(index, bool) or not isinstance(index, int) or index in seen or not 0 <= index < len(clip['cues']):
            raise ValueError('校对字幕序号不存在或重复')
        seen.add(index)
        text = row.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError('校对字幕不能为空或超过两千字')
        clip['cues'][index]['text'] = format_subtitle(text)
    clip['text'] = '\n'.join(c['text'] for c in clip['cues'])
    clip['manuscript'] = review_record({'text': manuscript, 'name': name})
    return result
