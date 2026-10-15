import json
import wave

import pytest

from audio_library import AudioLibrary


@pytest.fixture
def library(tmp_path):
    source=tmp_path/'voice.wav'
    with wave.open(str(source),'wb') as stream:
        stream.setparams((1,2,16000,0,'NONE','not compressed'))
        stream.writeframes(b'\0\0'*8000)
    audio=AudioLibrary(tmp_path/'audio')
    item=audio.import_file(source)['item']
    return audio,item,source


@pytest.mark.parametrize('broken',[
    '{unfinished', '[]', '{}',
    {'duration':'invalid'}, {'name':None}, {'cues':{}},
    {'tags':'invalid'}, {'filename':'../outside.wav'}, {'id':'different'},
])
def test_bad_record_does_not_block_valid_audio(library,broken):
    audio,item,_=library
    key='f'*32
    content={**item,'id':key,'filename':key+'.wav',**broken} if isinstance(broken,dict) else broken
    raw=json.dumps(content) if isinstance(content,dict) else content
    path=audio.record_path(key);path.write_text(raw,encoding='utf-8')
    result=audio.list()
    assert [row['id'] for row in result['items']]==[item['id']]
    assert result['total']==1 and len(result['warnings'])==1
    assert result['warnings'][0]['record']==path.name
    assert path.read_text(encoding='utf-8')==raw


def test_import_can_repair_library_with_unreadable_metadata(library):
    audio,item,source=library
    path=audio.record_path('0'*32);path.write_text('{broken',encoding='utf-8')
    result=audio.import_file(source)
    assert result['duplicate'] and result['item']['id']==item['id']
    assert audio.file(item['id']).is_file()
    assert path.read_text(encoding='utf-8')=='{broken'


def test_direct_lookup_reports_corrupt_record(library):
    audio,item,_=library
    path=audio.record_path(item['id']);path.write_text('{broken',encoding='utf-8')
    with pytest.raises(ValueError,match='音频资料'):
        audio.get(item['id'])
