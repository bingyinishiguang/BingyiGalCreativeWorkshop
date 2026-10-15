"""Verify local backup/restart/copy workflow against an existing native draft.

The source is read-only. All generated files stay under workspace/output.
No model, translation, or speech API is called.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from existing_draft import ExistingDraftEditor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--install',required=True)
    args=parser.parse_args()
    root=args.root.resolve();workspace=Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace/'output'):raise ValueError('Verification output must stay in workspace/output')
    root.mkdir(parents=True,exist_ok=True)
    source=args.source.resolve();before=hashlib.sha256(source.read_bytes()).hexdigest()
    load={'path':str(source),'installPath':args.install}
    editor=ExistingDraftEditor(root/'edits');loaded=editor.load(load)
    track=next((t for t in loaded['tracks'] if len(t['cues'])>10),loaded['tracks'][0])
    request={'sessionId':loaded['sessionId'],'trackIndex':track['index']}
    originals=[c['text'] for c in track['cues']];texts=originals[:];texts[0]='本地备份恢复验收字幕'
    state={'trackIndex':track['index'],'texts':texts,'manuscript':'  原稿保留空格。\n',
           'mode':'auto','stylePatch':{},'chatHistory':[],'editLog':['本地恢复验收']}
    saved=editor.progress_backup({**request,'tracks':[state]})
    backup_id=Path(saved['path']).stem.removeprefix('字幕编辑备份-')
    editor=ExistingDraftEditor(root/'edits');reloaded=editor.load(load)
    request['sessionId']=reloaded['sessionId']
    assert any(b['id']==backup_id and b['compatible'] for b in editor.recovery_list(request)['backups'])
    preview=editor.recovery_preview({**request,'backupId':backup_id,'texts':originals})
    assert preview['state']['texts']==texts and preview['state']['manuscript']==state['manuscript']
    assert preview['changes']==[{'cueIndex':0,'before':originals[0],'after':texts[0]}]
    progress=editor.progress_save({**request,'tracks':[state],'revision':(reloaded.get('progress') or {}).get('revision')})
    result=editor.save({**request,'rows':[{'cueIndex':i,'text':t} for i,t in enumerate(texts)],'normalize':True})
    session=editor.sessions[request['sessionId']]
    copy_path=Path(result['path'])/'draft_content.json'
    decoded=root/'copy-decoded.json'
    if loaded['encrypted']:editor.codec('dec',copy_path,decoded,args.install,'')
    else:decoded.write_bytes(copy_path.read_bytes())
    copy_data=json.loads(decoded.read_bytes());original_data=session['data']
    assert copy_data['tracks']==original_data['tracks']
    other_materials={k:v for k,v in original_data['materials'].items() if k!='texts'}
    assert {k:v for k,v in copy_data['materials'].items() if k!='texts'}==other_materials
    untouched_ids={s['material_id'] for t in original_data['tracks'] if t.get('type')=='text' and t is not original_data['tracks'][track['index']] for s in t.get('segments',[])}
    old={m['id']:m for m in original_data['materials']['texts']};new={m['id']:m for m in copy_data['materials']['texts']}
    assert all(old[i]==new[i] for i in untouched_ids)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    report={'encrypted':loaded['encrypted'],'cueCount':len(texts),'backupPreviewChanges':len(preview['changes']),
            'restartBackupRecovered':True,'rawManuscriptExact':True,'sourceHash':before,
            'sourceUnchanged':result['sourceUnchanged'],'roundTripVerified':result['roundTripVerified'],
            'tracksAndTimingExact':True,'otherMaterialsExact':True,'otherTextTracksExact':True,
            'copyPath':result['path'],'backupId':backup_id,'progressRevision':progress['revision'],
            'externalAPIRequests':0,'nativeRenderingNeedsJianyingReview':True}
    (root/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
