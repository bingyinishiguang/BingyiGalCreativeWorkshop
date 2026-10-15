import io
import json
import urllib.error

import pytest

import assistant_model as client


CONFIG = {'baseUrl': 'https://models.example/v1', 'model': 'test-model', 'apiKey': 'secret-test-key'}


@pytest.mark.parametrize('base_url,expected', [
    ('https://api.deepseek.com/v1', {'type': 'disabled'}),
    ('https://models.example/v1', None),
])
def test_deepseek_tool_requests_disable_default_thinking(monkeypatch, base_url, expected):
    captured = {}
    class Opener:
        def open(self, request, timeout):
            captured.update(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': 'ok'}}]}).encode())
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *args: Opener())
    client._request({**CONFIG, 'baseUrl': base_url}, [{'role': 'user', 'content': 'probe'}],
                    [client._tool('probe', 'test', {})],
                    {'type': 'function', 'function': {'name': 'probe'}})
    assert captured.get('thinking') == expected


def call(name, arguments):
    return {'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


def plan(monkeypatch, calls):
    monkeypatch.setattr(client, '_request', lambda *a, **k: {'content': None, 'tool_calls': calls})
    return client.plan_message(CONFIG, {'message': '修改字幕', 'project': {}})


def test_valid_tool_plan_and_project_context_omit_credentials_and_paths(monkeypatch):
    captured = {}
    def request(config, messages, *args):
        captured['messages'] = json.dumps(messages, ensure_ascii=False)
        return {'content': None, 'tool_calls': [call('replace_subtitle', {'cueIndex': 0, 'text': '你好'})]}
    monkeypatch.setattr(client, '_request', request)
    result = client.plan_message(CONFIG, {'message': '改第一条字幕', 'project': {
        'path': 'PRIVATE-PATH', 'apiKey': 'PRIVATE-KEY',
        'audioClips': [{'id': 'clip', 'path': 'PRIVATE-AUDIO-PATH', 'cues': [{'start': 0, 'end': 1, 'text': 'こんにちは'}]}]}})
    assert result['actions'] == [{'tool': 'replace_subtitle', 'arguments': {'cueIndex': 0, 'text': '你好'}}]
    assert 'こんにちは' in captured['messages']
    assert 'PRIVATE-' not in captured['messages']


@pytest.mark.parametrize('name,args', [
    ('run_shell', {'command': 'anything'}),
    ('replace_subtitle', {'cueIndex': True, 'text': 'a'}),
    ('replace_subtitle', {'cueIndex': -1, 'text': 'a'}),
    ('replace_subtitle', {'cueIndex': 1, 'text': ''}),
    ('replace_subtitle', {'cueIndex': 1, 'text': 'a', 'path': 'x'}),
    ('set_subtitle_style', {'style': {'size': float('nan')}}),
    ('set_subtitle_style', {'style': {'color': '#zzzzzz'}}),
    ('generate_subtitles', {'targetLanguage': 'invalid'}),
])
def test_unknown_tools_and_invalid_arguments_fail_before_execution(monkeypatch, name, args):
    with pytest.raises(ValueError):
        plan(monkeypatch, [call(name, args)])


def test_background_operations_cannot_mix_with_changes(monkeypatch):
    with pytest.raises(ValueError, match='单独'):
        plan(monkeypatch, [call('export_draft', {}), call('replace_subtitle', {'cueIndex': 0, 'text': 'x'})])


@pytest.mark.parametrize('entry', [None, 1, 'bad', {'type': 'function', 'function': []}])
def test_malformed_tool_entries_are_explainable_errors(monkeypatch, entry):
    with pytest.raises(ValueError):
        plan(monkeypatch, [entry])


@pytest.mark.parametrize('cues', [[None], [1], ['bad'], {'start': 0}])
def test_malformed_project_cues_rejected_before_network(monkeypatch, cues):
    def unexpected_request(*args):
        pytest.fail('invalid project must not reach provider')
    monkeypatch.setattr(client, '_request', unexpected_request)
    with pytest.raises(ValueError):
        client.plan_message(CONFIG, {'message': 'test', 'project': {'audioClips': [{'id': 'clip', 'cues': cues}]}})


@pytest.mark.parametrize('url', ['http://remote.example/v1', 'https://u:p@example.com',
                                  'https://example.com/v1?key=secret', 'file:///local'])
def test_endpoint_rejects_insecure_or_secret_bearing_urls(url):
    with pytest.raises(ValueError):
        client.endpoint({**CONFIG, 'baseUrl': url})


def test_request_http_error_never_echoes_provider_body(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError('https://models.example', 401, CONFIG['apiKey'], {}, io.BytesIO(CONFIG['apiKey'].encode()))
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(ValueError) as caught:
        client._request(CONFIG, [{'role': 'user', 'content': 'test'}])
    assert '401' in str(caught.value)
    assert CONFIG['apiKey'] not in str(caught.value)


def test_connection_requires_actual_tool_response(monkeypatch):
    monkeypatch.setattr(client, '_request', lambda *a, **k: {'content': 'I support tools'})
    assert client.test_connection(CONFIG)['toolCalling'] is False
    monkeypatch.setattr(client, '_request', lambda *a, **k: {'tool_calls': [call('connection_probe', {})]})
    assert client.test_connection(CONFIG)['toolCalling'] is True
