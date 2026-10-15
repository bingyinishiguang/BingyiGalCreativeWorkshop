"""Read a real encrypted draft and verify only independent experimental copies."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from existing_draft import ExistingDraftEditor
from draft_video_tools import DraftVideoTools


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--assets',required=True)
    parser.add_argument('--install',required=True)
    args=parser.parse_args()
    workspace=Path(__file__).resolve().parents[1]
    root=args.root.resolve()
    if not root.is_relative_to(workspace/'output'):raise ValueError('Only output/ verification directories are allowed')
    root.mkdir(parents=True,exist_ok=True)
    original=args.source.read_bytes()
    editor=ExistingDraftEditor(root/'relink')
    loaded=editor.load({'path':str(args.source),'installPath':args.install})
    tools=DraftVideoTools(editor);request={'sessionId':loaded['sessionId']}
    preview=tools.relink_preview({**request,'root':args.assets})
    (root/'素材修复预览.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),'utf-8')
    # Unique-name matches are only applied to this disposable verification copy.
    choices={r['id']:r['candidates'][0]['path'] for r in preview['rows'] if r['status'] in ('unique','identical')}
    report={'encrypted':loaded['encrypted'],'scanned':preview['scanned'],'missing':len(preview['rows']),
            'unique':len(choices),'ambiguous':sum(r['status']=='ambiguous' for r in preview['rows']),
            'unresolved':sum(r['status']=='missing' for r in preview['rows']),
            'inaccessible':sum(r['accessIssue'] for r in preview['rows']),'externalAPICalls':0}
    if choices:
        result=tools.relink_save({**request,'previewId':preview['previewId'],'choices':choices})
        expected=copy.deepcopy(editor.sessions[loaded['sessionId']]['data'])
        for ref,path in choices.items():
            group,index=ref.rsplit(':',1);expected['materials'][group][int(index)]['path']=path
        decoded=root/'relinked.json'
        editor.codec('dec',Path(result['path'])/'draft_content.json',decoded,args.install,'')
        assert json.loads(decoded.read_bytes())==expected
        report.update(relinkCopy=result['path'],relinkRoundTripExact=True)
        second=ExistingDraftEditor(root/'character');second_loaded=second.load({'path':result['path'],'installPath':args.install})
        tools2=DraftVideoTools(second);second_request={'sessionId':second_loaded['sessionId']}
        info=tools2.character_info(second_request)
        for track in info['tracks']:
            assets=[a for a in track['assets'] if Path(next(m['path'] for m in expected['materials']['videos'] if m['id']==a['materialId'])).is_file()]
            if not assets:continue
            si=assets[0]['segmentIndex'];example=expected['tracks'][track['index']]['segments'][si]
            if example.get('keyframe_refs') or example.get('common_keyframes') or example.get('reverse') or example.get('speed',1)!=1:continue
            timer=example['target_timerange'];start=timer['start']/1e6;end=(timer['start']+timer['duration'])/1e6
            if end-start<.2:continue
            mid=assets[0]['materialId']
            fake_cues=[{'start':start,'end':(start+end)/2,'text':'本地边界验收'},{'start':(start+end)/2,'end':end,'text':'同表情切换验收'}]
            switches=[{'cueIndex':0,'materialId':mid,'reason':'验收'},{'cueIndex':1,'materialId':mid,'reason':'验收'}]
            token=tools2.remember(second_request,'character',{'cues':fake_cues,'assets':[{'materialId':mid,'label':'原表情'}],'switches':switches})
            changed=tools2.character_save({**second_request,'previewId':token,'videoTrackIndex':track['index'],'segmentIndex':si})
            tools2.editor.codec('dec',Path(changed['path'])/'draft_content.json',root/'character.json',args.install,'')
            actual=json.loads((root/'character.json').read_bytes())
            assert actual['materials']==expected['materials']
            assert [t for i,t in enumerate(actual['tracks']) if i!=track['index']]==[t for i,t in enumerate(expected['tracks']) if i!=track['index']]
            assert actual['tracks'][track['index']]['segments'][:si]==expected['tracks'][track['index']]['segments'][:si]
            assert actual['tracks'][track['index']]['segments'][si+2:]==expected['tracks'][track['index']]['segments'][si+1:]
            report.update(characterCopy=changed['path'],characterRoundTripExact=True,otherTracksExact=True)
            break
    assert args.source.read_bytes()==original
    report.update(sourceUnchanged=True,sourceHash=hashlib.sha256(original).hexdigest(),nativeRenderingNeedsManualReview=True)
    (root/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
