"""Create a real editable acceptance draft without changing the source project."""
import argparse
import hashlib
import json
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gal_story import GalStory
from gal_story_draft import export
from audio_library import AudioLibrary
from background_library import BackgroundLibrary
from sprite_library import SpriteLibrary
from rough_cut import atomic_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--drafts',type=Path,required=True)
    parser.add_argument('--media',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();raw=args.source.read_bytes();p=json.loads(raw)
    root=args.data.resolve()
    story=GalStory(root/'GalStory',BackgroundLibrary(root/'exports/Backgrounds'),SpriteLibrary(root/'exports/Library'),
        AudioLibrary(root/'exports/Audio'),SimpleNamespace(settings=lambda:{}),None)
    story._update=lambda *a,**k:None
    args.media.mkdir(parents=True,exist_ok=True)
    p['id']=uuid.uuid4().hex;p['name']='明天见 · 剪映草稿验收'
    p['output']={'draftDirectory':str(args.drafts.resolve()),'materialDirectory':str(args.media.resolve())}
    result=export(story,p,p['id'],threading.Event())
    folder=Path(result['path']);content=json.loads((folder/'draft_content.json').read_text('utf-8'))
    meta=json.loads((folder/'draft_meta_info.json').read_text('utf-8'))
    missing=[m['path'] for group in ('videos','audios') for m in content['materials'][group] if not Path(m['path']).is_file()]
    missing_registry=[m['file_Path'] for group in meta['draft_materials'] for m in group['value'] if not Path(m['file_Path']).is_file()]
    assert not missing and not missing_registry
    for track in content['tracks']:
        for left,right in zip(track['segments'],track['segments'][1:]):
            a=left['target_timerange'];b=right['target_timerange'];assert a['start']+a['duration']<=b['start']
    assert args.source.read_bytes()==raw
    # Expose this acceptance project in the ordinary project selector without
    # replacing the user's current last-project pointer.
    atomic_json(story.projects/(p['id']+'.json'),story.normalize(p))
    record=story.exports/p['id'];record.mkdir(exist_ok=True)
    atomic_json(record/'result.json',dict(result,id=p['id'],kind='draft',state='complete',projectId=p['id']))
    result.update(sourceUnchanged=True,sourceHash=hashlib.sha256(raw).hexdigest(),missingMedia=missing,missingRegistry=missing_registry,
        tracks=[{'name':t['name'],'type':t['type'],'segments':len(t['segments'])} for t in content['tracks']],nativePlaybackVerified=False)
    args.report.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.report,result)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
