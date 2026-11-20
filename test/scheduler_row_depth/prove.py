#!/usr/bin/env python3
"""证明帧调度器的行准备结果、全部状态、公开输出和存储操作逐周期一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/control/ps_window_scheduler.sv'
HELPERS = ['rtl/common/onehot_check.sv', 'rtl/common/parallel_prefix_add.sv']
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument(source, registers, current):
    marker = 'lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k);'
    assert source.count(marker) == 1
    source = source.replace(marker, '''lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k,
    input wire [FRAME_COUNT*(32-$clog2(SIZE))-1:0] formal_frame_k_data,
    input wire [4095:0] formal_metadata_data,
    output wire [4095:0] formal_state,
    output wire [4095:0] formal_memory_ports);''')
    marker = '    logic [TILE_W-1:0] frame_k [FRAME_COUNT];'
    assert source.count(marker) == 1
    source = source.replace(marker, '''    wire [TILE_W-1:0] frame_k [FRAME_COUNT];
    for(genvar formal_frame=0; formal_frame<FRAME_COUNT; formal_frame++) begin:g_formal_k
        assign frame_k[formal_frame]=formal_frame_k_data[formal_frame*TILE_W+:TILE_W];
    end''')
    pattern = re.compile(r'    regfile #\(.*?\n    \);', re.S)
    blocks = pattern.findall(source)
    assert len(blocks) == 1 and ') u_frame_metadata (' in blocks[0]
    source = pattern.sub('    assign frame_metadata_o_rd_data = formal_metadata_data[2*p_metadata_width-1:0];', source)
    pattern = re.compile(r'    always_ff @\(posedge clk\) begin\n        if \(command_active && command_complete\) begin\n            frame_k\[active_id\] <=.*?\n        end\n    end', re.S)
    assert len(pattern.findall(source)) == 1
    frame_k_write = re.search(r'frame_k\[active_id\] <= (.*?);', pattern.search(source)[0])[1]
    source = pattern.sub('', source)
    observed = [name if name != 'target' else "(((phase == OPENING) || (phase == SWEEPING) || (phase == DRAINING)) ? target : (ID_W+1)'(0))" for name in registers]
    observations = '    assign formal_state = {' + ', '.join(observed) + '};\n'
    observations += '''    assign formal_memory_ports = {
        frame_metadata_i_wr_en,frame_metadata_i_wr_mask,frame_metadata_i_wr_addr,
        frame_metadata_i_wr_data,frame_metadata_i_rd_en,frame_metadata_i_rd_addr,
        (command_active && command_complete),active_id,
        (FRAME_K_WRITE_EXPRESSION)};
'''
    observations = observations.replace('FRAME_K_WRITE_EXPRESSION', frame_k_write)
    if current:
        observations += '''    // 存储返回每周期可任意变化，状态关系直接由实际更新逻辑导出。
    always_comb begin
        assert(stream_rows_remaining == (cfg_stream - row_base));
        if ((phase == PREPARE_PRODUCTS) || (phase == PREPARE_TARGET) ||
            (phase == OPENING) || (phase == SWEEPING) || (phase == DRAINING)) begin
            assert(next_stream_rows_remaining == (stream_rows_remaining - 32'(current_rows)));
            assert(row_group_complete == ((row_base + 32'(current_rows)) == cfg_stream));
        end
    end
'''
        if 'selected_initial_offset' in source:
            observations += '''    always_comb begin
        if (!command_active && !command_buffer_valid && candidate_ready && candidate_init)
            assert(selected_initial_offset == next_slice_offset);
    end
'''
        if 'prepare_rows_last_value' in source:
            observations += '''    always_comb begin
        if (phase == PREPARE_PARTS)
            assert(prepare_rows_last == (PART_MATH_W'(prepare_rows) - PART_MATH_W'(1)));
    end
'''
    return source.replace('endmodule', observations + 'endmodule', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--profiles', nargs='+', default=['1:1:1', '4:3:4', '16:16:32', '16:16:0', '16:17:64'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    registers = sorted(set(re.findall(r'\b(\w+)\s*<=', original.split('endmodule', 1)[0])))
    assert 'frame_k' not in registers
    for label, source in [('reference', original), ('current', current)]:
        (out / f'{label}.sv').write_text(instrument(source, registers, label == 'current'))
    helpers = []
    for name in HELPERS:
        path = out / Path(name).name
        path.write_bytes((ROOT / name).read_bytes())
        helpers.append(path)
    report = {'passed': False, 'reference_commit': args.reference,
              'source': SOURCE, 'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'helper_sha256': {name: digest(ROOT / name) for name in HELPERS},
              'input_assumptions': [], 'initial_reset': True,
              'initial_state_relation': 'all original state signals start equal; unreset values remain arbitrary',
              'memory_relation': 'common arbitrary frame K words and metadata return each cycle; all read/write ports compared',
              'common_state_signals': len(registers),
              'target_comparison': 'every cycle in OPENING, SWEEPING and DRAINING; every public output and all other original state signals are compared in every phase',
              'profiles': []}
    for profile in args.profiles:
        size, frames, reuse = map(int, profile.split(':'))
        name = f's{size}_f{frames}_r{reuse}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        commands = []
        for label in ['reference', 'current']:
            sources = [out / f'{label}.sv'] + helpers
            commands += [f'read_slang --top ps_window_scheduler -D SYNTHESIS=1 -GSIZE={size} '
                         f'-GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} ' +
                         ' '.join(shlex.quote(str(path)) for path in sources),
                         'prep -top ps_window_scheduler -flatten', 'async2sync', 'opt_clean',
                         f'rename ps_window_scheduler {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -make_outcmp -flatten reference current miter',
                     'prep -top miter -flatten', 'chformal -lower', 'opt -full',
                     'sat -seq 1 -tempinduct -maxsteps 16 -set-at 1 in_rst_n 0 -set-at 1 cmp_formal_state 1 -prove trigger 0 -prove-asserts -verify']
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=240)
        text = log.read_text()
        assert result.returncode == 0 and 'SUCCESS' in text, text[-6000:]
        row = {'SIZE': size, 'FRAME_COUNT': frames, 'MAX_REUSE_TILES': reuse,
               'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    assert (ROOT / SOURCE).read_text() == current
    assert report['helper_sha256'] == {name: digest(ROOT / name) for name in HELPERS}
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
