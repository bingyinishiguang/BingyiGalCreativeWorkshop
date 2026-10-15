from test_gal_story import story
from gal_story_render import plan,render,scene_base,face
from ice_story_skin import geometry
from PIL import ImageChops
import json


def test_missing_optional_font_falls_back_to_windows_font(monkeypatch):
    import ice_story_skin
    from pathlib import Path
    loaded=[]
    class StaticFont:
        def set_variation_by_axes(self, axes):
            raise OSError('not a variable font')
    monkeypatch.setattr(Path,'is_file',lambda p:p.name=='msyh.ttc')
    monkeypatch.setattr(ice_story_skin.ImageFont,'truetype',lambda path,size:(loaded.append(path) or StaticFont()))
    ice_story_skin.font.cache_clear()
    try:
        assert isinstance(ice_story_skin.font(34),StaticFont)
        assert Path(loaded[0]).name=='msyh.ttc'
    finally:
        ice_story_skin.font.cache_clear()

def test_approved_ice_artwork_and_narration_keep_same_logo(story):
    p=story.parse({'text':'冰翼：你好。\n旁白：安静。'})
    a=render(story,p,0,0,fades=False);b=render(story,p,1,0,fades=False)
    assert ImageChops.difference(a.crop((0,879,390,1020)),b.crop((0,879,390,1020))).getbbox() is None
    later=render(story,p,1,.3,fades=False)
    assert ImageChops.difference(b.crop((1588,998,1620,1030)),later.crop((1588,998,1620,1030))).getbbox()
    assert face(34).getmask('冰翼').getbbox()

def test_ice_pagination_stays_inside_safe_plate_for_every_font_size(story):
    p=story.parse({'text':'冰翼：'+('新的故事从这里开始。'*20)})
    for size in (24,34,40,41,56):
        p['settings']['fontSize']=size
        for mode in ('auto','standard','extended'):
            p['settings']['dialogueLayout']=mode
            for x,y in ((340,800),(1500,980)):
                p['clips'][0].update(textX=x,textY=y)
                measured=plan(story,p);seg=measured['segments'][0];g=geometry(measured['project']['clips'][0],measured['project']['settings'])
                assert g['x']>=425 and g['x']+g['w']==1720
                assert g['y']+g['h']<=(1008 if g['extended'] else 1000)
                assert max(map(len,seg['pages']))<=g['lines']
                assert ''.join(line for page in seg['pages'] for line in page)==p['clips'][0]['text']
                assert all(face(size).getlength(line)<=g['w'] for page in seg['pages'] for line in page)

def test_legacy_skin_remains_available_and_layout_is_saved(story):
    p=story.parse({'text':'冰翼：保留既有项目。'})
    p['settings'].update(skin='violet',dialogueLayout='extended')
    story.save({'project':p})
    saved=story.load(p['id'])
    assert saved['settings']['dialogueLayout']=='extended'
    assert render(story,saved,0).size==(1920,1080)


def test_panel_opacity_changes_plate_for_every_color_and_layout(story):
    from ice_story_skin import composite
    from PIL import Image
    p=story.parse({'text':'冰翼：透明底板。'})
    for skin in ('ice','violet','amber','slate'):
        for mode in ('standard','extended'):
            p['settings'].update(skin=skin,dialogueLayout=mode,panelOpacity=.2)
            low=Image.new('RGBA',(1920,1080));composite(low,story.kit,p['clips'][0],p['settings'],p['characters'])
            p['settings']['panelOpacity']=.9
            high=Image.new('RGBA',(1920,1080));composite(high,story.kit,p['clips'][0],p['settings'],p['characters'])
            assert low.getpixel((1200,960))[3]<high.getpixel((1200,960))[3]
            # Preserving the logo must not create an opaque rectangular patch.
            assert low.getpixel((0,900))[3]<high.getpixel((0,900))[3]
