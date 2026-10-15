"""Conservative native Jianying text styling, with an explicit field boundary.

Coordinates and sizes use draft units, not browser pixels. Font descriptors come
only from a loaded draft or a locally saved preset, never from model paths.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from assistant_model import _validate

PROPERTIES = {
    'size': {'type': 'number', 'minimum': 2, 'maximum': 50},
    'color': {'type': 'string', 'pattern': '^#[a-fA-F0-9]{6}$'},
    'borderColor': {'type': 'string', 'pattern': '^#[a-fA-F0-9]{6}$'},
    'borderWidth': {'type': 'number', 'minimum': 0, 'maximum': .3},
    'x': {'type': 'number', 'minimum': -1, 'maximum': 1},
    'y': {'type': 'number', 'minimum': -1, 'maximum': 1},
    'fontId': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
}
FONT_FIELDS = ('font_path', 'font_resource_id', 'font_name', 'font_id', 'font_title',
               'font_category_id', 'font_category_name', 'font_source_platform',
               'font_team_id', 'font_url', 'fonts')
MATERIAL_FIELDS = set(FONT_FIELDS) | {'font_size', 'text_color', 'border_color', 'border_width', 'content'}


def validate_patch(value):
    _validate(value, {'type': 'object', 'properties': PROPERTIES, 'additionalProperties': False})
    return {key: item.lower() if key in ('color', 'borderColor') else item for key, item in value.items()}


def font_descriptor(item):
    content = json.loads(item['content'])
    styles = content.get('styles', [])
    if not isinstance(styles,list):return None
    fonts = [s.get('font') for s in styles if isinstance(s, dict) and s.get('font')]
    if not fonts or any(f != fonts[0] for f in fonts):
        return None
    font = fonts[0]
    if not isinstance(font, dict) or not isinstance(font.get('path'), str) or not font['path']:
        return None
    return {'richFont': copy.deepcopy(font),
            'material': {k: copy.deepcopy(item[k]) for k in FONT_FIELDS if k in item}}


def font_id(descriptor):
    return hashlib.sha256(json.dumps(descriptor, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def font_label(descriptor):
    fields = descriptor['material']
    return fields.get('font_name') or Path(descriptor['richFont']['path']).stem


def available_font(descriptor):
    try:
        return Path(descriptor['richFont']['path']).is_file()
    except OSError:
        return False


def font_catalog(data):
    fonts = {};seen=set()
    for item in data.get('materials', {}).get('texts', []):
        descriptor = font_descriptor(item)
        if descriptor:
            # Caption materials often give the same font a new metadata UUID.
            # One selectable font is enough; keep its full native descriptor.
            identity=json.dumps(descriptor['richFont'],sort_keys=True,ensure_ascii=False)
            if identity in seen:continue
            seen.add(identity)
            fonts[font_id(descriptor)] = descriptor
    return fonts


def rgb(color):
    return [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]


def hex_color(values):
    if not isinstance(values, list) or len(values) != 3:
        return None
    try:
        return '#' + ''.join(f'{max(0, min(255, round(v*255))):02x}' for v in values)
    except (TypeError, ValueError, OverflowError):
        return None


def describe(item, segment):
    try:
        validate_structure(item)
    except ValueError:
        transform=segment.get('clip',{}).get('transform',{})
        return {'size':None,'color':None,'borderColor':None,'borderWidth':None,
                'x':transform.get('x',0),'y':transform.get('y',0),
                'fontId':None,'fontName':'特殊样式，请保留原样式'}
    content = json.loads(item['content'])
    styles = content.get('styles', [])
    rows = []
    for s in styles:
        strokes = s.get('strokes') or []
        stroke = strokes[0] if strokes else {}
        rows.append({'size': s.get('size', item.get('font_size')),
                     'color': hex_color(s.get('fill', {}).get('content', {}).get('solid', {}).get('color')) or item.get('text_color'),
                     'borderColor': hex_color(stroke.get('content', {}).get('solid', {}).get('color')) or item.get('border_color'),
                     'borderWidth': stroke.get('width', item.get('border_width', 0))})
    result = {key: rows[0][key] if rows and all(r[key] == rows[0][key] for r in rows) else None
              for key in ('size', 'color', 'borderColor', 'borderWidth')}
    transform = segment.get('clip', {}).get('transform', {})
    result.update(x=transform.get('x', 0), y=transform.get('y', 0))
    descriptor = font_descriptor(item)
    result['fontId'] = font_id(descriptor) if descriptor else None
    result['fontName'] = font_label(descriptor) if descriptor else '原字体（混合或未指定）'
    return result


def validate_structure(item):
    """Unsupported native effects must produce a useful error, not a partial edit."""
    try:
        content=json.loads(item['content'])
        if not isinstance(content,dict) or not isinstance(content.get('text'),str):raise ValueError()
        styles=content.get('styles',[])
        if not isinstance(styles,list):raise ValueError()
        for style in styles:
            if not isinstance(style,dict):raise ValueError()
            fill=style.get('fill',{})
            if not isinstance(fill,dict) or not isinstance(fill.get('content',{}),dict):raise ValueError()
            solid=fill.get('content',{}).get('solid',{})
            if not isinstance(solid,dict):raise ValueError()
            strokes=style.get('strokes',[])
            if not isinstance(strokes,list):raise ValueError()
            for stroke in strokes:
                if not isinstance(stroke,dict) or not isinstance(stroke.get('content',{}),dict):raise ValueError()
                if not isinstance(stroke.get('content',{}).get('solid',{}),dict):raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise ValueError('文字样式结构不受支持，请保留原样式') from None


def apply_style(item, segment, patch, fonts, *, allow_missing_font=False):
    """Change only requested styling; ranges, animation, timing and media survive."""
    if not patch:
        return
    validate_structure(item)
    content = json.loads(item['content'])
    styles = content.get('styles')
    rich = set(patch) - {'x', 'y'}
    if rich and (not isinstance(styles, list) or not styles or any(not isinstance(s, dict) for s in styles)):
        raise ValueError('文字样式结构不受支持，请保留原样式')
    if 'fontId' in patch:
        descriptor = fonts.get(patch['fontId'])
        if not descriptor or (not allow_missing_font and not available_font(descriptor)):
            raise ValueError('预设字体文件不可用，请选择草稿中可用的字体或保留原字体')
        for key in FONT_FIELDS:
            item.pop(key, None)
        item.update(copy.deepcopy(descriptor['material']))
        for style in styles:
            style['font'] = copy.deepcopy(descriptor['richFont'])
    for key, field in [('size', 'font_size'), ('color', 'text_color'),
                       ('borderColor', 'border_color'), ('borderWidth', 'border_width')]:
        if key in patch:
            item[field] = patch[key]
    for style in styles or []:
        if 'size' in patch:
            style['size'] = patch['size']
        if 'color' in patch:
            fill = style.setdefault('fill', {}).setdefault('content', {})
            if set(fill) - {'solid'}:
                raise ValueError('渐变或特效填充暂不支持统一颜色')
            fill.setdefault('solid', {})['color'] = rgb(patch['color'])
        if 'borderColor' in patch or 'borderWidth' in patch:
            strokes = style.setdefault('strokes', [])
            if not isinstance(strokes, list) or len(strokes) > 1:
                raise ValueError('多层描边暂不支持统一调整')
            if not strokes:
                strokes.append({'content': {'solid': {'color': rgb(item.get('border_color', '#000000'))}},
                                'width': item.get('border_width', 0)})
            stroke = strokes[0]
            if 'borderColor' in patch:
                content_fill = stroke.setdefault('content', {})
                if set(content_fill) - {'solid'}:
                    raise ValueError('特效描边暂不支持统一颜色')
                content_fill.setdefault('solid', {})['color'] = rgb(patch['borderColor'])
            if 'borderWidth' in patch:
                stroke['width'] = patch['borderWidth']
    if 'x' in patch or 'y' in patch:
        if segment.get('common_keyframes') or segment.get('keyframe_refs'):
            raise ValueError('该字幕带关键帧，当前版本不调整位置，请仅修改文字样式')
        clip = segment.get('clip')
        if not isinstance(clip, dict):
            raise ValueError('字幕缺少位置结构，不能调整坐标')
        transform = clip.get('transform')
        if not isinstance(transform,dict):
            raise ValueError('字幕缺少位置结构，不能调整坐标')
        for key in ('x', 'y'):
            if key in patch:
                transform[key] = patch[key]
    if rich:
        item['content'] = json.dumps(content, ensure_ascii=False, separators=(',', ':'))


def verify_boundary(before, after, track_index, styled_ids):
    """Structural diff invariant: only text styling and chosen track XY may differ."""
    a, b = copy.deepcopy(before), copy.deepcopy(after)
    for data in (a, b):
        for item in data['materials']['texts']:
            if item['id'] in styled_ids:
                for key in MATERIAL_FIELDS:
                    item.pop(key, None)
        for segment in data['tracks'][track_index]['segments']:
            transform = segment.get('clip', {}).get('transform')
            if transform is not None:
                transform.pop('x', None); transform.pop('y', None)
    if a != b:
        raise ValueError('字幕样式修改越过了允许的数据范围')
