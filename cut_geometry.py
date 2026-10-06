"""Canvas-pixel positions and fit-relative percentages used by preview and drafts."""
from __future__ import annotations


def default_transform(width, height, source_width, source_height, actor=None):
    fit = min(width / source_width, height / source_height)
    if actor is None:
        scale = max(width / source_width, height / source_height) / fit * 100
        x = y = 0
    else:
        scale = height * actor.get('height', .9) / (source_height * fit) * 100
        x = actor.get('x', 0) * width / 2
        y = (actor.get('height', .9) - 1) * height / 2
    return dict(scaleX=scale, scaleY=scale, x=x, y=y, rotation=0, uniform=True)


def normalize_transform(raw, fallback, number, width, height):
    if raw is None:
        return fallback
    if not isinstance(raw, dict):
        raise ValueError('位置大小参数格式不正确')
    result = {key: number(raw.get(key, fallback[key]), label, low, high)
              for key, label, low, high in (
                  ('scaleX', '水平缩放百分比', 1, 2000),
                  ('scaleY', '垂直缩放百分比', 1, 2000),
                  ('x', '水平位置', -width * 10, width * 10),
                  ('y', '垂直位置', -height * 10, height * 10),
                  ('rotation', '旋转角度', -360, 360))}
    result['uniform'] = raw.get('uniform', True) is True
    if result['uniform']:
        result['scaleY'] = result['scaleX']
    return result


def clip_values(transform, width, height):
    return dict(scale_x=transform['scaleX'] / 100, scale_y=transform['scaleY'] / 100,
                transform_x=transform['x'] * 2 / width,
                transform_y=transform['y'] * 2 / height,
                rotation=transform['rotation'])
