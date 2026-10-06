import copy
import json
from pathlib import Path
import pytest
from test_local_tts import studio
from script_voice import ScriptVoice

def write_voice(tts,key='one',name='因幡巡'):
    folder=tts.voices.root/key;folder.mkdir(exist_ok=True)
    for filename in ('model.ckpt','model.pth','reference.wav'): (folder/filename).write_bytes(b'fixture')
    (folder/'参考台词.txt').write_text('これは参考の台詞です。',encoding='utf-8')
    value=dict(id=key,name=name,work='自定义作品',gpt='model.ckpt',sovits='model.pth',reference='reference.wav',promptFile='参考台词.txt',promptLanguage='ja',textLanguage='zh')
    (folder/'voice.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return folder,value

def test_relative_paths_new_detection_rename_and_selection(studio):
    t,calls=studio;folder,value=write_voice(t)
    data=t.voices.scan();item=data['items'][0];assert item['ready'] and item['name']=='因幡巡'
    assert item['preset']['gpt']==str((folder/'model.ckpt').resolve())
    assert item['preset']['prompt']=='これは参考の台詞です。'
    selected=t.select_voice(item['id']);assert selected['character']=='因幡巡' and calls==[]
    value['name']='我填写的新名字';(folder/'voice.json').write_text(json.dumps(value),encoding='utf-8')
    renamed=t.voices.scan()['items'][0];assert renamed['id']==item['id'] and renamed['name']==value['name']
    write_voice(t,'two','绫地宁宁');assert len(t.voices.scan()['items'])==2

def test_invalid_duplicate_and_missing_do_not_break_other_voices(studio):
    t,_=studio;first,value=write_voice(t);second,_=write_voice(t,'two','绫地宁宁')
    (second/'model.pth').unlink();data=t.voices.scan();assert [i['ready'] for i in data['items']]==[True,False]
    with pytest.raises(ValueError,match='文件丢失'):t.select_voice(data['items'][1]['id'])
    bad=t.voices.root/'bad';bad.mkdir();(bad/'voice.json').write_text('{invalid',encoding='utf-8')
    assert t.voices.scan()['errors']
    value['name']='重复';(second/'voice.json').write_text(json.dumps(value),encoding='utf-8')
    data=t.voices.scan();assert not any(i['ready'] for i in data['items']) and data['errors']

def test_catalog_profiles_not_written_into_manual_store_and_versions_are_frozen(studio):
    t,_=studio;folder,_=write_voice(t);voice=ScriptVoice(t.root.parent/'jobs',t)
    item=voice.presets()['items'][0];before=copy.deepcopy(item['preset'])
    voice.capture({'preset':item['preset']});saved=json.loads(voice.profiles.read_text('utf-8'))
    assert len(saved)==1 and len(voice.presets()['items'])==2
    take=t.generate({'text':'你好'},preset=before)
    data=json.loads((folder/'voice.json').read_text('utf-8'));data['name']='新名字';(folder/'voice.json').write_text(json.dumps(data),encoding='utf-8')
    assert t.history()['items'][0]['preset']==before
    assert voice.presets()['items'][1]['name']=='新名字'
