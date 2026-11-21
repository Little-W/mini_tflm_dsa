#!/usr/bin/env python3
"""检查有序坐标比较器的完整二态输入和四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ((2, 1), (8, 4), (32, 0), (32, 3), (32, 4), (32, 5), (35, 4), (40, 4))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def helper(path, name):
    text = path.read_text()
    return text[text.index('module ia_ordered_coordinate_equal #('):].replace(
        'module ia_ordered_coordinate_equal #(', 'module ' + name + ' #(', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/loaders/ia_loader.sv'
    reference = args.reference_root.resolve() / 'rtl/npu/loaders/ia_loader.sv'
    common = [root / 'rtl/common/add_equal.sv', root / 'rtl/common/parallel_prefix_add.sv']
    hashes = {str(path): digest(path) for path in [source, reference, *common]}
    modules = out / 'coordinate_modules.sv'
    modules.write_text(helper(source, 'current_equal') + '\n' + helper(reference, 'reference_equal'))
    runs = []
    for width, low in PROFILES:
        for use_lut in (0, 1):
            name = f'w{width}_l{low}_u{use_lut}'
            proof = out / (name + '.sv')
            proof.write_text(f'''module proof(input logic [{width-1}:0] a,b,
input logic [{width-low-1}:0] target, output logic equivalent);
logic current_result,reference_result;
current_equal #(.p_width({width}),.p_low_width({low}),.p_use_lut({use_lut})) current_i
(.i_a(a),.i_b(b),.i_target(target),.o_equal(current_result));
reference_equal #(.p_width({width}),.p_low_width({low}),.p_use_lut({use_lut})) reference_i
(.i_a(a),.i_b(b),.i_target(target),.o_equal(reference_result));
assign equivalent=current_result==reference_result;
endmodule
''')
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top proof ' + shlex.join(map(str, [modules, *common, proof])) +
                '\nprep -top proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, timeout=180)
            passed = result.returncode == 0 and 'no model found: SUCCESS!' in log.read_text()
            runs.append(dict(width=width, low_width=low, use_lut=bool(use_lut), passed=passed,
                input_bits=3*width-low, log_sha256=digest(log)))
            if not passed:
                raise RuntimeError('Coordinate proof did not complete: ' + str(log))
    tb = out / 'four_state.sv'
    lines = ['module four_state;', 'logic [39:0] a,b,target;',
        'integer sample,bit_index,state_value,checks;', 'logic [15:0] results_current,results_reference;']
    for profile, (width, low) in enumerate(PROFILES):
        for use_lut in (0, 1):
            index = 2*profile+use_lut
            for label in ('current', 'reference'):
                lines += [f'{label}_equal #(.p_width({width}),.p_low_width({low}),.p_use_lut({use_lut})) u_{label}_{index}',
                    f'(.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_target(target[{width-low-1}:0]),.o_equal(results_{label}[{index}]));']
    lines += ['''function automatic logic four_digit(input integer value);
case(value) 0:four_digit=1'b0;1:four_digit=1'b1;2:four_digit=1'bx;default:four_digit=1'bz;endcase
endfunction
initial begin
checks=0;
for(sample=0;sample<1024;sample=sample+1)begin
 a='0;b='0;target='0;state_value=sample;
 for(bit_index=0;bit_index<2;bit_index=bit_index+1)begin a[bit_index]=four_digit(state_value%4);state_value=state_value/4;end
 for(bit_index=0;bit_index<2;bit_index=bit_index+1)begin b[bit_index]=four_digit(state_value%4);state_value=state_value/4;end
 target[0]=four_digit(state_value%4);
 #1;if(results_current!==results_reference)$fatal(1,"coordinate four-state mismatch");checks=checks+16;
end
for(sample=0;sample<20004;sample=sample+1)begin
 a={$urandom,$urandom};b={$urandom,$urandom};target={$urandom,$urandom};
 if(sample<4)begin
  for(bit_index=0;bit_index<40;bit_index=bit_index+1)begin a[bit_index]=four_digit(sample);b[bit_index]=four_digit(sample);target[bit_index]=four_digit(sample);end
 end else case(sample%5)
  1:a[$urandom_range(0,39)]=1'bx;
  2:b[$urandom_range(0,39)]=1'bz;
  3:target[$urandom_range(0,39)]=1'bx;
  4:for(bit_index=0;bit_index<40;bit_index=bit_index+1)begin a[bit_index]=four_digit($urandom_range(0,3));b[bit_index]=four_digit($urandom_range(0,3));target[bit_index]=four_digit($urandom_range(0,3));end
  default:;
 endcase
 #1;if(results_current!==results_reference)$fatal(1,"coordinate four-state mismatch");checks=checks+16;
end
$display("ORDERED_COORDINATE_PASS checks=%0d",checks);$finish;
end
endmodule
''']
    tb.write_text('\n'.join(lines))
    binary = out / 'four_state.vvp'
    compile_command = [shutil.which('iverilog') or '/home/agent/.local/bin/iverilog', '-g2012',
        '-s', 'four_state', '-o', str(binary), *map(str, [modules, *common, tb])]
    with (out / 'four_state_compile.log').open('w') as stream:
        subprocess.run(compile_command, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
    run = subprocess.run([shutil.which('vvp') or '/home/agent/.local/bin/vvp', str(binary)],
        text=True, capture_output=True, timeout=180, check=True)
    (out / 'four_state.log').write_text(run.stdout + run.stderr)
    expected_checks = (1024+20004)*16
    if f'checks={expected_checks}' not in run.stdout or hashes != {str(path): digest(path) for path in [source, reference, *common]}:
        raise RuntimeError('Coordinate check did not complete or source changed')
    report = dict(passed=True, source_sha256=hashes, binary_input_constraints=[], runs=runs,
        four_state=dict(passed=True, comparisons=expected_checks, exhaustive_input_bits=5,
            exhaustive_patterns=1024, additional_patterns=20004, values=['0','1','x','z']))
    (out / 'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, binary_proofs=len(runs), four_state_comparisons=expected_checks)))


if __name__ == '__main__':
    main()
