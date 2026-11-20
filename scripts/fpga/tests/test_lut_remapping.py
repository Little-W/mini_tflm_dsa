#!/usr/bin/env python3
"""用寄存乘加与移位设计验证映射、组合等价及检查点复用。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

DESIGN = '''module lut_remapping_case(
    input wire clk,
    input wire [24:0] a,
    input wire [17:0] b,
    input wire [31:0] c,
    input wire [3:0] shift,
    output reg [31:0] q
);
reg signed [24:0] a_q;
reg signed [17:0] b_q;
reg [31:0] c_q;
reg [3:0] shift_q;
wire signed [42:0] product = a_q * b_q;
wire [31:0] selected = (product[31:0] ^ c_q) + {14'd0,b_q};
always @(posedge clk) begin
    a_q <= a;
    b_q <= b;
    c_q <= c;
    shift_q <= shift;
    q <= (selected << shift_q) ^ {c_q[15:0],c_q[31:16]};
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parents[1]
    (folder / 'design.sv').write_text(DESIGN)
    cases = {'case': {'top': 'lut_remapping_case', 'options': [], 'sources': ['design.sv'],
                      'configuration': 'Registered multiply, add and variable shift'}}
    (folder / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    command = [sys.executable, str(scripts / 'open_fpga_synth.py'), '--case-config', str(folder / 'cases.json'),
               '--source-root', str(folder), '--cases', 'case', '--out', str(folder / 'prepared'), '--through', 'pre_lut']
    with (folder / 'prepare.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    source = folder / 'prepared/case'
    results = {}
    for name, mode, options in [('native-xaiger1', 'native-xaiger1', []),
                                ('physical-cost', 'physical-cost', []),
                                ('legacy', 'legacy', []),
                                ('small-lut-cost', 'physical-cost', ['--small-lut-area-cost', '0.75'])]:
        output = folder / name
        command = [sys.executable, str(scripts / 'remap_fpga_luts.py'), '--source', str(source),
                   '--out', str(output), '--mode', mode] + options
        with (folder / (name + '.log')).open('w') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        result = json.loads((output / 'summary.json').read_text())
        assert result['functional_verification']['passed']
        assert result['resources']['dsp48e1'] == 1
        assert result['longest_register_path_cells'] > 0
        results[name] = {'passed': True, 'resources': result['resources'],
                         'longest_register_path_cells': result['longest_register_path_cells']}
    output = folder / 'physical-cost'
    stage = (output / 'mapping_stage.json').read_bytes()
    command = [sys.executable, str(scripts / 'remap_fpga_luts.py'), '--source', str(source),
               '--out', str(output), '--mode', 'physical-cost', '--resume']
    with (folder / 'resume.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    assert stage == (output / 'mapping_stage.json').read_bytes()
    checkpoint = source / 'pre_lut.il'
    original = checkpoint.read_bytes()
    checkpoint.write_bytes(original + b'\n')
    try:
        rejected = subprocess.run(command, capture_output=True, text=True)
        assert rejected.returncode != 0 and 'differs from its saved stage digest' in rejected.stderr
    finally:
        checkpoint.write_bytes(original)
    results['checkpoint_checks'] = {'identical_mapping_stage_reused': True, 'modified_input_rejected': True,
                                     'source_sha256': hashlib.sha256(original).hexdigest()}
    (folder / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps({key: item.get('passed', True) for key, item in results.items()}))


if __name__ == '__main__':
    main()
