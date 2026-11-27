#!/usr/bin/env python3
"""证明真实 RAM 越界预测覆盖所有地址、步长、突发类型和命令选择。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / 'rtl/soc/soc_axi_ram.sv'
    pattern = r'    (?:wire|logic) rd_issue_oob.*?(?=    wire rd_issue_fault)'
    region = re.search(pattern, source.read_text(), re.S).group(0)
    model_source = args.source_root / 'test/models/soc_axi_ram.sv'
    if re.search(pattern, model_source.read_text(), re.S).group(0) != region:
        raise RuntimeError('生产存储器与仿真存储器的越界计算不同')
    harness = out / 'formal.sv'
    harness.write_text('''module bound_formal #(parameter AW=32,DW=64,DP=32768)(
    input [AW:0] rd_byte_addr_q,rd_pipe_cmd_byte_addr,
    input [2:0] rd_size_active_q,
    input [1:0] rd_burst_active_q,
    input rd_pipe_cmd,rd_pipe_beat,
    output correct
);
    localparam BYTEW=DW/8;
    localparam ADDR_LSB=BYTEW<=1 ? 0 : $clog2(BYTEW);
    localparam WORD_ADDR_BITS=AW-ADDR_LSB;
    wire [AW:0] step=(AW+1)'(1) << rd_size_active_q;
    wire [AW:0] next_address=rd_burst_active_q==2'b00 ? rd_byte_addr_q :
        (rd_byte_addr_q & ~(step-(AW+1)'(1))) + step;
    wire [AW:0] selected_address=rd_pipe_cmd ? rd_pipe_cmd_byte_addr :
        (rd_pipe_beat ? next_address : rd_byte_addr_q);
    wire [WORD_ADDR_BITS:0] rd_issue_word_addr=selected_address[AW:ADDR_LSB];
''' + region + '''
    assign correct=rd_issue_oob == (rd_issue_word_addr >= (WORD_ADDR_BITS+1)'(DP));
endmodule
''')
    profiles = [(aw, dw, dp) for aw, dw in ((8, 8), (8, 64), (16, 32), (32, 32), (32, 64), (40, 128))
                for dp in (1, 3, 16, 32, 64, 128, 1024, 1031, 32768, 32769)]
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([harness], args.source_root)
    source_hashes = {str(path.relative_to(args.source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sources if path.is_relative_to(args.source_root)}
    summary = {'passed': False, 'inputs_constrained': False,
               'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'model_sha256': hashlib.sha256(model_source.read_bytes()).hexdigest(),
               'dependency_sha256': source_hashes,
               'profiles': []}
    for aw, dw, dp in profiles:
        name = f'aw{aw}_dw{dw}_dp{dp}'
        script = out / (name + '.ys')
        log = out / (name + '.log')
        script.write_text('read_verilog -sv ' + ' '.join(shlex.quote(str(path)) for path in sources) + '\n' +
                          f'chparam -set AW {aw} -set DW {dw} -set DP {dp} bound_formal\n' +
                          'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n' +
                          'prep -top bound_formal -flatten\ncheck -assert\n' +
                          'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in log.read_text()
        summary['profiles'].append({'address_width': aw, 'data_width': dw, 'memory_words': dp,
                                    'passed': passed})
        if not passed:
            raise RuntimeError(f'越界预测证明未通过：{log}')
    if any(hashlib.sha256((args.source_root / name).read_bytes()).hexdigest() != value
           for name, value in source_hashes.items()):
        raise RuntimeError('验证期间依赖源码发生变化')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(profiles)}))


if __name__ == '__main__':
    main()
