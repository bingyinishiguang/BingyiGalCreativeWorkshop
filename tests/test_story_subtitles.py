import threading
from test_gal_story import story
from gal_story_render import plan,export
from story_subtitles import subtitles,timestamp

def test_srt_tracks_actual_page_frames_and_skips_blank_cg_and_choices(story):
    p=story.parse({'text':'冰翼：'+('把故事继续写下去。'*12)+'\n旁白：钟声响了。'})
    p['clips'][0]['duration']=1.7
    cg=dict(p['clips'][1]);cg.update(id='blank_cg',type='eyecatch',text='',captionEnabled=False)
    choice=dict(cg);choice.update(id='choice_srt_skip',type='choice',options=['留下','离开'])
    p['clips'] += [cg,choice]
    measured=plan(story,p)
    value=subtitles(measured)
    assert '留下' not in value and '离开' not in value
    for seg in measured['segments'][:2]:
        for start,end in seg['pageFrames']:
            assert f'{timestamp(seg["startFrame"]+start)} --> {timestamp(seg["startFrame"]+end)}' in value
    assert timestamp(30)=='00:00:01,000'
    assert timestamp(108001)=='01:00:00,033'

def test_srt_written_alongside_verified_mp4(story):
    p=story.parse({'text':'冰翼：明天见。'})
    p['clips'][0]['duration']=.3
    ident='subtitle_export';story.jobs[ident]=dict(id=ident,state='running',progress=0)
    result=export(story,p,ident,threading.Event())
    from pathlib import Path
    data=Path(result['subtitlePath']).read_text('utf-8-sig')
    assert '00:00:00,000 --> 00:00:00,300' in data and '明天见。' in data
    story.jobs[ident].update(result,state='complete',kind='export',projectId=p['id'])
    assert story.subtitle_file(ident).is_file()
    import json
    (story.exports/ident/'result.json').write_text(json.dumps(story.jobs[ident]),'utf-8')
    assert story.outputs(p['id'])['items'][0]['subtitleUrl']==result['subtitleUrl']

    p['clips'][0].update(type='eyecatch',text='',captionEnabled=False)
    ident='textless_export';story.jobs[ident]=dict(id=ident,state='running',progress=0)
    textless=export(story,p,ident,threading.Event())
    assert textless['subtitleUrl']=='' and textless['subtitlePath']==''
