"""Cancel-aware host for optional local ASR in a separate Python process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def recognize(audio_path, config, cancel, progress):
    model = Path(str(config.get('modelPath') or '')).expanduser()
    if not config.get('modelPath') or not model.is_dir() or not (model / 'model.bin').is_file():
        raise ValueError('请在助手设置中选择已有的 faster-whisper 模型目录（含 model.bin）')
    configured = str(config.get('pythonPath') or '').strip()
    if not configured and getattr(sys, 'frozen', False):
        raise ValueError('打包版请配置已安装 faster-whisper 的外部 Python 路径')
    interpreter = Path(configured or sys.executable)
    if not interpreter.is_file() or interpreter.suffix.lower() != '.exe' and os.name == 'nt':
        raise ValueError('语音识别 Python 路径不存在，请选择 python.exe')
    if config.get('device', 'cpu') not in ('cpu', 'cuda', 'auto'):
        raise ValueError('识别设备不正确')
    if config.get('computeType', 'int8') not in ('int8', 'float16', 'float32', 'int8_float16', 'auto', 'default'):
        raise ValueError('识别计算精度不正确')
    audio = Path(audio_path).resolve()
    if not audio.is_file():
        raise ValueError('配音文件不存在')
    worker = Path(__file__).with_name('assistant_asr_worker.py')
    if not worker.is_file():
        raise ValueError('识别工作程序缺失，请重新安装工坊')
    with tempfile.TemporaryDirectory(prefix='bingyi-asr-') as folder:
        root = Path(folder)
        request, result, status = (root / name for name in ('request.json', 'result.json', 'progress.json'))
        request.write_text(json.dumps({'audio': str(audio), 'config': {
            'modelPath': str(model.resolve()), 'device': config.get('device', 'cpu'),
            'computeType': config.get('computeType', 'int8'), 'language': config.get('language', 'auto'),
            'includeWords': bool(config.get('includeWords', False))
        }}, ensure_ascii=False), 'utf-8')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        with (root / 'worker.log').open('wb') as log:
            process = subprocess.Popen([str(interpreter), str(worker), str(request), str(result), str(status)],
                                       cwd=str(root), stdout=log, stderr=log, **options)
            deadline = time.monotonic() + 7200
            last_status = ''
            try:
                while process.poll() is None:
                    if cancel.is_set():
                        raise ValueError('字幕任务已取消')
                    if time.monotonic() > deadline:
                        raise ValueError('识别任务超过两小时，请分段处理音频')
                    if status.is_file():
                        try:
                            message = json.loads(status.read_text('utf-8')).get('message', '')
                            if message and message != last_status:
                                progress(message)
                                last_status = message
                        except (OSError, ValueError):
                            pass
                    cancel.wait(.2)
                if cancel.is_set():
                    raise ValueError('字幕任务已取消')
                if not result.is_file():
                    raise ValueError('识别进程未能启动或意外退出，请检查 Python 环境与模型兼容性')
                if result.stat().st_size > 20_000_000:
                    raise ValueError('识别结果过大，请分段处理')
                data = json.loads(result.read_text('utf-8'))
                if data.get('error'):
                    raise ValueError(data['error'])
                if process.returncode or not isinstance(data.get('cues'), list):
                    raise ValueError('语音识别结果格式不正确')
                return data['cues']
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
