"""Verify the frozen native codec with a synthetic draft and explicit editor DLLs."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    workspace = Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace / '工作数据'):
        raise ValueError('Verification data must stay under workspace work data')
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'plain.json'
    encrypted = root / 'encrypted.data'
    restored = root / 'restored.json'
    raw = json.dumps({'id':'synthetic', 'tracks':[], 'materials':{}}, ensure_ascii=False).encode()
    source.write_bytes(raw)
    for operation, before, after in [('enc', source, encrypted), ('dec', encrypted, restored)]:
        result = subprocess.run([str(args.exe.resolve()), '--draft-codec-worker', operation,
                                 str(args.install.resolve()), str(before), str(after)],
                                capture_output=True, timeout=30, creationflags=0x08000000)
        if result.returncode != 0 or not after.is_file():
            raise RuntimeError('Frozen codec failed: ' + operation)
    assert source.read_bytes() == raw
    assert restored.read_bytes() == raw
    assert encrypted.read_bytes() != raw
    report = {'passed':True, 'frozenWorker':True, 'externalPythonRequired':False,
              'originalUnchanged':True, 'roundTripExact':True,
              'sha256':hashlib.sha256(raw).hexdigest()}
    (root / 'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
