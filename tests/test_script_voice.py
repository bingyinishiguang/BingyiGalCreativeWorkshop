import copy
import io
import json
import threading
import time
import wave
import zipfile

import pytest
from audio_library import AudioLibrary
from local_tts import LocalTTS
from rough_cut import number
from script_plan import normalize_plan
from script_import import parse_script,document_text
from script_voice import ScriptVoice


def test_types_roles_voice_and_uncertain_lines():
    p=parse_script('【场景】教室\n【背景】同名素材\n【旁白】放学了。\n【心理描写】【男主】【无配音】她在等谁？\n【对话】【莉莉子】【有配音】你好。\n男主：再见。\n一段未标明类别的文字\n莉莉子：你等等。')
    assert [r['kind'] for r in p['rows']]==['narrator','inner','dialogue','dialogue','narrator','dialogue']
    assert [r['voice'] for r in p['rows']]==[False,False,True,False,False,False]
    assert len(p['directives'])==2 and p['rows'][4]['reviewed'] is False
    assert p['rows'][5]['warnings'] and p['rows'][2]['character']=='莉莉子'
    assert normalize_plan(p,number)['directives'][1]['value']=='同名素材'


def test_docx_paragraphs_tables_and_utf16(tmp_path):
    path=tmp_path/'剧本.docx'
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>【旁白】</w:t></w:r><w:r><w:t>放学后。</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>【对话】【莉莉子】【有配音】你好。</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
    with zipfile.ZipFile(path,'w') as z:z.writestr('word/document.xml',xml)
    assert len(parse_script(document_text(path))['rows'])==2
    text=tmp_path/'test.txt';text.write_bytes('旁白：你好'.encode('utf-16'))
    assert document_text(text)=='旁白：你好'
    path.write_bytes(b'bad file')
    with pytest.raises(ValueError):document_text(path)
    with pytest.raises(ValueError):parse_script('【场景】教室')


@pytest.fixture
def service(tmp_path):
    t=LocalTTS(tmp_path/'tts',AudioLibrary(tmp_path/'audio'))
    paths={}
    for key,extension in [('gpt','.ckpt'),('sovits','.pth'),('reference','.wav')]:
        f=tmp_path/(key+extension);f.write_bytes(b'fixture');paths[key]=str(f)
    t.save(dict(**paths,prompt='reference',name='测试声音',promptLanguage='ja',serviceMode='external'))
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000)
    requests=[]
    def call(base,route,payload=None,limit=None):
        if route=='/openapi.json':return b'{"paths":{"/tts":{},"/set_gpt_weights":{},"/set_sovits_weights":{}}}'
        if route=='/tts':
            requests.append(copy.deepcopy(payload))
            if payload['text']=='失败句':raise ValueError('模拟推理失败')
            return stream.getvalue()
        return b'{"message":"success"}'
    t.call=call
    s=ScriptVoice(tmp_path/'script',t);profile=s.capture({})
    plan=parse_script('【对话】【莉莉子】【有配音】你好。\n【对话】【莉莉子】【有配音】失败句\n男主：再见。')
    for row in plan['rows']:row['voicePreset']=profile['id'];row['language']='ja'
    return s,plan,requests


def wait(s,job):
    end=time.monotonic()+5
    while time.monotonic()<end:
        result=s.job(job['id'])
        if result['state'] not in ('queued','running','stopping'):return result
        time.sleep(.01)
    raise AssertionError('job did not finish')


def test_partial_retry_presets_and_original_binding(service):
    s,plan,requests=service;original=copy.deepcopy(plan);settings=s.tts.settings()
    result=wait(s,s.start({'scriptPlan':plan}))
    assert result['state']=='partial' and result['completed']==2
    good,bad,male=result['plan']['rows']
    assert good['audio'] and not bad['audio'] and not male['audio']
    assert len(good['versions'])==1 and requests[0]['text_lang']=='ja'
    assert requests[0]['prompt_lang']=='ja' and s.tts.settings()==settings and plan==original
    binding=s.select_take({'id':good['take']})
    assert binding['audioBinding']['text']=='你好。' and binding['audioBinding']['character']=='莉莉子'
    requests.clear();again=wait(s,s.start({'scriptPlan':result['plan']}))
    assert again['total']==1 and requests[0]['text']=='失败句'
    regenerated=wait(s,s.start({'scriptPlan':result['plan'],'rowIds':[good['id']]}))
    assert len(regenerated['plan']['rows'][0]['versions'])==2
    assert s.tts.file(good['take']).is_file()


def test_review_and_missing_voice_preflight(service):
    s,plan,_=service;plan['rows'][0]['warnings']=['确认配音'];plan['rows'][0]['reviewed']=False
    with pytest.raises(ValueError,match='解析提示'):s.start({'scriptPlan':plan})
    plan['rows'][0]['reviewed']=True;plan['rows'][0]['voicePreset']='missing'
    with pytest.raises(ValueError,match='声音预设'):s.start({'scriptPlan':plan})
    assert s.list()['items']==[]


def test_standalone_script_round_trip_without_background(service):
    s,plan,_=service;draft=s.save_plan({'name':'纯剧本','scriptPlan':plan})
    assert s.plan(draft['id'])['plan']==normalize_plan(plan,number)
    assert s.list_plans()['items'][0]['name']=='纯剧本'
    with pytest.raises(ValueError):s.plan('../bad')


def test_version_selection_restores_missing_library_copy(service):
    s,plan,_=service
    result=wait(s,s.start({'scriptPlan':plan,'rowIds':[plan['rows'][0]['id']]}))
    row=result['plan']['rows'][0]
    path=s.tts.library.file(row['audio']);path.unlink()
    chosen=s.select_take({'id':row['take']})
    assert s.tts.library.file(chosen['audio']).is_file()
    assert chosen['audioBinding']['text']==row['text']


def test_stop_and_restart_recovery(service):
    s,plan,_=service;entered=threading.Event();release=threading.Event();old=s.tts.generate
    def generate(*args,**kwargs):entered.set();assert release.wait(3);return old(*args,**kwargs)
    s.tts.generate=generate
    job=s.start({'scriptPlan':plan});assert entered.wait(2)
    with pytest.raises(ValueError,match='正在进行'):s.start({'scriptPlan':plan})
    s.cancel({'id':job['id']});release.set();result=wait(s,job)
    assert result['state']=='stopped' and result['completed']==1 and result['plan']['rows'][0]['audio']
    result['state']='running';s.path(job['id']).write_text(json.dumps(result),encoding='utf-8')
    recovered=ScriptVoice(s.root,s.tts).job(job['id'])
    assert recovered['state']=='interrupted' and recovered['plan']['rows'][0]['audio']
