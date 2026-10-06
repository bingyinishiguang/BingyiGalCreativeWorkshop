from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from background_library import BackgroundLibrary
from rough_cut import RoughCut
from sprite_library import SpriteLibrary


@pytest.fixture
def production(tmp_path):
    backgrounds = BackgroundLibrary(tmp_path / 'backgrounds')
    source = tmp_path / 'classroom.png'
    Image.new('RGB', (960, 540), '#224466').save(source)
    bg = backgrounds.import_file(source)['item']
    sprites = SpriteLibrary(tmp_path / 'sprites')
    actor = Image.new('RGBA', (400, 600))
    ImageDraw.Draw(actor).rectangle((150, 100, 250, 500), fill='#aabbffff')
    person = sprites.save('测试作品', '测试人物', 'body', 'face', 'normal', actor)
    cut = RoughCut(tmp_path / 'roughcut', backgrounds, sprites)
    payload = {'name': '测试粗剪', 'scenes': [
        {'background': bg['id'], 'duration': 4, 'actors': [{'id': person['id'], 'slot': 1, 'x': .45, 'height': .9}]},
        {'background': bg['id'], 'duration': 3, 'actors': []},
    ]}
    return cut, backgrounds, bg, person, payload


def test_background_duplicate_repair_and_restore(production, tmp_path):
    _, library, bg, _, _ = production
    library.trash(bg['id'])
    (library.media / bg['filename']).unlink()
    source = tmp_path / 'classroom.png'
    result = library.import_file(source)
    assert result['duplicate'] and result['item']['deleted'] == 0
    assert not library.get(bg['id'])['missing']
    assert library.file(bg['id']).is_file()
    assert library.list()['total'] == 1


def test_project_roundtrip_and_frame_quantization(production):
    cut, _, _, _, payload = production
    payload['scenes'][0]['duration'] = .345
    saved = cut.save(payload)
    assert saved['scenes'][0]['durationUs'] == 333333
    assert saved['scenes'][1]['start'] == 333333
    assert cut.load(saved['id']) == saved
    assert cut.list_projects()['items'][0]['id'] == saved['id']


@pytest.mark.parametrize('size', [(1920,1080), (1080,1920), (1080,1440), (1440,1080), (1080,1080), (1234,876)])
def test_transform_roundtrip_and_draft_coordinates(production, size):
    cut, _, _, _, payload = production
    payload.update(width=size[0], height=size[1])
    transform = dict(scaleX=175, scaleY=120, x=150, y=-210, rotation=15, uniform=False)
    payload['scenes'][0]['actors'][0]['transform'] = transform
    payload['scenes'][0]['backgroundTransform'] = dict(transform, x=-120, rotation=-7)
    result = cut.export(payload)
    saved = cut.load(result['project']['id'])
    assert saved['scenes'][0]['actors'][0]['transform'] == transform
    assert cut.normalize(saved) == cut.normalize(payload)
    content = json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    clip = content['tracks'][2]['segments'][0]['clip']
    assert clip['scale'] == dict(x=1.75,y=1.2)
    assert clip['transform']['x']*size[0]/2 == pytest.approx(150)
    assert clip['transform']['y']*size[1]/2 == pytest.approx(-210)
    assert clip['rotation'] == 15
    bg = content['tracks'][0]['segments'][0]['clip']
    assert bg['transform']['x']*size[0]/2 == pytest.approx(-120)
    assert bg['rotation'] == -7


@pytest.mark.parametrize('field,value', [('scaleX',0),('scaleY',float('nan')),('x',float('inf')),('rotation',361)])
def test_invalid_transform_rejected(production, field, value):
    cut, _, _, _, payload = production
    payload['scenes'][0]['actors'][0]['transform'] = {field:value}
    with pytest.raises(ValueError):
        cut.normalize(payload)


def test_cover_uses_pixel_position_and_rotation():
    canvas = Image.new('RGB',(200,200),'black')
    image = Image.new('RGBA',(100,100))
    ImageDraw.Draw(image).rectangle((35,40,65,60), fill='red')
    transform = dict(scaleX=100,scaleY=100,x=20,y=30,rotation=90)
    RoughCut._paste_transform(canvas,image,transform,dict(width=200,height=200))
    box = canvas.getbbox()
    assert box is not None
    assert (box[0]+box[2])/2 == pytest.approx(120,abs=2)
    assert (box[1]+box[3])/2 == pytest.approx(70,abs=2)
    assert box[3]-box[1] > box[2]-box[0]


def test_export_is_self_contained_and_does_not_overwrite(production):
    cut, backgrounds, bg, _, payload = production
    first = cut.export(payload)
    second = cut.export(payload)
    assert first['path'] != second['path']
    folder = Path(first['path'])
    draft = json.loads((folder / 'draft_content.json').read_text(encoding='utf-8'))
    assert draft['duration'] == 7_000_000
    assert draft['canvas_config']['width'] == 1920
    assert [t['name'] for t in draft['tracks']] == ['背景', '角色 1', '角色 2']
    assert [len(t['segments']) for t in draft['tracks']] == [2, 0, 1]
    paths = [Path(v['path']) for v in draft['materials']['videos']]
    assert all(p.is_file() and p.is_relative_to(folder) for p in paths)
    actor = next(p for p in paths if p.name.startswith('测试人物'))
    with Image.open(actor) as image:
        assert image.size == (101, 401)
    settings = draft['tracks'][2]['segments'][0]['clip']
    assert settings['transform']['x'] == .45
    assert settings['transform']['y'] == pytest.approx(-.1)
    meta = json.loads((folder / 'draft_meta_info.json').read_text(encoding='utf-8'))
    assert meta['draft_fold_path'] == str(folder)
    assert meta['draft_id'] == draft['id']
    second_content = json.loads((Path(second['path']) / 'draft_content.json').read_text(encoding='utf-8'))
    assert second_content['id'] != draft['id']
    assert meta['tm_duration'] == 7_000_000
    assert (folder / 'draft_cover.jpg').is_file()
    assert not list(cut.exports.glob('.bingyi-building-*'))
    #Deleting the source library does not break the exported media.
    backgrounds.file(bg['id']).unlink()
    assert all(p.is_file() for p in paths)


@pytest.mark.parametrize('mutate', [
    lambda p: p['scenes'][0].update(duration=float('nan')),
    lambda p: p['scenes'][0].update(background='missing'),
    lambda p: p['scenes'][0]['actors'][0].update(id='missing'),
    lambda p: p.update(id='../../outside'),
])
def test_invalid_inputs_do_not_create_drafts(production, mutate):
    cut, _, _, _, payload = production
    mutate(payload)
    with pytest.raises(ValueError):
        cut.export(payload)
    assert not list(cut.exports.iterdir())


def test_missing_engine_leaves_saved_project_and_no_draft(production, monkeypatch):
    import builtins
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'pyJianYingDraft':
            raise ImportError('missing')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    cut, _, _, _, payload = production
    with pytest.raises(ValueError, match='缺少粗剪依赖'):
        cut.export(payload)
    assert len(cut.list_projects()['items']) == 1
    assert not list(cut.exports.iterdir())


def test_video_continues_and_loop_does_not_change_total(production, tmp_path):
    import shutil
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('Video fixture needs system FFmpeg')
    cut, backgrounds, _, _, _ = production
    video = tmp_path / 'video.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=30',
                    '-t', '2', '-pix_fmt', 'yuv420p', '-y', str(video)], check=True,
                   capture_output=True, creationflags=0x08000000)
    bg = backgrounds.import_file(video)['item']
    payload = {'name':'视频连续测试','scenes':[
        {'background':bg['id'],'duration':1,'actors':[]},
        {'background':bg['id'],'duration':4,'loop':True,'actors':[]},
    ]}
    saved = cut.normalize(payload)
    assert saved['scenes'][1]['videoStart'] == 1
    result = cut.export(payload)
    content = json.loads((Path(result['path'])/'draft_content.json').read_text(encoding='utf-8'))
    parts = content['tracks'][0]['segments']
    assert [p['target_timerange']['duration'] for p in parts] == [1_000_000,1_000_000,2_000_000,1_000_000]
    assert [p['source_timerange']['start'] for p in parts] == [0,1_000_000,0,0]
    assert content['duration'] == 5_000_000
    assert cut.normalize(cut.save(payload))['scenes'][1]['videoStart'] == 1
    payload['scenes'][1]['loop'] = False
    with pytest.raises(ValueError, match='长度不足'):
        cut.normalize(payload)


def test_publish_retries_transient_windows_failure(tmp_path, monkeypatch):
    from rough_cut import publish_directory
    source=tmp_path/'staging';source.mkdir();(source/'content').write_text('draft')
    target=tmp_path/'final';original=Path.rename;calls=[]
    def busy_once(path,destination):
        calls.append(path)
        if len(calls)==1:
            error=PermissionError('Busy');error.winerror=5;raise error
        return original(path,destination)
    monkeypatch.setattr(Path,'rename',busy_once);monkeypatch.setattr('rough_cut.time.sleep',lambda _:None)
    publish_directory(source,target)
    assert len(calls)==2 and (target/'content').read_text()=='draft'
    with pytest.raises(FileExistsError):publish_directory(source,target)

def test_publish_does_not_hide_permanent_failure(tmp_path,monkeypatch):
    from rough_cut import publish_directory
    source=tmp_path/'staging';source.mkdir();error=PermissionError('Permanent')
    def reject(*args):raise error
    monkeypatch.setattr(Path,'rename',reject)
    with pytest.raises(PermissionError):publish_directory(source,tmp_path/'final')
    assert source.exists()
