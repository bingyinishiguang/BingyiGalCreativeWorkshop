import copy,threading
import pytest
from PIL import ImageChops
from test_gal_story import story
from gal_story_render import plan,render,export,inspect_video

def choice_project(story):
    p=story.parse({'text':'冰翼：接下来呢？'})
    p['clips'][0].update(type='choice',speakerId='',text='选择接下来的场景',
                         options=['留在工作室','去窗边看看'],selectedOption=1,voiceEnabled=False,duration=1)
    return p

def test_choice_preserves_options_and_highlights_preselected_result(story):
    p=choice_project(story);before=copy.deepcopy(p)
    normalized=story.normalize(p)
    assert normalized['clips'][0]['options']==p['clips'][0]['options'] and p==before
    a=render(story,p,0,0,fades=False);b=render(story,p,0,.8,fades=False)
    assert ImageChops.difference(a,b).getbbox()
    assert plan(story,p)['segments'][0]['pages']==[[]]
    story.save({'project':p});assert story.load(p['id'])['clips'][0]['selectedOption']==1

def test_long_choice_is_explicitly_rejected_without_text_loss(story):
    p=choice_project(story)
    p['clips'][0]['options'][0]='这是一个很长的选择。'*20
    with pytest.raises(ValueError,match='选项过长'):plan(story,p)
    p['clips'][0]['options']=['一个选项']
    with pytest.raises(ValueError,match='两到三个'):story.normalize(p)

def test_cg_caption_defaults_off_and_can_be_enabled(story):
    p=choice_project(story);p['clips'][0].update(type='eyecatch',backgroundId='kit:day',text='',captionText='三天后',captionEnabled=False)
    a=render(story,p,0,fades=False)
    p['clips'][0]['captionText']='第二天清晨'
    assert ImageChops.difference(a,render(story,p,0,fades=False)).getbbox() is None
    p['clips'][0]['captionEnabled']=True
    assert ImageChops.difference(a,render(story,p,0,fades=False)).getbbox()

def test_choice_and_caption_encode_to_real_video(story,tmp_path):
    p=choice_project(story)
    p['settings']['indicator']=False
    p['clips'][0]['duration']=.4
    second=copy.deepcopy(p['clips'][0]);second.update(id='caption_scene',type='eyecatch',backgroundId='kit:time-card-day',text='',captionEnabled=True,captionText='次日清晨')
    p['clips'].append(second)
    ident='choice_caption_export'
    story.jobs[ident]=dict(id=ident,state='running',progress=0)
    result=export(story,p,ident,threading.Event())
    metadata=inspect_video(result['path'])
    assert metadata['width']==1920 and metadata['height']==1080
    assert abs(metadata['duration']-.8)<.04

def test_unsupported_glyph_is_reported_before_export(story):
    p=story.parse({'text':'冰翼：这里有一个不支持的字符😀。'})
    with pytest.raises(ValueError,match=r'U\+1F600'):plan(story,p)
    assert '😀' in p['clips'][0]['text']
