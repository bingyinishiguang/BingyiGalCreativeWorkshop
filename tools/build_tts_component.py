"""Reproducible CPU-only inference component. Never writes the user's voice catalog."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def build(source,out,original,version='1.0.0-cpu'):
    source=source.resolve();out=out.resolve();original=original.resolve()
    if not isinstance(version,str) or not 1<=len(version)<=100:raise ValueError('Invalid component version')
    if out.exists():raise ValueError('Output exists; choose a new version directory')
    if out==source or out.is_relative_to(source):raise ValueError('Output must be separate from source')
    if not (source/'service/runtime/python.exe').is_file():raise ValueError('CPU source runtime missing')
    out.mkdir(parents=True);removed=[];copied=[];source_bytes=0
    for folder,dirs,files in os.walk(source,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink() and not (Path(folder)/d).is_junction()
                 and not (Path(folder).relative_to(source).as_posix()=='service' and d=='工作数据')]
        for name in sorted(files):
            path=Path(folder)/name;relative=path.relative_to(source);size=path.stat().st_size;source_bytes+=size
            license_file=any(x in name.lower() for x in ('license','copying','notice'))
            reason=None
            if '__pycache__' in relative.parts or path.suffix.lower()=='.pyc':reason='bytecode-cache'
            elif not license_file and path.suffix.lower() in ('.lib','.pdb','.h','.hpp','.cpp','.c','.a','.ipynb'):reason='compile-only-or-notebook'
            elif relative.parts[:3]==('service','runtime','include'):reason='development-headers'
            elif relative.parts[:3]==('service','runtime','Scripts'):reason='development-cli'
            if reason:
                removed.append(dict(path=relative.as_posix(),bytes=size,reason=reason));continue
            target=out/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            copied.append(relative.as_posix())
    #Existing smaller tools were verified against the supported audio formats.
    replacements=[]
    for name in ('ffmpeg.exe','ffprobe.exe'):
        small=original/'service/runtime'/name;target=out/'service/bin'/name
        if small.is_file() and target.is_file() and small.stat().st_size<target.stat().st_size:
            replacements.append(dict(path='service/bin/'+name,before=target.stat().st_size,after=small.stat().st_size,sourceSha256=digest(small)))
            shutil.copy2(small,target)
    #Strip redundant silence/headers only through lossless archives; model weights
    #stay byte-for-byte identical, including original half-precision checkpoints.
    (out/'voices').mkdir(exist_ok=True)
    (out/'voices/README.txt').write_text('音色包请解压到组件根目录，保留 voices 目录结构。\n',encoding='utf-8')
    (out/'README.txt').write_text('冰翼外置CPU配音组件\n把组件解压到独立文件夹，在软件“语音配音”中选择此文件夹。\n音色包单独解压到同一个组件文件夹，保留 voices/ 目录结构，再刷新音色。\n移动组件后重新选择新位置；个人音色配置和已生成音频保存在主软件数据目录。\nCPU默认，采样步数16或32，默认32。GPU扩展另行提供。\n更新时解压到新文件夹，验证再切换；不要直接覆盖正在使用的组件。\n',encoding='utf-8')
    inventory=[]
    for path in sorted((out/'service').rglob('*')):
        if path.is_file():inventory.append(dict(path=path.relative_to(out).as_posix(),bytes=path.stat().st_size,sha256=digest(path)))
    write(out/'component-files.json',dict(schemaVersion=1,files=inventory))
    manifest=dict(schemaVersion=1,componentId='bingyi-gpt-sovits',componentVersion=version,adapter='api_v2',serviceRoot='service',voicesRoot='voices',modelFamily='v4',devices=['cpu'],languages=['zh','ja','en','yue','ko','auto'],inventory='component-files.json',inventorySha256=digest(out/'component-files.json'))
    write(out/'component.json',manifest)
    voices=[]
    for directory in sorted((out/'voices').iterdir()):
        if not directory.is_dir():continue
        entries=[dict(path=p.relative_to(out).as_posix(),bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(directory.rglob('*')) if p.is_file()]
        voices.append(dict(folder=directory.name,bytes=sum(e['bytes'] for e in entries),files=entries))
    report=dict(source=str(source),output=str(out),sourceBytes=source_bytes,componentBytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),coreBytes=sum(e['bytes'] for e in inventory),removed=removed,replacements=replacements,voices=voices,weightPolicy='unchanged bytes; no quantization or precision change',status='built; requires real inference and archive/extracted verification')
    write(out.parent/'component-build-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('removed','voices')},ensure_ascii=True),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--original',type=Path,default=ROOT/'tts_bundle');parser.add_argument('--version',default='1.0.0-cpu')
    args=parser.parse_args();build(args.source,args.out,args.original,args.version)


if __name__=='__main__':main()
