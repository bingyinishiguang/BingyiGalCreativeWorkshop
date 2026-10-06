from pathlib import Path
import json
import pytest
from PIL import Image,ImageDraw
from sprite_library import SpriteLibrary
from sprite_composer import trim_transparent
from composition_library import CompositionLibrary,render_aligned
from rough_cut import RoughCut
from background_library import BackgroundLibrary

@pytest.fixture
def setup(tmp_path):
    sprites=SpriteLibrary(tmp_path/'sprites')
    ids=[]; originals=[]
    for n,left in enumerate((10,30)):
        raw=Image.new('RGBA',(100,200));d=ImageDraw.Draw(raw)
        d.rectangle((40,40,60,180),fill='white');d.rectangle((left,100,left+5,150),fill='red')
        image=trim_transparent(raw)
        ids.append(sprites.save('Test','Heroine','standing',str(n),'normal',image)['id']);originals.append(raw)
    store=CompositionLibrary(tmp_path/'cut',sprites)
    return sprites,store,ids,originals,tmp_path

def test_source_coordinates_survive_png_storage_and_group_render(setup):
    sprites,store,ids,originals,_=setup
    suggested=store.suggest(ids)
    assert (suggested['width'],suggested['height'])==(100,200)
    assert all(m['mode']=='原始坐标' for m in suggested['members'])
    group=store.save_group(suggested)
    for m,original in zip(group['members'],originals):
        restored=render_aligned(sprites.file(m['id'],False),m)
        assert restored.tobytes()==original.tobytes()
        assert restored.getpixel((50,50))==(255,255,255,255)
    assert CompositionLibrary(store.root,sprites).list()['groups']==[group]

def test_aligned_media_export_and_snapshot_independent_of_group_edits(setup):
    sprites,store,ids,originals,tmp=setup
    group=store.save_group(store.suggest(ids))
    backgrounds=BackgroundLibrary(tmp/'bg');source=tmp/'bg.png';Image.new('RGB',(200,200),'black').save(source)
    bg=backgrounds.import_file(source)['item'];cut=RoughCut(tmp/'cut',backgrounds,sprites)
    actors=[]
    for m in group['members']:
        actors.append(dict(id=m['id'],slot=0,x=0,height=.9,alignment=m))
    payload=dict(width=1080,height=1920,scenes=[dict(background=bg['id'],duration=1,actors=[a]) for a in actors])
    saved=cut.save(payload)
    group['members'][0]['left']+=8;updated=store.save_group(group)
    assert updated['version']!=group['version']
    assert cut.load(saved['id'])['scenes'][0]['actors'][0]['alignment']['left']!=updated['members'][0]['left']
    exported=cut.export(saved);content=json.loads((Path(exported['path'])/'draft_content.json').read_text('utf-8'))
    for material in content['materials']['videos']:
        if material['width']==100:
            with Image.open(material['path']) as im:assert im.size==(100,200);assert im.getpixel((50,50))==(255,255,255,255)

def test_presets_separate_ratios_and_scale_pixel_offsets(setup):
    sprites,store,ids,_,_=setup
    t=dict(scaleX=150,scaleY=150,x=192,y=-108,rotation=10,uniform=True)
    scene=dict(backgroundTransform=t,actors=[dict(id=ids[0],slot=0,transform=t)])
    p=store.save_preset(dict(name='Landscape',width=1920,height=1080,scene=scene))
    a=store.apply_preset(dict(id=p['id'],width=1280,height=720))
    assert a['actors'][0]['transform']['x']==128
    assert a['actors'][0]['transform']['y']==-72
    assert a['actors'][0]['transform']['scaleX']==150
    with pytest.raises(ValueError,match='画幅'):store.apply_preset(dict(id=p['id'],width=1080,height=1920))
    store.rename_preset(dict(id=p['id'],name='Changed'));assert store.list()['presets'][0]['name']=='Changed'
    store.delete_preset(p['id']);assert store.list()['presets']==[]

def test_group_rejects_other_pose_and_excessive_canvas(setup):
    sprites,store,ids,_,_=setup
    other=sprites.save('Test','Heroine','sitting','0','normal',Image.new('RGBA',(100,100),'white'))['id']
    with pytest.raises(ValueError,match='姿势'):store.suggest([ids[0],other])
    suggestion=store.suggest(ids);suggestion.update(width=20000,height=20000)
    with pytest.raises(ValueError,match='四千万'):store.save_group(suggestion)

def test_group_rejects_duplicate_and_malformed_members(setup):
    _,store,ids,_,_=setup
    for value in ([ids[0],ids[0]], [ids[0],{}], [ids[0],None]):
        with pytest.raises(ValueError):store.suggest(value)
    with pytest.raises(ValueError):store.save_group(dict(name='Bad',members=[None,None]))
