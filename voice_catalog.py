"""User-authored voice folders; scanning never loads or executes model weights."""
import json
import re
import threading
import uuid
from pathlib import Path
from subtitle_tools import read_text

EXAMPLE={'id':'your_character','name':'填写中文角色名','work':'填写作品名',
         'gpt':'model.ckpt','sovits':'model.pth','reference':'reference.wav',
         'promptFile':'参考台词.txt','promptLanguage':'ja','textLanguage':'zh','speed':1.0}

class VoiceCatalog:
    def __init__(self,root,tts):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.tts=tts;self.lock=threading.RLock()
        from tts_bundle import seed_voices
        seed_voices(self.root,self.tts.component.root())
        example=self.root/'新音色填写示例.json'
        if not example.exists():example.write_text(json.dumps(EXAMPLE,ensure_ascii=False,indent=2),encoding='utf-8')
        self.scan()

    def scan(self):
        with self.lock:
            items=[];errors=[];seen={};duplicate=set()
            paths=sorted(self.root.glob('*/voice.json'))
            if len(paths)>200:errors.append({'file':str(self.root),'message':'音色文件夹超过二百个，仅扫描前二百个'})
            for path in paths[:200]:
                try:
                    if path.stat().st_size>64_000:raise ValueError('音色配置超过 64 KB')
                    raw=json.loads(path.read_text('utf-8-sig'))
                    if not isinstance(raw,dict):raise ValueError('配置必须是 JSON 对象')
                    key=raw.get('id',path.parent.name)
                    if not isinstance(key,str) or not re.fullmatch(r'[\w-]{1,64}',key):raise ValueError('id 只允许字母、数字、中文、下划线或短横线，最多六十四字')
                    name=raw.get('name','');work=raw.get('work','')
                    if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('请填写不超过一百字的音色 name')
                    if not isinstance(work,str) or len(work)>100:raise ValueError('作品名 work 最多一百字')
                    stable=uuid.uuid5(uuid.NAMESPACE_URL,'bingyi-voice:'+key).hex
                    if stable in seen:
                        duplicate.add(stable);raise ValueError('音色 id 重复，请为每个音色填写不同的 id')
                    seen[stable]=path
                    config=dict(name=name.strip(),character=name.strip())
                    for field,suffix in [('gpt',{'.ckpt'}),('sovits',{'.pth'}),('reference',{'.wav','.mp3','.flac','.ogg','.m4a'})]:
                        value=raw.get(field,'')
                        if not isinstance(value,str) or not value.strip():raise ValueError('请填写 '+field+' 文件路径')
                        resolve=self.tts.resolve_resource
                        target=Path(resolve(value))
                        if not target.is_absolute():target=path.parent/target
                        target=target.resolve()
                        if target.suffix.lower() not in suffix:raise ValueError(field+' 文件扩展名不正确')
                        config[field]=str(target)
                    for field in ('serviceRoot','endpoint','promptLanguage','textLanguage','speed','sampleSteps','fragmentInterval'):
                        if field in raw:config[field]=resolve(raw[field]) if field=='serviceRoot' else raw[field]
                    if raw.get('promptFile'):
                        if not isinstance(raw['promptFile'],str):raise ValueError('promptFile 必须是参考台词文件路径')
                        prompt=Path(resolve(raw['promptFile']));prompt=prompt if prompt.is_absolute() else path.parent/prompt
                        if not prompt.is_file() or prompt.stat().st_size>16_000:raise ValueError('参考台词文件丢失或超过 16 KB')
                        config['prompt']=read_text(prompt).strip()
                    else:config['prompt']=str(raw.get('prompt','')).strip()
                    if not config['prompt']:raise ValueError('请填写参考台词 prompt 或 promptFile')
                    config=self.tts.validate(config)
                    missing=[k for k in ('gpt','sovits','reference') if not Path(config[k]).is_file()]
                    items.append(dict(id=stable,key=key,name=config['name'],work=work.strip(),preset=config,
                                      file=str(path),ready=not missing,message='已就绪' if not missing else '文件丢失：'+', '.join(missing)))
                except (OSError,ValueError,TypeError,UnicodeError) as error:
                    errors.append(dict(file=str(path),message=str(error)))
            for item in items:
                if item['id'] in duplicate:item.update(ready=False,message='音色 id 重复，请修改配置')
            self.items=items
            return dict(folder=str(self.root),items=items,errors=errors)

    def get(self,voice_id):
        data=self.scan();item=next((i for i in data['items'] if i['id']==voice_id),None)
        if not item:raise ValueError('音色配置未找到，请刷新音色库')
        if not item['ready']:raise ValueError(item['name']+'：'+item['message'])
        return item
