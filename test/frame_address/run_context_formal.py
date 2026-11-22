#!/usr/bin/env python3
"""Prove that captured frame parameters equal the actual scheduler's active command."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    top = ROOT / 'rtl/npu/top/npu_top.sv'
    scheduler = ROOT / 'rtl/npu/control/ps_window_scheduler.sv'
    text = top.read_text()
    first = text.index('        logic [31:0] frame_exec_rows,')
    last = text.index('        logic requant_group_ready;', first)
    capture = text[first:last]
    names = {'core_rst_n':'rst_n', 'frame_command_rows':'rows', 'frame_command_cols':'cols',
             'frame_command_p0':'p0', 'frame_command_column':'column0',
             'frame_command_init':'frame_init', 'frame_command_final':'frame_final'}
    for old, new in names.items():
        capture = capture.replace(old, new)
    capture = '    wire frame_command_start = command_valid && command_ready;\n' + capture
    property_text = '''
    assign formal_bad = command_active &&
        ({frame_exec_rows, frame_exec_cols, frame_exec_p0, frame_exec_column, frame_exec_init, frame_exec_final} !=
         {rows, cols, p0, column0, frame_init, frame_final});
'''
    modified = scheduler.read_text().replace('endmodule', capture + property_text + '\nendmodule', 1)
    marker = 'lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k);'
    if modified.count(marker) != 1:
        raise RuntimeError('Expected one scheduler output declaration')
    modified = modified.replace(marker, marker[:-2] + ',\n    output logic formal_bad);')
    actual = out / 'scheduler_context.sv'
    actual.write_text(modified)
    files = [actual, ROOT / 'rtl/common/onehot_check.sv', ROOT / 'rtl/common/regfile.v',
             ROOT / 'rtl/common/parallel_prefix_add.sv', ROOT / 'rtl/common/unsigned_compare.sv']
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (top, scheduler, *files[1:])},
                  extracted_sha256=digest(actual), inputs_constrained=False,
                  initialization='Reset on the first sampled cycle', runs=[])
    for size, frames, reuse in ((1,1,1), (4,3,4), (16,16,32), (16,16,0)):
        folder = out / f's{size}_f{frames}_r{reuse}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('read_slang -D ASIC_SYNTHESIS=1 --top ps_window_scheduler ' +
                          f'-GSIZE={size} -GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} ' +
                          shlex.join(map(str, files)) + '\n' +
                          'prep -top ps_window_scheduler -flatten\n' +
                          'delete -output */o:*\nexpose ps_window_scheduler/formal_bad\n' +
                          'opt -full\nmemory_map\nasync2sync\nopt -full\n' +
                          'sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 '
                          '-verify -prove formal_bad 0 -timeout 90\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Proof did not complete: {log}')
        report['runs'].append(dict(size=size, frames=frames, reuse=reuse, passed=True, log_sha256=digest(log)))
        print(f'size={size} frames={frames} reuse={reuse}: PASS', flush=True)
    if report['source_sha256'] != {
            str(p.relative_to(ROOT)): digest(p) for p in (top, scheduler, *files[1:])}:
        raise RuntimeError('Verification sources changed during execution')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
