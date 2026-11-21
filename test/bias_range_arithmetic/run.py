#!/usr/bin/env python3
"""证明实际偏置范围组合逻辑，并检查严格四态行为。"""
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
SOURCE = Path('rtl/npu/loaders/bias_loader_buffer.sv')
REFERENCE = 'fe0ed2325743c9b353b74377fbe7b4a1e9d19d64'
WIDTHS = (1, 2, 3, 8, 12, 28, 29, 32)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def region(text):
    begin = text.index('  for (genvar request_i = 0; request_i < 2; request_i++) begin : g_range_request')
    end = text.index('  for (genvar b = 0;', begin)
    return text[begin:end]


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       cwd=ROOT, check=True, timeout=180)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (args.source_root / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    def surrounding(text):
        text = text.replace(region(text), 'RANGE_COMPARISON')
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
        return re.sub(r'\s+', '', text)
    if surrounding(current) != surrounding(reference):
        raise ValueError('范围计算之外的缓冲区逻辑存在差异')
    models = []
    for label, source in [('reference', reference), ('current', current)]:
        (out / (label + '_source.sv')).write_text(source)
        path = out / (label + '.sv')
        path.write_text(f'''module range_{label} #(parameter W=29)(
    input wire [W-1:0] load_request_idx, current_block_idx, group_blocks_needed,
    input wire [1:0][W:0] bank_end_q,
    output wire [1:0][1:0] window_end_valid
);
    localparam CNT_W=W;
    localparam RANGE_WIDTH=W+1;
''' + region(source) + 'endmodule\n')
        models.append(path)
    helper = args.source_root / 'rtl/common/parallel_prefix_add.sv'
    miter = out / 'proof.sv'
    miter.write_text('''module proof #(parameter W=29)(
    input wire [W-1:0] load_request_idx, current_block_idx, group_blocks_needed,
    input wire [1:0][W:0] bank_end_q,
    output wire correct
);
    wire [1:0][1:0] a,b;
    range_reference #(.W(W)) r(load_request_idx,current_block_idx,group_blocks_needed,bank_end_q,a);
    range_current #(.W(W)) c(load_request_idx,current_block_idx,group_blocks_needed,bank_end_q,b);
    assign correct = a == b;
endmodule
''')
    bench = out / 'four_state.sv'
    bench.write_text('''module four_state;
    parameter integer W=29;
    localparam integer BITS=5*W+2;
    reg [BITS-1:0] inputs;
    wire [1:0][1:0] a,b;
    wire [W-1:0] load_request_idx, current_block_idx, group_blocks_needed;
    wire [1:0][W:0] bank_end_q;
    assign {bank_end_q,group_blocks_needed,current_block_idx,load_request_idx}=inputs;
    range_reference #(.W(W)) r(load_request_idx,current_block_idx,group_blocks_needed,bank_end_q,a);
    range_current #(.W(W)) c(load_request_idx,current_block_idx,group_blocks_needed,bank_end_q,b);
    reg [31:0] random_state=32'h793fea25;
    integer sample,bit_index,choice;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value=value^(value<<13);
            next_value=next_value^(next_value>>17);
            step=next_value^(next_value<<5);
        end
    endfunction
    initial begin
        for(sample=0;sample<20000;sample=sample+1) begin
            for(bit_index=0;bit_index<BITS;bit_index=bit_index+1) begin
                random_state=step(random_state);
                choice=sample<5000?int'(random_state[0]):int'(random_state[1:0]);
                case(choice)
                    0:inputs[bit_index]=1'b0;
                    1:inputs[bit_index]=1'b1;
                    2:inputs[bit_index]=1'bx;
                    3:inputs[bit_index]=1'bz;
                endcase
            end
            #1;
            if(a!==b) $fatal(1,"Bias range differs at sample %0d",sample);
        end
        $display("BIAS_RANGE_FOUR_STATE_PASS samples=20000 comparisons=80000");
        $finish;
    end
endmodule
''')
    report = {'passed': False, 'reference_ref': args.reference_ref,
              'source_sha256': {label: digest(out / (label + '_source.sv'))
                                for label in ('reference', 'current')},
              'helper_sha256': digest(helper), 'inputs_constrained': False,
              'surrounding_logic_unchanged': True, 'runs': []}
    for width in WIDTHS:
        script, log = out / f'w{width}.ys', out / f'w{width}.log'
        script.write_text(f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top proof -GW={width} ' +
            ' '.join(shlex.quote(str(path)) for path in models + [miter, helper]) +
            '\nprep -top proof -flatten\nopt_clean\ncheck -assert\n' +
            'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
        text = execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in text:
            raise RuntimeError('范围比较证明未完成')
        binary = out / f'w{width}.vvp'
        execute(['iverilog', '-g2012', '-s', 'four_state', f'-Pfour_state.W={width}',
                 '-o', str(binary), *map(str, models), str(helper), str(bench)],
                out / f'w{width}_four_build.log')
        four_log = out / f'w{width}_four.log'
        text = execute(['vvp', str(binary)], four_log)
        if 'BIAS_RANGE_FOUR_STATE_PASS' not in text:
            raise RuntimeError('四态检查未完成')
        row = {'width': width, 'input_bits': 5 * width + 2, 'passed': True,
               'four_state_samples': 20000, 'four_state_comparisons': 80000,
               'formal_log_sha256': digest(log), 'four_state_log_sha256': digest(four_log)}
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
