#!/usr/bin/env python3
"""使用实际引擎与检查器状态证明配置消费时的完整范围值。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'test'))
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import process_tree_rss


def run_limited(script, log, command=None):
    command = command or [sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                          '--worker', str(script)]
    started, peak = time.monotonic(), 0
    with log.open('w') as output:
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        while process.poll() is None:
            peak = max(peak, process_tree_rss(process.pid))
            if peak > 500*1024*1024:
                process.terminate()
                process.wait()
                raise RuntimeError('形式检查超过 500 MiB 进程内存限制')
            time.sleep(0.1)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    return {'elapsed_seconds': round(time.monotonic()-started, 2),
            'peak_process_tree_rss_bytes': peak, 'rss_limit_mib': 500,
            'script': script.name, 'log': log.name}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_ranges(source):
    begin = source.index('  logic [32:0] dma_range_size [4];')
    end = source.index('  always_comb begin', begin)
    arithmetic = source[begin:end]
    begin = source.index('    for (int i=0;i<4;i++) begin dma_range_base[i]=0;', end)
    end = source.index('\n  assign rd_req', begin)
    selection = '  always_comb begin\n'+source[begin:end]
    text = '  logic [31:0] proof_expected_base[4];\n  logic [32:0] proof_expected_end[4];\n'+arithmetic+selection
    for old, new in (('dma_range_base', 'proof_expected_base'), ('dma_range_end', 'proof_expected_end'),
                     ('dma_range_size', 'proof_expected_size'), ('unused_dma_range_carry', 'proof_unused_range_carry'),
                     ('g_dma_range_end', 'g_expected_range_end')):
        text = re.sub(r'\b'+old+r'\b', new, text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    parser.add_argument('--bus-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/vector_engine.sv'
    original = read_rtl_source(args.reference+':rtl/npu/conv/vector_engine.sv', cwd=ROOT, text=True)
    body = source.read_text().replace('module vector_engine #(', 'module checked_ranges_control #(', 1)
    checker = (ROOT/'rtl/npu/conv/vector_config_check.sv').read_text()
    state_names = re.search(r'typedef enum logic \[3:0\] \{(.*?)\} state_t;', checker, re.S)[1]
    state_names = [item.strip() for item in state_names.split(',')]
    properties = (HERE/'properties.sv.inc').read_text()
    declarations = ''
    for state_name in ('IDLE', 'CALCULATE', 'CAPTURE', 'FIELDS', 'RANGE_SELECT', 'RANGE_ADD',
                       'RANGE_COMPARE', 'COMPLETE'):
        index = state_names.index(state_name)
        constant = 'PROOF_'+state_name
        declarations += f"  localparam logic [3:0] {constant} = 4'd{index};\n"
        properties = properties.replace('u_config_check.'+state_name, constant)
    body = body.replace('endmodule', original_ranges(original)+declarations+properties+'\nendmodule', 1)
    proof = out/'control.sv'; proof.write_text(body)
    conv = ROOT/'rtl/npu/conv'
    sources = [conv/'conv_im2col_pkg.sv', conv/'vector_engine_pkg.sv']
    sources += [path for path in sorted(conv.glob('*.sv')) if path not in sources and path != source]
    sources += list(sorted((ROOT/'rtl/common').glob('*.v')))+list(sorted((ROOT/'rtl/common').glob('*.sv')))
    script = out/'prepare.ys'
    script.write_text('read_slang -j 1 -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top checked_ranges_control '+
        f'-GTILE=16 -GPE_COUNT=8 -GBUS_WIDTH={args.bus_width} '+
        ' '.join(shlex.quote(str(path)) for path in sources+[proof])+f'''
delete -output checked_ranges_control/w:*
prep -top checked_ranges_control -flatten
async2sync
setattr -unset keep
opt -full
chformal -lower
opt_clean
write_json {out}/control.json
''')
    stages = {'prepare': run_limited(script, out/'prepare.log')}
    command = [sys.executable, str(HERE/'control_worker.py'), str(out)]
    command_path = out/'worker.command.json'; command_path.write_text(json.dumps(command)+'\n')
    stages['formal'] = run_limited(command_path, out/'formal.log', command=command)
    summary = json.loads((out/'summary.json').read_text())
    checked = sources+[source, Path(__file__).resolve(), HERE/'control_worker.py', HERE/'properties.sv.inc']
    summary.update(bus_width=args.bus_width, reference=args.reference,
                   reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
                   source_sha256={str(path.relative_to(ROOT)):sha(path) for path in checked}, stages=stages)
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed':summary['passed'],'bus_width':args.bus_width,'stages':stages}),flush=True)


if __name__ == '__main__':
    main()
