"""Local expression groups and aspect-specific composition presets."""
from __future__ import annotations
import copy
import json
import math
import threading
import uuid
from PIL import Image
from rough_cut import atomic_json, number
from cut_geometry import normalize_transform


def alignment(value):
    if not isinstance(value, dict):
        raise ValueError('表情对齐参数格式不正确')
    result = {k: number(value.get(k, default), label, low, high) for k,default,label,low,high in (
        ('width',0,'组画布宽度',1,20000),('height',0,'组画布高度',1,20000),
        ('left',0,'图片偏移 X',-20000,20000),('top',0,'图片偏移 Y',-20000,20000),
        ('scale',1,'素材校准比例',.05,20))}
    if result['width'] != int(result['width']) or result['height'] != int(result['height']):
        raise ValueError('组画布宽高必须是整数')
    result['width'],result['height']=int(result['width']),int(result['height'])
    if result['width']*result['height'] > 40_000_000:
        raise ValueError('表情组画布超过四千万像素')
    result['groupId']=str(value.get('groupId',''))[:32]
    result['version']=str(value.get('version',''))[:32]
    return result


def render_aligned(source, placement):
    p=alignment(placement)
    with Image.open(source) as image:
        image=image.convert('RGBA')
        #Inverse mapping into a fixed canvas avoids giant intermediate images.
        return image.transform((p['width'],p['height']),Image.Transform.AFFINE,
            (1/p['scale'],0,-p['left']/p['scale'],0,1/p['scale'],-p['top']/p['scale']),
            resample=Image.Resampling.BICUBIC)


def ratio(width,height):
    divisor=math.gcd(int(width),int(height))
    return f'{int(width)//divisor}:{int(height)//divisor}'


class CompositionLibrary:
    def __init__(self,root,sprites,recover=None):
        self.root=root; self.sprites=sprites; self.recover=recover
        self.lock=threading.RLock()

    def read(self,kind):
        path=self.root/(kind+'.json')
        return json.loads(path.read_text('utf-8')) if path.is_file() else []

    def list(self):
        with self.lock:
            return {'groups':self.read('expression-groups'),'presets':self.read('composition-presets')}

    def item(self,item_id):
        item=self.sprites.metadata(item_id)
        if item is None or not self.sprites.file(item_id,False):
            raise ValueError('表情素材丢失、已删除或不在普通立绘库')
        return item

    def suggest(self,ids):
        if (not isinstance(ids,list) or not 2<=len(ids)<=100
                or not all(isinstance(i,str) and i for i in ids) or len(set(ids))!=len(ids)):
            raise ValueError('请选择 2–100 张同姿势表情')
        items=[self.item(i) for i in dict.fromkeys(ids)]
        identities={(i['game'],i['character'],i['body']) for i in items}
        if len(identities)!=1:
            raise ValueError('表情组需要同一作品、角色和姿势；不同姿势请分别建组')
        placements=[]
        for item in items:
            geometry=item.get('sourceGeometry')
            if not geometry and self.recover:
                geometry=self.recover(item)
            if geometry:
                p=alignment(dict(geometry,scale=1));mode='原始坐标'
            else:
                p=dict(width=item['width'],height=item['height'],left=0,top=0,scale=1)
                mode='PNG画布（请核对）'
            placements.append(dict(id=item['id'],name=item['displayName'] or item['face'],mode=mode,**p))
        width=max(p['width'] for p in placements);height=max(p['height'] for p in placements)
        return dict(name=items[0]['character']+' · '+items[0]['body'],width=width,height=height,members=placements)

    def save_group(self,payload):
        name=str(payload.get('name','')).strip()[:100]
        members=payload.get('members')
        if not name or not isinstance(members,list) or not 2<=len(members)<=100:
            raise ValueError('请填写组名，并选择 2–100 个表情')
        if not all(isinstance(m,dict) for m in members):
            raise ValueError('表情成员格式不正确')
        self.suggest([m.get('id') for m in members])
        group_id=str(payload.get('id') or uuid.uuid4().hex)
        if len(group_id)!=32 or any(c not in '0123456789abcdef' for c in group_id):
            raise ValueError('表情组编号不正确')
        version=uuid.uuid4().hex
        clean=[]
        for m in members:
            p=alignment(dict(m,width=payload.get('width'),height=payload.get('height'),groupId=group_id,version=version))
            clean.append(dict(id=m['id'],name=str(m.get('name',''))[:100],mode=str(m.get('mode','人工校准'))[:40],**p))
        result=dict(id=group_id,version=version,name=name,width=clean[0]['width'],height=clean[0]['height'],members=clean)
        with self.lock:
            groups=self.read('expression-groups')
            if payload.get('id') and not any(g['id']==group_id for g in groups):
                raise ValueError('表情组不存在')
            groups=[g for g in groups if g['id']!=group_id]+[result]
            atomic_json(self.root/'expression-groups.json',groups)
        return result

    def save_preset(self,payload):
        name=str(payload.get('name','')).strip()[:100]
        width=int(number(payload.get('width'), '画布宽度',320,3840))
        height=int(number(payload.get('height'), '画布高度',320,3840))
        scene=payload.get('scene')
        if not name or not isinstance(scene,dict):
            raise ValueError('请填写预设名称并选定镜头')
        fallback=dict(scaleX=100,scaleY=100,x=0,y=0,rotation=0,uniform=True)
        bg=normalize_transform(scene.get('backgroundTransform'),fallback,number,width,height)
        actors=scene.get('actors',[])
        if not isinstance(actors,list) or len(actors)>2:
            raise ValueError('构图预设最多两个角色')
        clean=[]
        for actor in actors:
            self.item(actor.get('id'))
            a=dict(id=actor['id'],slot=int(number(actor.get('slot',0),'角色槽位',0,1)),
                x=actor.get('x',0),height=actor.get('height',.9),
                transform=normalize_transform(actor.get('transform'),fallback,number,width,height))
            if 'alignment' in actor:a['alignment']=alignment(actor['alignment'])
            if any(i['slot']==a['slot'] for i in clean):raise ValueError('角色槽位重复')
            clean.append(a)
        result=dict(id=uuid.uuid4().hex,name=name,width=width,height=height,ratio=ratio(width,height),
                    backgroundTransform=bg,actors=clean)
        with self.lock:
            presets=self.read('composition-presets')
            atomic_json(self.root/'composition-presets.json',presets+[result])
        return result

    def apply_preset(self,payload):
        with self.lock:
            preset=next((p for p in self.read('composition-presets') if p['id']==payload.get('id')),None)
        if preset is None:raise ValueError('构图预设不存在')
        w=int(number(payload.get('width'),'画布宽度',320,3840));h=int(number(payload.get('height'),'画布高度',320,3840))
        if ratio(w,h)!=preset['ratio']:raise ValueError('预设画幅不匹配，请切换画幅或选择对应预设')
        result=copy.deepcopy(preset)
        for t in [result['backgroundTransform']]+[a['transform'] for a in result['actors']]:
            t['x']*=w/preset['width'];t['y']*=h/preset['height']
        for a in result['actors']:self.item(a['id'])
        return result

    def rename_preset(self,payload):
        name=str(payload.get('name','')).strip()[:100]
        if not name:raise ValueError('请输入预设名称')
        with self.lock:
            presets=self.read('composition-presets')
            p=next((p for p in presets if p['id']==payload.get('id')),None)
            if p is None:raise ValueError('构图预设不存在')
            p['name']=name;atomic_json(self.root/'composition-presets.json',presets)
        return p

    def delete_preset(self,item_id):
        with self.lock:
            presets=self.read('composition-presets')
            atomic_json(self.root/'composition-presets.json',[p for p in presets if p['id']!=item_id])
