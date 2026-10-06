import json
import shutil
import subprocess
import wave
from pathlib import Path
import pytest
from PIL import Image
from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from column_workflow import ColumnWorkflow, overlay_transform
from rough_cut import RoughCut
from sprite_library import SpriteLibrary

@pytest.fixture
def column(tmp_path):
    backgrounds = BackgroundLibrary(tmp_path/'backgrounds')
    still=tmp_path/'画面.png';Image.new('RGB',(320,180),'blue').save(still)
    bg=backgrounds.import_file(still)['item']
    badge=tmp_path/'装饰.png';Image.new('RGBA',(120,80),'#ffffff80').save(badge)
    image=backgrounds.import_file(badge)['item']
    audio=AudioLibrary(tmp_path/'audio');items=[]
    for name,samples in [('配音',32160),('BGM',16000)]:
        path=tmp_path/(name+'.wav')
        with wave.open(str(path),'wb') as out:
            out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b'\0\0'*samples)
        items.append(audio.import_file(path)['item'])
    cut=RoughCut(tmp_path/'cut',backgrounds,SpriteLibrary(tmp_path/'sprites'),audio)
    dest=tmp_path/'dest';dest.mkdir()
    config=dict(id='ifgal',name='IfGal',background=bg['id'],bgm=items[1]['id'],episodeDirectory=str(tmp_path),draftDirectory=str(dest),overlays=[dict(image=image['id'],name='任意全片图片',width=12,left=2,top=2)])
    return cut,ColumnWorkflow(cut),config,items,backgrounds

def test_preset_reload_and_voice_rounding(column):
    cut,columns,config,items,_=column
    saved=columns.save(dict(config,voices=[{'audio':items[0]['id']}]))
    assert ColumnWorkflow(cut).list()['items']==[saved] and 'voices' not in saved
    assert 'episodeDirectory' not in saved
    request=dict(config=saved,voices=[{'audio':items[0]['id']}],name='本期',episodeDirectory=config['episodeDirectory'])
    project=columns.build(request)
    assert project['durationUs']==2_033_333 and project['audioClips'][0]['duration']==2.01
    assert cut.load(project['id'])['workflow']['episodeDirectory']==config['episodeDirectory']
    assert columns.build(request)['id']!=project['id']

def test_bgm_loop_full_layer_and_independent_paths(column):
    cut,columns,config,items,_=column
    request=dict(config=config,voices=[{'audio':items[0]['id']}])
    once=columns.build(request)
    assert len([c for c in once['audioClips'] if c['kind']=='bgm'])==1
    project=columns.build(dict(request,config=dict(config,bgmLoop=True)))
    music=[c for c in project['audioClips'] if c['kind']=='bgm']
    assert len(music)==3 and sum(c['duration'] for c in music)==pytest.approx(2.033333)
    folder=Path(cut.export(project)['path'])
    assert folder.parent==Path(config['draftDirectory'])
    draft=json.loads((folder/'draft_content.json').read_text('utf-8'))
    overlay=next(t for t in draft['tracks'] if t.get('name','').startswith('全片图片'))
    assert len(overlay['segments'])==1
    assert overlay['segments'][0]['target_timerange']=={'start':0,'duration':project['durationUs']}
    assert len([t for t in draft['tracks'] if t['type']=='audio'])==2
    assert len(draft['materials']['audios'])==2
    assert len(draft['tracks'])==4 and all(t['segments'] for t in draft['tracks'])
    assert len(list((folder/'media').iterdir()))==4
    assert cut.load(project['id'])['overlays']==project['overlays']

def test_layout_and_missing_source_validation(column):
    cut,columns,config,items,backgrounds=column
    t=overlay_transform({'left':2,'top':2,'width':12,'rotation':0},1920,1080,120,80)
    assert t['x']==pytest.approx(-806.4) and t['y']==pytest.approx(441.6)
    with pytest.raises(ValueError):columns.save(dict(config,id='../escape'))
    with pytest.raises(ValueError):columns.build(dict(config=config,voices=[{'audio':items[0]['id']}],episodeDirectory='missing-directory'))
    with pytest.raises(ValueError):cut.normalize({'scenes':[{'background':config['background'],'duration':3}],'overlays':[dict(config['overlays'][0],width=float('nan'))]})
    backgrounds.trash(config['overlays'][0]['image'])
    with pytest.raises(ValueError):columns.build(dict(config=config,voices=[{'audio':items[0]['id']}]))

def test_multiple_voices_and_old_project(column):
    cut,columns,config,items,_=column
    project=columns.build(dict(config=dict(config,bgm=''),voices=[{'audio':items[0]['id'],'opening':True},{'audio':items[0]['id']}]))
    voices=project['audioClips'];assert len(voices)==2
    assert voices[1]['start']>=voices[0]['start']+voices[0]['duration']
    assert sum(s['durationUs'] for s in project['scenes'])>=round((voices[-1]['start']+voices[-1]['duration'])*1e6)
    old=cut.save({'name':'旧项目','scenes':[{'background':config['background'],'duration':3}]})
    assert 'overlays' not in old and 'workflow' not in old

def test_episode_isolation_and_legacy_configuration(column,tmp_path):
    cut,columns,config,items,_=column
    saved=columns.save(config)
    preset=columns.root/'ifgal.json'
    legacy=dict(saved,episodeDirectory=config['episodeDirectory'])
    preset.write_text(json.dumps(legacy),encoding='utf-8')
    before=preset.read_bytes()
    assert 'episodeDirectory' not in columns.list()['items'][0]
    first=columns.build(dict(config=legacy,name='第一期',episodeDirectory=str(tmp_path),voices=[{'audio':items[0]['id']}]))
    #The persisted project is checked through the public loader as well.
    first_snapshot=cut.load(first['id'])
    second=columns.build(dict(config=dict(legacy,overlays=[dict(config['overlays'][0],width=25,left=50)]),name='第二期',voices=[{'audio':items[0]['id']},{'audio':items[0]['id']}]))
    assert second['id']!=first['id'] and second['durationUs']>first['durationUs']
    assert second['workflow']['episodeDirectory']==''
    assert first_snapshot==cut.load(first['id']) and first_snapshot['overlays'][0]['width']==12
    assert preset.read_bytes()==before
    derived=columns.save(dict(saved,id='alternative',name='另一种配置',overlays=second['overlays']))
    assert derived['overlays'][0]['width']==25 and preset.read_bytes()==before

def test_video_loop_single_source_and_layer(column,tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('ffmpeg unavailable')
    cut,columns,config,items,backgrounds=column
    source=tmp_path/'short.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=30','-t','1','-pix_fmt','yuv420p',str(source)],check=True)
    bg=backgrounds.import_file(source)['item']
    project=columns.build(dict(config=dict(config,background=bg['id'],permissions={'background':{'asset':bg['id'],'mode':'loop'}}),voices=[{'audio':items[0]['id']}]))
    folder=Path(cut.export(project)['path']);draft=json.loads((folder/'draft_content.json').read_text('utf-8'))
    track=next(t for t in draft['tracks'] if t.get('name')=='背景')
    assert len(track['segments'])==3
    assert sum(s['target_timerange']['duration'] for s in track['segments'])==project['durationUs']
    assert all(s['source_timerange']['start']+s['source_timerange']['duration']<=1_000_000 for s in track['segments'])
    assert len(draft['materials']['videos'])==2
    assert len([t for t in draft['tracks'] if t.get('name','').startswith('全片图片')])==1

def test_revisions_snapshot_and_stale_save(column):
    cut,columns,config,items,_=column
    first=columns.save(config)
    second=columns.save(dict(first,bgmVolume=.4))
    assert first['revision']==1 and second['revision']==2
    assert columns.revision(first['id'],1)==first
    with pytest.raises(ValueError,match='更新'):columns.save(first)
    project=columns.build(dict(config=first,voices=[{'audio':items[0]['id']}]))
    assert project['generation']['source']['snapshot']==first
    assert project['generation']['effectiveConfig']['bgmVolume']==1
    normalized=cut.save(project)
    assert normalized['generation']==project['generation']
    folder=Path(cut.export(normalized)['path'])
    assert json.loads((folder/'bingyi-storyboard.json').read_text('utf-8'))['generation']==project['generation']
    assert columns.revision(first['id'],1)==first

def test_missing_inputs_save_and_idempotency(column):
    cut,columns,config,items,backgrounds=column
    pending=columns.save(dict(config,background=''))
    request=dict(config=pending,voices=[])
    assert columns.preflight(request)['state']=='needsInput'
    assert not list(cut.projects.glob('*.json'))
    with pytest.raises(ValueError):columns.build(request)
    saved=columns.save(dict(pending,background=config['background']))
    request=dict(config=saved,voices=[{'audio':items[0]['id']}],requestId='same-operation')
    first=columns.build(request)
    assert ColumnWorkflow(cut).build(request)==first
    assert len(list(cut.projects.glob('*.json')))==1
    with pytest.raises(ValueError,match='内容已改变'):columns.build(dict(request,name='different'))
    backgrounds.trash(config['overlays'][0]['image'])
    checked=columns.preflight(dict(config=saved,voices=[{'audio':items[0]['id']}]))
    assert checked['state']=='needsInput' and any('图片' in i['message'] for i in checked['issues'])
    assert columns.save(saved)['revision']==3

def test_version_and_gain_boundaries(column):
    cut,columns,config,items,_=column
    assert columns.preflight(dict(config=dict(config,schemaVersion=99),voices=[]))['state']=='invalid'
    with pytest.raises(ValueError):columns.save(dict(config,schemaVersion=99))
    for volume in (0, .2, 1, 2):
        project=columns.build(dict(config=dict(config,bgmVolume=volume),voices=[{'audio':items[0]['id']}]))
        assert next(c for c in project['audioClips'] if c['kind']=='bgm')['volume']==volume
    with pytest.raises(ValueError):cut.normalize(dict(scenes=[{'background':config['background'],'duration':3}],generation={'schemaVersion':99}))

def test_video_permission_does_not_follow_replacement(column,tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('ffmpeg unavailable')
    cut,columns,config,items,backgrounds=column
    source=tmp_path/'permission.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=red:s=320x180:r=30','-t','1','-pix_fmt','yuv420p',str(source)],check=True)
    bg=backgrounds.import_file(source)['item']
    raw=dict(config,background=bg['id'])
    request=dict(config=raw,voices=[{'audio':items[0]['id']}])
    assert columns.preflight(request)['state']=='needsInput'
    assert columns.preflight(dict(request,config=dict(raw,permissions={'background':{'asset':'other','mode':'loop'}})))['state']=='needsInput'
    allowed=dict(raw,permissions={'background':{'asset':bg['id'],'mode':'loop'}})
    assert columns.preflight(dict(request,config=allowed))['state']=='ready'
    assert columns.build(dict(request,config=allowed))['generation']['effectiveConfig']['permissions']['background']['mode']=='loop'
