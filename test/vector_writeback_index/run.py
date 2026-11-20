#!/usr/bin/env python3
"""验证写回索引寄存器、有效数据周期和实际 FPGA 字节输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_writeback.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7254ced6')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--formal-only', action='store_true')
    parser.add_argument('--numeric-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'xilinx_models.sv'
    primitive = re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0)
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', primitive, flags=re.S) + '\n')
    old = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    registers = ['state', 'base_address', 'total_bytes', 'written_bytes',
                 'lane_offset', 'byte_output', 'burst_length']
    sources = {}
    invariant = '''
  localparam int p_check_width = $clog2(4*TILE+2*BUS_BYTES);
  wire [p_check_width-1:0] check_byte = p_check_width'(BUS_BYTES) +
      p_check_width'(written_bytes) - p_check_width'(lane_offset);
  wire [BUS_BYTES-1:0] check_groups_equal;
  for (genvar bank=0; bank<BUS_BYTES; bank++) begin : g_check_groups
    assign check_groups_equal[bank] = group_index_q[bank] ==
        GROUP_INDEX_WIDTH'(GROUP_INDEX_WIDTH'(check_byte >> BUS_SHIFT) +
          GROUP_INDEX_WIDTH'(BUS_SHIFT'(bank) < check_byte[BUS_SHIFT-1:0]));
  end
  assign formal_invariant = (state != REQUEST && state != DATA) ||
      (first_bank == check_byte[BUS_SHIFT-1:0] && (&check_groups_equal));
'''
    for label, content in [('reference', old), ('current', current)]:
        content, count = re.subn(r'input wire src_wready, wr_done, wr_error\s*\n',
                                'input wire src_wready, wr_done, wr_error,\n'
                                '  output wire [4095:0] formal_state,\n'
                                '  output wire formal_invariant\n', content, count=1)
        if count != 1:
            raise ValueError('Writeback output declaration differs')
        # 无效周期的数据不参与接口比较；全部有效周期比较每个数据位。
        content = content.replace('assign src_wdata=rotation_stage[BUS_SHIFT];',
                                  "assign src_wdata=src_wvalid ? rotation_stage[BUS_SHIFT] : '0;")
        relation = invariant if label == 'current' else "assign formal_invariant = 1'b1;\n"
        content = content.replace('endmodule', 'assign formal_state = {' + ', '.join(registers) +
                                  '};\n' + relation + '\nendmodule', 1)
        path = out / (label + '_formal.sv')
        path.write_text(content)
        sources[label] = path
    raw = out / 'current.sv'
    raw.write_text(current)
    report = dict(reference_ref=args.reference, source_sha256=digest(raw),
                  reference_sha256=hashlib.sha256(old.encode()).hexdigest(),
                  primitive_library_sha256=digest(library), primitive_model_sha256=digest(model),
                  public_data_comparison='All data bits whenever src_wvalid is asserted',
                  control_comparison='All other public outputs and original state at every cycle',
                  formal=[], numeric=[])
    if not args.numeric_only:
        for tile, bus, fpga in [(8, 32, True), (16, 32, True), (16, 64, True),
                                (16, 128, True), (32, 64, True), (16, 64, False)]:
            folder = out / f'formal_t{tile}_b{bus}_{"fpga" if fpga else "generic"}'
            folder.mkdir(exist_ok=True)
            commands = []
            defines = '-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC' if fpga else '-D ASIC_SYNTHESIS'
            for label, path in sources.items():
                commands += [f'read_slang --top vector_writeback -GTILE={tile} -GBUS_WIDTH={bus} {defines} ' +
                             ' '.join(shlex.quote(str(p)) for p in [path, model]),
                             'prep -top vector_writeback -flatten', 'memory_map', 'async2sync', 'opt_clean',
                             'rename vector_writeback ' + label, 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'miter -equiv -flatten reference current miter', 'prep -top miter -flatten',
                         'sat -verify -prove trigger 0 -tempinduct -seq 1 -set-init-zero '
                         '-set-at 1 in_rst_n 0 -maxsteps 4']
            script, log = folder / 'run.ys', folder / 'formal.log'
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                      '--worker', str(script)], cwd=ROOT, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=180)
            if run.returncode or 'SUCCESS' not in log.read_text():
                raise RuntimeError(log.read_text()[-6000:])
            item = dict(tile=tile, bus_width=bus, fpga=fpga, passed=True,
                        compared_state_signals=len(registers), log_sha256=digest(log),
                        input_constraint='Reset is active at the first edge; all later inputs are unconstrained')
            report['formal'].append(item)
            print(json.dumps(item), flush=True)
    if not args.formal_only:
        main_cpp = ROOT / 'test/vector_writeback_rotation/main.cpp'
        for bus in [32, 64, 128]:
            folder = out / f'sim{bus}'
            folder.mkdir(exist_ok=True)
            command = [args.verilator, '--cc', '--exe', '--build', '--assert', '--timing', '-Wno-fatal', '-j', '1',
                       '--top-module', 'vector_writeback', '-DXILINX_FPGA', '-DNPU_SIM_ASSERT',
                       '-GTILE=16', f'-GBUS_WIDTH={bus}', '--Mdir', str(folder / 'obj'),
                       '--output-groups', '0', '--output-split', '12000',
                       '-CFLAGS', f'-std=c++20 -O1 -DTEST_BUS_WIDTH={bus} -fsanitize=undefined -fno-sanitize-recover=all',
                       '-LDFLAGS', '-fsanitize=undefined',
                       '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O1 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
                       str(raw), str(model), str(main_cpp)]
            with (folder / 'compile.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            binary = folder / 'obj/Vvector_writeback'
            run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
            (folder / 'run.log').write_text(run.stdout + run.stderr)
            item = json.loads(run.stdout.strip().splitlines()[-1])
            if not item['passed']:
                raise RuntimeError('Numeric comparison incomplete')
            item.update(binary_sha256=digest(binary), log_sha256=digest(folder / 'run.log'),
                        test_sha256=digest(main_cpp), compile_command=command)
            report['numeric'].append(item)
            print(json.dumps({key: value for key, value in item.items() if key != 'compile_command'}), flush=True)
    if report['source_sha256'] != digest(ROOT / SOURCE):
        raise RuntimeError('Production source changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
