"""Acceptance checks for assistant transactions, using real project/draft adapters."""
import copy
import io
import json
import threading
import time
import wave
from pathlib import Path

import pytest
from PIL import Image

from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from rough_cut import RoughCut
from sprite_library import SpriteLibrary
from ai_subtitle_assistant import SubtitleAssistant


@pytest.fixture
def studio(tmp_path):
    source = tmp_path / 'voice.wav'
    with wave.open(str(source), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 16000 * 4)
    audio = AudioLibrary(tmp_path / 'audio')
    item = audio.import_file(source)['item']
    backgrounds = BackgroundLibrary(tmp_path / 'backgrounds')
    background = tmp_path / 'background.png'
    Image.new('RGB', (640, 360), '#224466').save(background)
    bg = backgrounds.import_file(background)['item']
    cut = RoughCut(tmp_path / 'cut', backgrounds, SpriteLibrary(tmp_path / 'sprites'), audio)
    payload = {'name': 'AI acceptance', 'scenes': [{'background': bg['id'], 'duration': 10}],
               'audioClips': [{'audio': item['id'], 'start': 5, 'sourceStart': 1, 'duration': 2}],
               'textClips': [{'text': 'Keep this title', 'start': 0, 'duration': 1}]}
    return cut, audio, item, cut.save(payload)


def finished(assistant, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = assistant.job(job_id)
        if result['status'] in ('complete', 'completed', 'failed', 'cancelled', 'stopped'):
            return result
        time.sleep(.01)
    pytest.fail('assistant worker did not finish')


SOURCE_CUES = [{'start': .1, 'end': 1.5, 'text': 'こんにちは'},
               {'start': 1.8, 'end': 3.8, 'text': 'さようなら'}]


def prepare(tmp_path, studio, monkeypatch):
    cut, audio, item, project = studio
    assistant = SubtitleAssistant(tmp_path / 'assistant', cut, audio)
    monkeypatch.setattr(assistant, 'recognize', lambda *args: copy.deepcopy(SOURCE_CUES))
    def translate(cues, *args):
        return [{**cue, 'text': text} for cue, text in zip(cues, ['你好。', '再见。'])]
    monkeypatch.setattr(assistant, 'translate', translate)
    return assistant, cut, audio, item, project


def test_pipeline_to_real_draft_preserves_other_content_and_trim_mapping(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    original = copy.deepcopy(project)
    started = assistant.pipeline({'project': project, 'export': True})
    job = finished(assistant, started['job']['id'])
    assert job['status'] == 'completed', job
    changed = job['project']
    assert changed['scenes'] == original['scenes']
    assert changed['textClips'] == original['textClips']
    assert changed['audioClips'][0]['cues'] == [
        {**SOURCE_CUES[0], 'text': '你好'}, {**SOURCE_CUES[1], 'text': '再见'}]
    assert project == original
    assert audio.get(item['id'])['cues'] == []
    folder = Path(job['exportResult']['path'])
    draft = json.loads((folder / 'draft_content.json').read_text('utf-8'))
    texts = {m['id']: json.loads(m['content'])['text'] for m in draft['materials']['texts']}
    segments = [s for t in draft['tracks'] if t['type'] == 'text' for s in t['segments']
                if texts[s['material_id']] != 'Keep this title']
    assert [(s['target_timerange']['start'], s['target_timerange']['duration']) for s in segments] == [
        (5_000_000, 500_000), (5_800_000, 1_200_000)]
    assert any(t['type'] == 'audio' for t in draft['tracks'])
    assert any(t['type'] == 'video' for t in draft['tracks'])
    assert not list(cut.exports.glob('.bingyi-building-*'))


@pytest.mark.parametrize('step', ['recognize', 'translate'])
def test_cancel_before_commit_never_publishes_project_or_draft(tmp_path, studio, monkeypatch, step):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return copy.deepcopy(SOURCE_CUES)
    monkeypatch.setattr(assistant, step, blocked)
    original = copy.deepcopy(project)
    key = assistant.pipeline({'project': project, 'export': True})['job']['id']
    assert entered.wait(2)
    assistant.cancel({'id': key})
    release.set()
    job = finished(assistant, key)
    assert job['status'] == 'cancelled', job
    assert 'project' not in job and 'result' not in job
    assert project == original
    assert cut.load(project['id']) == original
    assert not list(cut.exports.iterdir())


def test_failed_translation_leaves_saved_project_and_redacts_secrets(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    assistant.save_settings({'translation': {'appId': 'app', 'secret': 'translation-secret'}})
    def failed(*args):
        raise ValueError('Provider echoed translation-secret')
    monkeypatch.setattr(assistant, 'translate', failed)
    key = assistant.pipeline({'project': project, 'export': True})['job']['id']
    job = finished(assistant, key)
    assert job['status'] == 'failed'
    assert 'translation-secret' not in job['error']
    assert 'project' not in job and 'result' not in job
    assert cut.load(project['id']) == project
    assert not list(cut.exports.iterdir())


def test_invalid_recognition_timestamps_never_publish_result(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    monkeypatch.setattr(assistant, 'recognize', lambda *args: [{'start': 0, 'end': 99, 'text': 'outside audio'}])
    key = assistant.pipeline({'project': project, 'translate': False, 'export': True})['job']['id']
    job = finished(assistant, key)
    assert job['status'] == 'failed'
    assert 'project' not in job and 'result' not in job
    assert cut.load(project['id']) == project
    assert not list(cut.exports.iterdir())


def test_cancel_during_export_preserves_successful_commit_and_result_path(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    export = cut.export
    def blocked(project):
        entered.set()
        assert release.wait(3)
        return export(project)
    monkeypatch.setattr(cut, 'export', blocked)
    key = assistant.pipeline({'project': project, 'export': True})['job']['id']
    assert entered.wait(2)
    assert assistant.cancel({'id': key})['status'] == 'running'
    release.set()
    job = finished(assistant, key)
    assert job['status'] == 'completed', job
    assert (Path(job['exportResult']['path']) / 'draft_content.json').is_file()


def test_baidu_api_translates_text_while_preserving_timing(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    assistant.save_settings({'translation': {'appId': 'test-id', 'secret': 'test-secret'}})
    # Restore the real provider method; only its network boundary is replaced.
    monkeypatch.setattr(assistant, 'translate', SubtitleAssistant.translate.__get__(assistant))
    project['audioClips'][0]['cues'] = [SOURCE_CUES[0]]
    captured = []
    def urlopen(request, timeout):
        captured.append(request)
        return io.BytesIO(json.dumps({'trans_result': [{'src': 'こんにちは', 'dst': '你好'}]}).encode())
    monkeypatch.setattr('ai_subtitle_assistant.urllib.request.urlopen', urlopen)
    key = assistant.pipeline({'project': project, 'recognize': False, 'translate': True})['job']['id']
    job = finished(assistant, key)
    assert job['status'] == 'completed', job
    assert job['project']['audioClips'][0]['cues'] == [{**SOURCE_CUES[0], 'text': '你好'}]
    assert captured[0].full_url.startswith('https://fanyi-api.baidu.com/')
    assert b'test-secret' not in captured[0].data


def test_audio_only_project_gets_background_coverage(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    project['scenes'] = []
    key = assistant.pipeline({'project': project, 'export': True})['job']['id']
    job = finished(assistant, key)
    assert job['status'] == 'completed', job
    assert job['project']['scenes'][0]['blank'] is True
    assert job['project']['durationUs'] >= 7_000_000
    assert (Path(job['exportResult']['path']) / 'draft_content.json').is_file()


def test_settings_redact_keys_and_preserve_them_when_resaving_public_settings(tmp_path, studio):
    cut, audio, *_ = studio
    assistant = SubtitleAssistant(tmp_path / 'assistant', cut, audio)
    public = assistant.save_settings({'models': [{'id': 'one', 'name': 'Test', 'baseUrl': 'https://example.com/v1',
                                                'model': 'test', 'apiKey': 'model-secret'}],
                                      'activeModelId': 'one', 'translation': {'secret': 'translation-secret'}})
    encoded = json.dumps(public)
    assert 'model-secret' not in encoded and 'translation-secret' not in encoded
    assert public['models'][0]['hasApiKey'] is True
    assistant.save_settings(public)
    assert assistant.model()['apiKey'] == 'model-secret'
    assert assistant._settings()['translation']['secret'] == 'translation-secret'


def test_chat_modifies_selected_subtitles_without_touching_other_tracks(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    project['audioClips'][0]['cues'] = copy.deepcopy(SOURCE_CUES)
    assistant.save_settings({'models': [{'id': 'one', 'baseUrl': 'https://example.com/v1', 'model': 'test'}], 'activeModelId': 'one'})
    monkeypatch.setattr('assistant_model.plan_message', lambda *args: {'message': 'Change', 'actions': [
        {'tool': 'replace_subtitle', 'arguments': {'cueIndex': 0, 'text': '你好。'}},
        {'tool': 'set_subtitle_style', 'arguments': {'style': {'color': '#ff0000'}}}]})
    original = copy.deepcopy(project)
    result = assistant.chat({'message': '改字幕', 'project': project, 'clipId': project['audioClips'][0]['id']})
    changed = result['project']
    assert changed['audioClips'][0]['cues'][0]['text'] == '你好'
    assert changed['audioClips'][0]['subtitleStyle']['color'] == '#ff0000'
    assert changed['subtitleStyle'] == original['subtitleStyle']
    assert changed['scenes'] == original['scenes'] and changed['textClips'] == original['textClips']
    assert project == original


def test_backend_refuses_unrecognized_tool_without_project_commit(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    assistant.save_settings({'models': [{'id': 'one', 'baseUrl': 'https://example.com/v1', 'model': 'test'}], 'activeModelId': 'one'})
    monkeypatch.setattr('assistant_model.plan_message', lambda *args: {'actions': [{'tool': 'delete_file', 'arguments': {}}]})
    with pytest.raises(ValueError, match='未支持'):
        assistant.chat({'message': 'test', 'project': project})
    assert cut.load(project['id']) == project


def test_normalization_preserves_script_links_workflow_and_generation_metadata(tmp_path, studio, monkeypatch):
    assistant, cut, audio, item, project = prepare(tmp_path, studio, monkeypatch)
    project['audioClips'][0].update(sourceRow='row1', linkedText='title1', voice={
        'versions': [item['id']], 'take': 'take1', 'voiceId': 'voice1', 'spokenText': 'こんにちは', 'speed': 1})
    project['textClips'][0].update(sourceRow='row1', voice={'versions': [item['id']], 'take': 'take1'})
    project['scriptPlan'] = {'rows': [{'id': 'row1', 'kind': 'narrator', 'text': 'Keep this title'}], 'gap': .3}
    project['scriptBase'] = copy.deepcopy(project['scenes'][0])
    project['scriptBaseline'] = {key: copy.deepcopy(project[key]) for key in ('scenes', 'audioClips', 'textClips')}
    project['scriptTiming'] = {'plan': copy.deepcopy(project['scriptPlan']), 'base': copy.deepcopy(project['scenes'][0])}
    project['workflow'] = {'episodeDirectory': str(tmp_path), 'draftDirectory': str(tmp_path), 'presetName': 'Recipe'}
    project['overlays'] = []
    project['generation'] = {'schemaVersion': 1, 'generator': 'column', 'createdAt': '2026-10-12',
                             'source': {'name': 'source'}, 'effectiveConfig': {}, 'voices': {}, 'episode': {}, 'resolved': {}}
    normalized = assistant.validate_project(project)
    key = assistant.pipeline({'project': normalized})['job']['id']
    result = finished(assistant, key)
    assert result['status'] == 'completed', result
    changed = result['project']
    for field in ('scriptPlan', 'scriptBase', 'scriptBaseline', 'scriptTiming', 'workflow', 'overlays', 'generation'):
        assert changed[field] == normalized[field], field
    for field in ('voice', 'sourceRow', 'linkedText'):
        assert changed['audioClips'][0][field] == normalized['audioClips'][0][field], field
    assert changed['textClips'] == normalized['textClips']
