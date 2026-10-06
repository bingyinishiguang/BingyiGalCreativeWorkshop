"""Local GPT-SoVITS api_v2 inference; immutable takes, no training."""
from __future__ import annotations

import hashlib
import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import subprocess
import os
import time
import atexit
from datetime import datetime, timezone
from pathlib import Path

from rough_cut import atomic_json

DEFAULT_ROOT = ''
MAX_AUDIO = 50_000_000


def endpoint(value):
    url = urllib.parse.urlsplit(str(value).strip())
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
            or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError('请填写本机 API 服务地址，例如 http://127.0.0.1:9880')
    try:
        url.port
    except ValueError:
        raise ValueError('API 端口格式不正确') from None
    return str(value).strip().rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('本地配音服务发生重定向，请检查 API 地址')


class LocalTTS:
    def __init__(self, root, library):
        self.root, self.library = Path(root).resolve(), library
        self.root.mkdir(parents=True, exist_ok=True)
        self.records = self.root/'takes'
        self.records.mkdir(exist_ok=True)
        self.config = self.root/'preset.json'
        from tts_bundle import Component
        self.component = Component(self.root/'component-location.json')
        self.service_lease = None
        self.process_endpoint = None
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(NoRedirect())
        self.process = None
        self.process_device = None
        self.idle_timer = None
        self.last_used = time.monotonic()
        atexit.register(self.close)
        from voice_catalog import VoiceCatalog
        self.voices=VoiceCatalog(self.root.parent/'音色库',self)
        if not self.config.exists():
            ready=next((v for v in self.voices.items if v['ready']),None)
            if ready:self.save(ready['preset'])

    def resolve_resource(self, value):
        from tts_bundle import resolve
        return resolve(value, self.component.root())

    def component_status(self):
        result = self.component.status()
        result['serviceState'] = ('loading-or-running' if self.process is not None and self.process.poll() is None else 'stopped')
        return result

    def select_component(self, root=None):
        if not self.lock.acquire(blocking=False):
            raise ValueError('正在生成配音，请完成后再切换组件')
        try:
            if root:
                self.component.inspect(root)
                self.close()
                self.component.select(root)
                from tts_bundle import seed_voices
                seed_voices(self.voices.root, self.component.root())
                self.voices.scan()
                if not self.config.exists():
                    ready = next((v for v in self.voices.items if v['ready']), None)
                    if ready:self.save(ready['preset'])
            else:
                self.close()
                self.component.disconnect()
            return self.component_status()
        finally:self.lock.release()

    def claim_service(self, base):
        """Hold an OS lock for this loopback port; a crashed owner releases it."""
        if self.service_lease is not None:return
        import tempfile
        port = urllib.parse.urlsplit(endpoint(base)).port or 80
        path = Path(tempfile.gettempdir()) / ('bingyi-tts-port-' + str(port) + '.lock')
        stream = path.open('a+b')
        if stream.tell() == 0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise ValueError('另一个软件窗口正在使用此配音端口，请关闭该窗口或更换端口') from None
        self.service_lease = stream

    def request_start(self, payload):
        if not self.lock.acquire(blocking=False):
            raise ValueError('正在生成配音，请完成后再启动或切换服务')
        try:
            config=self.save({'device':payload['device']}) if 'device' in payload else None
            return self.start(config)
        finally:self.lock.release()

    def start(self, config=None):
        """Start a dedicated inference instance with a separate writable config."""
        config=config or self.settings()
        if config.get('serviceMode') == 'external':
            self.test(config['endpoint'])
            return {'message':'已连接你指定的外部服务；软件不会停止该服务。'}
        if self.process is not None and self.process.poll() is None and (self.process_device!=config.get('device','cpu') or self.process_endpoint!=config['endpoint']):
            self.close()
        base=urllib.parse.urlsplit(endpoint(config['endpoint']))
        if self.process is not None and self.process.poll() is None:
            return {'message':'推理服务正在运行或启动中，请测试连接。'}
        try:
            self.probe(config['endpoint'])
            raise ValueError('此端口已有其他推理服务；请更换端口，或明确选择连接外部服务')
        except ConnectionError:
            pass
        folder=Path(config['serviceRoot']).resolve()
        runtime=folder/'runtime/python.exe';script=folder/'api_v2.py'
        if not runtime.is_file() or not script.is_file():
            raise ValueError('请先选择完整的外置配音组件；缺少 runtime/python.exe 或 api_v2.py。历史音频仍可使用')
        custom=dict(version='v4',device='cpu',is_half=False,
                    bert_base_path='GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large',
                    cnhuhbert_base_path='GPT_SoVITS/pretrained_models/chinese-hubert-base',
                    t2s_weights_path=config['gpt'],vits_weights_path=config['sovits'])
        for key in ('bert_base_path','cnhuhbert_base_path'):
            custom[key]=str((folder/custom[key]).resolve())
        for key in ('t2s_weights_path','vits_weights_path'):
            if not custom[key] or not Path(custom[key]).is_file():
                raise ValueError('请先选择有效的模型对，再启动推理服务')
        inference=self.root/'inference.yaml'
        #JSON is valid YAML, so the adapter needs no additional YAML dependency.
        atomic_json(inference,{'custom':custom})
        self.close()
        self.claim_service(config['endpoint'])
        log=(self.root/'service.log').open('ab')
        try:
            #Select acceleration on the target machine, not the author's GPU.
            guard="import ctypes,threading,os; k=ctypes.windll.kernel32; k.OpenProcess.restype=ctypes.c_void_p; k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]; h=k.OpenProcess(0x100000,False,int(sys.argv.pop(1))); h and threading.Thread(target=lambda:(k.WaitForSingleObject(h,0xffffffff),os._exit(0)),daemon=True).start(); "
            bootstrap="import sys; "+guard+"import json,runpy; ext=os.environ.get('BINGYI_TTS_ACCELERATION'); ext and sys.path.insert(0,ext); import torch; torch.set_num_threads(max(1,min(4,os.cpu_count() or 1))); p=sys.argv[1]; c=json.load(open(p,encoding='utf-8')); requested=os.environ.get('BINGYI_TTS_DEVICE','cpu'); gpu=requested=='cuda' and torch.cuda.is_available(); assert requested!='cuda' or gpu,'GPU acceleration is unavailable'; c['custom'].update(device='cuda' if gpu else 'cpu',is_half=gpu); json.dump(c,open(p,'w',encoding='utf-8')); sys.argv=sys.argv[2:]; from pathlib import Path; sys.path.insert(0,str(Path(sys.argv[0]).parent/'GPT_SoVITS')); runpy.run_path(sys.argv[0],run_name='__main__')"
            env=os.environ.copy()
            env.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',NLTK_DATA=str(folder/'runtime/nltk_data'),MPLCONFIGDIR=str(self.root/'matplotlib'))
            env['BINGYI_TTS_DEVICE']=config.get('device','cpu')
            extension=self.component.root()/'tts_acceleration/site-packages'
            if config.get('device')=='cuda' and extension.is_dir():env['BINGYI_TTS_ACCELERATION']=str(extension)
            else:env.pop('BINGYI_TTS_ACCELERATION',None)
            env['PATH']=str(folder/'bin')+os.pathsep+str(folder/'runtime')+os.pathsep+env.get('PATH','')
            self.process=subprocess.Popen([str(runtime),'-c',bootstrap,str(os.getpid()),str(inference.resolve()),str(script),'-a',base.hostname,'-p',str(base.port or 80),'-c',str(inference.resolve())],
                cwd=folder,stdout=log,stderr=subprocess.STDOUT,
                env=env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:
            self.close()
            raise
        finally:
            log.close()
        self.arm_idle()
        self.process_device=config.get('device','cpu')
        self.process_endpoint=config['endpoint']
        return {'message':'已启动本机推理服务，首次加载模型可能需要数分钟，请稍后测试连接。'}

    def close(self):
        if self.idle_timer is not None:self.idle_timer.cancel()
        proc=self.process
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill()
        if self.service_lease is not None:
            self.service_lease.close();self.service_lease=None

    def arm_idle(self):
        self.last_used=time.monotonic()
        if self.idle_timer is not None:self.idle_timer.cancel()
        if self.process is not None and self.process.poll() is None:
            self.idle_timer=threading.Timer(300,self.release_idle)
            self.idle_timer.daemon=True;self.idle_timer.start()

    def release_idle(self):
        if not self.lock.acquire(blocking=False):
            self.arm_idle();return
        try:
            if time.monotonic()-self.last_used>=299:self.close()
        finally:self.lock.release()

    def settings(self):
        value=json.loads(self.config.read_text('utf-8')) if self.config.is_file() else dict(
            name='女主声音', character='', serviceRoot=DEFAULT_ROOT,
            endpoint='http://127.0.0.1:9880', gpt='', sovits='', reference='',
            prompt='', promptLanguage='zh', textLanguage='zh', speed=1.0)
        for key in ('serviceRoot','gpt','sovits','reference'):
            value[key]=self.resolve_resource(value[key])
        value.setdefault('device','cpu')
        value.setdefault('serviceMode','managed')
        value.setdefault('sampleSteps',32)
        value.setdefault('fragmentInterval',.3)
        if not self.config.exists() and (self.component.root()/'service/api_v2.py').is_file():
            value['serviceRoot']=str(self.component.root()/'service')
        return value

    def select_voice(self,voice_id):
        item=self.voices.get(voice_id)
        return self.save(item['preset'])

    def save(self, payload):
        value=self.validate(payload)
        from tts_bundle import portable
        atomic_json(self.config,{k:portable(v,self.component.root()) if k in ('serviceRoot','gpt','sovits','reference') and v else v for k,v in value.items()})
        return value

    def validate(self, payload):
        value = self.settings()
        for key in ('name','character','serviceRoot','gpt','sovits','reference','prompt'):
            value[key] = str(payload.get(key, value[key])).strip()
            if len(value[key]) > (2000 if key == 'prompt' else 1000):
                raise ValueError('声音预设字段过长')
        if not value['name']:
            raise ValueError('请填写声音预设名称')
        value['endpoint'] = endpoint(payload.get('endpoint', value['endpoint']))
        for key in ('promptLanguage','textLanguage'):
            value[key] = str(payload.get(key,value[key]))
            if value[key] not in ('zh','en','ja','ko','yue','auto','all_zh','all_ja','all_ko','all_yue'):
                raise ValueError('语言设置不正确')
        try:
            speed=float(payload.get('speed',value['speed']))
        except (ValueError,TypeError):
            raise ValueError('语速格式不正确') from None
        if not math.isfinite(speed) or not .5 <= speed <= 2:
            raise ValueError('语速范围为 0.5—2')
        value['speed']=speed
        steps=payload.get('sampleSteps',value['sampleSteps'])
        if isinstance(steps,bool) or str(steps) not in ('16','32'):
            raise ValueError('采样步数只能选择 16 或 32')
        value['sampleSteps']=int(steps)
        try:interval=float(payload.get('fragmentInterval',value['fragmentInterval']))
        except (ValueError,TypeError):raise ValueError('句间停顿格式不正确') from None
        if not math.isfinite(interval) or not 0 <= interval <= 3:
            raise ValueError('句间停顿范围为 0—3 秒')
        value['fragmentInterval']=interval
        value['device']=str(payload.get('device',value.get('device','cpu')))
        if value['device'] not in ('cpu','cuda'):raise ValueError('请选择 CPU 或 GPU 加速')
        value['serviceMode']=str(payload.get('serviceMode',value.get('serviceMode','managed')))
        if value['serviceMode'] not in ('managed','external'):raise ValueError('请选择专用推理或明确连接外部服务')
        return value

    def devices(self):
        folder=Path(self.settings()['serviceRoot'])
        runtime=folder/'runtime/python.exe'
        if not runtime.is_file():return {'gpu':False,'message':'配音运行环境尚未安装，默认使用 CPU。'}
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        extension=self.component.root()/'tts_acceleration/site-packages'
        code="import sys,json,torch; ok=torch.cuda.is_available(); name='';\nif ok:\n try: torch.ones(1,device='cuda'); name=torch.cuda.get_device_name(0)\n except Exception: ok=False\nprint(json.dumps({'gpu':ok,'name':name,'cudaBuild':torch.version.cuda}))"
        if extension.is_dir():code="import sys;sys.path.insert(0,"+repr(str(extension))+");"+code
        try:
            result=subprocess.run([str(runtime),'-c',code],env=env,cwd=folder,capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            data=json.loads(result.stdout.decode('utf-8').strip().splitlines()[-1])
            data['message']='检测到可用 GPU：'+data.get('name','')+'，可选择加速配音。' if data['gpu'] else '当前运行环境不支持 GPU 加速，CPU 配音可用。可选安装匹配的 GPU 扩展包。'
            return data
        except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):return {'gpu':False,'message':'GPU 检测未通过，继续使用 CPU 配音。'}

    def models(self, root=None):
        folder=Path(root or self.settings()['serviceRoot'])
        if not folder.is_dir():
            raise ValueError('GPT-SoVITS 软件目录不存在')
        result={'gpt':[], 'sovits':[]}
        for key,prefix,suffix in [('gpt','GPT_weights','.ckpt'),('sovits','SoVITS_weights','.pth')]:
            for directory in sorted(folder.glob(prefix+'*')):
                if directory.is_dir():
                    result[key].extend(str(p.resolve()) for p in sorted(directory.glob('*'+suffix)) if p.is_file())
        return result

    def call(self, base, route, payload=None, limit=1_000_000):
        request=urllib.request.Request(base+route,
            data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type':'application/json'} if payload is not None else {})
        try:
            with self.opener.open(request,timeout=600 if route=='/tts' else 120) as response:
                data=response.read(limit+1)
                if len(data)>limit:raise ValueError('配音服务返回内容过大')
                return data
        except urllib.error.HTTPError as error:
            raw=error.read(8000)
            try:
                message=json.loads(raw).get('message','推理请求失败')
            except (ValueError,AttributeError):message='推理请求失败'
            raise ValueError(f'GPT-SoVITS：{str(message)[:200]}') from None
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError):
            raise ValueError('配音服务尚未连接；生成时会自动启动并等待模型加载，旧音频已保留') from None

    def probe(self, base):
        try:
            with self.opener.open(base+'/openapi.json',timeout=3) as response:
                spec=json.loads(response.read(1_000_001))
            if not isinstance(spec,dict) or not all(p in spec.get('paths',{}) for p in ('/tts','/set_gpt_weights','/set_sovits_weights')):
                raise ValueError('端口已被其他服务占用，请在配音设置中更换端口')
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as error:
            raise ConnectionError('配音服务尚未就绪') from error

    def ensure_ready(self, config):
        if config.get('serviceMode') == 'external':
            self.close()  #Only an instance we started can be stopped here.
            self.claim_service(config['endpoint'])
            self.test(config['endpoint']);return
        self.start(config)
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            if self.process is not None and self.process.poll() is not None:
                raise ValueError('推理服务启动失败，请查看配音服务日志：'+str(self.root/'service.log'))
            try:
                self.probe(config['endpoint'])
                return
            except ConnectionError:
                time.sleep(1)
        raise ValueError('模型仍在加载，请稍后重试；旧音频已保留。服务日志：'+str(self.root/'service.log'))

    def test(self, base=None):
        base=endpoint(base or self.settings()['endpoint'])
        try:
            spec=json.loads(self.call(base,'/openapi.json'))
        except (ValueError,UnicodeError) as error:
            raise ValueError(str(error)) from None
        if not isinstance(spec,dict):
            raise ValueError('服务返回的接口说明不正确，请核对 api_v2 地址')
        paths=spec.get('paths',{})
        if not all(p in paths for p in ('/tts','/set_gpt_weights','/set_sovits_weights')):
            raise ValueError('该服务不是支持模型切换的 GPT-SoVITS api_v2，请检查启动入口')
        return {'ok':True,'message':'已连接 api_v2；连接测试未生成音频、未切换模型'}

    @staticmethod
    def digest(path):
        sha=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):sha.update(chunk)
        return sha.hexdigest()

    def generate(self, payload, preset=None):
        text=str(payload.get('text','')).strip()
        if not 1 <= len(text) <= 1000:raise ValueError('请输入 1—1000 字配音台词')
        if not self.lock.acquire(blocking=False):
            raise ValueError('本机正在生成配音，请等待当前任务完成')
        target=None
        try:
            config=self.validate(preset) if preset is not None else self.settings()
            base=endpoint(config['endpoint'])
            files={}
            for key,label,suffix in [('gpt','GPT 模型',{'.ckpt'}),('sovits','SoVITS 模型',{'.pth'}),
                                     ('reference','参考音频',{'.wav','.mp3','.flac','.ogg','.m4a'})]:
                path=Path(config[key])
                if not config[key] or not path.is_file() or path.suffix.lower() not in suffix:
                    raise ValueError(f'请在声音预设中选择有效的{label}')
                files[key]=path.resolve()
            if not config['prompt']:raise ValueError('请填写参考音频实际说出的台词')
            self.ensure_ready(config)
            fingerprint={key:self.digest(path) for key,path in files.items()}
            for key,route in [('gpt','/set_gpt_weights'),('sovits','/set_sovits_weights')]:
                raw=self.call(base,route+'?'+urllib.parse.urlencode({'weights_path':str(files[key])}))
                result=json.loads(raw)
                if not isinstance(result,dict) or result.get('message')!='success':
                    raise ValueError('模型切换未成功，请检查训练模型与推理版本')
            request=dict(text=text,text_lang=config['textLanguage'],ref_audio_path=str(files['reference']),
                         prompt_text=config['prompt'],prompt_lang=config['promptLanguage'],
                         speed_factor=config['speed'],sample_steps=config['sampleSteps'],fragment_interval=config['fragmentInterval'],text_split_method='cut5',batch_size=1,
                         media_type='wav',streaming_mode=False,seed=-1)
            audio=self.call(base,'/tts',request,MAX_AUDIO)
            take_id=uuid.uuid4().hex;target=self.records/(take_id+'.wav')
            target.write_bytes(audio)
            try:
                with wave.open(str(target),'rb') as wav:
                    duration=wav.getnframes()/wav.getframerate()
                    if duration<=0 or wav.getsampwidth() not in (1,2,3,4):raise ValueError('音频无有效内容')
            except (wave.Error,EOFError):
                raise ValueError('推理服务没有返回有效的完整 WAV 音频') from None
            imported=self.library.import_file(target);item=imported['item']
            name=str(payload.get('name') or text[:25]).strip()[:100]
            if not imported['duplicate']:
                item=self.library.update({'id':item['id'],'name':name,'text':text,'character':config['character']})
            record=dict(id=take_id,audioId=item['id'],name=name,text=text,character=config['character'],
                        duration=duration,created=datetime.now(timezone.utc).isoformat(),
                        preset=config,fingerprints=fingerprint,audioHash=self.digest(target),
                        filename=target.name)
            atomic_json(self.records/(take_id+'.json'),record)
            target=None
            return record
        finally:
            if target is not None:target.unlink(missing_ok=True)
            self.lock.release()
            self.arm_idle()
            if self.process is None or self.process.poll() is not None:
                if self.service_lease is not None:
                    self.service_lease.close();self.service_lease=None

    def history(self):
        items=[json.loads(p.read_text('utf-8')) for p in self.records.glob('*.json')]
        return {'items':sorted(items,key=lambda r:r['created'],reverse=True)}

    def file(self, take_id):
        if not isinstance(take_id,str) or len(take_id)!=32 or any(c not in '0123456789abcdef' for c in take_id):
            raise ValueError('配音版本编号不正确')
        path=self.records/(take_id+'.wav')
        if not (self.records/(take_id+'.json')).is_file() or not path.is_file():
            raise ValueError('配音文件不存在')
        return path
