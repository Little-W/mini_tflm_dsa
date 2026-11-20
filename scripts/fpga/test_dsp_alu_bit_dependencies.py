#!/usr/bin/env python3
"""使用官方 DSP48E1 模型证明纯 ALU 的高位不影响低位结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model_file = out / 'dsp48e1.sv'
    model_file.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S) + '\n')
    registers = ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG', 'PREG', 'ACASCREG',
                 'BCASCREG', 'INMODEREG', 'OPMODEREG', 'ALUMODEREG', 'CARRYINREG', 'CARRYINSELREG')
    settings = ','.join('.' + name + '(0)' for name in registers)
    pins = ','.join('.' + name + "(1'b0)" for name in (
        'CLK', 'CEA1', 'CEA2', 'CEB1', 'CEB2', 'CEC', 'CED', 'CEAD', 'CEM', 'CEP',
        'CEINMODE', 'CECTRL', 'CEALUMODE', 'CECARRYIN', 'RSTA', 'RSTB', 'RSTC', 'RSTD',
        'RSTM', 'RSTP', 'RSTINMODE', 'RSTCTRL', 'RSTALUMODE', 'RSTALLCARRYIN',
        'CARRYCASCIN', 'MULTSIGNIN'))
    wrapper = f'''module observed_alu(
    input [47:0] ab, c, input carry, input [3:0] mode,
    output [47:0] p, pc
);
DSP48E1 #({settings},.USE_MULT("NONE"),.USE_DPORT("FALSE"),.USE_SIMD("ONE48"),
    .A_INPUT("DIRECT"),.B_INPUT("DIRECT")) u_dsp (
    .A(ab[47:18]),.B(ab[17:0]),.C(c),.D(25'd0),.ACIN(30'd0),.BCIN(18'd0),.PCIN(48'd0),
    .OPMODE(7'b0110011),.INMODE(5'd0),.CARRYINSEL(3'd0),.ALUMODE(mode),.CARRYIN(carry),
    .P(p),.PCOUT(pc),{pins});
endmodule
'''
    harness = out / 'formal.sv'
    harness.write_text(wrapper + '''module dsp_low_bits_formal #(parameter WIDTH=1)(
    input [47:0] ab, c, alternate_ab, alternate_c,
    input carry, input [3:0] mode
);
    localparam [47:0] MASK=48'hffffffffffff >> (48-WIDTH);
    wire [47:0] changed_ab=(ab & MASK) | (alternate_ab & ~MASK);
    wire [47:0] changed_c=(c & MASK) | (alternate_c & ~MASK);
    wire [47:0] first_p,first_pc,second_p,second_pc;
    observed_alu first(.ab(ab),.c(c),.carry(carry),.mode(mode),.p(first_p),.pc(first_pc));
    observed_alu second(.ab(changed_ab),.c(changed_c),.carry(carry),.mode(mode),.p(second_p),.pc(second_pc));
    always @* begin
        assert(first_p[WIDTH-1:0] == second_p[WIDTH-1:0]);
        assert(first_pc[WIDTH-1:0] == second_pc[WIDTH-1:0]);
        assert(first_p == first_pc);
    end
endmodule
''')
    summary = {'passed': False, 'primitive_library_sha256': digest(library),
               'primitive_model_sha256': digest(model_file), 'test_sha256': digest(Path(__file__)),
               'analyzer_sha256': digest(HERE / 'netlist_metrics.py'),
               'mode': {'USE_MULT': 'NONE', 'USE_SIMD': 'ONE48', 'OPMODE': '0110011',
                        'CARRYINSEL': '000', 'INMODE': '00000'},
               'arbitrary_input_bits': 197, 'ALUMODE_constrained': False,
               'high_operand_bits_independent': True, 'runs': []}
    for width in range(1, 49):
        script, log_path = out / f'width_{width}.ys', out / f'width_{width}.log'
        script.write_text('read_verilog -formal -sv -D VERIFIC ' +
                          ' '.join(shlex.quote(str(p)) for p in (model_file, harness)) + '\n' +
                          f'chparam -set WIDTH {width} dsp_low_bits_formal\n' +
                          'prep -top dsp_low_bits_formal -flatten\nchformal -lower\nopt -full\n' +
                          'sat -verify -prove-asserts -set-def-inputs -show-inputs\n')
        with log_path.open('w') as log:
            result = subprocess.run([sys.executable, str(HERE / 'open_fpga_synth.py'), '--worker', str(script)],
                                    stdout=log, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode or 'SAT proof finished - no model found: SUCCESS!' not in log_path.read_text():
            raise RuntimeError(log_path.read_text()[-10000:])
        item = {'low_bits': width, 'passed': True, 'log_sha256': digest(log_path)}
        summary['runs'].append(item)
        print(json.dumps(item), flush=True)
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
