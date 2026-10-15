import json
import re
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from sprite_library import SpriteLibrary
from gal_story import GalStory, StoryCancelled
from gal_story_draft import export
from draft_media import MediaPack


def make_story(tmp_path):
    story=GalStory(tmp_path/'story',BackgroundLibrary(tmp_path/'bg'),SpriteLibrary(tmp_path/'sprite'),
        AudioLibrary(tmp_path/'audio'),SimpleNamespace(settings=lambda:{}),None)
    story._update=lambda *a,**k:None
    return story


def test_editable_layers_durable_paths_and_fresh_versions(tmp_path):
    story=make_story(tmp_path)
    material_dir=tmp_path/'自选素材';material_dir.mkdir()
    project=story.parse({'text':'旁白：安静的夜晚。\n冰翼：明天见。'})
    project['output']={'materialDirectory':str(material_dir)}
    original=material_dir/'背景_夜晚工作室.png';original.write_bytes(b'user edit')
    result=export(story,project,'one',threading.Event())
    folder=Path(result['path']);content=json.loads((folder/'draft_content.json').read_text('utf-8'))
    meta=json.loads((folder/'draft_meta_info.json').read_text('utf-8'))
    assert original.read_bytes()==b'user edit'
    assert len(content['materials']['texts'])>=3
    assert {json.loads(t['content'])['text'] for t in content['materials']['texts']} >= {'明天见。','冰翼'}
    for item in content['materials']['videos']:
        path=Path(item['path']);assert path.is_file() and path.parent==material_dir
        assert not re.search(r'[-_][a-f0-9]{8,32}\.',path.name)
    assert all(Path(item['file_Path']).is_file() for group in meta['draft_materials'] for item in group['value'])
    assert (folder/'bingyi-generation.json').is_file()
    first=(folder/'draft_content.json').read_bytes()
    second=export(story,project,'two',threading.Event())
    assert result['path']!=second['path']
    assert (folder/'draft_content.json').read_bytes()==first


def test_collision_allocation_and_publish_rollback(tmp_path):
    staging=tmp_path/'stage';staging.mkdir();external=tmp_path/'external';external.mkdir()
    pack=MediaPack(staging,tmp_path/'unused',str(external))
    a=pack.allocate('冰翼-deadbeef','.png');b=pack.allocate('冰翼','.png')
    Image.new('RGBA',(2,2),'white').save(a);Image.new('RGBA',(2,2),'red').save(b)
    assert a.name=='冰翼.png' and b.name=='冰翼_版本2.png'
    pack.publish();assert (external/a.name).is_file()
    pack.rollback();assert not list(external.iterdir())


def test_cancelled_export_does_not_publish(tmp_path):
    story=make_story(tmp_path);project=story.demo();event=threading.Event();event.set()
    with pytest.raises(StoryCancelled):export(story,project,'cancel',event)
    assert not list((story.root/'drafts').iterdir())


def test_missing_output_directory_is_reported(tmp_path):
    story=make_story(tmp_path);project=story.demo()
    project['output']={'materialDirectory':str(tmp_path/'missing')}
    with pytest.raises(ValueError,match='素材目录'):export(story,project,'missing',threading.Event())


def test_frame_boundaries_never_overlap(tmp_path):
    story=make_story(tmp_path);project=story.demo()
    result=export(story,project,'frames',threading.Event())
    content=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    for track in content['tracks']:
        rows=track['segments']
        for before,after in zip(rows,rows[1:]):
            assert before['target_timerange']['start']+before['target_timerange']['duration']<=after['target_timerange']['start']


def test_voice_bgm_and_progress_remain_editable(tmp_path):
    story=make_story(tmp_path);source=tmp_path/'配音.wav'
    with wave.open(str(source),'wb') as wav:
        wav.setparams((1,2,48000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*48000)
    item=story.audio.import_file(source)['item']
    project=story.parse({'text':'旁白：夜深了。\n冰翼：明天见。'})
    project['clips'][0]['voiceId']=item['id'] # Remains silent when disabled.
    project['clips'][1].update(voiceId=item['id'],voiceText='明天见。')
    project['bgm']['id']=item['id']
    result=export(story,project,'audio',threading.Event())
    content=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    tracks={t['name']:t for t in content['tracks']}
    assert len(tracks['角色配音']['segments'])==1
    assert tracks['角色配音']['segments'][0]['target_timerange']['start']==2000000
    assert tracks['BGM']['segments'][0]['common_keyframes']
    assert tracks['语音进度']['segments'][0]['common_keyframes']
    assert len(tracks['底部快捷菜单']['segments'])==2
    assert len(tracks['语音进度底']['segments'])==1
    materials={m['id']:m for m in content['materials']['videos']}
    progress=materials[tracks['语音进度']['segments'][0]['material_id']]
    with Image.open(progress['path']) as fill:
        pixel=fill.convert('RGBA').getpixel((100,4));assert pixel[2]==255 and pixel[1]>pixel[0]
    assert all(t['segments'] for t in content['tracks'])


def test_all_colors_share_ice_geometry_artwork_alpha_and_font(tmp_path):
    from ice_story_skin import themed_read
    from gal_story_render import plan,face
    story=make_story(tmp_path);project=story.parse({'text':'冰翼：我们明天见。'})
    expected=plan(story,project)['segments'][0]['textRect']
    alpha=themed_read(story.kit,'dialogue.png','ice').getchannel('A').tobytes()
    for skin in ('violet','amber','slate'):
        project['clips'][0]['skin']=skin
        assert plan(story,project)['segments'][0]['textRect']==expected
        assert themed_read(story.kit,'dialogue.png',skin).getchannel('A').tobytes()==alpha
        assert face(34,skin=skin).path==face(34,skin='ice').path
        result=export(story,project,skin,threading.Event())
        content=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
        tracks={t['name']:t for t in content['tracks']}
        assert '说话者头像' not in tracks # Selecting a color cannot introduce a different composition.
        name=tracks['人物名 · 可编辑']['segments'][0]
        assert name['clip']['transform']['y']==pytest.approx(1-(816+27/2)/1080*2)
