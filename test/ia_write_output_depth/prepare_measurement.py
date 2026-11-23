#!/usr/bin/env python3
"""保存同一生产参数下的 IA 缓存参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source_group, read_current_source, shared_ia_parameters

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/ia_loader_cache_mgr.sv'
DEPENDENCY = 'rtl/npu/compute/select_add.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7ff66a59')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32,
                      RAM_WORD_ADDR_WIDTH=12, p_compact_offset_width=9)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        data = (read_rtl_source_group(args.reference + ':' + SOURCE, cwd=ROOT)
                if label == 'reference' else read_current_source(ROOT / SOURCE).encode())
        snapshot = out / (label + '.sv')
        snapshot.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        values = shared_ia_parameters(parameters, data.decode())
        cases[label] = dict(top='ia_loader_cache_mgr', sources=[str(snapshot), DEPENDENCY],
            parameters=values, options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
            [f'-G{name}={value}' for name, value in values.items()],
            configuration='生产 IA 缓存，完整外部 RAM 接口')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    manifest = dict(reference_commit=subprocess.check_output(
        ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        parameters=parameters, source_sha256=hashes,
        common_dependency_sha256={DEPENDENCY: hashlib.sha256((ROOT / DEPENDENCY).read_bytes()).hexdigest()})
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
