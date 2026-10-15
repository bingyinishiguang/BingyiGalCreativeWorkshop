"""Copy the creator's approved story assets into a portable runtime kit."""
import json
import hashlib
import shutil
from pathlib import Path

import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True,help='UI artwork directory containing runtime-kit')
parser.add_argument('--sprites',type=Path,required=True,help='Character artwork directory')
parser.add_argument('--backgrounds',type=Path,required=True,help='Background artwork directory')
args=parser.parse_args()
source=args.source
root = Path(__file__).resolve().parents[1] / 'ui' / 'assets' / 'story-kit'
root.mkdir(parents=True, exist_ok=True)
bindings=json.loads((source/'runtime-kit/ui_bindings.json').read_text('utf-8'))
corrected={'dialogue.png','dialogue-decoration.png','extended.png','extended-no-nameplate.png','narration.png'}
for asset in bindings['assets']:
    target=root/asset['filename']
    # Preserve the checked-in line-free artwork instead of restoring the old dividers.
    if asset['filename'] not in corrected or not target.is_file():
        shutil.copyfile(source/'runtime-kit'/asset['filename'],target)
    asset['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
shutil.copyfile(source/'layout_contract.json',root/'layout_contract.json')
bindings['integrationNote']='Shared dialogue geometry and quick menu / VOICE layers.'
(root/'ui_bindings.json').write_text(json.dumps(bindings,ensure_ascii=False,indent=2),'utf-8')
icons=root/'hud-icons';icons.mkdir(exist_ok=True)
for name in ('lock','settings','history','voice','auto','skip','star','close','fullscreen'):
    shutil.copyfile(source/'assets/icons'/f'icon_{name}_light.png',icons/(name+'.png'))
sprites = args.sprites
items = []
for i, emotion in enumerate(['微笑', '开心', '害羞', '惊讶', '难过', '生气'], 1):
    path = sprites / f'A{i:02}_自然站姿_{emotion}.png'
    filename = f'bingyi-{i}.png'
    shutil.copyfile(path, root / filename)
    items.append(dict(id=f'kit:sprite-{i}', kind='sprite', name=f'冰翼 · {emotion}', emotion=emotion, filename=filename))
backgrounds = args.backgrounds
for ident, name, filename in [('studio-day', '工作室 · 上午', 'S01_冰翼工作室_上午_空景_V1.1.png'),
                              ('studio-night', '工作室 · 夜间', 'S01_冰翼工作室_夜间_空景_V1.0.png'),
                              ('window-night', '窗边 · 夜间', 'S05_窗边独白室_夜间_空景_V1.0.png')]:
    target = ident + '.png'
    shutil.copyfile(backgrounds / filename, root / target)
    items.append(dict(id='kit:'+ident, kind='background', name=name, filename=target))
for ident, name in [('day', '日间过场'), ('night', '月夜过场')]:
    items.append(dict(id='kit:'+ident, kind='background', name=name, filename=ident+'.png'))
items += [a for a in json.loads((source/'runtime-kit/catalog_additions.json').read_text('utf-8')) if a['id'] not in {i['id'] for i in items}]
(root / 'catalog.json').write_text(json.dumps(items, ensure_ascii=False, indent=2), 'utf-8')
print('Prepared', len(items), 'assets')
