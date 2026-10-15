import copy
import json
import threading
import time

import pytest

from rough_cut import atomic_json
from timeline_voice_jobs import TimelineVoiceJobs
from test_timeline_voice import prepare
from test_local_tts import studio
from test_script_plan import setup


class Voice:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.fail = False
        self.busy = False

    def prepare(self, payload):
        return dict(request={'text':payload['text']}, preset=copy.deepcopy(payload['preset']),
                    timelineTarget={'id':payload['target'], 'displayText':payload['text'], 'character':'少女', 'voiceId':'voice'}, projectId='project')

    def generate_prepared(self, prepared):
        if self.busy:
            self.busy = False
            raise ValueError('本机正在生成配音，请等待当前任务完成')
        self.calls.append(prepared)
        self.entered.set()
        assert self.release.wait(5)
        if self.fail:
            self.fail = False
            raise ValueError('model missing')
        return {'id':prepared['timelineTarget']['id'], 'preset':prepared['preset']}


def payload(target='one'):
    return dict(text='台词', target=target, preset={'speed':1})


def finished(jobs, key):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = jobs.job(key)
        if row['status'] in ('complete', 'failed', 'stopped'):
            return row
        time.sleep(.01)
    pytest.fail('worker did not finish')


def test_serial_queue_freezes_input_and_persists_results(tmp_path):
    voice = Voice();jobs = TimelineVoiceJobs(tmp_path, voice)
    source = payload();a = jobs.start(source)
    assert voice.entered.wait(2)
    source['preset']['speed'] = 2
    b = jobs.start(payload('two'))
    assert jobs.job(b['id'])['status'] == 'queued'
    assert 'prepared' not in jobs.job(a['id'])
    voice.release.set()
    assert finished(jobs, a['id'])['result']['preset']['speed'] == 1
    assert finished(jobs, b['id'])['status'] == 'complete'
    assert [c['timelineTarget']['id'] for c in voice.calls] == ['one', 'two']
    recovered = TimelineVoiceJobs(tmp_path, Voice())
    assert recovered.job(a['id'])['result']['id'] == 'one'
    assert recovered.resume({'id':a['id']})['status'] == 'complete'


def test_stop_waits_for_active_take_and_does_not_run_queued(tmp_path):
    voice = Voice();jobs = TimelineVoiceJobs(tmp_path, voice)
    a = jobs.start(payload());assert voice.entered.wait(2)
    b = jobs.start(payload('two'))
    assert jobs.stop({'id':a['id']})['status'] == 'stopping'
    assert jobs.stop({'id':b['id']})['status'] == 'stopped'
    voice.release.set()
    row = finished(jobs, a['id'])
    assert row['status'] == 'stopped' and row['result']['id'] == 'one'
    assert len(voice.calls) == 1
    assert jobs.resume({'id':a['id']})['result'] == row['result']
    jobs.resume({'id':b['id']})
    assert finished(jobs, b['id'])['status'] == 'complete'


def test_failure_isolated_and_explicit_retry(tmp_path):
    voice = Voice();voice.fail = True;jobs = TimelineVoiceJobs(tmp_path, voice)
    a = jobs.start(payload());assert voice.entered.wait(2)
    b = jobs.start(payload('two'));voice.release.set()
    assert finished(jobs, a['id'])['error'] == 'model missing'
    assert finished(jobs, b['id'])['status'] == 'complete'
    jobs.resume({'id':a['id']})
    assert finished(jobs, a['id'])['status'] == 'complete'


@pytest.mark.parametrize('state', ['queued','running','stopping'])
def test_restart_requires_explicit_resume(tmp_path, state):
    voice = Voice();prepared = voice.prepare(payload())
    row = dict(id='a'*32, status=state, createdAt=1, prepared=prepared, binding=prepared['timelineTarget'], projectId='project', text='台词', error='', result=None)
    atomic_json(tmp_path / (row['id']+'.json'), row)
    jobs = TimelineVoiceJobs(tmp_path, voice)
    assert jobs.job(row['id'])['status'] == 'interrupted'
    assert not voice.entered.is_set()
    voice.release.set();jobs.resume({'id':row['id']})
    assert finished(jobs, row['id'])['status'] == 'complete'


def test_busy_shared_tts_waits_and_queue_has_capacity(tmp_path):
    voice = Voice();voice.busy = True;jobs = TimelineVoiceJobs(tmp_path, voice)
    jobs.MAX_PENDING = 1
    a = jobs.start(payload())
    with pytest.raises(ValueError, match='队列已满'):jobs.start(payload('two'))
    assert voice.entered.wait(2)
    voice.release.set()
    assert finished(jobs, a['id'])['status'] == 'complete'
    with pytest.raises(ValueError, match='不存在'):jobs.job('../other')


def test_real_voice_snapshot_preserves_existing_preview_contract(setup, studio, tmp_path):
    service, project, target, take, tts, calls = prepare(setup, studio)
    original = copy.deepcopy(project)
    jobs = TimelineVoiceJobs(tmp_path, service)
    row = jobs.start(dict(project=project, target=target, voiceId=take['timelineTarget']['voiceId'], text='后台台词'))
    result = finished(jobs, row['id'])['result']
    assert result['text'] == '后台台词'
    assert project == original and service.cut.list_projects()['items'] == []
    assert service.preview(dict(project=project, target=target, take=result['id'], mode='keep'))['project']['textClips'][0]['voice']['take'] == result['id']
