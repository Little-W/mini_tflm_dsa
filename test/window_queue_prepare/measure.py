#!/usr/bin/env python3
"""以相同参数测量窗口队列和完整 DMA 的准备字段路径。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')
REFERENCE = '8a31b855'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out/'reference.sv'
    reference.write_bytes(subprocess.check_output(
        ['git', 'show', f'{REFERENCE}:{SOURCE}'], cwd=ROOT))
    cases = {}
    for label, source in [('reference', reference), ('candidate', ROOT/SOURCE)]:
        cases['queue_'+label] = {
            'top': 'conv_window_queue', 'sources': [str(source)],
            'options': ['-DSYNTHESIS=1', '-GDEPTH=4', '-GWINDOW_LANES=8',
                        '-Gp_frontend_outstanding=3', '-GCOL_W=32'],
            'configuration': '完整窗口队列，深度4，8个通道，3个前端在途窗口，32位列号',
        }
        cases['dma_'+label] = {
            'top': 'axi_dual_block_dma',
            'sources': [str(ROOT/'rtl/npu/dma/axi_dual_block_dma.sv'), str(source)],
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                        '-GBUS_WIDTH=64', '-GWINDOW_LANES=8', '-GCONV_LINE_BYTES=128',
                        '-GCONV_CACHE_SETS=16', '-GCONV_CACHE_WAYS=2'],
            'configuration': '完整 DMA 的相同配置比较',
        }
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    reports = {}
    for name in cases:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(configuration), '--cases', name,
                        '--out', str(out/'pre_lut'), '--through', 'pre_lut'], cwd=ROOT, check=True)
        target = out/(name+'_cost')
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/remap_fpga_luts.py'),
                        '--source', str(out/'pre_lut'/name), '--out', str(target),
                        '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
        reports[name] = json.loads((target/'metrics.json').read_text())
    (out/'summary.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
