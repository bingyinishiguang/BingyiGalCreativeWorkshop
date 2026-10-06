"""Verify packaged media/draft dependencies with an isolated APPDATA directory."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from sprite_library import SpriteLibrary
from tools.verify_installer import listening_port, kill_test_processes, powershell


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--draft-directory', default='')
    parser.add_argument('--ui-smoke', action='store_true', help='Run the sentence review browser workflow against the frozen server')
    parser.add_argument('--draft-entry-ui', action='store_true', help='Verify the ordinary draft entry against the frozen server')
    parser.add_argument('--tts-inference', action='store_true', help='Synthesize both voices using an external component')
    parser.add_argument('--tts-component', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    workspace_data = Path(__file__).resolve().parents[1] / '工作数据'
    if not root.is_relative_to(workspace_data.resolve()):
        raise ValueError('验证数据必须放在项目工作数据内')
    root.mkdir(parents=True, exist_ok=True)
    appdata = root / 'appdata'
    data = appdata / 'BingyiGalCreativeWorkshop'
    sprites = SpriteLibrary(data / 'exports' / 'Library')
    actor = Image.new('RGBA', (400, 700))
    draw = ImageDraw.Draw(actor)
    draw.ellipse((130, 30, 270, 180), fill='#a5dbff')
    draw.polygon([(140, 160), (260, 160), (320, 650), (80, 650)], fill='#a5dbff')
    person = sprites.save('自制验收素材', '测试人物', 'standing', 'smile', 'normal', actor)
    other = sprites.save('自制验收素材', '测试人物', 'standing', 'surprise', 'normal', Image.new('RGBA',(400,700),'#efc4de'))
    source = root / 'test-background.png'
    Image.new('RGB', (960, 540), '#284766').save(source)
    env = dict(os.environ)
    env['APPDATA'] = str(appdata)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    proc = subprocess.Popen([str(args.exe.resolve())], cwd=args.exe.resolve().parent,
                            env=env, startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port = None
        for _ in range(35):
            if proc.poll() is not None:
                raise RuntimeError('冻结版提前退出，请检查隔离目录中的启动日志')
            port = listening_port(proc.pid)
            if port:
                break
            time.sleep(.5)
        if not port:
            raise RuntimeError('冻结版未能启动本地服务')
        base = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        opener.open(base+'/', timeout=30).read()
        #Leave the user's desktop available during unattended CPU inference.
        import ctypes
        owned=str(args.exe.resolve()).replace("'","''")
        handles=powershell("Get-Process -Name BingyiGalCreativeWorkshop -ErrorAction SilentlyContinue | "
                           f"Where-Object {{ $_.Path -eq '{owned}' }} | ForEach-Object {{ $_.MainWindowHandle }}")
        for handle in handles.splitlines():
            if handle.strip().isdigit() and int(handle):ctypes.windll.user32.ShowWindow(int(handle),6)
        def api(path, body=None):
            request = urllib.request.Request(base+path, data=None if body is None else json.dumps(body).encode(),
                                             headers={} if body is None else {'Content-Type':'application/json'})
            try:
                with opener.open(request, timeout=600 if 'generate' in path else 180) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                raise RuntimeError(path+': '+error.read(8000).decode('utf-8','replace')) from error
        for asset in ('production.js','production.css','production_v2.js','text_workspace.js','cut_geometry.js','cut_validation.js','cut_workspace.js','cut_composition.js','cut_studio.js','cut_script.js'):
            assert opener.open(base+'/ui/'+asset).status == 200
        tts_verified=[]
        if args.tts_inference:
            assert args.tts_component, '必须明确指定独立组件'
            component = args.tts_component.resolve()
            assert not component.is_relative_to(args.exe.resolve().parent)
            api('/api/localtts/component-select', {'root':str(component)})
            import socket
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));tts_port=sock.getsockname()[1]
            voices=api('/api/localtts/voices')['items']
            for name,language,text,steps in [('绫地宁宁','en','Hello.',16),('因幡巡','zh','你好。再见。',32)]:
                voice=next(v for v in voices if v['name']==name and v['ready'])
                config=api('/api/localtts/voice-select',{'id':voice['id']})
                assert all(Path(config[k]).is_relative_to(component) for k in ('serviceRoot','gpt','sovits','reference'))
                config.update(endpoint=f'http://127.0.0.1:{tts_port}',textLanguage=language,sampleSteps=steps,speed=.9,fragmentInterval=.7)
                api('/api/localtts/settings',config)
                take=api('/api/localtts/generate',{'text':text,'name':name+'冻结版配音验收'})
                assert take['duration']>0
                with wave.open(str(data/'LocalTTS/takes'/(take['id']+'.wav')),'rb') as wav:
                    assert wav.getnframes()>0
                tts_verified.append({'name':name,'language':language,'duration':take['duration'],'sampleSteps':steps,'speed':.9,'fragmentInterval':.7})
        item = api('/api/backgrounds/import', {'paths':[str(source)]})['results'][0]['item']
        actor_id = person['id']
        assert api('/api/roughcut/sprites')['total'] == 2
        if args.draft_directory:
            api('/api/roughcut/options', {'draftDirectory':args.draft_directory})
        project = {'name':'十秒粗剪验证', 'scenes':[
            {'background':item['id'],'duration':4,'actors':[{'id':actor_id,'slot':0,'x':0,'height':.9}]},
            {'background':item['id'],'duration':3,'actors':[{'id':actor_id,'slot':0,'x':-.45,'height':.9}]},
            {'background':item['id'],'duration':3,'actors':[{'id':actor_id,'slot':1,'x':.45,'height':.9}]},
        ]}
        result = api('/api/roughcut/export', project)
        folder = Path(result['path'])
        content = json.loads((folder/'draft_content.json').read_text(encoding='utf-8'))
        assert content['duration'] == 10_000_000
        assert [len(t['segments']) for t in content['tracks']] == [3, 2, 1]
        assert all(Path(v['path']).is_file() for v in content['materials']['videos'])
        restored = api('/api/roughcut/project?id='+result['project']['id'])
        assert restored['name'] == project['name'] and len(restored['scenes']) == 3
        #Exercise expression alignment, presets and sentence generation inside the frozen app.
        group=api('/api/composition/group-suggest',{'ids':[actor_id,other['id']]})
        group=api('/api/composition/group-save',group)
        voice_path=root/'full-voice.wav'
        with wave.open(str(voice_path),'wb') as wav:
            wav.setparams((1,2,8000,0,'NONE','not compressed'));wav.writeframes(bytes(32592))
        voice=api('/api/audio/import',{'paths':[str(voice_path)]})['results'][0]['item']
        transform=dict(scaleX=170,scaleY=170,x=90,y=-280,rotation=0,uniform=True)
        base_scene=dict(background=item['id'],duration=10,actors=[dict(id=actor_id,slot=0,alignment=group['members'][0],transform=transform)])
        preset=api('/api/composition/preset-save',dict(name='Frozen landscape',width=1920,height=1080,scene=base_scene))
        assert api('/api/composition/preset-apply',dict(id=preset['id'],width=1280,height=720))['actors'][0]['transform']['x']==60
        rows=[dict(id='1',kind='narrator',text='放学后，教室里只剩下我们。',hold=1),
              dict(id='2',kind='heroine',text='Hello, welcome back.',audio=voice['id'],pause=.5,
                   expression=dict(id=other['id'],slot=0,alignment=group['members'][1])),
              dict(id='3',kind='inner',text='他竟然还记得我。\n希望他没有发现。',audio=voice['id']),
              dict(id='4',kind='hero',text='Thanks.',hold=1.5)]
        generated=api('/api/roughcut/build-script',dict(name='中英台词测试',fps=30,scenes=[base_scene],reviewed=True,scriptPlan=dict(rows=rows,gap=.3)))
        scripted=generated['project'];assert len(scripted['scenes'])==4 and len(scripted['textClips'])==4
        assert all(c['duration']==2.037 and c['sourceStart']==0 for c in scripted['audioClips'])
        scripted_export=api('/api/roughcut/export',scripted)
        script_restored=api('/api/roughcut/project?id='+scripted_export['project']['id'])
        assert script_restored['scriptPlan']==scripted['scriptPlan']
        script_content=json.loads((Path(scripted_export['path'])/'draft_content.json').read_text('utf-8'))
        assert all(Path(v['path']).is_file() for v in script_content['materials']['videos']+script_content['materials']['audios'])
        ui_verified=False
        if args.ui_smoke:
            subprocess.run(['node',str(Path(__file__).parent.parent/'tests/ui_cut_script_smoke.cjs'),base+'/',str(root/'ui-qa'),str(voice_path)],check=True,timeout=180,creationflags=0x08000000)
            ui_verified=True
        entry_verified = False
        if args.draft_entry_ui:
            subprocess.run(['node', str(Path(__file__).parent.parent/'tests/ui_draft_workflow_smoke.cjs'), base+'/', str(root/'draft-entry-ui'), '--entry-only'], check=True, timeout=180, creationflags=0x08000000)
            entry_verified = True
        video_verified = False
        ffmpeg = shutil.which('ffmpeg')
        if ffmpeg:
            video = root / 'test-video.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=30',
                            '-t', '2', '-pix_fmt', 'yuv420p', '-y', str(video)], check=True,
                           capture_output=True, creationflags=0x08000000)
            video_item = api('/api/backgrounds/import', {'paths':[str(video)]})['results'][0]['item']
            api('/api/roughcut/options', {'draftDirectory':''})
            video_result = api('/api/roughcut/export', {'name':'冻结版视频循环验证','scenes':[
                {'background':video_item['id'],'duration':5,'loop':True,'actors':[]}]})
            video_content = json.loads((Path(video_result['path'])/'draft_content.json').read_text(encoding='utf-8'))
            assert video_content['duration'] == 5_000_000
            assert len(video_content['tracks'][0]['segments']) == 3
            video_verified = True
        assert api('/api/picker/open', {})['ok']
        ready = False
        for _ in range(120):
            log = data / 'topmost.log'
            log_text = log.read_text(encoding='utf-8', errors='replace') if log.is_file() else ''
            if 'PET_INIT_FAILED' in log_text:
                raise RuntimeError(log_text)
            ready = any('PET_READY hwnd=' in line and 'visible=True' in line
                        for line in log_text.splitlines())
            if ready:
                break
            time.sleep(.5)
        assert ready, '桌宠没有完成窗口加载'
        report = {'success':True, 'exe':str(args.exe.resolve()),'draft':result['path'],
                  'duration':10,'tracks':[t['name'] for t in content['tracks']],
                  'isolatedData':str(data),'videoVerified':video_verified,
                  'petWindowReady':ready,'scriptedDraft':scripted_export['path'],
                  'sentencePlanVerified':True,'frozenBrowserUI':ui_verified,'ordinaryDraftEntryUI':entry_verified,'jianyingOpened':False}
        report['externalTTS']=tts_verified
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        #The test owns this executable directory; other installations are excluded by path.
        kill_test_processes(args.exe.resolve().parent)


if __name__ == '__main__':
    main()
