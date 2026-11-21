#!/usr/bin/env python3
"""检查 SoC 存储器从请求选择到末拍标志的完整组合表达式。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'rtl/soc/soc_axi_ram.sv')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text()
    selection = re.search(r'    wire \[7:0\] rd_issue_beat.*?(?=    wire \[AW:0\] rd_issue_byte_addr)',
                          source, re.S).group(0)
    result = re.search(r'    \(\* keep = 1 \*\) logic rd_current_last.*?(?=    wire \[1:0\] rd_issue_resp)',
                       source, re.S).group(0)
    result = result.replace('rd_len_q[rd_rd_ptr_q]', 'queue_len')
    declaration = '''module read_selection(
    input wire rd_pipe_cmd, rd_pipe_cmd_from_queue, rd_pipe_beat,
    input wire [7:0] rd_beat_q, rd_len_active_q, queue_len, s_axi_arlen,
    output wire current_result, reference_result
);
    wire [7:0] rd_pipe_cmd_len = rd_pipe_cmd_from_queue ? queue_len : s_axi_arlen;
'''
    harness = out / 'read_selection.sv'
    harness.write_text(declaration + selection + result + '''
    assign current_result = rd_issue_last;
    assign reference_result = (rd_issue_beat == rd_issue_len);
endmodule
module proof(input [34:0] inputs, output correct);
    wire current_result, reference_result;
    read_selection u_selection(inputs[0], inputs[1], inputs[2],
        inputs[10:3], inputs[18:11], inputs[26:19], inputs[34:27],
        current_result, reference_result);
    assign correct = current_result == reference_result;
endmodule
''')
    script = out / 'proof.ys'
    script.write_text('read_verilog -sv -DSYNTHESIS=1 ' + shlex.quote(str(harness)) + '\n' +
                      'prep -top proof -flatten\ncheck -assert\n' +
                      'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
    log = out / 'proof.log'
    text = execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], log)
    if 'SAT proof finished - no model found: SUCCESS!' not in text:
        raise RuntimeError('末拍选择证明未完成')
    bench = out / 'four_state.sv'
    bench.write_text('''module four_state;
    reg [34:0] inputs;
    wire current_result, reference_result;
    integer test_index, bit_index, choice;
    reg [31:0] random_state = 32'h5a19cb37;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value = value ^ (value << 13);
            next_value = next_value ^ (next_value >> 17);
            step = next_value ^ (next_value << 5);
        end
    endfunction
    read_selection dut(inputs[0], inputs[1], inputs[2],
        inputs[10:3], inputs[18:11], inputs[26:19], inputs[34:27],
        current_result, reference_result);
    initial begin
        for (test_index = 0; test_index < 100000; test_index = test_index + 1) begin
            for (bit_index = 0; bit_index < 35; bit_index = bit_index + 1) begin
                random_state = step(random_state);
                choice = test_index < 20000 ? int'(random_state[0]) : int'(random_state[1:0]);
                case (choice)
                    0: inputs[bit_index] = 1'b0;
                    1: inputs[bit_index] = 1'b1;
                    2: inputs[bit_index] = 1'bx;
                    3: inputs[bit_index] = 1'bz;
                endcase
            end
            #1;
            if (current_result !== reference_result)
                $fatal(1, "Read selection mismatch at sample %0d", test_index);
        end
        $display("READ_SELECTION_FOUR_STATE_PASS samples=100000");
        $finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    execute(['iverilog', '-g2012', '-s', 'four_state', '-o', str(binary),
             str(harness), str(bench)], out / 'four_state_build.log')
    four_log = out / 'four_state.log'
    text = execute(['vvp', str(binary)], four_log)
    if 'READ_SELECTION_FOUR_STATE_PASS' not in text:
        raise RuntimeError('末拍选择四态检查未完成')
    report = {'passed': True, 'source_sha256': digest(args.source),
              'test_source_sha256': digest(Path(__file__)),
              'formal': {'passed': True, 'input_bits': 35, 'inputs_constrained': False,
                         'synthesis_expression': True, 'log_sha256': digest(log)},
              'four_state': {'passed': True, 'comparisons': 100000,
                             'log_sha256': digest(four_log)}}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
