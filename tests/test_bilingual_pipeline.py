import threading
from types import SimpleNamespace

import pytest
from bilingual_pipeline import BilingualPipeline


def pipeline():
    calls=[]
    complete=dict(id='child',state='complete',rows=[dict(chinese='作者中文',expression='0',review=True)],expressions=[dict(id='0',label='平静')])
    def export(payload):
        calls.append(('export',payload));assert payload['automatic'] is True
        assert 'reviewed' not in payload['rows'][0]
        return dict(path='prepared',subtitleCount=1,expressionCount=1)
    workflow=SimpleNamespace(start=lambda payload:calls.append(('start',payload)) or complete,
                             export=export,cancel=lambda payload:calls.append(('cancel',payload)))
    pause=SimpleNamespace(preview=lambda payload:dict(previewId='preview',rows=[dict(id=0,selected=True),dict(id=1,selected=False)]),
                          save=lambda payload:calls.append(('pause',payload)) or dict(cleanAudioId='clean',removedSeconds=.5))
    publish=lambda payload,result:calls.append(('publish',payload)) or dict(result,published=True)
    worker=BilingualPipeline(workflow,pause,publish);worker.prepare=lambda payload:dict(payload)
    worker.jobs['run']=dict(id='run',state='running',stage='',step=1,steps=5,started=0,cancel=threading.Event(),child=None)
    return worker,calls


def test_pipeline_automatically_exports_after_pause_and_preserves_optional_translation():
    worker,calls=pipeline();worker.run('run',dict(useBaidu=False))
    job=worker.job(dict(id='run'))
    assert job['state']=='awaiting_save' and 'result' not in job
    assert [v[0] for v in calls]==['pause','start','export']
    assert calls[0][1]['selected']==[0]
    assert calls[1][1]['cleanAudioId']=='clean' and calls[1][1]['useBaidu'] is False
    job=worker.save(dict(id='run',publish=dict(mode='overwrite')))
    assert job['state']=='complete' and job['result']['published']
    assert calls[-1][1]['publish']['mode']=='overwrite'


def test_no_eligible_pause_still_produces_draft():
    worker,calls=pipeline();worker.pause.preview=lambda payload:dict(rows=[])
    worker.run('run',dict(useBaidu=True))
    assert worker.job(dict(id='run'))['state']=='awaiting_save'
    assert [v[0] for v in calls]==['start','export']
    assert calls[0][1]['useBaidu'] is True


def test_save_failure_keeps_prepared_result_for_retry():
    worker,calls=pipeline();worker.run('run',dict(cleanPauses=False))
    publish=worker.publish
    worker.publish=lambda *args:(_ for _ in ()).throw(ValueError('原草稿被占用'))
    with pytest.raises(ValueError,match='被占用'):worker.save(dict(id='run',publish=dict(mode='overwrite')))
    assert worker.job(dict(id='run'))['state']=='awaiting_save'
    worker.publish=publish
    assert worker.save(dict(id='run',publish=dict(mode='new')))['state']=='complete'
    assert [v[0] for v in calls].count('start')==1
    with pytest.raises(ValueError):worker.save(dict(id='run',publish=dict(mode='new')))


def test_cancelled_pipeline_never_exports_or_publishes():
    worker,calls=pipeline();worker.jobs['run']['cancel'].set()
    worker.run('run',{})
    assert worker.job(dict(id='run'))['state']=='cancelled' and not calls


def test_failed_alignment_never_publishes():
    worker,calls=pipeline();worker.workflow.start=lambda payload:dict(id='child',state='failed',error='音频与原稿不对应')
    worker.run('run',dict(cleanPauses=False))
    assert worker.job(dict(id='run'))['state']=='failed'
    assert not any(v[0] in ('publish','export') for v in calls)
