"""Isolated optional faster-whisper worker, run by a configured Python runtime."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_worker_resources = []


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), 'utf-8')
    for attempt in range(50):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt==49:
                raise
            time.sleep(.02)


def main():
    request_path, result_path, progress_path = map(Path, sys.argv[1:4])
    request = json.loads(request_path.read_text('utf-8'))
    config = request['config']
    # Existing TTS distributions keep the Torch CUDA DLLs in their own runtime.
    # These environment changes are confined to this disposable subprocess.
    handles = []
    if os.name == 'nt':
        runtime = Path(sys.executable).parent
        for folder in (runtime, runtime / 'Lib/site-packages/torch/lib'):
            if folder.is_dir():
                os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
                if hasattr(os, 'add_dll_directory'):
                    handles.append(os.add_dll_directory(str(folder)))
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        write(result_path, {'error': '识别环境缺少 faster-whisper，请配置已安装它的 Python 环境'})
        return 1
    try:
        write(progress_path, {'message': '正在载入本地语音识别模型…'})
        model = WhisperModel(config['modelPath'], device=config.get('device', 'cpu'),
                             compute_type=config.get('computeType', 'int8'), local_files_only=True)
        # Keep native CUDA resources alive until this disposable process exits.
        # Some external runtimes fail during interpreter teardown after valid output.
        _worker_resources.extend([model, handles])
        language = config.get('language', 'auto')
        segments, _ = model.transcribe(request['audio'], language=None if language == 'auto' else language,
                                       task='transcribe', beam_size=5, word_timestamps=True, vad_filter=True,
                                       condition_on_previous_text=False)
        rows = []
        for segment in segments:
            text = segment.text.strip()
            if text and segment.end > segment.start:
                rows.append({'start': segment.start, 'end': segment.end, 'text': text})
                if config.get('includeWords'):
                    rows[-1]['words'] = [{'start': w.start, 'end': w.end, 'text': w.word}
                                         for w in (segment.words or [])]
                if len(rows) > 10000:
                    raise ValueError('识别字幕超过一万条，请分段处理')
                write(progress_path, {'message': f'已识别 {len(rows)} 段，处理至 {segment.end:.1f} 秒'})
        if not rows:
            raise ValueError('没有识别到语音，请检查音频或语言设置')
        write(result_path, {'cues': rows})
        return 0
    except Exception as error:
        # Worker inputs contain only local ASR settings, never external API keys.
        write(result_path, {'error': '本地语音识别失败：' + str(error)[:1000]})
        return 1


if __name__ == '__main__':
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
