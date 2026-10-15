"""Bounded unattended endurance check using disposable drafts, without network.

Checks rotating sessions, persisted text/style progress, stale window rejection,
restart recovery and original-file integrity at intervals. Never uses real media.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from existing_draft import ExistingDraftEditor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--minutes',type=float,default=45)
    parser.add_argument('--interval',type=float,default=180)
    args=parser.parse_args()
    root=args.root.resolve()
    workspace=Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace/'output'):
        raise ValueError('Endurance fixtures must stay in workspace/output')
    if not 1<=args.minutes<=120 or not 1<=args.interval<=300:
        raise ValueError('Invalid bounded duration or interval')
    root.mkdir(parents=True,exist_ok=True)
    originals=[]
    for i in range(10):
        folder=root/f'original-{i}';folder.mkdir(exist_ok=True)
        source=folder/'draft_content.json'
        body={'tracks':[{'type':'text','name':'字幕','segments':[{'material_id':'text','target_timerange':{'start':0,'duration':1000000},'clip':{'transform':{'x':0,'y':-.73}}}]}],
              'materials':{'texts':[{'id':'text','content':json.dumps({'text':f'字幕{i}','styles':[{'range':[0,len(f"字幕{i}")],'size':5}]})}]}}
        source.write_text(json.dumps(body),'utf-8')
        originals.append((source,hashlib.sha256(source.read_bytes()).hexdigest()))
    editor=ExistingDraftEditor(root/'edits')
    started=time.monotonic();rounds=[];deadline=started+args.minutes*60
    while True:
        iteration=len(rounds)
        oldest_page=None
        for i,(source,digest) in enumerate(originals):
            loaded=editor.load({'path':str(source)})
            payload={'sessionId':loaded['sessionId'],'trackIndex':0}
            if iteration:
                assert loaded['progress']['tracks'][0]['texts']==[f'第{iteration-1}轮校对{i}']
                assert loaded['progress']['tracks'][0]['stylePatch']=={'size':6+(iteration-1)%3}
            state={'trackIndex':0,'texts':[f'第{iteration}轮校对{i}'],'stylePatch':{'size':6+iteration%3},'manuscript':f'  原稿{i}。\n','mode':'auto','chatHistory':[],'editLog':[]}
            if i==0:oldest_page=({**payload,'sourcePath':loaded['sourcePath'],'sourceHash':loaded['sourceHash']},state)
            revision=(loaded.get('progress') or {}).get('revision')
            saved=editor.progress_save({**payload,'tracks':[state],'revision':revision})
            try:
                editor.progress_save({**payload,'tracks':[state],'revision':revision})
            except ValueError as error:
                assert '其他窗口' in str(error)
            else:
                raise AssertionError('Stale write was accepted')
            assert saved['revision']!=revision
            backed=editor.progress_backup({**payload,'tracks':[state]})
            backup_id=Path(backed['path']).stem.removeprefix('字幕编辑备份-')
            listed=editor.recovery_list(payload)['backups']
            assert any(b['id']==backup_id and b['compatible'] for b in listed)
            restored=editor.recovery_preview({**payload,'backupId':backup_id,'texts':[f'字幕{i}']})
            assert restored['state']['texts']==state['texts']
            assert restored['state']['stylePatch']==state['stylePatch']
            assert restored['state']['manuscript']==state['manuscript']
            assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
            assert len(editor.sessions)<=8
        # The first page was evicted by the ten rotating sessions. Its backup
        # must remain identifiable and recoverable after a fresh load.
        old_request,old_state=oldest_page
        assert old_request['sessionId'] not in editor.sessions
        expired_backup=editor.progress_backup({**old_request,'tracks':[old_state]})
        expired_id=Path(expired_backup['path']).stem.removeprefix('字幕编辑备份-')
        refreshed=editor.load({'path':str(originals[0][0])})
        restored=editor.recovery_preview({'sessionId':refreshed['sessionId'],'trackIndex':0,'backupId':expired_id,'texts':['original']})
        assert restored['state']['texts']==old_state['texts']
        # A new editor simulates a process restart while retaining local records.
        editor=ExistingDraftEditor(root/'edits')
        elapsed=time.monotonic()-started
        rounds.append({'round':iteration+1,'elapsedSeconds':round(elapsed,2),'sourcesUnchanged':10,'progressRecovered':10,'staleWritesRejected':10,'backupRestorationsVerified':10,'expiredPageBackupsRecovered':1})
        result={'status':'passed' if time.monotonic()>=deadline else 'running','elapsedSeconds':round(elapsed,2),'rounds':rounds}
        (root/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(rounds[-1]),flush=True)
        if result['status']=='passed':break
        time.sleep(min(args.interval,max(0,deadline-time.monotonic())))
    print('Endurance check passed',flush=True)


if __name__=='__main__':main()
