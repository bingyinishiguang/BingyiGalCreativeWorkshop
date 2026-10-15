"""Reviewed, language-independent shortening of excessive quiet pauses."""
from __future__ import annotations

import json
import math
import re
import subprocess
import uuid
import wave
from pathlib import Path

from draft_video_tools import file_hash
from gal_story_render import ffmpeg


def pause_candidates(log, duration, minimum=.9, keep=.45):
    if not math.isfinite(minimum+keep+duration) or not .5 <= minimum <= 5 or not .25 <= keep <= 1.2 or keep >= minimum:
        raise ValueError('停顿参数须保留至少 0.25 秒，检测阈值须大于保留时长')
    rows, start = [], None
    for kind, number in re.findall(r'silence_(start|end):\s*([0-9.]+)', log):
        value = float(number)
        if kind == 'start':
            start = value
        elif start is not None:
            if value-start >= minimum and start > .1 and value < duration-.1:
                rows.append(dict(id=len(rows),start=start,end=value,cutStart=start+keep/2,
                                 cutEnd=value-keep/2,keep=keep,selected=value-start <= 2,
                                 note='长停顿，可能用于段落或情绪表达，请试听' if value-start > 2 else '保留自然停顿，仅缩短中间静音'))
            start = None
    return rows


class PauseCleanup:
    def __init__(self, root, video):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.video, self.previews, self.outputs = video, {}, {}

    def source(self, payload):
        with self.video.editor.lock:
            session = self.video.session(payload)
            ti, si = payload.get('audioTrackIndex'), payload.get('audioSegmentIndex')
            if type(ti) is not int or type(si) is not int or not 0 <= ti < len(session['data']['tracks']):
                raise ValueError('请选择草稿配音')
            track = session['data']['tracks'][ti]
            if track.get('type') != 'audio' or not 0 <= si < len(track.get('segments', [])):
                raise ValueError('配音片段不存在')
            segment = track['segments'][si]
            material = next(m for m in session['data']['materials']['audios'] if m['id'] == segment['material_id'])
            path = Path(material['path'])
            if not path.is_file():
                raise ValueError('配音文件不存在')
            # Trimming an arbitrary source outside the selected clip would misalign the draft.
            sr = segment.get('source_timerange') or {'start':0}
            if segment.get('speed',1) != 1:
                raise ValueError('停顿整理目前需要原速播放的配音片段')
            duration = segment['target_timerange']['duration']/1e6
            if not 0 < duration <= 1800:
                raise ValueError('单次停顿整理支持 30 分钟以内的配音，请先分段')
            return path, duration, sr['start']/1e6

    def preview(self, payload):
        source, duration, source_start = self.source(payload)
        minimum, keep, threshold = float(payload.get('minimum',.9)),float(payload.get('keep',.45)),float(payload.get('threshold',-42))
        pause_candidates('',duration,minimum,keep)
        if not math.isfinite(threshold) or not -65 <= threshold <= -25:
            raise ValueError('静音阈值须在 -65 至 -25 dB 之间')
        result = subprocess.run([ffmpeg(),'-hide_banner','-nostats','-ss',str(source_start),'-i',str(source),'-t',str(duration),'-af',f'silencedetect=noise={threshold}dB:d={minimum}', '-f','null','-'],capture_output=True,timeout=300,creationflags=0x08000000)
        if result.returncode:
            raise ValueError('停顿检测失败，请检查音频格式和 FFmpeg')
        rows = pause_candidates(result.stderr.decode('utf-8',errors='replace'),duration,minimum,keep)
        key = uuid.uuid4().hex
        if len(self.previews) >= 16:
            self.previews.pop(next(iter(self.previews)))
        self.previews[key] = dict(source=source,digest=file_hash(source),rows=rows,duration=duration,sourceStart=source_start,sessionId=payload['sessionId'])
        return dict(previewId=key,rows=rows,duration=duration,sourceStart=source_start,note='短停顿、音频首尾保留；不自动去除有声音的呼吸、尾音或背景音乐')

    def save(self, payload):
        preview = self.previews.get(payload.get('previewId'))
        if not preview or preview['sessionId'] != payload.get('sessionId'):
            raise ValueError('停顿预览已失效，请重新检测')
        self.video.session(payload)
        source = preview['source']
        if file_hash(source) != preview['digest']:
            raise ValueError('音频已变化，请重新检测')
        chosen = payload.get('selected')
        if not isinstance(chosen,list) or not chosen or any(type(v) is not int or not 0 <= v < len(preview['rows']) for v in chosen) or len(set(chosen)) != len(chosen):
            raise ValueError('请选择已试听的停顿区间')
        folder = self.root/uuid.uuid4().hex
        folder.mkdir()
        decoded = folder/'pcm.wav'
        subprocess.run([ffmpeg(),'-v','error','-ss',str(preview['sourceStart']),'-i',str(source),'-t',str(preview['duration']),'-c:a','pcm_s16le','-y',str(decoded)],capture_output=True,check=True,timeout=300,creationflags=0x08000000)
        with wave.open(str(decoded),'rb') as audio:
            params = audio.getparams()
            frames = audio.readframes(audio.getnframes())
        width = params.nchannels*params.sampwidth
        cuts = sorted((round(preview['rows'][i]['cutStart']*params.framerate),round(preview['rows'][i]['cutEnd']*params.framerate)) for i in chosen)
        pieces, last, mapping, offset = [],0,[],0
        for a,b in cuts:
            if not last <= a < b <= params.nframes:
                raise ValueError('停顿删除范围无效')
            pieces.append(frames[last*width:a*width])
            mapping.append(dict(originalStart=last/params.framerate,originalEnd=a/params.framerate,newStart=offset/params.framerate))
            offset += a-last
            last = b
        pieces.append(frames[last*width:])
        mapping.append(dict(originalStart=last/params.framerate,originalEnd=params.nframes/params.framerate,newStart=offset/params.framerate))
        # Fade only the quiet join edges; retain all pause padding and speech.
        import numpy as np
        for i,piece in enumerate(pieces):
            samples = np.frombuffer(piece,dtype='<i2').reshape(-1,params.nchannels).copy()
            count = min(round(params.framerate*.005),len(samples)//2)
            if count:
                if i:
                    samples[:count] = (samples[:count]*np.linspace(0,1,count)[:,None]).astype('<i2')
                if i<len(pieces)-1:
                    samples[-count:] = (samples[-count:]*np.linspace(1,0,count)[:,None]).astype('<i2')
            pieces[i] = samples.tobytes()
        output = folder/(source.stem+'-自然停顿.wav')
        with wave.open(str(output),'wb') as audio:
            audio.setparams(params)
            audio.writeframes(b''.join(pieces))
        decoded.unlink()
        removed = sum(b-a for a,b in cuts)/params.framerate
        metadata = dict(path=str(output),duration=params.nframes/params.framerate-removed,removedSeconds=removed,timeMap=mapping,selected=chosen,sourceUnchanged=True)
        (folder/'停顿处理记录.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
        ident = uuid.uuid4().hex
        self.outputs[ident] = {**metadata,'sessionId':preview['sessionId'],'originalSource':str(source),'originalHash':preview['digest'],'cleanHash':file_hash(output)}
        return {**metadata,'cleanAudioId':ident}
