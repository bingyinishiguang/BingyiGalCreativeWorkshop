"""Conservative script import: retain uncertain text for human review."""
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from subtitle_tools import read_text


def document_text(path):
    path=Path(path)
    if path.suffix.lower()=='.txt':return read_text(path)
    if path.suffix.lower()!='.docx':raise ValueError('请选择 TXT 或 DOCX 剧本')
    if path.stat().st_size>10_000_000:raise ValueError('DOCX 文件最多 10 MB')
    try:
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size>4_000_000:raise ValueError('DOCX 文字内容过大')
            xml=archive.read(info)
        if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:raise ValueError('DOCX XML 格式不支持')
        tree=ET.fromstring(xml);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        lines=[]
        for paragraph in tree.findall('.//w:p',ns):
            value=''
            for node in paragraph.iter():
                tag=node.tag.rsplit('}',1)[-1]
                if tag=='t':value+=node.text or ''
                elif tag in ('br','cr'):value+='\n'
                elif tag=='tab':value+='\t'
            if value.strip():lines.append(value)
        return '\n'.join(lines)
    except (zipfile.BadZipFile,KeyError,ET.ParseError) as error:
        raise ValueError('无法读取 DOCX，请确认文件完整，旧版 DOC 请另存为 DOCX') from error


def parse_script(text, source='粘贴文本'):
    if not isinstance(text,str) or len(text)>2_000_000:raise ValueError('剧本文字最多 2 MB')
    rows=[];directives=[];scene_key=''
    types={'旁白':'narrator','心理':'inner','心理描写':'inner','内心':'inner','心声':'inner','对话':'dialogue','对白':'dialogue',
           '女主':'dialogue','女主对白':'dialogue','男主':'dialogue','男主对白':'dialogue',
           '女主内心':'inner','女主内心独白':'inner','男主内心':'inner'}
    for line_number,line in enumerate(text.splitlines(),1):
        raw=line.strip()
        if not raw:continue
        scene=re.fullmatch(r'【(场景|背景|立绘|表情|音效|BGM)】\s*(.*)',raw,re.I)
        if scene:
            directive={'line':line_number,'type':scene[1],'value':scene[2],'raw':raw}
            if scene[1] in ('场景','背景'):
                directive['id']=uuid.uuid5(uuid.NAMESPACE_URL,source+':'+str(line_number)+':'+raw).hex;scene_key=directive['id']
            directives.append(directive);continue
        kind='narrator';character='';voice=False;explicit=False;warnings=[];content=raw
        tags=[]
        while True:
            match=re.match(r'^(?:【([^】]+)】|\[([^\]]+)\])\s*',content)
            if not match:break
            tags.append(match[1] or match[2]);content=content[match.end():]
        recognized=False
        for tag in tags:
            if tag in ('男主','女主') and any(t in ('旁白','心理','心理描写','内心','心声','对话','对白') for t in tags):
                character=tag;recognized=True
            elif tag in types:
                kind=types[tag];recognized=True
                if tag.startswith('男主'):character='男主'
                elif tag.startswith('女主'):character='女主'
            elif tag in ('有配音','配音','无配音','不配音'):
                voice=tag in ('有配音','配音');explicit=True
            else:
                character=tag;recognized=True
                if kind=='narrator' and not any(t in types for t in tags):kind='dialogue'
        if not tags:
            match=re.match(r'^([^：:]{1,100})[：:]\s*(.+)$',content)
            if match:
                prefix,content=match.groups();recognized=True
                kind=types.get(prefix,'dialogue')
                if prefix not in types or prefix.startswith(('男主','女主')):character=prefix.replace('对白','').replace('内心独白','').replace('内心','')
        if not recognized:warnings.append('未标明文字类别，暂按旁白，请确认')
        if kind=='inner' and not character:warnings.append('心理描写未指定角色，请确认')
        if kind=='dialogue' and not character:warnings.append('对话未指定角色，请确认')
        if not content.strip():content=raw;warnings.append('标记后没有台词，请修改或删除')
        if len(content)>2000:raise ValueError(f'第 {line_number} 行超过两千字，请拆分')
        if not explicit:
            voice=kind=='dialogue' and character=='女主'
            if kind=='dialogue' and character not in ('男主','女主'):warnings.append('请确认该角色是否需要配音')
        rows.append(dict(id=uuid.uuid4().hex,kind=kind,character=character,text=content.strip(),voice=voice,
                         voiceExplicit=explicit,audio='',hold=3,holdExplicit=False,pause=None,warnings=warnings,
                         reviewed=not warnings,source=dict(file=source,line=line_number,raw=raw)))
        if scene_key:rows[-1]['sceneKey']=scene_key
        if len(rows)>500:raise ValueError('剧本最多五百句，请分批导入')
    if not rows:raise ValueError('没有找到可校对的台词')
    return {'rows':rows,'directives':directives,'gap':.3}
