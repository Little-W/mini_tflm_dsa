#!/usr/bin/env python3
"""测量完整读取保护器的 Xilinx 资源及寄存器之间的组合逻辑深度。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_axi_read_guard.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    parser.add_argument('--data-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    content = (read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT)
               if args.reference_ref else (ROOT / SOURCE).read_bytes())
    source = out / SOURCE.name
    source.write_bytes(content)
    sources = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']([source], ROOT)
    top = 'conv_axi_read_guard'
    parameters = dict(ADDR_W=32, DATA_W=args.data_width, SPLIT_GEMM_4K=1, READ_OUTSTANDING=4)
    options = ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1']
    options += [f'-G{name}={value}' for name, value in parameters.items()]
    cases = out / 'cases.json'
    cases.write_text(json.dumps({'guard': dict(
        top=top, configuration='完整读取保护器，四笔在途请求',
        parameters=parameters, options=options, sources=list(map(str, sources))
    )}, ensure_ascii=False, indent=2) + '\n')
    commands = [
        [sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
         '--case-config', cases, '--cases', 'guard', '--out', out / 'pre', '--through', 'pre_lut'],
        [sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
         '--source', out / 'pre/guard', '--out', out / 'mapped', '--mode', 'physical-cost',
         '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8',
         '--small-lut-area-cost', '1', '--discard-abc9-temporaries'],
    ]
    for index, command in enumerate(commands):
        with (out / f'stage_{index}.log').open('w') as log:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
    metrics = json.loads((out / 'mapped/metrics.json').read_text())
    verification = json.loads((out / 'mapped/verification.json').read_text())
    assert metrics['paths']['graph_complete'] and verification['passed']
    result = dict(scope=top, family='xc7', reference_ref=args.reference_ref,
                  source_sha256={str(SOURCE): hashlib.sha256(content).hexdigest()},
                  parameters=parameters, resources=metrics['resources'],
                  longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
                  graph_complete=True, mapping_verification=verification,
                  delay_target_ps=6667, wire_delay_ps=300)
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
