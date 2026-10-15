"""Baidu text translation shared by subtitle and bilingual reference workflows."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
import uuid


def translate_text(text, settings, source='ja', target='zh'):
    app_id, secret = settings.get('appId'), settings.get('secret')
    if not app_id or not secret:
        raise ValueError('请先配置百度翻译 APP ID 和密钥')
    language = {'ja':'jp','en':'en','zh':'zh','zh-CN':'zh','ko':'kor','fr':'fra','es':'spa','auto':'auto'}
    salt=uuid.uuid4().hex
    sign=hashlib.md5((str(app_id)+text+salt+str(secret)).encode('utf-8')).hexdigest()
    fields={'q':text,'from':language.get(source,source),'to':language.get(target,target),
            'appid':app_id,'salt':salt,'sign':sign}
    request=urllib.request.Request('https://fanyi-api.baidu.com/api/trans/vip/translate',
                                  data=urllib.parse.urlencode(fields).encode('utf-8'))
    with urllib.request.urlopen(request,timeout=45) as response:
        data=json.loads(response.read(2_000_000).decode('utf-8'))
    if data.get('error_code'):
        raise ValueError('百度翻译请求失败，错误码：'+str(data['error_code']))
    result='\n'.join(row['dst'] for row in data.get('trans_result',[]))
    if not result.strip():raise ValueError('百度翻译未返回译文')
    return result
