#!/usr/bin/env python3
"""比较实际偏置控制器的全部状态与输出，并证明准备阶段计算的消费条件。"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from common import ROOT, REFERENCE, CONTROL, HELPER, PROFILES, digest, snapshot


def run(folder, name, commands, success):
    script, log = folder / f'{name}.ys', folder / f'{name}.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=300)
    text = log.read_text()
    if result.returncode or success not in text:
        raise RuntimeError(text[-7000:])
    match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
    return {'passed': True, 'equivalent_bits': int(match[1]) if match else None,
            'script_sha256': digest(script), 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out / 'source', args.reference)
    helper = out / 'source' / HELPER
    observer = out / 'control_observer.sv'
    source = (out / 'source/current' / CONTROL).read_text()
    original = (out / 'source/reference' / CONTROL).read_text()
    registers = sorted(set(re.findall(r'\b(\w+)\s*<=', original)))
    assert source.count('endmodule') == 1
    observer.write_text(source.replace('endmodule', '''
  // 消费阶段的准备结果由实际状态更新导出，不限制外部配置或握手输入。
  always_comb begin
    assert(state <= S_NEXT_GROUP);
    assert(load_block_idx <= num_blocks);
    assert(current_block_idx <= num_blocks);
    assert(load_blocks_count <= count_t'(GROUP_BLOCKS_MAX));
    if (state >= S_INIT_MARK) begin
      assert(last_group_start_idx == ((num_blocks <= step_blocks_eff) ? count_t'(0) : count_t'(num_blocks - step_blocks_eff)));
    end
    if (state >= S_INIT_GROUP) begin
      assert(current_is_last_group == ((num_blocks == '0) || (current_block_idx >= last_group_start_idx)));
    end
    if ((state == S_INIT_GROUP) || (state == S_NEXT_GROUP) || (state == S_CMD)) begin
      assert(remaining_blocks == count_t'(num_blocks - load_block_idx));
    end
    if ((state == S_CMD) || (state == S_REQ) || (state == S_LOAD) || (state == S_WAIT)) begin
      assert(load_tail_offset == count_t'(load_blocks_count - count_t'(1)));
    end
    if (state == S_CMD) begin
      assert(remaining_blocks == count_t'(num_blocks - load_block_idx));
      assert(load_window_last == (count_t'(load_block_idx + load_blocks_count) >= num_blocks));
      assert(load_blocks_count == ((remaining_blocks < count_t'(GROUP_BLOCKS_MAX)) ? remaining_blocks : count_t'(GROUP_BLOCKS_MAX)));
    end
    if ((state == S_REQ) && tail_pending) begin
      assert(dma_base_addr == REG_WIDTH'(cfg_bias_base + (REG_WIDTH'(load_block_idx) << BLOCK_ADDR_SHIFT)));
      assert(load_blocks_count > count_t'(1));
      assert(load_tail_offset == count_t'(load_blocks_count - count_t'(1)));
    end
    if ((state == S_LOAD) && tail_pending) begin
      assert(load_blocks_count > count_t'(1));
      assert(tail_base_addr == REG_WIDTH'(cfg_bias_base +
          ((REG_WIDTH'(load_block_idx) + REG_WIDTH'(load_blocks_count) - 1) << BLOCK_ADDR_SHIFT)));
    end
  end
endmodule'''))
    models = {}
    for label, content in [('reference', original), ('current', observer.read_text())]:
        content = content.replace('    output logic                 switch_pending\n',
            '    output logic                 switch_pending,\n    output logic [4095:0] formal_state\n')
        assert 'output logic [4095:0] formal_state' in content
        content = content.replace('endmodule', '  assign formal_state = {' + ', '.join(registers) + '};\nendmodule')
        models[label] = out / (label + '_observed.sv')
        models[label].write_text(content)
    report = {'passed': False, 'inputs': inputs, 'external_input_assumptions': [],
              'initial_reset_for_invariants': True, 'profiles': []}
    for size, bus, register, count, groups in PROFILES:
        folder = out / f's{size}_b{bus}_r{register}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        options = f'-GSIZE={size} -GBUS_WIDTH={bus} -GREG_WIDTH={register} -GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups}'
        commands = []
        for label in ['reference', 'current']:
            commands += [f'read_slang --top bias_loader_ctrl {options} {shlex.quote(str(models[label]))} {shlex.quote(str(helper))}',
                         'prep -top bias_loader_ctrl -flatten', 'async2sync', 'opt_clean',
                         f'rename bias_loader_ctrl {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten reference current miter',
                     'prep -top miter -flatten', 'chformal -lower', 'opt -full',
                     'sat -seq 1 -tempinduct -maxsteps 20 -set-at 1 in_rst_n 0 -prove trigger 0 -prove-asserts -verify']
        equivalent = run(folder, 'equivalence', commands, 'SUCCESS')
        invariant = {'passed': True, 'method': 'proved with the complete state and output comparison',
                     'common_state_signals': len(registers)}
        row = {'SIZE': size, 'BUS_WIDTH': bus, 'REG_WIDTH': register,
               'COUNT_WIDTH': count, 'GROUP_BLOCKS_MAX': groups,
               'equivalence': equivalent, 'invariant': invariant, 'passed': True}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    assert digest(ROOT / HELPER) == inputs['common_helper']['sha256']
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
