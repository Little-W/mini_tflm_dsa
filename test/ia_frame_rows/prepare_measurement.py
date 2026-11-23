#!/usr/bin/env python3
"""保存完整 IA 加载器的参考与当前综合源码。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source_group, read_current_source, shared_ia_parameters

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7ff66a59')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    hashes = {}
    for label in ('reference', 'current'):
        folder = out/label
        folder.mkdir(exist_ok=True)
        sources = []
        hashes[label] = {}
        for name in ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr'):
            relative = Path('rtl/npu/loaders')/(name+'.sv')
            data = (read_rtl_source_group(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else read_current_source(ROOT/relative).encode())
            path = folder/relative.name
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        values = shared_ia_parameters(dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64,
            REG_WIDTH=32, COUNT_WIDTH=29, CACHE_BLOCKS=32, ORDERED_JOB=1),
            (folder / 'ia_loader.sv').read_text())
        cases['loader_'+label] = {
            'top': 'ia_loader',
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in values.items()],
            'parameters': values, 'sources': sources,
            'configuration': '完整 IA 加载器，包含配置、缓存控制、预取和共享 RAM 数据排列',
        }
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')


if __name__ == '__main__':
    main()
