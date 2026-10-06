from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from PIL import Image

from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from rough_cut import RoughCut
from sprite_library import SpriteLibrary
from subtitle_tools import parse_srt, read_text

SRT='1\n00:00:00,100 --> 00:00:01,500\n你好。\n\n2\n00:00:01,800 --> 00:00:03,800\n再见。\n'


@pytest.fixture
def dialogue(tmp_path):
    source=tmp_path/'配音.wav'
    with wave.open(str(source),'wb') as out:
        out.setparams((1,2,16000,0,'NONE','not compressed'))
        out.writeframes(b'\0\0'*16000*4)
    source.with_suffix('.srt').write_text(SRT,encoding='utf-8-sig')
    library=AudioLibrary(tmp_path/'audio')
    item=library.import_file(source)['item']
    bg_library=BackgroundLibrary(tmp_path/'backgrounds')
    bg_source=tmp_path/'病房.png'
    Image.new('RGB',(960,540),'blue').save(bg_source)
    bg=bg_library.import_file(bg_source)['item']
    sprites=SpriteLibrary(tmp_path/'sprites')
    cut=RoughCut(tmp_path/'roughcut',bg_library,sprites,library)
    payload={'name':'对白验证','scenes':[{'background':bg['id'],'duration':10}],
             'audioClips':[{'audio':item['id'],'start':0,'track':0,'character':'甲'},
                           {'audio':item['id'],'start':2,'track':1,'character':'乙',
                            'subtitleStyle':{'x':.2,'y':-.5,'color':'#ff0000','size':12}}]}
    return cut,library,item,payload,source


def test_same_name_srt_and_dedup_repair(dialogue):
    _,library,item,_,source=dialogue
    assert item['duration']==4
    assert len(item['cues'])==2
    assert library.import_file(source)['duplicate']
    library.file(item['id']).unlink()
    library.update({'id':item['id'],'deleted':True})
    restored=library.import_file(source)['item']
    assert not restored['missing'] and len(restored['cues'])==2


def test_export_overlapping_audio_and_independent_text(dialogue):
    cut,library,item,payload,_=dialogue
    result=cut.export(payload)
    folder=Path(result['path'])
    content=json.loads((folder/'draft_content.json').read_text('utf-8'))
    audio=[t for t in content['tracks'] if t['type']=='audio']
    assert len(audio)==2
    assert audio[0]['segments'][0]['target_timerange']['start']==0
    assert audio[1]['segments'][0]['target_timerange']['start']==2_000_000
    assert len(content['materials']['audios'])==1
    assert Path(content['materials']['audios'][0]['path']).is_relative_to(folder)
    texts=content['materials']['texts']
    assert len(texts)==4
    assert len({t['id'] for t in texts})==4
    assert all(t['type']=='text' for t in texts)
    styles=[json.loads(t['content'])['styles'][0] for t in texts]
    assert len({str(s['fill']) for s in styles})==2
    assert not list(cut.exports.glob('.bingyi-building-*'))
    library.file(item['id']).unlink()
    assert Path(content['materials']['audios'][0]['path']).is_file()


def test_same_track_overlap_rejected_and_visual_coverage(dialogue):
    cut,_,_,payload,_=dialogue
    payload['audioClips'][1]['track']=0
    with pytest.raises(ValueError,match='不能重叠'):
        cut.save(payload)
    payload['audioClips'][1]['track']=1
    payload['scenes'][0]['duration']=2
    with pytest.raises(ValueError,match='超出画面'):
        cut.export(payload)


def test_trimmed_srt_moves_with_audio(dialogue):
    cut,_,_,payload,_=dialogue
    payload['audioClips']=payload['audioClips'][:1]
    payload['audioClips'][0].update(start=5,sourceStart=1,duration=2)
    result=cut.export(payload)
    content=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    text_segments=[s for t in content['tracks'] if t['type']=='text' for s in t['segments']]
    assert [(s['target_timerange']['start'],s['target_timerange']['duration']) for s in text_segments]==[(5_000_000,500_000),(5_800_000,1_200_000)]


@pytest.mark.parametrize('text',['1\n00:00:01,000 --> 00:00:00,000\n错了','1\n00:61:00,000 --> 00:62:00,000\n错了','not srt'])
def test_invalid_srt(text):
    with pytest.raises(ValueError):parse_srt(text)


def test_subtitle_encodings(tmp_path):
    path=tmp_path/'字幕.srt'
    for encoding in ('utf-8-sig','utf-16','gb18030'):
        path.write_bytes(SRT.encode(encoding))
        assert len(parse_srt(read_text(path)))==2


def test_standalone_text_without_audio_roundtrip_and_overlap(dialogue):
    cut,_,_,payload,_=dialogue
    payload['audioClips']=[]
    payload['textClips']=[{'text':'旁白，没有配音。','start':1,'duration':3,'character':'旁白'},
                          {'text':'内心独白。','start':2,'duration':2,'character':'主角',
                           'subtitleStyle':{'x':.3,'y':.4,'size':12}}]
    saved=cut.save(payload)
    assert len(saved['textClips'])==2 and not saved['audioClips']
    result=cut.export(saved)
    content=json.loads((Path(result['path'])/'draft_content.json').read_text('utf-8'))
    texts=content['materials']['texts']
    assert len(texts)==2 and all(t['type']=='text' for t in texts)
    assert len([t for t in content['tracks'] if t['type']=='text'])==2
    assert not content['materials']['audios']
    segments=[s for t in content['tracks'] if t['type']=='text' for s in t['segments']]
    assert {(s['target_timerange']['start'],s['target_timerange']['duration']) for s in segments}=={(1_000_000,3_000_000),(2_000_000,2_000_000)}
    payload['textClips'][1]['duration']=20
    with pytest.raises(ValueError,match='超出画面'):cut.export(payload)


@pytest.mark.parametrize('entry',[{'text':''},{'text':'坏时间','start':float('nan')},
                                 {'text':'过长','start':10799,'duration':5},
                                 {'text':'坏样式','subtitleStyle':{'color':'bad'}}])
def test_invalid_standalone_text(dialogue,entry):
    cut,_,_,payload,_=dialogue
    payload['textClips']=[entry]
    with pytest.raises(ValueError):cut.save(payload)
