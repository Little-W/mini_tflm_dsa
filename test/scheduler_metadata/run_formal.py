#!/usr/bin/env python3
"""比较帧调度器公开输出、寄存状态和每一项帧元数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source
SOURCE = 'rtl/npu/control/ps_window_scheduler.sv'


def instrument(text, label):
    old = 'output logic [31:0] lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k);'
    new = '''output logic [31:0] lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k,
    output wire [31:0] formal_frame_column [FRAME_COUNT],
    output wire [31:0] formal_frame_row_part [FRAME_COUNT],
    output wire [31:0] formal_frame_rows [FRAME_COUNT]);'''
    assert text.count(old) == 1
    text = text.replace(old, new)
    body = '    for (genvar frame=0; frame<FRAME_COUNT; frame++) begin : g_formal_metadata\n'
    if 'u_frame_metadata' in text:
        values = ('u_frame_metadata.mem[frame][p_metadata_width-1 -: TILE_W]',
                  'u_frame_metadata.mem[frame][ROW_COUNT_W +: ROW_PART_W]',
                  'u_frame_metadata.mem[frame][ROW_COUNT_W-1:0]')
    else:
        values = ('frame_column[frame]', 'frame_row_part[frame]', 'frame_rows[frame]')
    for field, value in zip(('column', 'row_part', 'rows'), values):
        body += f"      assign formal_frame_{field}[frame] = 32'({value});\n"
    text = text.replace('endmodule', body + '    end\nendmodule', 1)
    # 候选组合值只在命令寄存器的实际使能边沿比较；全部公开输出继续逐周期比较。
    for name in ('candidate_column', 'candidate_row', 'candidate_rows', 'candidate_cols'):
        text = re.sub(r'\b' + name + r'\b', label + '_' + name, text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='954ed7c9')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', text=True)
    current = (ROOT / SOURCE).read_text()
    for label, text in (('reference', original), ('current', current)):
        (out / f'{label}.sv').write_text(instrument(text, label))
    results = []
    for size, frames, reuse in ((1,1,1), (4,3,4), (16,16,32), (16,16,0), (16,17,64)):
        commands = []
        for label in ('reference', 'current'):
            paths = [out / f'{label}.sv', ROOT / 'rtl/common/onehot_check.sv', ROOT / 'rtl/common/regfile.v']
            commands += [f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top ps_window_scheduler '
                         f'-GSIZE={size} -GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} ' + ' '.join(map(str,paths)),
                         'prep -top ps_window_scheduler -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename ps_window_scheduler {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current proof', 'hierarchy -top proof',
                     'equiv_simple -seq 1', 'equiv_induct -seq 4', 'equiv_simple -seq 1', 'equiv_status -assert']
        script = out / f's{size}_f{frames}_r{reuse}.ys'; log = script.with_suffix('.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        results.append({'size':size, 'frames':frames, 'max_reuse_tiles':reuse, 'passed':True,
                        'equivalent_bits':int(match[1]), 'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
        print(json.dumps(results[-1]), flush=True)
    assert current == (ROOT / SOURCE).read_text()
    report = {'passed':True, 'reference':args.reference, 'inputs_constrained':False,
              'all_public_outputs_compared':True, 'all_metadata_compared':True, 'profiles':results,
              'source_sha256':hashlib.sha256(current.encode()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
