#!/usr/bin/env python3
"""证明参数描述符准备和读取、写回地址译码的组合关系。"""
from __future__ import annotations

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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
DEPENDENCIES = [Path('rtl/npu/conv/conv_im2col_pkg.sv'),
                Path('rtl/npu/conv/vector_engine_pkg.sv'),
                Path('rtl/common/parallel_prefix_add.sv'), Path('rtl/common/add_equal.sv')]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def span(source):
    first = source.index('  assign rd_start =')
    first = source.index('\n', first) + 1
    middle = source.index('  assign parameter_row_last_fire', first)
    last = source.index('  wire signed [15:0] input_lane', middle)
    return first, middle, last


def preparation_fragment(source):
    first, middle, _ = span(source)
    body = source[first:middle]
    # 组合准备值与保存寄存器分别检查，这里保留实际加法和判断表达式。
    if '  always_ff ' in body:
        body = body[:body.index('  always_ff ')]
    suffix = '_next' if 'parameter_row_stride_next' in body else ''
    return f'''module vector_parameter_prepare (
    input vector_engine_pkg::vector_engine_cfg_t c,
    output logic [31:0] prepared_stride,
    output logic prepared_two_rows, prepared_three_rows
);
    logic [31:0] parameter_row_stride;
    logic parameter_two_rows, parameter_three_rows;
    {body}
    assign prepared_stride = parameter_row_stride{suffix};
    assign prepared_two_rows = parameter_two_rows{suffix};
    assign prepared_three_rows = parameter_three_rows{suffix};
endmodule
'''


def decode_fragment(source, bus, tile):
    _, middle, last = span(source)
    state = re.search(r'typedef enum logic \[5:0\].*?state_t;', source, re.S)[0]
    load = re.search(r'typedef enum logic \[2:0\].*?load_t;', source, re.S)[0]
    helper = re.search(r'^module vector_read_address_add\b.*?^endmodule', source, re.M | re.S)
    body = source[middle:last]
    # 两侧使用同一个已接收请求索引；真实保存和消费关系由引擎观察模块检查。
    body = re.sub(r'\bsoft_lut_index(?:_q)?\b', 'prepared_lut_index', body)
    return f'''module vector_read_decode #(
    parameter int BUS_WIDTH={bus}, TILE={tile}, DMA_SIZE=4*TILE,
    parameter int BUS_BYTES=BUS_WIDTH/8, BUS_SHIFT=$clog2(BUS_BYTES),
    parameter int INPUT_INDEX_W=$clog2(DMA_SIZE), ACTIVE_COUNT_W=$clog2(TILE+1)
) (
    input logic clk,
    input logic [5:0] state,
    input logic [2:0] load_kind,
    input vector_engine_pkg::vector_engine_cfg_t c,
    input logic spatial, rd_raw_valid,
    input logic [ACTIVE_COUNT_W-1:0] active,
    input logic [15:0] channel_base,
    input logic [31:0] vector_offset, load_tap_offset, pool_byte_offset, channels, position_offset, taps,
    input logic [7:0] prepared_lut_index,
    input logic [31:0] parameter_row_stride,
    input logic parameter_two_rows, parameter_three_rows,
    input logic [INPUT_INDEX_W:0] pool_elements, pool_pixels,
    input logic [INPUT_INDEX_W-1:0] rd_col_base,
    input logic [BUS_WIDTH-1:0] rd_raw_data,
    output logic rd_im2col, rd_use_16bits, param_bad,
    output logic [31:0] rd_p0, rd_q0, rd_base_addr, rd_row_stride, rd_rows_to_read, rd_valid_cols, load_bytes,
    output logic [7:0] rd_burst_len_m1,
    output logic [31:0] write_origin_value
);
    {state}
    {load}
    logic [31:0] read_address_base, read_address_offset;
    logic [15:0] read_address_channel;
    logic [1:0] unused_read_address_carry;
    logic parameter_row_last_fire;
    {body}
    assign write_origin_value = write_origin_next;
endmodule
{helper.group() if helper else ''}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='dde5e7c9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f'{args.reference_rev}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    initial_hashes = {str(path): digest(ROOT / path) for path in [SOURCE] + DEPENDENCIES}
    inputs = out / 'inputs'
    inputs.mkdir(exist_ok=True)
    (inputs / 'reference_engine.sv').write_text(reference)
    (inputs / 'current_engine.sv').write_text(current)
    packages = []
    for relative in DEPENDENCIES:
        copied = inputs / relative.name
        copied.write_bytes((ROOT / relative).read_bytes())
        packages.append(copied)
    report = {
        'passed': False, 'reference_rev': args.reference_rev,
        'source_sha256': initial_hashes[str(SOURCE)],
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'dependency_sha256': initial_hashes, 'input_assumptions': [],
        'proof_scope': 'Actual parameter preparation expressions; complete read configuration, read address, parameter validation, and write-origin decode for arbitrary prepared descriptors and LUT request index',
        'registered_consumer_checks': 'test/monitors/vector_engine_observer.sv:vector_control_datapath_observer',
        'runs': [],
    }
    cases = {}

    def compare(name, top, model, configuration):
        folder = out / name
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in [('reference', reference), ('candidate', current)]:
            path = folder / (label + '.sv')
            path.write_text(model(source))
            commands += [
                f'read_slang -D ASIC_SYNTHESIS=1 --top {top} ' + shlex.join(map(str, packages + [path])),
                f'prep -top {top} -flatten', 'opt -full', f'rename {top} {label}', f'design -stash {label}',
            ]
            if name == 'bus64_tile16':
                cases[label] = {'top': top, 'options': [], 'sources': list(map(str, packages + [path])),
                                'configuration': configuration}
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'rename -hide reference/w:* candidate/w:*',
            'equiv_make reference candidate comparison', 'hierarchy -top comparison',
            'equiv_simple', 'equiv_status -assert',
        ]
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'name': name, 'configuration': configuration,
               'equivalent_bits': int(match[1]) if match else None,
               'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
               'script_sha256': digest(script), 'log_sha256': digest(log)}
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'组合关系证明未完成：{log}\n{text[-8000:]}')
        return row

    report['preparation'] = compare('parameter_prepare', 'vector_parameter_prepare', preparation_fragment,
                                    'Full 32-bit modulo stride and two/three-row qualification')
    for bus, tile in [(32, 16), (64, 16), (128, 16), (32, 3), (64, 32)]:
        row = compare(f'bus{bus}_tile{tile}', 'vector_read_decode',
                      lambda source: decode_fragment(source, bus, tile),
                      f'BUS{bus} TILE{tile}; every state and complete read/write address outputs')
        report['runs'].append({'bus_width': bus, 'tile': tile, **row})
    range_out = out / 'ranges'
    subprocess.run([sys.executable, str(Path(__file__).with_name('run_ranges_formal.py')),
                    '--out', str(range_out), '--reference-rev', args.reference_rev], cwd=ROOT, check=True)
    report['ranges'] = json.loads((range_out / 'summary.json').read_text())
    if initial_hashes != {str(path): digest(ROOT / path) for path in [SOURCE] + DEPENDENCIES}:
        raise RuntimeError('验证期间向量引擎或公共依赖发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
