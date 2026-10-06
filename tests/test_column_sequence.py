import json
import subprocess
import wave
from pathlib import Path
import pytest
from test_column_workflow import column
from column_sequence import normalize_sequence, compile_sequence


def test_explicit_timeline_gaps_extend_beyond_voice_and_export(sequence):
    cut,columns,config,request,_,video=sequence
    config['sequence']=[dict(itemId='a',background=video,sourceStart=0,duration=8),
                        dict(itemId='b',background=video,sourceStart=10,duration=8,gapBefore=4)]
    req=request(16)
    assert columns.preflight(req)['state']=='needsInput'
    with pytest.raises(ValueError,match='超出'):columns.build(req)
    config['durationPolicy']='timeline'
    config.update(bgm=req['voices'][0]['audio'],bgmLoop=True,bgmVolume=1)
    before=list(cut.root.glob('projects/*.json'))
    checked=columns.preflight(req)
    assert checked['state']=='ready' and checked['arrangement']['durationUs']==20_000_000
    assert list(cut.root.glob('projects/*.json'))==before
    project=columns.build(req)
    assert [s['durationUs'] for s in project['scenes']]==[8_000_000,4_000_000,8_000_000]
    assert project['scenes'][1]['blank'] is True
    music=[clip for clip in project['audioClips'] if clip['kind']=='bgm']
    assert sum(clip['duration'] for clip in music)==20 and all(clip['volume']==1 for clip in music)
    item=project['generation']['resolved']['sequence'][1]
    assert (item['gapStartFrame'],item['gapEndFrame'],item['startFrame'],item['endFrame'])==(240,360,360,600)
    folder=Path(cut.export(project)['path']);draft=json.loads((folder/'draft_content.json').read_text('utf-8'))
    background=draft['tracks'][0]['segments']
    assert [(s['target_timerange']['start'],s['target_timerange']['duration']) for s in background]==[(0,8_000_000),(12_000_000,8_000_000)]
    assert draft['duration']==20_000_000
    overlays=[s for t in draft['tracks'][1:] for s in t['segments'] if t['type']=='video']
    assert any(s['target_timerange']['duration']==20_000_000 for s in overlays)


def test_gap_requires_explicit_frame_adjustment(sequence):
    _,_,config,_,backgrounds,video=sequence
    rows=normalize_sequence([dict(itemId='g',background=video,duration=1,gapBefore=.01)])
    with pytest.raises(ValueError,match='空隙需确认'):compile_sequence(rows,backgrounds,30,0,None)
    rows[0]['acceptFrameAdjustment']=True
    scenes,resolved=compile_sequence(rows,backgrounds,30,0,None)
    assert resolved[0]['gapEndFrame']==0 and len(scenes)==1


def test_leading_and_trailing_blank_preserve_duration_and_cover(sequence):
    cut,columns,config,request,_,video=sequence
    config.update(durationPolicy='timeline',overlays=[],bgm='')
    config['sequence']=[dict(itemId='a',background=video,duration=8,gapBefore=4),
                        dict(itemId='fill',background=config['background'],timing='remainder',gapBefore=4)]
    p=columns.build(request(8))
    assert p['durationUs']==16_000_000 and p['scenes'][0]['blank'] and p['scenes'][-1]['blank']
    folder=Path(cut.export(p)['path']);draft=json.loads((folder/'draft_content.json').read_text('utf-8'))
    assert draft['duration']==16_000_000 and (folder/'draft_cover.jpg').is_file()


@pytest.fixture
def sequence(column, tmp_path):
    cut, columns, config, items, backgrounds = column
    path=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=320x180:r=30:d=30','-c:v','mpeg4','-y',str(path)],check=True)
    video=backgrounds.import_file(path)['item']['id']
    rows=[dict(itemId='first',background=video,sourceStart=1,duration=8),
          dict(itemId='second',background=video,sourceStart=12,duration=12),
          dict(itemId='fill',background=config['background'],timing='remainder')]
    conf=dict(config,visualMode='sequence',sequence=rows,bgm='')
    def request(seconds):
        path=tmp_path/f'voice-{seconds}.wav'
        with wave.open(str(path),'wb') as out:
            out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b'\0\0'*round(seconds*16000))
        voice=cut.audio_library.import_file(path)['item']['id']
        return dict(config=conf,voices=[{'audio':voice}])
    return cut,columns,conf,request,backgrounds,video


def test_remainder_recalculates_without_mutating_template(sequence):
    cut,columns,config,request,_,_=sequence
    saved=columns.save(config);before=json.dumps(saved,sort_keys=True)
    a=request(23);a['config']=saved
    first=columns.build(a);snapshot=cut.load(first['id'])
    b=request(27);b['config']=saved
    second=columns.build(b)
    assert [s['durationUs'] for s in first['scenes']]==[8_000_000,12_000_000,3_000_000]
    assert [s['durationUs'] for s in second['scenes']]==[8_000_000,12_000_000,7_000_000]
    assert [s['videoStart'] for s in first['scenes'][:2]]==[1,12]
    assert cut.load(first['id'])==snapshot
    assert json.dumps(columns.list()['items'][0],sort_keys=True)==before
    checked=columns.preflight(a)
    assert checked['arrangement']['durationUs']==23_000_000
    assert [r['itemId'] for r in checked['arrangement']['sequence']]==['first','second','fill']
    folder=Path(cut.export(first)['path']);draft=json.loads((folder/'draft_content.json').read_text('utf-8'))
    track=next(t for t in draft['tracks'] if t['type']=='video' and len(t['segments'])==3)
    assert [s['source_timerange']['start'] for s in track['segments'][:2]]==[1_000_000,12_000_000]
    assert sum(s['target_timerange']['duration'] for s in track['segments'])==23_000_000
    assert all(s['volume']==0 for s in track['segments'])


@pytest.mark.parametrize('case,message',[('gap','还差'),('overflow','超出'),('cap','上限'),('range','视频结尾'),('video-fill','只支持图片')])
def test_conflicts_block_before_project_is_saved(sequence,case,message):
    cut,columns,config,request,_,video=sequence
    req=request(19 if case=='overflow' else 27)
    if case=='gap':config['sequence'].pop()
    if case=='cap':config['sequence'][-1]['maxDuration']=5
    if case=='range':config['sequence'][1]['sourceStart']=25
    if case=='video-fill':config['sequence'][-1]['background']=video
    checked=columns.preflight(req)
    assert checked['state']=='needsInput' and message in checked['issues'][0]['message']
    with pytest.raises(ValueError,match=message):columns.build(req)
    assert not list(cut.root.glob('projects/*.json'))


def test_order_and_duplicate_ids(sequence):
    _,_,config,_,_,_=sequence
    with pytest.raises(ValueError,match='最后'):normalize_sequence(config['sequence'][::-1])
    config['sequence'][1]['itemId']='first'
    with pytest.raises(ValueError,match='编号重复'):normalize_sequence(config['sequence'])


@pytest.mark.parametrize('fps',[24,25,30,60])
def test_fractional_ranges_require_consent_and_do_not_overread(sequence,fps):
    _,_,config,_,backgrounds,video=sequence
    rows=[dict(itemId='fraction',background=video,sourceStart=27.99,duration=2.01),config['sequence'][-1]]
    with pytest.raises(ValueError,match='按帧'):compile_sequence(normalize_sequence(rows),backgrounds,fps,1,1+3*fps)
    rows[0]['acceptFrameAdjustment']=True
    scenes,resolved=compile_sequence(normalize_sequence(rows),backgrounds,fps,1,1+3*fps)
    assert resolved[0]['sourceStartUs']+resolved[0]['durationUs']<=30_000_000
    assert sum(round(s['duration']*fps) for s in scenes)==3*fps


def test_zero_remainder_emits_no_empty_clip(sequence):
    _,columns,_,request,_,_=sequence
    p=columns.build(request(20))
    assert len(p['scenes'])==2
    assert p['generation']['resolved']['sequence'][-1]['durationUs']==0


def test_dedicated_opening_precedes_main_sequence(sequence):
    _,columns,config,request,_,_=sequence
    req=request(23);intro=request(2.01)['voices'][0]
    req['voices']=[dict(intro,opening=True),*req['voices']]
    config['openingBackground']=config['background']
    p=columns.build(req)
    assert [s['durationUs'] for s in p['scenes']]==[2_033_333,8_000_000,12_000_000,3_000_000]
    assert p['generation']['resolved']['sequence'][0]['startFrame']==61
    assert p['durationUs']==25_033_333


@pytest.mark.parametrize('fps',[24,25,30,60])
def test_fractional_source_range_survives_project_normalization(sequence,fps):
    _,columns,config,request,_,video=sequence
    req=request(3);config['fps']=fps
    config['sequence']=[dict(itemId='near-end',background=video,sourceStart=27.99,duration=2.01,acceptFrameAdjustment=True),config['sequence'][-1]]
    assert columns.preflight(req)['state']=='ready'
    p=columns.build(req)
    assert round(p['scenes'][0]['videoStart']*1e6)+p['scenes'][0]['durationUs']<=30_000_000
    assert p['durationUs']==3_000_000
