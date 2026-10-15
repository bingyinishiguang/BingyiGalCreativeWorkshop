import hashlib
import json
import threading
import urllib.parse
from contextlib import contextmanager

import pytest
import baidu_translation
import bilingual_dialogue


def test_baidu_signs_japanese_and_returns_only_translation(monkeypatch):
    @contextmanager
    def respond(request,timeout):
        fields=urllib.parse.parse_qs(request.data.decode())
        assert fields['from']==['jp'] and fields['to']==['zh']
        assert fields['q']==['今日は。']
        assert fields['sign']==[hashlib.md5(('id今日は。'+fields['salt'][0]+'secret').encode()).hexdigest()]
        assert timeout==45
        yield type('Response',(),{'read':lambda self,n:json.dumps({'trans_result':[{'dst':'今天。'}]}).encode()})()
    monkeypatch.setattr(baidu_translation.urllib.request,'urlopen',respond)
    assert baidu_translation.translate_text('今日は。',{'appId':'id','secret':'secret'})=='今天。'


def test_reference_cache_skips_network_and_has_no_credentials(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(bilingual_dialogue,'translate_text',lambda text,*args:calls.append(text) or '今天。')
    settings={'appId':'private-id','secret':'private-secret'}
    cancel=threading.Event()
    assert bilingual_dialogue.reference_translations(['今日は。','今日は。'],settings,tmp_path,cancel,lambda _:None)=={'今日は。':'今天。'}
    assert bilingual_dialogue.reference_translations(['今日は。'],settings,tmp_path,cancel,lambda _:None)=={'今日は。':'今天。'}
    assert calls==['今日は。']
    cached=next(tmp_path.glob('*.json')).read_text('utf-8')
    assert 'private-id' not in cached and 'private-secret' not in cached


def test_failed_reference_is_not_cached_and_cancel_stops_requests(tmp_path,monkeypatch):
    def fail(*args):raise ValueError('百度翻译请求失败，错误码：52001')
    monkeypatch.setattr(bilingual_dialogue,'translate_text',fail)
    settings={'appId':'id','secret':'secret'};cancel=threading.Event()
    with pytest.raises(ValueError,match='52001'):
        bilingual_dialogue.reference_translations(['今日は。'],settings,tmp_path,cancel,lambda _:None)
    assert not list(tmp_path.glob('*.json'))
    cancel.set()
    with pytest.raises(ValueError,match='取消'):
        bilingual_dialogue.reference_translations(['今日は。'],settings,tmp_path,cancel,lambda _:None)


def test_missing_translation_configuration_is_explicit(tmp_path):
    with pytest.raises(ValueError,match='百度'):
        bilingual_dialogue.reference_translations(['今日は。'],{},tmp_path,threading.Event(),lambda _:None)


def test_rate_limit_backoff_can_be_cancelled_without_caching(tmp_path,monkeypatch):
    cancel=threading.Event();calls=[]
    def limited(*args):
        calls.append(args[0]);cancel.set()
        raise ValueError('百度翻译请求失败，错误码：54003')
    monkeypatch.setattr(bilingual_dialogue,'translate_text',limited)
    with pytest.raises(ValueError,match='取消'):
        bilingual_dialogue.reference_translations(['今日は。'],dict(appId='id',secret='secret'),tmp_path,cancel,lambda _:None)
    assert calls==['今日は。'] and not list(tmp_path.glob('*.json'))
