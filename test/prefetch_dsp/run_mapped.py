#!/usr/bin/env python3
"""使用完整Xilinx器件模型比较预取映射网表与SYNTHESIS路径的RTL。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pyosys
from run_four_state import bench


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--cycles', type=int, default=4096)
    args = parser.parse_args()
    formal, out = args.formal.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((formal/'summary.json').read_text())
    profile = summary['profiles'][2]
    parameters = profile['parameters']
    ports = json.loads((formal/'profile_2/current_state.json').read_text())['modules']['current']['ports']
    candidate = formal/'sources/current/rtl/npu/conv/conv_im2col_prefetch.sv'
    reference = out/'reference_prefetch.sv'
    reference_text, count = re.subn(r'\bmodule\s+conv_im2col_prefetch\b', 'module reference_prefetch', candidate.read_text())
    if count != 1:
        raise RuntimeError('预取模块定义数量不符')
    reference.write_text(reference_text)
    text = bench(parameters, ports, args.cycles)
    parameter_text = ','.join(f'.{name}({value})' for name, value in parameters.items())
    text = text.replace(f'conv_im2col_prefetch #({parameter_text}) u_current', 'conv_im2col_prefetch u_current')
    start = text.index(' // 按位注入 X/Z')
    stop = text.index(' if(phases!==', start)
    text = text[:start]+text[stop:]
    text = text.replace('task automatic check_outputs;\n', 'task automatic check_outputs;\n if(cycles>=32) begin\n')
    text = text.replace(' samples=samples+1;\n', ' samples=samples+1;\n end\n')
    text = text.replace('PREFETCH_FOUR_STATE_PASS', 'PREFETCH_MAPPED_PASS')
    testbench = out/'tb.sv'
    testbench.write_text(text)
    sources = [formal/'sources/current'/name for name in summary['source_sha256']['current']
               if name != 'rtl/npu/conv/conv_im2col_prefetch.sv']
    library = Path(pyosys.__file__).resolve().parent/'share/xilinx/cells_sim.v'
    sources += [reference, args.mapped.resolve(), library, testbench]
    hashes = {str(path): digest(path) for path in sources}
    command = [args.verilator, '--binary', '--timing', '--top-module', 'tb',
               '-DSYNTHESIS=1', '-Wno-fatal', '--output-groups', '0', '-j', '1',
               '-CFLAGS', '-std=c++20 -O1', '--Mdir', str(out/'obj')]+list(map(str, sources))
    with (out/'build.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    with (out/'run.log').open('w') as log:
        subprocess.run([str(out/'obj/Vtb')], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    match = re.search(r'PREFETCH_MAPPED_PASS cycles=(\d+) samples=(\d+) outputs=(\d+) injections=0 phases=1fff', (out/'run.log').read_text())
    if not match:
        raise RuntimeError('完整映射输出比较未完成')
    if hashes != {str(path): digest(path) for path in sources}:
        raise RuntimeError('验证期间源码发生变化')
    report = dict(passed=True, parameters=parameters, cycles=int(match[1]), samples=int(match[2]),
                  warmup_cycles=32, output_ports=int(match[3]), output_bits=profile['output_bits'],
                  output_comparisons=int(match[2])*int(match[3]), all_phases_covered=True,
                  source_sha256=hashes, command=command, log_sha256=digest(out/'run.log'))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
