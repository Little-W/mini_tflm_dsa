#!/usr/bin/env python3
"""证明实际双模式 DMA 的生产数据排列性质。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOP = 'axi_dual_block_dma'
ACTUAL = (
    'rtl/npu/conv/conv_im2col_pkg.sv',
    'rtl/npu/dma/axi_dual_block_dma.sv',
    'rtl/npu/dma/axi_linear_block_dma.sv',
    'rtl/common/regfile.v',
    'rtl/common/add_equal.sv',
)
ABSTRACT = (
    'rtl/npu/conv/conv_im2col_frontend.sv',
    'rtl/npu/dma/conv_window_queue.sv',
    'rtl/npu/dma/axi_write_page_guard.sv',
    'rtl/npu/conv/conv_axi_read_guard.sv',
    'rtl/npu/conv/conv_axi_read_mux.sv',
)
PROPERTIES = '''
    // 输出无效周期也检查格式与列起点、通道掩码的对应关系。
    (* keep *) logic layout_s8_aligned, layout_s16_lanes;
    (* keep *) logic layout_linear_s8_aligned, layout_linear_s16_lanes;
    assign layout_s8_aligned = wr_use_16bits || !(|wr_col_base[2:0]);
    assign layout_s16_lanes = !wr_use_16bits ||
        !(wr_valid[4] || wr_valid[5] || wr_valid[6] || wr_valid[7]);
    assign layout_linear_s8_aligned = linear_use_16bits || !(|linear_col[2:0]);
    assign layout_linear_s16_lanes = !linear_use_16bits ||
        !(linear_valid[4] || linear_valid[5] || linear_valid[6] || linear_valid[7]);
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=(16, 64))
    args = parser.parse_args()
    out = args.out.resolve()
    snapshots = out / 'sources'
    snapshots.mkdir(parents=True, exist_ok=True)
    hashes = {}
    paths = []
    for source in (*ACTUAL, *ABSTRACT):
        data = (ROOT / source).read_bytes()
        hashes[source] = sha(data)
        text = data.decode()
        if source in ABSTRACT:
            # 独立输出每周期任意变化，覆盖该模块所有状态及输入产生的输出集合。
            start = text.index('module ')
            end = text.index(');', start) + 2
            text = '(* blackbox *) ' + text[start:end] + '\nendmodule\n'
        elif source == ACTUAL[1]:
            text = text.replace('\nendmodule', PROPERTIES + '\nendmodule', 1)
        target = snapshots / Path(source).name
        target.write_text(text)
        paths.append(target)
    report = {
        'passed': True,
        'source_sha256': hashes,
        'snapshot_sha256': {path.name: sha(path.read_bytes()) for path in paths},
        'driver_sha256': sha(Path(__file__).read_bytes()),
        'actual_modules': [Path(source).stem for source in ACTUAL[1:]],
        'unconstrained_output_modules': [Path(source).stem for source in ABSTRACT],
        'external_input_constraints': {'rst_n': '0 on the first sampled clock; arbitrary afterwards'},
        'initial_state': 'arbitrary defined values before the first reset clock',
        'properties': {
            's8': 'wr_use_16bits == 0 implies wr_col_base[2:0] == 0',
            's16': 'wr_use_16bits == 1 implies wr_valid[7:4] == 0',
            'qualification': 'every cycle following the first reset clock, including invalid output cycles',
        },
        'profiles': [],
    }
    for size in args.sizes:
        if size < 8:
            raise ValueError('The production-layout proof requires SIZE >= 8')
        folder = out / f'size_{size}'
        folder.mkdir(exist_ok=True)
        script = folder / 'run.ys'
        options = f'-GSIZE={size} -GIM2COL_SIZE=16 -GBUS_WIDTH=64 -GDATA_WIDTH=16 -GREG_WIDTH=32'
        script.write_text(
            f'read_slang --top {TOP} -D SYNTHESIS=1 -D XILINX_FPGA=1 '
            '-D YOSYS=1 -D VERIFIC=1 ' + options + ' ' +
            ' '.join(shlex.quote(str(path)) for path in paths) + '\n' +
            f'prep -top {TOP} -flatten\n' +
            f'delete -output {TOP}/w:*\n' +
            f'expose {TOP}/w:layout_*\n' +
            'cutpoint -blackbox\nmemory_map\nasync2sync\nopt -full\nopt_clean -purge\n' +
            f'select -module {TOP}\nstat\n' +
            'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 '
            '-set-def-inputs -set-def-formal -set-init-def '
            '-prove layout_s8_aligned 1 -prove layout_s16_lanes 1 '
            '-prove layout_linear_s8_aligned 1 -prove layout_linear_s16_lanes 1 -verify\n' +
            'sat -seq 1 -tempinduct-inductonly -maxsteps 1 '
            '-set-def-inputs -set-def-formal -set-init-def '
            '-prove layout_s8_aligned 1 -prove layout_s16_lanes 1 '
            '-prove layout_linear_s8_aligned 1 -prove layout_linear_s16_lanes 1 -verify\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        passed = (result.returncode == 0 and 'Induction step proven: SUCCESS!' in text
                  and 'SAT proof finished - no model found: SUCCESS!' in text)
        entry = {
            'SIZE': size, 'IM2COL_SIZE': 16, 'BUS_WIDTH': 64, 'DATA_WIDTH': 16,
            'passed': passed, 'reset_base_steps': 2, 'induction_steps': 1,
            'script_sha256': sha(script.read_bytes()),
            'log_sha256': sha(log.read_bytes()),
        }
        report['profiles'].append(entry)
        report['passed'] = all(profile['passed'] for profile in report['profiles'])
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(entry), flush=True)
        if not passed:
            print(text[-6000:])
            raise SystemExit(1)
    assert hashes == {source: sha((ROOT / source).read_bytes()) for source in hashes}


if __name__ == '__main__':
    main()
