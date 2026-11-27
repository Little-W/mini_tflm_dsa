#!/usr/bin/env python3
"""比较十六位 FIFO 的完整控制状态、公开输出和全部数据存储端口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/writeback/vec_s16_to_fifo.sv'
PROFILES = ((16, 1, 32), (16, 2, 64), (16, 3, 32), (16, 4, 32),
            (16, 4, 64), (16, 16, 64), (16, 32, 32), (16, 64, 64),
            (8, 8, 32), (32, 4, 64))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_ports(text, ports):
    """保留端口注释，并在声明末端插入 ANSI 端口分隔符。"""
    end = text.index('\n);', text.index('module vec_s16_to_fifo'))
    header = text[:end].rstrip()
    comment = re.search(r'//[^\n]*$', header)
    if comment:
        header = header[:comment.start()].rstrip() + ', ' + comment[0]
    else:
        header += ','
    return header + '\n' + ports.lstrip(',\n').rstrip() + text[end:]


def observed_source(text):
    """数据 RAM 保持共同任意返回值，逐项比较其写数据、地址和使能。"""
    if 'i_full_select' not in text:
        ports = ''',
    input wire logic i_full_select=1'b1, // 所选输出格式。
    input wire logic i_output_pending=1'b1, // 当前分组需要生成输出。
    input wire logic i_other_full=1'b0, // 另一种输出格式的容量状态。
    output logic o_issue_full // 原完整输出条件与分组资格的组合结果。
'''
        text = append_ports(text, ports)
        text = text.replace('endmodule',
            '    assign o_issue_full = (i_full_select ? fifo_full_flag : i_other_full) && i_output_pending;\nendmodule', 1)
    address = '(BANKS*VLEN<=1?1:$clog2(BANKS*VLEN))'
    ports = f''',
    input wire logic [VLEN*16-1:0] formal_ram_data, // 共同的数据存储返回值。
    output logic formal_write_enable, // 实际存储写使能。
    output logic [{address}-1:0] formal_write_address, // 实际存储写地址。
    output logic [VLEN*16-1:0] formal_write_data, // 实际存储写数据。
    output logic formal_read_enable, // 实际存储读使能。
    output logic [{address}-1:0] formal_read_address, // 实际存储读地址。
    output logic [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts, // 全部银行保存的有效行数。
    output logic [4:0] formal_saved_relation // 寄存条件、银行索引与当前状态的关系。
'''
    text = append_ports(text, ports)
    replacement = '''
    assign formal_write_enable = in_valid && !write_bank_blocked;
    assign formal_write_address = ram_wr_addr;
    assign formal_write_data = in_vec_s16;
    assign formal_read_enable = ram_read_en;
    assign formal_read_address = ram_rd_addr;
    assign ram_rd_data = formal_ram_data;
    for (genvar bank=0; bank<BANKS; bank++) begin : g_formal_count
        assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = bank_count[bank];
    end
'''
    text, count = re.subn(r'    vec_s8_fifo_row_ram\s*#\(.*?\)\s*u_ram\s*\(.*?\);',
                          replacement, text, flags=re.S)
    if count != 1:
        raise ValueError('需要唯一的数据存储实例')
    if 'logic partial_write_q;' in text:
        relations = '''
    assign formal_saved_relation[0] = write_bank_blocked_q == bank_ready[write_bank];
    assign formal_saved_relation[1] = next_write_bank_blocked_q == bank_ready[next_bank(write_bank)];
    assign formal_saved_relation[2] = partial_write_q == (write_ptr != '0);
    assign formal_saved_relation[3] = int'(write_bank) < BANKS;
    assign formal_saved_relation[4] = int'(read_bank) < BANKS;
'''
    else:
        relations = "    assign formal_saved_relation = 5'b11111;\n"
    return text.replace('endmodule', relations + '\nendmodule', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='4927debf')
    parser.add_argument('--profiles', nargs='+')
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=source, text=True).strip()
    reference = subprocess.check_output(['git', 'show', revision+':'+SOURCE], cwd=source, text=True)
    current = (source/SOURCE).read_text()
    snapshot = {}
    for label, text in (('reference', reference), ('current', current)):
        snapshot[label] = out/(label+'.sv')
        snapshot[label].write_text(observed_source(text))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    common = resolve([source/'rtl/npu/writeback/fifo_bank_watermark.sv',
                      source/'rtl/npu/writeback/fifo_s16_issue_full.sv'], source)
    checked = [source/SOURCE, *common, Path(__file__)]
    hashes = {str(path): digest(path) for path in checked}
    report = dict(reference_commit=revision, source_sha256=hashes,
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  initial_reset_cycle=1, subsequent_inputs_constrained=False,
                  ram_returns_constrained=False, data_storage_implementation_changed=False,
                  compared='全部公开输出、共同寄存状态、全部银行行数、存储读写地址和使能及存储写数据',
                  saved_relations=['当前写银行阻塞位', '下一写银行阻塞位', '部分写入标志',
                                   '写银行索引有效', '读银行索引有效'], results=[])
    for vlen, banks, bus in PROFILES:
        for watermark in (0, 1):
            name = f'v{vlen}_n{banks}_b{bus}_w{watermark}'
            if args.profiles and name not in args.profiles:
                continue
            folder = out/name
            folder.mkdir(exist_ok=True)
            commands = []
            for label, path in snapshot.items():
                commands += [
                    f'read_slang --top vec_s16_to_fifo -GVLEN={vlen} -GBANKS={banks} '
                    f'-GBUS_WIDTH={bus} -Gp_precomputed_watermark={watermark} -D SYNTHESIS=1 '+
                    shlex.join(map(str, [path, *common])),
                    'prep -top vec_s16_to_fifo -flatten', 'async2sync', 'memory_map', 'opt -full',
                    'rename vec_s16_to_fifo '+label, 'design -stash '+label,
                ]
            commands += [
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'expose -dff -shared reference/w:* current/w:*',
                'miter -equiv -make_outcmp -flatten reference current miter',
                'hierarchy -top miter', 'opt_clean',
                'sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 in_rst_n 0 -prove trigger 0 -verify',
            ]
            script = folder/'proof.ys'
            script.write_text('\n'.join(commands)+'\n')
            log = folder/'proof.log'
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
                                '--worker', script], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=600)
            text = log.read_text()
            if 'Induction step proven: SUCCESS!' not in text:
                raise RuntimeError('完整状态归纳没有完成：'+str(log))
            result = dict(profile=name, passed=True, vlen=vlen, banks=banks, bus_width=bus,
                          precomputed_watermark=watermark, log_sha256=digest(log))
            report['results'].append(result)
            (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps(result), flush=True)
    if not report['results'] or hashes != {str(path): digest(path) for path in checked}:
        raise RuntimeError('需要完整执行指定参数且保持被检查源码不变')
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
