#!/usr/bin/env python3
"""复用完整 NPU 仿真程序检查 WS、IS、INT8、INT16 与三种分块存储布局。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    simulator = args.sim.resolve()
    out = args.out.resolve()
    manifest = json.loads((simulator / 'build.json').read_text())
    binary = simulator / 'obj/Vtb_conv_npu'
    assert manifest['returncode'] == 0
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == manifest['binary_sha256']
    source_root = Path(manifest.get('source_root', ROOT))
    for relative, expected in manifest['source_sha256'].items():
        if relative.startswith(('rtl/', 'include/')):
            assert hashlib.sha256((source_root / relative).read_bytes()).hexdigest() == expected, relative
    sys.path.insert(0, str(ROOT / 'test/frame_address'))
    from run_npu import packed_cases
    sys.path.insert(0, str(ROOT / 'test/ps_compression'))
    from run_shared_npu import npu
    report = npu.run_suite(binary, out.parent, out.name,
                          packed_cases(out, manifest), no_random=False, timeout=900)
    assert report['passed']
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('SHARED_ROLE_PACKED_PASS', len(report['measurements']), flush=True)


if __name__ == '__main__':
    main()
