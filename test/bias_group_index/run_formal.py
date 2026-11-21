#!/usr/bin/env python3
"""使用实际顶层索引逻辑和偏置缓冲区证明组首地址选择的时序等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
BUFFER = Path('rtl/npu/loaders/bias_loader_buffer.sv')
MEMORY = Path('rtl/common/regfile.v')
HELPER = Path('rtl/common/parallel_prefix_add.sv')

# 两侧接收同一任意存储返回值；同时证明所有读写端口逐周期相同。
# 相同初始存储和相同端口操作可逐拍保持每一个存储位相同。
MEMORY_MODEL = '''module regfile #(
    parameter int p_data_width=64, p_depth=512, p_addr_width=9, p_write_unit=8
) (
    input logic clk, i_wr_en, i_rd_en,
    input logic [p_addr_width-1:0] i_wr_addr, i_rd_addr,
    input logic [p_data_width-1:0] i_wr_data, i_formal_read_data,
    input logic [p_data_width/p_write_unit-1:0] i_wr_mask,
    output logic [p_data_width-1:0] o_rd_data
);
    assign o_rd_data=i_formal_read_data;
endmodule
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def index_block(source):
    found = re.findall(r'        always_comb begin\n            is_bias_read_idx =.*?\n        end\n',
                       source, flags=re.S)
    if len(found) != 1:
        raise RuntimeError('Expected one production bias index block')
    block = found[0]
    if 'is_bias_row_wrap' in block:
        declarations = ('  logic is_bias_row_wrap;\n'
                        '  logic [IS_BIAS_VALID_W:0] is_bias_row_distance;\n')
        assignments = []
        for name in ('is_bias_row_distance', 'is_bias_row_wrap'):
            matches = re.findall(r'assign ' + name + r'\s*=.*?;', source, flags=re.S)
            if len(matches) != 1:
                raise RuntimeError('Expected one production assignment for ' + name)
            assignments.append(matches[0])
        assignments = '\n'.join(assignments)
        block = declarations + assignments + "\n" + block
    return block


def group_start(source):
    found = re.findall(r'\.group_read_start\s*\(([^\n]+)\)', source)
    if found != ['is_mode && send_ia_trigger && !bias_sleep']:
        raise RuntimeError('Bias group-start connection changed')
    return found[0]


def prepare_buffer(buffer, block, start):
    ports = '''    input logic acc_data_valid, init_cfg_ia, send_ia_trigger, bias_sleep,
    input logic [$clog2(GROUP_BLOCKS_MAX * SIZE)-1:0] is_bias_row_idx,
    input logic [$clog2(GROUP_BLOCKS_MAX * SIZE):0] is_bias_rows_valid,
    input logic [63:0] i_formal_read_data,
'''
    old_ports = '''    input  wire logic                 group_read_start,
    input  wire logic [$clog2(GROUP_BLOCKS_MAX * SIZE)-1:0] group_read_idx,
'''
    if buffer.count(old_ports) != 1:
        raise RuntimeError('Bias buffer group ports changed')
    source = buffer.replace(old_ports, ports)
    marker = '  localparam int BYTES_PER_WORD = DATA_WIDTH / 8;'
    declarations = f'''  localparam int IS_BIAS_ROW_W = $clog2(GROUP_BLOCKS_MAX * SIZE);
  localparam int IS_BIAS_VALID_W = IS_BIAS_ROW_W + 1;
  logic [IS_BIAS_ROW_W-1:0] is_bias_read_idx;
  wire [IS_BIAS_ROW_W-1:0] group_read_idx = is_bias_read_idx;
  wire group_read_start = {start};
{block}
'''
    source = source.replace(marker, declarations + marker)
    old_read_port = '.o_rd_data(storage_o_rd_data)'
    if source.count(old_read_port) != 1:
        raise RuntimeError('Bias memory read port changed')
    source = source.replace(old_read_port,
                            old_read_port + ', .i_formal_read_data(i_formal_read_data)')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='bdd7109f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_top = (ROOT / TOP).read_text()
    reference_top = read_rtl_source(f'{args.reference_rev}:{TOP}', cwd=ROOT, text=True)
    blocks = {'reference': index_block(reference_top), 'current': index_block(current_top)}
    starts = {label: group_start(source) for label, source in
              (('reference', reference_top), ('current', current_top))}
    buffer = (ROOT / BUFFER).read_text()
    hashes = {str(p): digest((ROOT / p).read_bytes()) for p in (TOP, BUFFER, MEMORY, HELPER)}
    model = out / 'memory_model.sv'
    model.write_text(MEMORY_MODEL)
    snapshots = {}
    for label, block in blocks.items():
        snapshots[label] = out / (label + '.sv')
        snapshots[label].write_text(prepare_buffer(buffer, block, starts[label]))
    report = {'passed': False, 'reference_rev': args.reference_rev,
              'source_sha256': hashes, 'inputs_constrained': False,
              'reference_top_sha256': digest(reference_top.encode()),
              'index_block_sha256': {k: digest(v.encode()) for k, v in blocks.items()},
              'memory_return': 'common unconstrained 64-bit value on every cycle',
              'memory_state_relation': 'identical initial storage and identical read/write ports',
              'memory_model_sha256': digest(model.read_bytes()), 'profiles': []}
    for size, bus, count, groups in ((4, 32, 1, 1), (16, 32, 12, 4),
                                    (16, 64, 29, 32), (16, 128, 29, 32),
                                    (16, 64, 32, 64), (32, 64, 32, 1)):
        folder = out / f's{size}_b{bus}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in snapshots.items():
            commands += [
                f'read_slang --top bias_loader_buffer -GSIZE={size} -GBUS_WIDTH={bus} '
                f'-GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups} '
                + shlex.quote(str(source)) + ' ' + shlex.quote(str(model)) + ' '
                + shlex.quote(str(ROOT / HELPER)),
                'prep -top bias_loader_buffer -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename -hide bias_loader_buffer/is_bias_read_idx bias_loader_buffer/group_read_idx',
                f'rename bias_loader_buffer {label}', f'design -stash {label}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert',
        ]
        script = folder / 'run.ys'
        log = folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        case = {'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count,
                'GROUP_BLOCKS_MAX': groups,
                'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
                'equivalent_bits': int(match[1]) if match else None,
                'script_sha256': digest(script.read_bytes()), 'log_sha256': digest(log.read_bytes())}
        report['profiles'].append(case)
        print(json.dumps(case), flush=True)
        if not case['passed']:
            raise RuntimeError(f'Formal comparison did not complete: {log}')
    if hashes != {str(p): digest((ROOT / p).read_bytes()) for p in (TOP, BUFFER, MEMORY, HELPER)}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
