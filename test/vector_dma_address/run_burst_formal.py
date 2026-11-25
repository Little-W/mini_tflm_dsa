#!/usr/bin/env python3
"""检查实际向量突发长度编码的完整二值输入与四态行为。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/conv/vector_engine_address.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = SOURCE.read_text()
    reference = subprocess.check_output(['git', 'show',
        args.reference + ':rtl/npu/conv/vector_engine_address.sv'], cwd=ROOT, text=True)
    function = re.search(r'  function automatic logic \[7:0\] burst_length_from_bytes\b.*?endfunction',
                         current, re.S)[0]
    function = re.sub(r'\bp_bus_shift\b', 'BUS_SHIFT', function)
    function = re.sub(r'\bp_bus_bytes\b', 'BUS_BYTES', function)
    expression = re.search(r'burst_length_from_bytes\s*=\s*([^;]+);', reference)[1]
    expression = re.sub(r'\bp_bus_shift\b', 'BUS_SHIFT', expression)
    expression = re.sub(r'\bp_bus_bytes\b', 'BUS_BYTES', expression)
    shifts = (0, 1, 2, 3, 4, 5, 6, 8, 16, 24, 25, 31)
    report = {'passed': False, 'reference': args.reference, 'input_bits': 32,
              'inputs_constrained': False, 'source_sha256': digest(SOURCE), 'runs': []}
    model = f'''module burst_compare #(parameter integer BUS_SHIFT=3,
    parameter integer BUS_BYTES=1 << BUS_SHIFT)(
    input logic [31:0] value,
    output logic [7:0] expected, actual, output logic equal_result);
{function}
    assign expected = {expression};
    assign actual = burst_length_from_bytes(value);
    assign equal_result = expected == actual;
endmodule
'''
    model_path = out / 'model.sv'
    model_path.write_text(model)
    for shift in shifts:
        script = out / f'shift_{shift}.ys'
        log = out / f'shift_{shift}.log'
        script.write_text(f'read_slang --top burst_compare -GBUS_SHIFT={shift} '
                          f'{shlex.quote(str(model_path))}\n'
                          'prep -top burst_compare -flatten\nopt -full\n'
                          'sat -verify -prove equal_result 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            process = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                      '--worker', script], cwd=ROOT, stdout=stream,
                                     stderr=subprocess.STDOUT, check=False)
        passed = process.returncode == 0 and 'SUCCESS' in log.read_text()
        report['runs'].append({'bus_shift': shift, 'passed': passed, 'log_sha256': digest(log)})
        if not passed:
            raise RuntimeError(f'突发长度证明未完成：{log}')

    tb = out / 'four_state.sv'
    instances = '\n'.join(f'burst_compare #(.BUS_SHIFT({shift})) u_{index}'
        f'(.value(value),.expected(expected[{index}]),.actual(actual[{index}]),.equal_result());'
        for index, shift in enumerate(shifts))
    tb.write_text(f'''module tb;
    logic [31:0] value, random_value;
    wire [7:0] expected[{len(shifts)}], actual[{len(shifts)}];
    integer checked=0;
    {instances}
    task automatic compare;
        #1;
        for(integer profile=0;profile<{len(shifts)};profile=profile+1) begin
            if(expected[profile] !== actual[profile])
                $fatal(1,"burst encoding mismatch profile=%0d value=%h",profile,value);
            checked=checked+1;
        end
    endtask
    initial begin
        for(integer index=0;index<4096;index=index+1) begin
            value=$urandom; compare();
        end
        for(integer index=0;index<32;index=index+1) begin
            value=32'd1<<index;compare();value=value-1'b1;compare();
            random_value=$urandom;
            value=random_value;value[index]=1'bx;compare();
            value=random_value;value[index]=1'bz;compare();
        end
        value=0;compare();value='1;compare();value='x;compare();value='z;compare();
        $display("VECTOR_BURST_FOUR_STATE_PASS checks=%0d",checked);$finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    build = subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                            str(model_path), str(tb)], capture_output=True, text=True)
    (out / 'four_state_build.log').write_text(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError('四态测试编译未完成')
    run = subprocess.run(['vvp', str(binary)], capture_output=True, text=True)
    (out / 'four_state.log').write_text(run.stdout + run.stderr)
    count = re.search(r'VECTOR_BURST_FOUR_STATE_PASS checks=(\d+)', run.stdout)
    if run.returncode or count is None or digest(SOURCE) != report['source_sha256']:
        raise RuntimeError('突发编码四态检查未完成或源码已改变')
    report['four_state'] = {'passed': True, 'checks': int(count[1]),
                            'log_sha256': digest(out / 'four_state.log')}
    report['model_sha256'] = digest(model_path)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
