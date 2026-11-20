#!/usr/bin/env python3
"""提取实际范围检查表达式，证明任意地址、长度和分配区间的快速通路条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/conv_axi_read_guard.sv'


def decode(source, name, address_width, data_width):
    if 'assign request_addr_ext' in source:
        start = source.index('    assign request_addr_ext')
        declarations = ('logic [32:0] request_addr_ext;\nlogic request_page_fits;\n'
                        'logic [0:0] fast_allocation;\n')
        if 'logic request_format_legal;' in source:
            declarations += 'logic request_format_legal;\nlogic direct_legal;\n'
        if 'p_fpga_page_range' in source:
            declarations += "localparam bit p_fpga_page_range = 1'b0;\n"
    else:
        start = source.index('    always_comb begin\n        request_end')
        declarations = 'logic [32:0] request_end;\n'
    end = source.index("        lane = '0;", start)
    body = source[start:end] + '    end\n'
    # 四个分配区间使用相同的谓词，分别证明单个区间后按逻辑或合并。
    body = re.sub(r'(?<=<)4(?=;)', '1', body)
    return f'''module {name} (
  input logic enable,
  input logic [{address_width-1}:0] s_araddr,
  input logic [7:0] s_arlen,
  input logic [2:0] s_arsize,
  input logic [1:0] s_arburst,
  input logic [31:0] base_q[1],
  input logic [32:0] end_q[1],
  output logic fast_legal
);
localparam int ADDR_W={address_width}, DATA_W={data_width};
localparam int BUS_BYTES=DATA_W/8, BUS_SHIFT=$clog2(BUS_BYTES);
{declarations}{body}
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='aa2ef9a3')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    # 范围谓词之外，字节选择与全部寄存器更新保持相同；完整输出另由状态等价检查覆盖。
    selection = "        lane = '0;"
    state = '    always_ff @(posedge clk or negedge rst_n) begin'
    old_start, current_start = old.index(selection), current.index(selection)
    old_end = old.index('\n    end\n', old_start)
    current_end = current.index('\n    end\n', current_start)
    if old[old_start:old_end] != current[current_start:current_end]:
        raise AssertionError('byte-selection logic changed')
    if old[old.index(state):] != current[current.index(state):]:
        raise AssertionError('register or state-transition logic changed')
    (out / 'reference.sv').write_text(old)
    (out / 'current.sv').write_text(current)
    results = []
    cases = [(32, width) for width in (16, 32, 64, 128, 256)]
    cases += [(width, data) for width in (16, 33, 40) for data in (32, 64)]
    for address_width, data_width in cases:
        case = out / f'a{address_width}_d{data_width}'
        case.mkdir(exist_ok=True)
        miter = case / 'range_miter.sv'
        miter.write_text(decode(old, 'range_reference', address_width, data_width) +
                         decode(current, 'range_current', address_width, data_width) + f'''
module range_miter (
  input logic enable,
  input logic [{address_width-1}:0] s_araddr,
  input logic [7:0] s_arlen,
  input logic [2:0] s_arsize,
  input logic [1:0] s_arburst,
  input logic [31:0] base_q[1],
  input logic [32:0] end_q[1],
  output logic equivalent
);
  logic old_fast, new_fast;
  range_reference u_reference (.fast_legal(old_fast), .*);
  range_current u_current (.fast_legal(new_fast), .*);
  assign equivalent = old_fast == new_fast;
endmodule
''')
        script = case / 'run.ys'
        script.write_text('read_slang --top range_miter ' + shlex.quote(str(miter)) + '\n' +
                          'prep -top range_miter -flatten\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        log_path = case / 'proof.log'
        with log_path.open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log_path.read_text():
            raise AssertionError(f'SAT success marker missing: {case}')
        results.append({'ADDR_W': address_width, 'DATA_W': data_width, 'passed': True})
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(old.encode()).hexdigest(),
              'scope': 'single allocation predicate for every input bit pattern; four predicates combine by OR',
              'registers_unchanged': True, 'byte_selection_unchanged': True, 'inputs_constrained': False,
              'configurations': results}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('GUARD_RANGE_EQUIVALENCE_PASS', len(results), out / 'summary.json')


if __name__ == '__main__':
    main()
