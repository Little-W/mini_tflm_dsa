#!/usr/bin/env python3
"""导出生产 IA 控制器的完整参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader_ctrl.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='324eba48')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    parameters = dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32, COUNT_WIDTH=29, COMPACT_S8=0,
        p_indexed_slot_rows=1, p_precomputed_slot_mask=1, p_precomputed_frame_rows=1,
        p_precomputed_packed_tiles=1, p_parallel_request_match=1)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    texts = {'reference': subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT),
             'current': (ROOT/SOURCE).read_bytes()}
    cases, hashes = {}, {}
    for label, data in texts.items():
        path = out/(label+'.sv'); path.write_bytes(data)
        sources = resolve([path], ROOT)
        for source in sources:
            hashes[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        cases[label] = dict(top='ia_loader_ctrl', sources=list(map(str, sources)),
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                    [f'-G{key}={value}' for key, value in parameters.items()],
            parameters=parameters, configuration='生产 IA 控制器，全部公开输出保留')
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'reference_revision': args.reference,
        'source_sha256': hashes}, indent=2)+'\n')


if __name__ == '__main__':
    main()
