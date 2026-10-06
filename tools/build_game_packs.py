"""Build one normal-outfit ZIP per work, retaining original metadata and directories."""
from __future__ import annotations
import argparse,hashlib,json,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sprite_composer import (IsolationPolicy,scan_characters,scan_lime_poses,web_catalog,
                            _lime_layer_filename,web_composite)
from txt_parser import scan_txt_library
from pack_import import analyze


def scan(games: Path):
    png=scan_characters(games/'常轨脱离')
    lime=scan_lime_poses(games/'LimeLightLemonadeJam')
    txt,warnings=scan_txt_library(games)
    if warnings:raise RuntimeError(warnings[:5])
    catalog=web_catalog(png,lime,txt,IsolationPolicy(),existing_only=True)
    return png,lime,txt,catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', help='Only rebuild this work and retain other manifest entries')
    args=parser.parse_args()
    source=ROOT/'sprite-packs/personal-library/games'
    output=ROOT/'作品素材包'
    output.mkdir(exist_ok=True)
    png,lime,txt,catalog=scan(source)
    policy=IsolationPolicy();manifest=json.loads((source.parent/'pack.json').read_text(encoding='utf-8'))
    adapters={g['folder']:g['adapter'] for g in manifest['games']}
    if args.game and args.game not in adapters:
        parser.error('Unknown work: '+args.game)
    results=[]
    if args.game and (output/'素材包清单.json').is_file():
        results=[r for r in json.loads((output/'素材包清单.json').read_text(encoding='utf-8')) if r['game']!=args.game]
    for game_name in ([args.game] if args.game else sorted(adapters)):
        game=source/game_name
        refs=set();body_count=0;face_count=0;sample=None
        for character,entry in catalog.get(game_name,{}).get('characters',{}).items():
            for body,faces in entry['bodies'].items():
                if entry['bodyCategories'][body]!='normal':continue
                body_count+=1;face_count+=len(faces)
                if sample is None:sample=(game_name,character,body,faces[0])
                if game_name=='常轨脱离':
                    ch=png[character]
                    refs.add(next(layer.path for layer in ch.bodies if layer.name==body))
                    refs.update(layer.path for layer in ch.faces if layer.name in faces)
                elif game_name=='LimeLightLemonadeJam':
                    pose=next(p for p in lime[character] if body.startswith(p.label+'｜'))
                    dress=body[len(pose.label)+1:]
                    for recipe in [*pose.dresses[dress],*(r for f in faces for r in pose.faces[f])]:
                        filename=_lime_layer_filename(pose,recipe)
                        if filename is None:raise RuntimeError(recipe)
                        refs.add(pose.pbd_path.parent/filename)
                else:
                    b=txt[game_name][character].bodies[body];pose=b.pose
                    keys=[*pose.dresses[b.dress_name],*(k for f in faces for k in pose.faces[f])]
                    refs.update(pose.layers[k].image_path for k in keys)
        if not sample:raise RuntimeError('No normal outfits: '+game_name)
        #Original coordinate and recipe files are needed by the importer.
        refs.update(p for p in game.rglob('*') if p.is_file() and p.suffix.lower() in {'.txt','.sinfo','.pbd'})
        refs={p.resolve() for p in refs}
        assert all(p.is_relative_to(game.resolve()) and p.is_file() for p in refs)
        image=web_composite(*sample,png,lime,txt);assert image.getbbox();image.close()
        pack_id='game-'+hashlib.sha256(game_name.encode()).hexdigest()[:12]
        pack={'formatVersion':1,'id':pack_id,'name':game_name+'立绘素材包','version':'1.1.1',
              'games':[{'folder':game_name,'adapter':adapters[game_name]}]}
        archive=output/(game_name+'.zip')
        tmp=archive.with_suffix('.building.zip')
        entries={}
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
            z.writestr('pack.json',json.dumps(pack,ensure_ascii=False,indent=2))
            for path in sorted(refs):
                name='games/'+path.relative_to(source).as_posix()
                z.write(path,name);entries[name]=path.stat().st_size
        with zipfile.ZipFile(tmp) as z:
            broken=z.testzip()
            if broken:raise RuntimeError('CRC failure: '+broken)
            actual={i.filename:i.file_size for i in z.infolist() if i.filename!='pack.json'}
            assert actual==entries
            assert json.loads(z.read('pack.json'))==pack
        tmp.replace(archive)
        analysis=analyze(str(archive))
        if not analysis.ok or analysis.games!=[game_name]:raise RuntimeError(analysis.as_dict())
        results.append({'game':game_name,'zip':archive.name,'bytes':archive.stat().st_size,
                        'files':len(refs),'png':sum(p.suffix.lower()=='.png' for p in refs),
                        'bodies':body_count,'combinations':face_count,
                        'sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()})
        print(json.dumps(results[-1],ensure_ascii=True),flush=True)
    results.sort(key=lambda r:r['game'])
    (output/'素材包清单.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 按作品独立素材包','', '每个 ZIP 对应一部作品。特殊服装素材（暴露、泳衣、睡衣）已移除。',
           '在工坊「设置 → 素材包导入」选择所需作品 ZIP，导入后重新扫描素材。','',
           '|作品|ZIP 大小|PNG 数量|身体／服装／姿势|可用组合|','|---|---:|---:|---:|---:|']
    for r in results:lines.append(f"|{r['game']}|{r['bytes']/1048576:.1f} MB|{r['png']}|{r['bodies']}|{r['combinations']}|")
    (output/'使用说明.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('VERIFIED',len(results),'game ZIPs',flush=True)

if __name__=='__main__':main()
