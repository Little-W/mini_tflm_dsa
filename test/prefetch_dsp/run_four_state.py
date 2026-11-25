#!/usr/bin/env python3
"""比较完整预取模块的全部公开输出，并覆盖输入未知值与高阻态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bench(parameters, ports, cycles):
    inputs = {name: len(port['bits']) for name, port in ports.items()
              if port['direction'] == 'input' and name != 'i_clk'}
    outputs = {name: len(port['bits']) for name, port in ports.items()
               if port['direction'] == 'output'}
    width = sum(inputs.values())
    declarations = ['logic i_clk;']
    for name, bits in inputs.items():
        declarations.append(('conv_im2col_pkg::conv_cfg_t ' if name == 'i_c'
                             else f'logic [{bits-1}:0] ') + name + ';')
    for name, bits in outputs.items():
        declarations.append(f'logic [{bits-1}:0] reference_{name}, current_{name};')
    connections = {label: [] for label in ('reference', 'current')}
    for name, port in ports.items():
        for label in connections:
            value = f'{label}_{name}' if port['direction'] == 'output' else name
            connections[label].append(f'.{name}({value})')
    parameter_text = ','.join(f'.{name}({value})' for name, value in parameters.items())
    instances = '\n'.join(f'{module} #({parameter_text}) u_{label}(\n' +
                          ',\n'.join(connections[label]) + ');'
                          for label, module in (('reference', 'reference_prefetch'),
                                                ('current', 'conv_im2col_prefetch')))
    comparison = '\n'.join(f'if(reference_{name} !== current_{name}) '
                          f'$fatal(1,"output {name} mismatch at sample %0d",samples);'
                          for name in outputs)
    return '''module tb;
''' + '\n'.join(declarations) + f'''
localparam integer INPUT_BITS={width};
logic [((INPUT_BITS+31)/32)*32-1:0] random_bits;
logic [INPUT_BITS-1:0] input_bits;
integer seed=32'h57b28416;
integer samples=0;
integer cycles=0;
integer injected=0;
logic [12:0] phases='0;
''' + instances + '''
// 每次检查包含数据、有效位、预取阶段及所有引用字段。
task automatic check_outputs;
''' + comparison + '''
 samples=samples+1;
 if ((^current_o_prefetch_phase !== 1'bx) && current_o_prefetch_phase<=12)
   phases[current_o_prefetch_phase]=1'b1;
endtask

task automatic tick;
 i_clk=1'b0;#2;check_outputs();
 i_clk=1'b1;#2;check_outputs();
 i_clk=1'b0;#2;check_outputs();
 cycles=cycles+1;
endtask

task automatic randomize_inputs(input integer step);
 for(integer word=0;word<(INPUT_BITS+31)/32;word=word+1)
   random_bits[word*32+:32]=$random(seed);
''' + ' {' + ','.join(inputs) + '''}=random_bits[INPUT_BITS-1:0];
 i_rst_n=1'b1;
 i_cfg_valid=1'b0;
 i_cfg_ready=1'b1;
 i_cache_port_valid=1'b1;
 i_cache_port_ready=1'b1;
 i_c.prefetch_enable=1'b1;
 if(step%64<32) begin
   i_c.windowed=1'b1;
   i_c.input_w=16'd16;i_c.input_h=16'd8;i_c.input_c=16'd16;
   i_c.group_c=16'd16;i_c.kernel_w=16'd3;i_c.kernel_h=16'd3;
   i_c.stride_h=16'd1;i_c.stride_w=16'd1;
   i_c.dilation_h=16'd1;i_c.dilation_w=16'd1;
   i_c.output_w=16'd14;i_c.output_h=16'd6;
 end
 if(step%97==0) i_cfg_valid=1'b1;
 if(step%131==0) begin i_cache_port_valid=1'b0;i_cache_port_ready=1'b0;end
 if(step%257==0) i_rst_n=1'b0;
endtask

initial begin
 i_clk=1'b0;
''' + ' {' + ','.join(inputs) + '''}='0;
 tick();
 for(integer step=0;step<''' + str(cycles) + ''';step=step+1) begin
   randomize_inputs(step);tick();
 end
 // 按位注入 X/Z，配置与握手端口也参与检查。
 for(integer bit_index=0;bit_index<INPUT_BITS;bit_index=bit_index+1) begin
   for(integer state_index=0;state_index<2;state_index=state_index+1) begin
     randomize_inputs(bit_index*2+state_index);
''' + '     input_bits={' + ','.join(inputs) + '''};
     input_bits[bit_index]=state_index==0 ? 1'bx : 1'bz;
''' + '     {' + ','.join(inputs) + '''}=input_bits;
     tick();injected=injected+1;
   end
 end
 if(phases!==13'h1fff) $fatal(1,"phase coverage incomplete: %h",phases);
 $display("PREFETCH_FOUR_STATE_PASS cycles=%0d samples=%0d outputs=''' + str(len(outputs)) + ''' injections=%0d phases=%h",cycles,samples,injected,phases);
 $finish;
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=4096)
    args = parser.parse_args()
    formal, out = args.formal.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((formal/'summary.json').read_text())
    relative = 'rtl/npu/conv/conv_im2col_prefetch.sv'
    for name in summary['source_sha256']['reference']:
        if name != relative and summary['source_sha256']['reference'][name] != summary['source_sha256']['current'][name]:
            raise RuntimeError('参考与当前实现的依赖不同：'+name)
    sources = [formal/'sources/current'/name for name in summary['source_sha256']['current']]
    hashes = {str(path): digest(path) for path in sources}
    reference_text = (formal/'sources/reference'/relative).read_text()
    reference_text, count = re.subn(r'\bmodule\s+conv_im2col_prefetch\b',
                                    'module reference_prefetch', reference_text)
    if count != 1:
        raise RuntimeError('预取参考模块定义数量不符')
    reference = out/'reference_prefetch.sv'
    reference.write_text(reference_text)
    results = []
    for index, profile in enumerate(summary['profiles']):
        folder = out/f'profile_{index}'
        folder.mkdir(exist_ok=True)
        ports = json.loads((formal/f'profile_{index}/current_state.json').read_text())['modules']['current']['ports']
        testbench = folder/'tb.sv'
        testbench.write_text(bench(profile['parameters'], ports, args.cycles))
        executable = folder/'simv'
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable)] + list(map(str, sources)) + [str(reference), str(testbench)]
        with (folder/'compile.log').open('w') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        with (folder/'run.log').open('w') as log:
            subprocess.run(['vvp', str(executable)], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=240)
        match = re.search(r'PREFETCH_FOUR_STATE_PASS cycles=(\d+) samples=(\d+) outputs=(\d+) injections=(\d+) phases=1fff', (folder/'run.log').read_text())
        if not match:
            raise RuntimeError('四态输出比较未完成：'+str(folder))
        record = dict(parameters=profile['parameters'], passed=True, cycles=int(match[1]),
                      samples=int(match[2]), output_ports=int(match[3]), injections=int(match[4]),
                      compared_output_bits=profile['output_bits'], all_phases_covered=True,
                      bench_sha256=digest(testbench), log_sha256=digest(folder/'run.log'))
        results.append(record)
        print(json.dumps(record), flush=True)
    if hashes != {str(path): digest(path) for path in sources}:
        raise RuntimeError('验证期间源码发生变化')
    report = dict(passed=True, source_sha256=summary['source_sha256'], profiles=results,
                  total_cycles=sum(row['cycles'] for row in results),
                  total_samples=sum(row['samples'] for row in results),
                  total_output_comparisons=sum(row['samples']*row['output_ports'] for row in results),
                  total_injected_bits=sum(row['injections'] for row in results))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
