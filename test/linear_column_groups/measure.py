#!/usr/bin/env python3
"""测量32个缓存槽配置下线性DMA的完整资源与连接路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='07a199ac')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    parameters = {'SIZE':64,'BUS_WIDTH':64,'CACHE_BLOCKS':32,'READ_OUTSTANDING':4,
                  'WRITE_OUTSTANDING':4,'RD_CONTEXT_DEPTH':4}
    cases = {}
    for name in ('reference','current'):
        path = out/(name+'.sv')
        path.write_bytes(subprocess.check_output(['git','show',reference+':'+SOURCE],cwd=ROOT)
                         if name == 'reference' else (ROOT/SOURCE).read_bytes())
        cases[name] = {'top':'axi_linear_block_dma','sources':[str(path)],
            'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1',*[f'-G{k}={v}' for k,v in parameters.items()]],
            'configuration':parameters}
    config = out/'cases.json'
    config.write_text(json.dumps(cases,indent=2)+'\n')
    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
        '--cases','reference','current','--out',out/'mapping','--through','pre_lut'],cwd=ROOT,check=True)
    rows = {}
    for name in cases:
        cost = out/'cost'/name
        subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/'mapping'/name,
            '--out',cost,'--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300',
            '--max-lut-inputs','8','--discard-abc9-temporaries'],cwd=ROOT,check=True)
        rows[name] = {'manifest':json.loads((cost/'manifest.json').read_text()),
            'summary':json.loads((cost/'summary.json').read_text()),
            'mapped_sha256':hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()}
        print(name,rows[name]['summary']['resources']['lut_sites_nominal_before_packing'],
              rows[name]['summary']['longest_register_path_cells'],flush=True)
    report = {'reference_commit':reference,'parameters':parameters,'cases':rows,
        'source_sha256':hashlib.sha256((ROOT/SOURCE).read_bytes()).hexdigest()}
    assert (ROOT/SOURCE).read_bytes() == (out/'current.sv').read_bytes()
    (out/'measurement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
