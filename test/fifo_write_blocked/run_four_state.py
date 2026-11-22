#!/usr/bin/env python3
"""用实际 FIFO 控制和存储端口检查写入阻塞状态的四态周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_s8_to_fifo.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text

PROFILES = ((16, 1, 64, 1), (16, 2, 32, 1), (16, 3, 64, 1),
            (16, 8, 32, 1), (16, 16, 64, 1), (16, 32, 32, 1),
            (16, 32, 64, 1), (16, 64, 64, 1), (16, 32, 64, 0),
            (8, 8, 32, 0), (32, 32, 64, 0))
STATE_FIELDS = ('bank_ready', 'ready_bank_count_q', 'active_read_count_q',
                'last_beat_idx_q', 'write_bank', 'write_bank_mask_q',
                'read_bank', 'write_ptr', 'read_ptr', 'stream_active',
                'data_valid', 'beat_idx', 'vec_valid_num_col_tmp',
                'vec_valid_num_row_tmp', 'transpose_mode_tmp', 'co_active',
                'co_data_valid', 'co_row', 'co_col', 'co_beat',
                'co_current_bank', 'co_last_col_q', 'co_last_tile_row_q',
                'co_row_limit_q')
PORTS = ('oa_fifo_req', 'output_valid', 'output_row_switch', 'output_mask',
         'output_data', 'fifo_full_flag', 'formal_ram_write_data',
         'formal_ram_write_addr', 'formal_ram_read_addr',
         'formal_ram_write_enable', 'formal_ram_read_enable',
         'formal_bank_nonempty', 'formal_bank_counts')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source: str, label: str) -> str:
    """保留完整控制、计数存储及数据选择，仅将数据 RAM 返回值设为共同输入。"""
    spec = importlib.util.spec_from_file_location(
        'fifo_control_ports', ROOT / 'test/fifo_read_qualification/run_formal.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    text = helper.observed_source(source)
    text = re.sub(r'\bvec_s8_to_fifo_full\b', 'fifo_' + label, text)
    text = re.sub(r'\bfifo_bank_watermark\b', 'watermark_' + label, text)
    # 组合过程使用显式自动敏感列表；所有条件、赋值和时序过程保留原文。
    return text.replace('always_comb', 'always @*')


def pair_source() -> str:
    header = '''module fifo_pair #(
    parameter VLEN=16, BANKS=32, BUS_WIDTH=64, CYCLIC=1, INDEX=0
)(
    input logic clk, rst_n, check_now,
    input logic [7:0] controls,
    input logic [31:0] counts, data_word,
    input integer cycle,
    output longint unsigned checks=0,
    output longint unsigned writes=0, releases=0, group_releases=0,
    output longint unsigned simultaneous=0, blocked=0, unknown_controls=0
);
    localparam CW=$clog2(VLEN+1), BW=(BANKS<=1)?1:$clog2(BANKS);
    localparam RW=$clog2(VLEN), LANES=BUS_WIDTH/8;
    wire start_permitted=controls[0], in_valid=controls[1], in_tile_done=controls[2];
    wire transpose_mode=controls[3], coalesce_enable=controls[4];
    wire coalesce_group_start=controls[5], output_ready=controls[6];
    wire [31:0] reserve_banks=controls[7] ? counts : 32'd1;
    wire [31:0] threshold=controls[7] ? {26'd0,counts[5:0]} : 32'(BANKS-1);
    wire [31:0] coalesce_rows={27'd0,counts[28],counts[19:16]};
    wire [31:0] coalesce_cols={27'd0,counts[29],counts[23:20]};
    wire [RW-1:0] vec_valid_num_col=counts[0+:RW];
    wire [RW-1:0] vec_valid_num_row=counts[8+:RW];
    wire [VLEN*8-1:0] in_vec_s8=(VLEN*8)'({8{data_word}});
    wire [LANES-1:0][VLEN*8-1:0] ram_data=(LANES*VLEN*8)'({64{data_word}});
'''
    instances = ''
    for label in ('reference', 'current'):
        instances += f'''
    fifo_{label} #(.VLEN(VLEN), .BANKS(BANKS), .BUS_WIDTH(BUS_WIDTH),
        .p_cyclic_storage(CYCLIC), .p_precomputed_watermark(1'b1)) u_{label}(
        .clk, .rst_n, .start_permitted, .in_valid, .in_tile_done, .in_vec_s8,
        .transpose_mode, .coalesce_enable, .coalesce_group_start,
        .coalesce_rows, .coalesce_cols, .reserve_banks,
        .i_ready_bank_threshold(threshold), .vec_valid_num_col, .vec_valid_num_row,
        .output_ready, .formal_ram_read_data(ram_data));
'''
    checks = '    always @(posedge check_now) begin\n'
    for field in (*STATE_FIELDS, *PORTS):
        checks += f'''        if (u_reference.{field} !== u_current.{field})
            $fatal(1,"FIFO four-state mismatch profile=%0d cycle=%0d field={field}",INDEX,cycle);
        checks++;
'''
    relations = {
        'write_bank_blocked_q': '(|(u_current.bank_ready & u_current.write_bank_mask_q))',
        'next_write_bank_blocked_q': '(|(u_current.bank_ready & u_current.next_write_bank_mask))',
        'read_row_limit_q': "(CW'(u_current.read_ptr) + CW'(1))",
        'transpose_row_count_q': "(CW'(u_current.vec_valid_num_row_tmp) + CW'(1))",
    }
    for field, expected in relations.items():
        checks += f'''        if (u_current.{field} !== {expected})
            $fatal(1,"FIFO saved state mismatch profile=%0d cycle=%0d field={field}",INDEX,cycle);
        checks++;
'''
    checks += '''    end
    always @(posedge clk) begin
        if (rst_n === 1'b1) begin
            if (u_current.finish_write_bank === 1'b1 && u_current.write_bank_blocked === 1'b0) writes++;
            if ((|u_current.bank_release) === 1'b1) releases++;
            if (u_current.co_finish === 1'b1 && coalesce_enable === 1'b1) group_releases++;
            if ((|u_current.bank_release) === 1'b1 && (|u_current.bank_write_complete) === 1'b1) simultaneous++;
            if (u_current.write_bank_blocked === 1'b1) blocked++;
            if ((^controls) === 1'bx) unknown_controls++;
        end
    end
endmodule
'''
    return header + instances + checks


def bench_source(cycles: int, profiles: tuple) -> str:
    text = pair_source() + '''
module tb;
    logic clk=0, rst_n=0, check_now=0;
    logic [7:0] controls=0;
    logic [31:0] counts=32'h00110f0f, data_word=0;
    logic [31:0] random_state=32'h8a2ef813;
    integer cycle=0;
    longint unsigned total_checks=0;
    function automatic [31:0] random_word;
        begin
            random_state=random_state^(random_state<<13);
            random_state=random_state^(random_state>>17);
            random_state=random_state^(random_state<<5);
            random_word=random_state;
        end
    endfunction
    function automatic logic four_symbol(input logic [3:0] value);
        case(value)
            4'd0: four_symbol=1'bx;
            4'd1: four_symbol=1'bz;
            default: four_symbol=value[0];
        endcase
    endfunction
    task automatic check_values;
        begin #1;check_now=1;#1;check_now=0;end
    endtask
    task automatic advance;
        begin
            #1;clk=1;#1;check_values();#1;clk=0;#1;
        end
    endtask
'''
    for index, (vlen, banks, bus, cyclic) in enumerate(profiles):
        text += f'''    fifo_pair #(.VLEN({vlen}), .BANKS({banks}), .BUS_WIDTH({bus}),
        .CYCLIC({cyclic}), .INDEX({index})) u{index}(.clk,.rst_n,.check_now,.controls,.counts,.data_word,.cycle);
'''
    text += f'''    initial begin
        advance();advance();
        for (cycle=0;cycle<{cycles};cycle++) begin
            // 定向阶段连续写入并输出，随后覆盖未知控制、配置和数据位。
            rst_n=(cycle%509==0 || cycle%509==1) ? 1'b0 : 1'b1;
            if (cycle%509<160) begin
                controls=8'b01100111;
                controls[2]=(cycle%509<96) || (cycle%16==15);
                controls[3]=(cycle/509)%2;
                controls[4]=(cycle%509>=96) && ((cycle/509)%3==1);
                controls[5]=1'b1;
                controls[6]=(cycle%7!=0);
                counts=cycle%509<96 ? 32'h00110000 : 32'h00110f0f;
                data_word=random_word();
            end else begin
                for (integer bit_index=0;bit_index<8;bit_index++)
                    controls[bit_index]=four_symbol(4'(random_word()));
                for (integer bit_index=0;bit_index<32;bit_index++) begin
                    counts[bit_index]=four_symbol(4'(random_word()));
                    data_word[bit_index]=four_symbol(4'(random_word()));
                end
                if (cycle%17==0) rst_n=four_symbol(4'(random_word()));
            end
            check_values();advance();
            if (cycle%512==511) begin
                $display("PROGRESS cycles=%0d",cycle+1);
                $fflush();
            end
        end
'''
    for index in range(len(profiles)):
        text += f'''        total_checks+=u{index}.checks;
        $display("PROFILE index={index} checks=%0d writes=%0d releases=%0d group_releases=%0d simultaneous=%0d blocked=%0d unknown_controls=%0d",u{index}.checks,u{index}.writes,u{index}.releases,u{index}.group_releases,u{index}.simultaneous,u{index}.blocked,u{index}.unknown_controls);
'''
    text += f'''        $display("FIFO_BLOCKED_FOUR_STATE_PASS cycles={cycles} profiles={len(profiles)} comparisons=%0d",total_checks);
        $finish;
    end
endmodule
'''
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='cfcc1a95ddcd93625636efc15b8c2b2b1835730f')
    parser.add_argument('--reference-file', type=Path)
    parser.add_argument('--cycles', type=int, default=4096)
    parser.add_argument('--timeout', type=int, default=900,
                        help='每种模式的四态仿真执行上限，单位为秒')
    parser.add_argument('--profile', type=int, help='只运行指定序号的参数配置')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout 必须为正整数')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root.resolve() / SOURCE
    source = read_rtl_text(source_path)
    reference = (read_rtl_text(args.reference_file) if args.reference_file else
                 read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True))
    memory_marker = 'module vec_s8_fifo_row_ram'
    if source[source.index(memory_marker):] != reference[reference.index(memory_marker):]:
        raise RuntimeError('FIFO data storage implementations differ')
    paths = []
    for label, content in (('reference', reference), ('current', source)):
        path = out / (label + '.sv')
        path.write_text(model(content, label))
        paths.append(path)
    profiles = PROFILES if args.profile is None else (PROFILES[args.profile],)
    bench = out / 'tb.sv'
    bench.write_text(bench_source(args.cycles, profiles))
    dependencies = [ROOT / 'rtl/common/regfile.v', ROOT / 'rtl/common/parallel_prefix_add.sv']
    report = {'passed': False, 'reference': args.reference,
              'source_sha256': digest(source_path),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'runner_sha256': digest(Path(__file__)), 'cycles_per_mode': args.cycles,
              'simulation_timeout_seconds': args.timeout, 'coalesce_size_bits': 5,
              'initial_reset_cycles': 2, 'data_memory_return': 'common generated four-state words repeated across memory lanes',
              'combinational_process_sensitivity': 'always_comb rendered as always @* for event simulation',
              'complete_control_preserved': True, 'compared_state_fields': list(STATE_FIELDS),
              'compared_ports': list(PORTS), 'saved_state_relations': 4,
              'source_dependencies_sha256': {str(p.relative_to(ROOT)): digest(p) for p in dependencies},
              'generated_source_sha256': {p.name: digest(p) for p in (*paths, bench)}, 'runs': []}
    for name, definition in (('fpga', 'XILINX_FPGA'), ('generic', 'ASIC_SYNTHESIS')):
        binary = out / (name + '.vvp')
        with (out / (name + '_build.log')).open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-D' + definition, '-s', 'tb',
                            '-o', str(binary), *map(str, (*paths, *dependencies, bench))],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        log = out / (name + '.log')
        with log.open('w') as stream:
            subprocess.run(['vvp', str(binary)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
        output = read_rtl_text(log)
        completed = re.search(r'FIFO_BLOCKED_FOUR_STATE_PASS cycles=(\d+) profiles=(\d+) comparisons=(\d+)', output)
        if completed is None:
            raise RuntimeError('Four-state cycle comparison did not complete: ' + str(log))
        coverage = []
        for line in output.splitlines():
            if line.startswith('PROFILE '):
                row = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                row['parameters'] = dict(zip(('vlen', 'banks', 'bus_width', 'cyclic_storage'), profiles[row['index']]))
                coverage.append(row)
        report['runs'].append({'mode': name, 'passed': True, 'cycles': int(completed[1]),
                               'profiles': len(profiles), 'comparisons': int(completed[3]),
                               'coverage': coverage, 'log_sha256': digest(log)})
        print(json.dumps({key: report['runs'][-1][key] for key in ('mode', 'passed', 'cycles', 'profiles', 'comparisons')}), flush=True)
    if source != read_rtl_text(source_path):
        raise RuntimeError('FIFO source changed during verification')
    report['passed'] = True
    report['comparisons'] = sum(row['comparisons'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
