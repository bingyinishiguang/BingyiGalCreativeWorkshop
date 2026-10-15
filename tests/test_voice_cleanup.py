import hashlib
import json
import wave
from pathlib import Path
from types import SimpleNamespace
import pytest
from voice_cleanup import find_repetitions, VoiceCleanup


def test_japanese_duplicate_inside_long_cue():
    cues=[{'start':60,'end':66,'text':'今日はいい天気ですね、一緒に遊びませんか、一緒に遊びませんか。'}]
    rows=find_repetitions(cues,'今日はいい天気ですね、一緒に遊びませんか。')
    assert len(rows)==1 and rows[0]['text']=='一緒に遊びませんか'
    assert 60<rows[0]['start']<rows[0]['end']==66
    assert rows[0]['estimated'] and not rows[0]['wordTimestamps']


def test_word_times_and_script_intentional_repeat():
    cue={'start':10,'end':14,'text':'一緒に遊びませんか、一緒に遊びませんか','words':[{'start':10,'end':12,'text':'一緒に遊びませんか'},{'start':12,'end':14,'text':'一緒に遊びませんか'}]}
    rows=find_repetitions([cue],'一緒に遊びませんか')
    assert len(rows)==1 and rows[0]['start']==12 and rows[0]['wordTimestamps']
    assert find_repetitions([cue],cue['text'])==[]
    assert find_repetitions([cue],'一起去玩吗')==[]


def test_three_minute_audio_adjacent_japanese_sentences():
    cues=[{'start':0,'end':2,'text':'今日はいい天気ですね'},
          {'start':88,'end':90,'text':'一緒に遊びませんか？'},
          {'start':90.3,'end':92.3,'text':'一緒に遊びませんか。'},
          {'start':178,'end':180,'text':'それではまた会いましょう'}]
    rows=find_repetitions(cues,'今日はいい天気ですね。一緒に遊びませんか？それではまた会いましょう。')
    assert len(rows)==1
    assert rows[0]['firstStart']==88 and rows[0]['start']==90.3 and rows[0]['end']==92.3


def test_short_japanese_sentence():
    rows=find_repetitions([{'start':0,'end':1,'text':'行こう。'},{'start':1.1,'end':2.1,'text':'行こう。'}],'行こう。')
    assert len(rows)==1 and rows[0]['text']=='行こう' and rows[0]['start']==1.1


def test_no_repeat_and_required_script():
    assert find_repetitions([{'start':0,'end':2,'text':'今日は良い天気ですね'}],'今日は良い天気ですね')==[]
    with pytest.raises(ValueError): find_repetitions([], '日語')
    with pytest.raises(ValueError): find_repetitions([{'start':0,'end':2,'text':'日本語'}], '')
    with pytest.raises(ValueError): find_repetitions([{'start':0,'end':float('nan'),'text':'日本語'}], '日本語')


def test_cleanup_pcm_and_original_unchanged(tmp_path):
    source=tmp_path/'original.wav'
    with wave.open(str(source),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(1000);w.writeframes(b'\x01\x00'*6000)
    raw=source.read_bytes()
    imports=[]
    audio=SimpleNamespace(file=lambda _:source,get=lambda _:{'cues':[{'start':1,'end':5,'text':'一緒に遊びませんか一緒に遊びませんか'}]},import_file=lambda p:imports.append(p) or {'item':{'id':'clean'}})
    clean=VoiceCleanup(tmp_path/'clean',audio,None)
    plan=clean.preview({'audioId':'audio','manuscript':'一緒に遊びませんか'})
    row=plan['rows'][0]
    result=clean.save({'previewId':plan['previewId'],'cuts':[{'id':0,'start':row['start'],'end':row['end']}]})
    assert source.read_bytes()==raw and result['removedSeconds']==2
    with wave.open(result['path'],'rb') as w: assert w.getnframes()==4000
    assert result['audioId']=='clean' and imports
    assert json.loads((Path(result['path']).parent/'配音删减记录.json').read_text('utf-8'))['sourceUnchanged']
    for cuts in ([],[{'id':0,'start':-1,'end':2}],[{'id':0,'start':0,'end':5}],[{'id':True,'start':3,'end':5}]):
        with pytest.raises(ValueError):clean.save({'previewId':plan['previewId'],'cuts':cuts})
