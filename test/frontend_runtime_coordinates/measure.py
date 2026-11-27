#!/usr/bin/env python3
"""测量完整运行寄存器及实际 SoC 参数前端的组合路径和器件资源。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

from run_formal import ROOT, SOURCE, REFERENCE, PARAMETERS, PROFILES
from run_four_state import port_declarations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--cases', nargs='+', default=['runtime_reference', 'runtime_current'])
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--lanes', type=int, choices=(8,16), default=8)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT/SOURCE).read_text()
    reference = out/'reference_runtime.sv'
    reference.write_bytes(subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)], cwd=ROOT))
    match = re.search(r'module conv_im2col_runtime_registers\s*#\((.*?)\)\s*\((.*?)\);', source, re.S)
    ports = port_declarations(source)
    parameters = re.findall(r'\bparameter\s+(?:int|bit)\s+(\w+)\s*=', match[1])
    wrapper = out/'registered_runtime.sv'
    body = 'module registered_runtime #(\n'+match[1]+') (\n'+match[2]+'\n);\n'
    body += '\n'.join('  '+kind+' '+name+'_q;' for direction, kind, name in ports
                      if direction=='input' and name not in ('clk','rst_n'))
    body += '\n  always_ff @(posedge clk) begin\n'
    body += '\n'.join('    '+name+'_q <= '+name+';' for direction, kind, name in ports
                      if direction=='input' and name not in ('clk','rst_n'))
    body += '\n  end\n  conv_im2col_runtime_registers #('
    body += ','.join('.'+name+'('+name+')' for name in parameters)+') u_runtime(\n'
    body += ',\n'.join('    .'+name+'('+name+('_q' if direction=='input' and name not in ('clk','rst_n') else '')+')'
                        for direction, kind, name in ports)+'\n  );\nendmodule\n'
    wrapper.write_text(body)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    runtime_parameters = dict(zip(PARAMETERS, PROFILES[1 if args.lanes == 8 else 0]))
    runtime_parameters.update(p_row_high_width=27, p_cache_sets=16, p_cache_ways=2)
    frontend_parameters = dict(SIZE=16,SLOT_W=6,LANES=args.lanes,BUS_WIDTH=64,CACHE_SETS=16,
        CACHE_WAYS=2,LINE_BYTES=128,REGISTER_DESCRIPTOR=1,CACHE_RESPONSE_DEPTH=2)
    cases = {}
    for scope, top, inputs, values in (
        ('runtime', 'registered_runtime', [wrapper], runtime_parameters),
        ('frontend', 'conv_im2col_frontend', [ROOT/'rtl/npu/conv/conv_im2col_frontend.sv'], frontend_parameters)):
        for label in ('reference', 'current'):
            sources = ([reference] if label=='reference' else [])+inputs
            cases[scope+'_'+label] = dict(top=top, parameters=values,
                configuration=f'{args.lanes}通道卷积前端坐标保存，输入与输出均保留寄存边界',
                sources=list(map(str,resolve(sources,ROOT))),
                options=['-DSYNTHESIS=1','-DXILINX_FPGA=1',
                         *['-G'+name+'='+str(value) for name,value in values.items()]])
    case_file = out/'cases.json'
    case_file.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    resume = ['--resume'] if args.resume else []
    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',case_file,
        '--cases',*args.cases,'--out',out,'--through','pre_lut',*resume],cwd=ROOT,check=True)
    for name in args.cases:
        subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/name,
            '--out',out/(name+'_mapped'),'--mode','physical-cost','--delay-target-ps','6667',
            '--wire-delay-ps','300','--max-lut-inputs','8','--discard-abc9-temporaries',*resume],cwd=ROOT,check=True)


if __name__ == '__main__':
    main()
