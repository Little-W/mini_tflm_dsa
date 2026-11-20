#!/usr/bin/env python3
"""用实际偏置控制器检查四态握手与未采样配置输入的逐周期行为。"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import ROOT, REFERENCE, CONTROL, HELPER, PARAMETERS, digest, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out / 'source', args.reference)
    original = (out / 'source/reference' / CONTROL).read_text()
    registers = sorted(set(re.findall(r'\b(\w+)\s*<=', original)))
    ports = re.findall(r'^\s*(input|output)\s+logic\s+(\[[^\]]+\]\s*)?(\w+)\s*,?\s*$',
                       original[:original.index(');')], re.M)
    assert ports and ports[0][2] == 'clk'
    files = []
    for label in ['reference', 'current']:
        content = (out / 'source' / label / CONTROL).read_text()
        content = re.sub(r'\bbias_loader_ctrl\b', 'bias_loader_' + label, content)
        content = content.replace('    output logic                 switch_pending\n',
            '    output logic                 switch_pending,\n    output logic [4095:0] formal_state\n')
        assert 'output logic [4095:0] formal_state' in content
        content = content.replace('endmodule', '  assign formal_state = {' + ', '.join(registers) + '};\nendmodule')
        path = out / f'{label}.sv'
        path.write_text(content)
        files.append(path)
    declarations = []
    for direction, width, name in ports:
        if direction == 'input':
            declarations.append(f'  logic {width or ""} {name};')
        else:
            declarations += [f'  wire {width or ""} {label}_{name};' for label in ['reference', 'current']]
    declarations += ['  wire [4095:0] reference_state, current_state;']
    parameters = ','.join(f'.{k}({v})' for k, v in PARAMETERS.items() if k != 'DATA_WIDTH')
    instances = []
    for label in ['reference', 'current']:
        connections = ','.join(f'.{name}({name if direction == "input" else label + "_" + name})'
                               for direction, _, name in ports)
        instances.append(f'  bias_loader_{label} #({parameters}) u_{label}({connections},.formal_state({label}_state));')
    output_names = [name for direction, _, name in ports if direction == 'output'] + ['state']
    reference_result = '{' + ','.join('reference_' + name for name in output_names) + '}'
    current_result = '{' + ','.join('current_' + name for name in output_names) + '}'
    bench = out / 'tb.sv'
    bench.write_text('module tb;\n' +
        '\n'.join(f'  localparam {key}={value};' for key, value in PARAMETERS.items()) + '\n' +
        '\n'.join(declarations + instances) + f'''
  integer seed=32'h3d24a618;
  integer cycles=0, accepted_configs=0, unknown_handshake_cycles=0;
  always #5 clk=~clk;
  initial begin
    clk=0;rst_n=0;init_cfg=0;bias_base=0;m=0;bias_step_blocks=0;
    bias_switch=0;bias_last_loop=0;load_bias_granted=0;dma_busy=0;dma_done=0;
    load_block_valid=0;load_block_bank=0;
    repeat(2) @(negedge clk);
    for(integer sample_i=0;sample_i<32768;sample_i=sample_i+1) begin
      rst_n=(sample_i%257)!=0;
      init_cfg=($random(seed)&31)==0;
      bias_base=$random(seed);m=$random(seed);bias_step_blocks=$random(seed);
      if(sample_i%7==0) m=32'(sample_i%1025);
      if(sample_i%5==0) bias_step_blocks=32'(sample_i%65);
      if(sample_i%11==0) bias_base=0;
      bias_switch=$random(seed);bias_last_loop=$random(seed);
      load_bias_granted=$random(seed);dma_busy=$random(seed);dma_done=$random(seed);
      load_block_valid=$random(seed);load_block_bank=$random(seed);
      if(init_cfg && rst_n) accepted_configs=accepted_configs+1;
      if(!init_cfg) begin
        bias_base[sample_i%32]=1'bx;
        m[(sample_i/3)%32]=1'bz;
        bias_step_blocks[(sample_i/7)%32]=1'bx;
      end
      if(sample_i%4==0) begin
        case((sample_i/4)%8)
          0:load_bias_granted=1'bx;
          1:load_bias_granted=1'bz;
          2:dma_done=1'bx;
          3:load_block_valid=1'bz;
          4:load_block_bank=1'bx;
          5:bias_switch=1'bx;
          6:bias_last_loop=1'bz;
          7:dma_busy=1'bx;
        endcase
        unknown_handshake_cycles=unknown_handshake_cycles+1;
      end
      @(posedge clk);#1;cycles=cycles+1;
      if({reference_result} !== {current_result})
        $fatal(1,"Four-state state/output mismatch cycle=%0d",sample_i);
      @(negedge clk);
    end
    $display("FOUR_STATE_PASS cycles=%0d accepted_configs=%0d unknown_handshake_cycles=%0d",
             cycles,accepted_configs,unknown_handshake_cycles);
    $finish;
  end
endmodule
''')
    executable = out / 'simulation.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable)] + \
              [str(p) for p in files] + [str(out / 'source' / HELPER), str(bench)]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.run(['vvp', str(executable)], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'FOUR_STATE_PASS cycles=(\d+) accepted_configs=(\d+) unknown_handshake_cycles=(\d+)', result.stdout)
    assert result.returncode == 0 and match, result.stdout + result.stderr
    report = {'passed': True, 'inputs': inputs, 'parameters': PARAMETERS,
              **dict(zip(['cycles', 'accepted_configs', 'unknown_handshake_cycles'], map(int, match.groups()))),
              'common_state_signals': len(registers), 'all_public_outputs_compared_each_cycle': True,
              'sampled_configuration': 'binary values covering the complete input widths',
              'unknown_inputs': 'X/Z handshake controls and configuration bits when init_cfg is zero',
              'universal_four_state_equivalence_claimed': False,
              'source_sha256': {p.name: digest(p) for p in files + [bench]},
              'build_command': command, 'build_log_sha256': digest(out / 'build.log'),
              'run_log_sha256': digest(out / 'run.log')}
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    assert digest(ROOT / HELPER) == inputs['common_helper']['sha256']
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['passed', 'cycles', 'accepted_configs', 'unknown_handshake_cycles']}))


if __name__ == '__main__':
    main()
