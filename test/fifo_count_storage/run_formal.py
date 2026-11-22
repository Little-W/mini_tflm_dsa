#!/usr/bin/env python3
"""检查 FIFO 计数存储的有效状态、公开输出与数据存储端口。"""
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
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_s8_to_fifo.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expose_memory_ports(source):
    """逐存储体比较任意读数据、全部写数据及地址和使能。"""
    text = source[:source.index('module vec_s8_to_fifo_linear')]
    text = text.replace('    output wire                 fifo_full_flag\n);', '''    output wire                 fifo_full_flag,
    input wire [BUS_WIDTH/8-1:0][VLEN*8-1:0] formal_ram_read_data,
    output wire [BUS_WIDTH/8-1:0][VLEN*8-1:0] formal_ram_write_data,
    output wire [BUS_WIDTH/8-1:0][31:0] formal_ram_write_addr, formal_ram_read_addr,
    output wire [BUS_WIDTH/8-1:0] formal_ram_write_enable, formal_ram_read_enable,
    output wire [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts
);''')
    if 'input wire [BUS_WIDTH/8-1:0][VLEN*8-1:0] formal_ram_read_data' not in text:
        raise ValueError('FIFO port declaration differs')
    ports = '''assign fifo_ram_o_rd_data = $bits(fifo_ram_o_rd_data)'(formal_ram_read_data[ram_bank]);
        assign formal_ram_write_data[ram_bank] = (VLEN*8)'(fifo_ram_i_wr_data);
        assign formal_ram_write_addr[ram_bank] = 32'(fifo_ram_i_wr_addr);
        assign formal_ram_read_addr[ram_bank] = 32'(fifo_ram_i_rd_addr);
        assign formal_ram_write_enable[ram_bank] = fifo_ram_i_wr_en;
        assign formal_ram_read_enable[ram_bank] = fifo_ram_i_rd_en;'''
    text, count = re.subn(r'vec_s8_fifo_row_ram\s*#\(.*?\)\s*u_fifo_ram\s*\(.*?\);', ports, text, flags=re.S)
    if count != 2:
        raise ValueError(f'Expected both storage layouts, found {count}')
    return text + source[source.index('module fifo_bank_watermark'):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='cc0d4f69')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_text = read_rtl_text(ROOT / SOURCE)
    reference_text = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    helper = 'module vec_s8_fifo_row_ram'
    if current_text[current_text.index(helper):] != reference_text[reference_text.index(helper):]:
        raise ValueError('Storage implementation differs')
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut6_2.sv'
    model_text = re.search(r'^module LUT6_2\b.*?^endmodule', read_rtl_text(library), re.M | re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model_text, flags=re.S) + '\n')
    source_files = {}
    for label, text in [('reference', reference_text), ('current', current_text)]:
        source_files[label] = out / (label + '.sv')
        exposed = expose_memory_ports(text)
        # 同名关系信号参与归纳等价，寄存上限必须等于参考实现的完整表达式。
        row_limit = ('co_row_limit_q' if re.search(r'logic\s*\[COUNT_WIDTH-1:0\]\s+co_row_limit_q;', text)
                     else "COUNT_WIDTH'(co_row[3:0]) + COUNT_WIDTH'(1)")
        marker = '  wire co_group_last ='
        exposed = exposed.replace(marker,
            '  (* keep *) wire [COUNT_WIDTH-1:0] formal_co_row_limit = ' + row_limit + ';\n' + marker, 1)
        if '(* keep *) wire [COUNT_WIDTH-1:0] formal_co_row_limit' not in exposed:
            raise ValueError('FIFO row-group predicate declaration differs')
        # 过程内临时索引不属于寄存状态；两份实现各自保留其完整计算表达式。
        exposed = re.sub(r'\bread_bank_i\b', label + '_read_bank_index', exposed)
        marker = '  logic co_group_last_result;'
        relation = '  for (genvar bank=0; bank<BANKS; bank++) begin : g_count_relation\n'
        if 'u_bank_count' in exposed:
            relation += "    if (p_count_storage) begin : g_memory\n"
            relation += "      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = bank_ready[bank] ? g_count_memory.u_bank_count.mem[bank] : '0;\n"
            relation += "    end else begin : g_registers\n"
            relation += "      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = g_count_registers.bank_count[bank];\n    end\n"
        else:
            relation += '    assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = bank_count[bank];\n'
        relation += '  end\n'
        exposed = exposed.replace(marker, relation + marker, 1)
        source_files[label].write_text(exposed)
    report = {'reference_ref': args.reference, 'source_sha256': digest(ROOT / SOURCE),
              'reference_sha256': hashlib.sha256(reference_text.encode()).hexdigest(),
              'primitive_library_sha256': digest(library), 'primitive_model_sha256': digest(model),
              'inputs_constrained': False, 'ram_read_data_constrained': False,
              'row_limit_relation_compared': True, 'all_bank_counts_compared': True,
              'data_storage_implementation_identical': True, 'regfile_sha256': digest(ROOT / 'rtl/common/regfile.v'), 'formal': []}
    profiles = [(16, 64, 64, 1, True), (16, 32, 32, 1, True), (16, 32, 64, 1, True),
                (16, 3, 64, 1, True), (16, 16, 64, 1, True),
                (16, 32, 64, 1, False), (16, 32, 64, 0, True),
                (8, 8, 32, 0, True)]
    for vlen, banks, bus, cyclic, fpga in profiles:
        name = f'v{vlen}_n{banks}_b{bus}_c{cyclic}_{"fpga" if fpga else "generic"}'
        folder = out / name
        folder.mkdir(exist_ok=True)
        commands = []
        define = '-D XILINX_FPGA -D VERIFIC' if fpga else '-D ASIC_SYNTHESIS'
        for label, path in source_files.items():
            commands += [
                f'read_slang --top vec_s8_to_fifo_full -GVLEN={vlen} -GBANKS={banks} '
                f'-GBUS_WIDTH={bus} -Gp_cyclic_storage={cyclic} {define} ' +
                ' '.join(shlex.quote(str(p)) for p in (path, model, ROOT / 'rtl/common/regfile.v')),
                'prep -top vec_s8_to_fifo_full -flatten', 'async2sync', 'memory_map', 'opt -full',
                'rename vec_s8_to_fifo_full ' + label, 'design -stash ' + label,
            ]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 3', 'equiv_simple -seq 1', 'equiv_status -assert']
        script, log_path = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log_path.open('w') as log:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=300)
        log = read_rtl_text(log_path)
        if result.returncode or 'Equivalence successfully proven' not in log:
            raise RuntimeError(log[-10000:])
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log)
        item = {'vlen': vlen, 'banks': banks, 'bus_width': bus, 'cyclic_storage': cyclic,
                'fpga': fpga, 'passed': True, 'equivalent_bits': int(match[1]),
                'log_sha256': digest(log_path)}
        report['formal'].append(item)
        print(json.dumps(item), flush=True)
    if report['source_sha256'] != digest(ROOT / SOURCE):
        raise RuntimeError('Source changed during formal verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(item['equivalent_bits'] for item in report['formal'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
