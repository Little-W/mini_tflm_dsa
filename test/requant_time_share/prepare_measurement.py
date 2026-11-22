#!/usr/bin/env python3
"""保存完整量化模块的固定输入，并生成各物理通道数的综合配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from requant_test_utils import RTL_SOURCES

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lanes', type=int, nargs='+', default=[16, 4, 2, 1])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = []
    hashes = {}
    for relative in RTL_SOURCES:
        source = ROOT / relative
        target = out / source.name
        target.write_bytes(source.read_bytes())
        sources.append(str(target))
        hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    cases = {}
    for lanes in args.lanes:
        if lanes not in (1, 2, 4, 8, 16):
            raise ValueError('Physical lanes must divide the complete 16-element row')
        cases[f'lanes{lanes}'] = {
            'top': 'vec_requant',
            'options': ['-D', 'SYNTHESIS=1', '-GBUS_WIDTH=64', '-GVLEN=16',
                        '-GMAX_IA_REUSE=32', '-GENABLE_S16=1',
                        f'-Gp_compute_lanes={lanes}', '-Gp_input_rows=512', '-Gp_parameter_output=0'],
            'parameters': {'BUS_WIDTH': 64, 'VLEN': 16, 'MAX_IA_REUSE': 32,
                           'ENABLE_S16': 1, 'p_compute_lanes': lanes,
                           'p_input_rows': 512},
            'sources': sources,
            'configuration': '十六元素量化接口，完整 WS/IS/INT16 和五百一十二行组容量',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'input_manifest.json').write_text(json.dumps(hashes, indent=2) + '\n')


if __name__ == '__main__':
    main()
