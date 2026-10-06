"""使用合成素材启动隔离预览，不读取个人图库。"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
import app_paths
import sprite_composer
from background_library import BackgroundLibrary
from sprite_library import SpriteLibrary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--audio-samples', nargs='*',default=[])
    args = parser.parse_args()
    root = args.data_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    packs = root / 'sprite-packs'
    packs.mkdir(exist_ok=True)
    app_paths.resolve_data_dir = lambda: root
    app_paths.packs_dir = lambda: packs
    exports = root / 'exports'
    backgrounds = BackgroundLibrary(exports / 'Backgrounds')
    fixtures = root / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    for title, color in [('classroom', '#21476b'), ('street', '#354f59'), ('night', '#182d47')]:
        path = fixtures / (title + '.png')
        canvas = Image.new('RGB', (960, 540), color)
        draw = ImageDraw.Draw(canvas)
        for x in range(90, 850, 220):
            draw.rectangle((x,70,x+160,350),fill='#628faa',outline='#c7e8f7',width=8)
        draw.rectangle((0,400,960,540),fill='#0e263e')
        canvas.save(path)
        backgrounds.import_file(path, ['测试场景'])
    sprites = SpriteLibrary(exports / 'Library')
    from audio_library import AudioLibrary
    audio = AudioLibrary(exports/'Audio')
    for sample in args.audio_samples:
        audio.import_file(sample)
    for face, color in [('smile', '#91d5fa'), ('surprise', '#efc4de')]:
        image = Image.new('RGBA',(400,700))
        draw = ImageDraw.Draw(image)
        draw.ellipse((130,60,270,200),fill=color)
        draw.polygon([(150,190),(250,190),(320,630),(80,630)],fill=color)
        sprites.save('自制验收素材','测试人物','standing',face,'normal',image)
    policy = sprite_composer.IsolationPolicy.load(root / 'isolation-decisions.json')
    state = sprite_composer.BootState(root, exports)
    state.publish({}, {}, {}, policy)
    thread = threading.Thread(target=sprite_composer.run_web_app,args=(root,state),
                              kwargs={'open_browser':False,'scan_in_background':False},daemon=True)
    thread.start()
    while not getattr(sprite_composer,'LAST_URL',None):
        time.sleep(.05)
    (root/'preview-url.txt').write_text(sprite_composer.LAST_URL,encoding='utf-8')
    thread.join()


if __name__ == '__main__':
    main()
