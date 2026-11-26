#!/usr/bin/env python3
"""用相同映射参数比较三个完整调用模块的分段减法资源。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '84d2374a'
CASES = {
    'address': ('rtl/npu/conv/vector_engine_address.sv', {
        'p_tile': 16, 'p_bus_width': 64, 'p_dma_size': 64, 'p_pe_count': 8,
        'p_window_lanes': 8, 'p_shared_quant_enable': 1,
        'p_shared_storage_enable': 1, 'p_registered_read_phase': 1}),
    'predictor': ('rtl/npu/dma/cache/conv_next_use_predictor.sv', {}),
    'geometry': ('rtl/npu/conv/conv_im2col_geometry.sv', {'p_lanes': 8}),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for name, (relative, parameters) in CASES.items():
        reference = out/(name+'_reference.sv')
        reference.write_bytes(subprocess.check_output(
            ['git', 'show', REFERENCE+':'+relative], cwd=ROOT))
        for label, source in [('reference', reference), ('candidate', ROOT/relative)]:
            cases[name+'_'+label] = {
                'top': Path(relative).stem, 'sources': [str(source)],
                'options': ['-DSYNTHESIS=1']+[f'-G{key}={value}' for key, value in parameters.items()],
                'configuration': '完整调用模块的分段减法资源比较',
            }
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                    '--case-config', str(configuration), '--cases', *cases,
                    '--out', str(out/'pre_lut'), '--through', 'pre_lut'], cwd=ROOT, check=True)
    reports = {}
    for name in cases:
        target = out/(name+'_cost')
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/remap_fpga_luts.py'),
                        '--source', str(out/'pre_lut'/name), '--out', str(target),
                        '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
        reports[name] = json.loads((target/'metrics.json').read_text())
    (out/'summary.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
