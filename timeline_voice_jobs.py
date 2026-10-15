"""Persistent, serial audition jobs. Results never mutate the user's timeline."""
import copy
import json
import threading
import time
import uuid
from pathlib import Path

from rough_cut import atomic_json


class TimelineVoiceJobs:
    MAX_PENDING = 30

    def __init__(self, root, voice):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.voice = voice
        self.lock = threading.RLock()
        self.worker = None
        self.records = {}
        for path in self.root.glob('*.json'):
            try:
                row = json.loads(path.read_text('utf-8'))
                if row['id'] != path.stem or 'prepared' not in row:
                    continue
                # A restart requires explicit consent to launch inference again.
                if row['status'] in ('queued', 'running', 'stopping'):
                    row.update(status='interrupted', error='软件已重启，点击续跑继续；已有配音保留')
                    self._save(row)
                self.records[row['id']] = row
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def _save(self, row):
        row['updatedAt'] = time.time()
        atomic_json(self.root / (row['id'] + '.json'), row)

    @staticmethod
    def _public(row):
        return copy.deepcopy({k: v for k, v in row.items() if k != 'prepared'})

    def _find(self, key):
        if key not in self.records:
            raise ValueError('配音任务不存在')
        return self.records[key]

    def job(self, key):
        with self.lock:
            return self._public(self._find(key))

    def list(self):
        with self.lock:
            return {'items': [self._public(r) for r in sorted(self.records.values(), key=lambda r: r['createdAt'], reverse=True)]}

    def _capacity(self):
        if sum(r['status'] in ('queued', 'running', 'stopping') for r in self.records.values()) >= self.MAX_PENDING:
            raise ValueError('配音队列已满，请等待已有任务完成')

    def _launch(self):
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._run, daemon=True, name='timeline-voice-jobs')
            self.worker.start()

    def start(self, payload):
        prepared = copy.deepcopy(self.voice.prepare(payload))
        with self.lock:
            self._capacity()
            row = dict(id=uuid.uuid4().hex, status='queued', createdAt=time.time(),
                       prepared=prepared, binding=prepared['timelineTarget'],
                       projectId=prepared.get('projectId', ''), text=prepared['request']['text'], error='', result=None)
            self._save(row)
            self.records[row['id']] = row
            response = self._public(row)
            self._launch()
            return response

    def resume(self, payload):
        with self.lock:
            row = self._find(payload.get('id'))
            if row['result'] is not None or row['status'] in ('queued', 'running', 'stopping', 'complete'):
                return self._public(row)
            self._capacity()
            row.update(status='queued', error='')
            self._save(row)
            response = self._public(row)
            self._launch()
            return response

    def stop(self, payload):
        with self.lock:
            row = self._find(payload.get('id'))
            if row['status'] == 'queued':
                row['status'] = 'stopped'
            elif row['status'] == 'running':
                row['status'] = 'stopping'
            self._save(row)
            return self._public(row)

    def _run(self):
        while True:
            with self.lock:
                row = next((r for r in self.records.values() if r['status'] == 'queued'), None)
                if row is None:
                    self.worker = None
                    return
                row['status'] = 'running'
                self._save(row)
                prepared = copy.deepcopy(row['prepared'])
            try:
                result = self.voice.generate_prepared(prepared)
                with self.lock:
                    row.update(result=result, status='stopped' if row['status'] == 'stopping' else 'complete', error='')
                    self._save(row)
            except Exception as error:
                with self.lock:
                    # LocalTTS already serializes synchronous and legacy requests.
                    # Its busy rejection happens before inference: safe to retry.
                    busy = isinstance(error, ValueError) and str(error) == '本机正在生成配音，请等待当前任务完成'
                    row.update(status=('stopped' if row['status'] == 'stopping' else 'queued') if busy else 'failed', error='' if busy else str(error)[:1000])
                    self._save(row)
                if busy:
                    time.sleep(.5)
