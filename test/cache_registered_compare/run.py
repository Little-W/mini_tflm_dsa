#!/usr/bin/env python3
"""验证缓存查询字段和分组比较寄存在同一边沿的完整接口行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path('rtl/npu/dma/cache')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instance(module, output):
    return f'''{module} #(.p_set_width(SI), .p_capture_range(CAPTURE)) u_{output} (
    .clk(clk), .i_request(request), .i_fg_state(state),
    .i_request_count(occupied), .i_req_fire(fire), .i_lookup_input_valid(valid),
    .i_preview_source_select(preview), .i_work_word(work_word), .i_demand_word(demand_word),
    .i_expected_set(expected_set), .i_base(base), .i_end(bound),
    .i_request_range(request_range), .i_head_range(head_range),
`ifndef SYNTHESIS
    .i_reference(reference_bits),
`endif
    .o_request({output}[OBS-1:4]), .o_work_word_matches({output}[3]),
    .o_work_snapshot_matches({output}[2]), .o_demand_word_matches({output}[1]),
    .o_response_snapshot_ready({output}[0]));
'''


def model():
    return '''module comparison #(parameter SI=7, CAPTURE=1,
    parameter IN=268+2*SI, OBS=135+SI)(
    input logic clk, input logic [IN-1:0] stimulus,
    output logic equivalent, output logic four_state_equal);
    logic [130+SI:0] request;
    logic [1:0] state;
    logic occupied, fire, valid, preview, request_range, head_range;
    logic [29:0] work_word, demand_word;
    logic [SI-1:0] expected_set;
    logic [31:0] base, bound;
    logic [4:0] reference_bits;
    logic [OBS-1:0] expected, actual;
    assign {request,state,occupied,fire,valid,preview,work_word,demand_word,
            expected_set,base,bound,request_range,head_range,reference_bits}=stimulus;
''' + instance('reference_fields', 'expected') + instance('conv_cache_snapshot_fields', 'actual') + '''
    assign equivalent = expected == actual;
    assign four_state_equal = expected === actual;
endmodule
'''


def bench():
    return '''module tb;
    parameter SI=7, CAPTURE=1;
    localparam IN=268+2*SI;
    logic clk=0;
    logic [IN-1:0] stimulus;
    logic [31:0] random_state=32'hc35e2971;
    wire equivalent, four_state_equal;
    integer checks=0;
    comparison #(.SI(SI),.CAPTURE(CAPTURE)) dut(.*);
    task automatic tick;
        clk=0; #1; clk=1; #1;
        if (four_state_equal !== 1'b1) $fatal(1,"Snapshot mismatch check=%0d input=%h",checks,stimulus);
        checks++; clk=0;
    endtask
    initial begin
        for (integer sample=0; sample<32; sample++) begin
            for (integer bit_index=0; bit_index<IN; bit_index++) begin
                random_state=random_state ^ (random_state << 13);
                random_state=random_state ^ (random_state >> 17);
                random_state=random_state ^ (random_state << 5);
                stimulus[bit_index]=random_state[0];
            end
            if (sample%4==0) stimulus='0;
            if (sample%4==1) stimulus='1;
            tick();
            for (integer bit_index=0; bit_index<IN; bit_index++) begin
                stimulus[bit_index]=1'bx; tick();
                stimulus[bit_index]=1'bz; tick();
                stimulus[bit_index]=random_state[bit_index%32];
            end
        end
        stimulus='x; tick(); stimulus='z; tick();
        $display("PASS checks=%0d",checks); $finish;
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    parser.add_argument('--candidate-fields', type=Path, default=ROOT / CACHE / 'conv_cache_snapshot_fields.sv')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = []
    for name in ('conv_cache_snapshot_equal.sv', 'conv_cache_snapshot_fields.sv'):
        text = subprocess.check_output(['git', 'show', f'{args.reference}:{CACHE / name}'], cwd=ROOT, text=True)
        reference.append(text.replace('conv_cache_snapshot_equal', 'reference_equal').replace(
            'conv_cache_snapshot_fields', 'reference_fields'))
    files = [args.candidate_fields.resolve(), ROOT / CACHE / 'conv_cache_registered_equal.sv',
             ROOT / CACHE / 'conv_cache_snapshot_range.sv']
    files += sorted((ROOT / 'rtl/common').glob('*.sv'))
    hashes = {str(path): digest(path) for path in files}
    source = out / 'comparison.sv'
    source.write_text('\n'.join(reference) + '\n' + model())
    testbench = out / 'tb.sv'
    testbench.write_text(bench())
    report = {'reference_commit': args.reference, 'input_constraints': [],
              'source_sha256': hashes, 'formal': [], 'four_state': []}
    for width in (1, 4, 7, 8):
        for capture in (0, 1):
            name = f's{width}_capture{capture}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text(f'read_slang -DSYNTHESIS=1 --top comparison -GSI={width} -GCAPTURE={capture} ' +
                shlex.join(map(str, [source] + files)) + '\nprep -top comparison -flatten\ncheck -assert\n' +
                'sat -seq 2 -prove-skip 1 -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            if 'SUCCESS!' not in log.read_text():
                raise RuntimeError(f'形式验证未完成：{log}')
            report['formal'].append({'set_width': width, 'capture_range': capture, 'passed': True})
    for capture in (0, 1):
        binary = out / f'four_state_{capture}.vvp'
        with (out / f'compile_{capture}.log').open('w') as log:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', f'-Ptb.CAPTURE={capture}', '-o', str(binary),
                            str(source), *map(str, files), str(testbench)], stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, check=True, timeout=120)
        (out / f'four_state_{capture}.log').write_text(result.stdout + result.stderr)
        if 'PASS checks=' not in result.stdout:
            raise RuntimeError('四态执行检查未完成')
        report['four_state'].append({'capture_range': capture, 'checks': 32*(1+2*282)+2, 'passed': True})
    for name, expected in hashes.items():
        if digest(Path(name)) != expected:
            raise RuntimeError(f'验证期间源码发生变化：{name}')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
