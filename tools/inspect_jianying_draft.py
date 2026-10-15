"""Read-only source draft audit and encrypted-copy experiment.

Writes only into an explicitly chosen workspace output directory. Asset matches
are suggestions, not automatic replacements. Never registers or overwrites drafts.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subtitle_tools import format_subtitle


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_status(path):
    try:
        return 'present' if Path(path).is_file() else 'missing'
    except OSError:
        return 'unreadable'


def run_codec(codec, operation, source, output):
    # DLL/C++ ABI and cwd changes stay in a disposable process.
    result = subprocess.run([sys.executable, str(codec), operation, str(source), str(output)],
                            capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    if result.returncode or not output.is_file():
        raise ValueError('草稿编解码失败，请核对剪映版本与案例适配器')


def remap_styles(content, old, new):
    # Jianying uses character ranges; preserve individual rich-text spans.
    offsets = [0] * (len(old) + 1)
    for tag, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for i in range(a, b + 1):
            offsets[i] = c + round((i-a)*(d-c)/(b-a)) if b>a else c
    offsets[-1] = len(new)
    for style in content.get('styles', []):
        if not isinstance(style.get('range'), list) or len(style['range']) != 2:
            raise ValueError('草稿文字样式范围不受支持')
        start, length = style['range']
        if not isinstance(start, int) or not isinstance(length, int) or not 0<=start<=start+length<=len(old):
            raise ValueError('草稿文字范围超出文本，需专项适配')
        style['range'] = [offsets[start], offsets[start+length]-offsets[start]]


def inspect(source, assets, output, codec, track_name):
    source, assets, output, codec = map(lambda p: Path(p).resolve(), (source, assets, output, codec))
    workspace = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(workspace) or output.is_relative_to(source.parent) or output.is_relative_to(assets):
        raise ValueError('检查结果必须放在工坊工作区内，且不能位于原草稿或素材库中')
    if not source.is_file() or not assets.is_dir() or not codec.is_file():
        raise ValueError('草稿、素材库或编解码脚本不存在')
    output.mkdir(parents=True, exist_ok=True)
    before = digest(source)
    decoded = output/'draft.decrypted.json'
    try:
        original = json.loads(source.read_bytes())
        decoded.write_text(json.dumps(original,ensure_ascii=False), 'utf-8')
        encrypted_source = False
    except (ValueError, UnicodeError):
        run_codec(codec, 'dec', source, decoded)
        original = json.loads(decoded.read_bytes())
        encrypted_source = True
    tracks = original.get('tracks', [])
    rows = []
    for kind, values in original.get('materials', {}).items():
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and item.get('path'):
                path = str(item['path'])
                access = file_status(path)
                rows.append({'kind': kind, 'id': item.get('id'), 'path': path,
                             'exists': access == 'present', 'access': access, 'name': PureWindowsPath(path).name})
    wanted = {row['name'].casefold() for row in rows if not row['exists']}
    matches = {name: [] for name in wanted}
    scanned = 0
    for path in assets.rglob('*'):
        if path.is_file():
            scanned += 1
            if path.name.casefold() in matches:
                matches[path.name.casefold()].append(str(path))
    for row in rows:
        row['candidates'] = matches.get(row['name'].casefold(), []) if not row['exists'] else []
        row['status'] = 'present' if row['exists'] else 'candidate' if len(row['candidates']) == 1 else 'ambiguous' if row['candidates'] else row['access']
    selected = [t for t in tracks if t.get('type') == 'text' and t.get('name') == track_name]
    if len(selected) != 1:
        raise ValueError('字幕轨道名称不唯一或不存在，请明确指定轨道')
    ids = {s['material_id'] for s in selected[0]['segments']}
    non_selected_ids = {s.get('material_id') for t in tracks if t is not selected[0] for s in t.get('segments', [])}
    if ids & non_selected_ids:
        raise ValueError('字幕素材被其他轨道共用，不能直接修改副本')
    modified = copy.deepcopy(original)
    changed = []
    for item in modified['materials'].get('texts', []):
        if item.get('id') not in ids:
            continue
        content = json.loads(item['content'])
        old = content['text']; new = format_subtitle(old)
        if not new:
            raise ValueError('字幕规范后为空，请人工核对')
        if new != old:
            remap_styles(content, old, new)
            content['text'] = new
            item['content'] = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
            # Per-character ASR metadata must not remain inconsistent with the text.
            if 'words' in item:
                item['words'] = {'start_time': [], 'end_time': [], 'text': []}
            changed.append({'id': item['id'], 'before': old, 'after': new})
    # Compare every source field except the explicitly changed text materials.
    check_a, check_b = copy.deepcopy(original), copy.deepcopy(modified)
    changed_ids = {r['id'] for r in changed}
    for d in (check_a, check_b):
        d['materials']['texts'] = [m for m in d['materials']['texts'] if m['id'] not in changed_ids]
    assert check_a == check_b, 'Non-caption draft fields changed'
    plain = output/'copy-test.modified.json'
    plain.write_text(json.dumps(modified, ensure_ascii=False, separators=(',', ':')), 'utf-8')
    encrypted, readback = output/'copy-test.encrypted', output/'copy-test.readback.json'
    run_codec(codec, 'enc', plain, encrypted)
    run_codec(codec, 'dec', encrypted, readback)
    assert json.loads(readback.read_bytes()) == modified, 'Encryption round-trip mismatch'
    assert digest(source) == before, 'Source draft changed during audit'
    report = {'source': str(source), 'sourceSha256': before, 'sourceUnchanged': True,
              'encryptedSource': encrypted_source, 'roundTripVerified': True,
              'track': track_name, 'subtitleCount': len(selected[0]['segments']),
              'changedCaptions': changed, 'assetFilesScanned': scanned,
              'assets': rows, 'copyEncryptedPath': str(encrypted),
              'note': '仅工作区副本实验，未写回或注册剪映草稿；同名素材候选需人工确认'}
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    lines = ['# EP02 草稿只读检查与副本实验', '',
             f'- 原工程保持不变：SHA-256 `{before}`',
             f'- 解密、字幕标点修改、加密往返：通过；字幕 {len(ids)} 条，调整 {len(changed)} 条',
             f'- 素材库文件数：{scanned}；确认缺失引用：{sum(r["access"] == "missing" for r in rows)}；无法读取引用：{sum(r["access"] == "unreadable" for r in rows)}',
             '- 修改副本只位于工坊 output，未写回剪映目录', '', '## 缺失素材匹配建议', '']
    for row in rows:
        if not row['exists']:
            lines.append('- **'+row['name']+'**：'+({'candidate':'找到唯一同名候选，仍需核对内容','ambiguous':'多个同名候选，不自动替换','missing':'未找到同名素材','unreadable':'当前权限无法读取，不能判定丢失'}[row['status']]))
            lines.extend('  - `'+p+'`' for p in row['candidates'])
    lines += ['', '当前仅验证数据完整性与编解码。修改副本在剪映中打开、播放、保存重开的兼容性尚未验证。']
    (output/'报告.md').write_text('\n'.join(lines), 'utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--draft', required=True)
    parser.add_argument('--assets', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--codec', required=True)
    parser.add_argument('--track', default='中文字幕')
    args=parser.parse_args()
    report=inspect(args.draft,args.assets,args.output,args.codec,args.track)
    print(json.dumps({k: report[k] for k in ('sourceUnchanged','roundTripVerified','subtitleCount','assetFilesScanned')},ensure_ascii=False))
