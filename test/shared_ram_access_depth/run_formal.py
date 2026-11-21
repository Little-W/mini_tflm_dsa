#!/usr/bin/env python3
"""证明共享存储的末级访问控制保持全部存储命令与控制状态。"""
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
SOURCE = 'rtl/npu/buffers/ia_ps_shared_ram.sv'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def channel(source: str, name: str) -> str:
    start = source.index('module ia_ps_channel_ram #(')
    end = source.index('\nendmodule', start) + len('\nendmodule')
    return source[start:end].replace('module ia_ps_channel_ram #(', f'module {name} #(', 1)


def memory_equal(path: str) -> str:
    reference, current = f'u_reference.{path}', f'u_current.{path}'
    return f'''({reference}.i_rd_en == {current}.i_rd_en &&
      {reference}.i_wr_en == {current}.i_wr_en &&
      (!{reference}.i_rd_en || {reference}.i_rd_addr == {current}.i_rd_addr) &&
      (!{reference}.i_wr_en || ({reference}.i_wr_addr == {current}.i_wr_addr &&
       {reference}.i_wr_mask == {current}.i_wr_mask &&
       {reference}.i_wr_data == {current}.i_wr_data)))'''


def miter(reference: str, current: str) -> str:
    common = '''.clk(clk), .rst_n(rst_n), .i_cfg_valid(i_cfg_valid),
      .i_cfg_ia_banks(i_cfg_ia_banks),
      .i_ia_read_addr(i_ia_read_addr), .i_ia_write_addr(i_ia_write_addr),
      .i_ia_write_data(i_ia_write_data), .i_ia_shared_write_data(i_ia_shared_write_data),
      .i_ia_write_mask(i_ia_write_mask), .i_ps_read_addr(i_ps_read_addr),
      .i_ps_write_addr(i_ps_write_addr), .i_ps_write_data(i_ps_write_data)'''
    parameters = '''.p_bank_bytes(p_bank_bytes), .p_total_bytes(p_total_bytes),
      .p_shared_write_stage(p_shared_write_stage)'''
    return channel(reference, 'channel_reference') + '\n' + channel(current, 'channel_current') + f'''
// 存储命令逐位检查；同步读取的选择状态独立检查，存储数据不参与控制判断。
module regfile #(
  parameter int p_data_width=128, p_depth=128, p_addr_width=$clog2(p_depth), p_write_unit=8
)(input logic clk, i_wr_en, i_rd_en,
  input logic [p_addr_width-1:0] i_wr_addr, i_rd_addr,
  input logic [p_data_width-1:0] i_wr_data,
  input logic [p_data_width/p_write_unit-1:0] i_wr_mask,
  output logic [p_data_width-1:0] o_rd_data);
  assign o_rd_data = '0;
endmodule

module access_miter #(
  parameter int p_bank_bytes=8192, p_total_bytes=57344,
  parameter bit p_shared_write_stage=1'b1,
  parameter int p_addr_width=$clog2(p_total_bytes/16),
  parameter int p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1)
)(
  input logic clk, rst_n, i_access_enable, i_cfg_valid,
  input logic [p_bank_count_width-1:0] i_cfg_ia_banks,
  input logic [1:0] i_ia_read_en, i_ia_write_en,
  input logic [p_addr_width-1:0] i_ia_read_addr [2], i_ia_write_addr [2],
  input logic [127:0] i_ia_write_data [2],
  input logic [127:0] i_ia_shared_write_data,
  input logic [15:0] i_ia_write_mask [2],
  input logic [3:0] i_ps_read_en, i_ps_write_en,
  input logic [p_addr_width-1:0] i_ps_read_addr [4], i_ps_write_addr [4],
  input logic [127:0] i_ps_write_data [4],
  output logic equivalent
);
  localparam int p_max_ia_banks=p_total_bytes/p_bank_bytes>=8 ? 4 : 2;
  logic reference_fault, current_fault;
  logic [127:0] reference_ia_data [2], current_ia_data [2];
  logic [127:0] reference_ps_data [4], current_ps_data [4];
  logic [1:0] ia_return_equal;
  logic [3:0] ps_return_equal, fixed_memory_equal;
  logic [p_max_ia_banks-2:0] chunk_return_equal;
  logic [p_max_ia_banks-2:0][3:0] shared_memory_equal;
  channel_reference #({parameters}) u_reference(
      {common},
      .i_ia_read_en(i_ia_read_en & {{2{{i_access_enable}}}}),
      .i_ia_write_en(i_ia_write_en & {{2{{i_access_enable}}}}),
      .i_ps_read_en(i_ps_read_en & {{4{{i_access_enable}}}}),
      .i_ps_write_en(i_ps_write_en & {{4{{i_access_enable}}}}),
      .o_capacity_fault(reference_fault), .o_ia_read_data(reference_ia_data),
      .o_ps_read_data(reference_ps_data));
  channel_current #({parameters}) u_current(
      {common}, .i_access_enable(i_access_enable),
      .i_ia_read_en(i_ia_read_en), .i_ia_write_en(i_ia_write_en),
      .i_ps_read_en(i_ps_read_en), .i_ps_write_en(i_ps_write_en),
      .o_capacity_fault(current_fault), .o_ia_read_data(current_ia_data),
      .o_ps_read_data(current_ps_data));
  for(genvar port_index=0;port_index<2;port_index++) begin : g_ia_return
    assign ia_return_equal[port_index] =
      u_reference.ia_return_bank_q[port_index] == u_current.ia_return_bank_q[port_index];
  end
  for(genvar port_index=0;port_index<4;port_index++) begin : g_ps_return
    assign ps_return_equal[port_index] =
      u_reference.ps_return_select_q[port_index] == u_current.ps_return_select_q[port_index];
    assign fixed_memory_equal[port_index] = {memory_equal('g_fixed_channel[port_index].u_ram')};
  end
  for(genvar bank=1;bank<p_max_ia_banks;bank++) begin : g_shared_bank
    assign chunk_return_equal[bank-1] =
      u_reference.g_shared_bank[bank].return_chunk_q == u_current.g_shared_bank[bank].return_chunk_q;
    for(genvar port_index=0;port_index<4;port_index++) begin : g_channel
      assign shared_memory_equal[bank-1][port_index] =
        {memory_equal('g_shared_bank[bank].g_channel[port_index].u_ram')};
    end
  end
  assign equivalent = reference_fault == current_fault &&
      u_reference.configured_q == u_current.configured_q &&
      u_reference.ia_banks_q == u_current.ia_banks_q &&
      (&ia_return_equal) && (&ps_return_equal) && (&chunk_return_equal) &&
      (&fixed_memory_equal) && (&shared_memory_equal) && {memory_equal('u_ia_ram')};
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--baseline-ref', default='dde5e7c9')
    parser.add_argument('--profiles', nargs='+', default=['2048:6', '2048:8', '8192:7', '8192:9'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT)
    current = (source_root / SOURCE).read_bytes()
    target = out / 'access_miter.sv'
    target.write_text(miter(reference.decode(), current.decode()))
    results = []
    for profile in args.profiles:
        bank_bytes, banks = map(int, profile.split(':'))
        for stage in (0, 1):
            label = f'b{bank_bytes}_n{banks}_s{stage}'
            script, log = out / f'{label}.ys', out / f'{label}.log'
            options = (f'-Gp_bank_bytes={bank_bytes} -Gp_total_bytes={bank_bytes*banks} '
                       f'-Gp_shared_write_stage={stage}')
            script.write_text(f'read_slang --top access_miter {options} {shlex.quote(str(target))}\n'
                              'prep -top access_miter -flatten\nasync2sync\nopt_clean\n'
                              'sat -verify -tempinduct -seq 2 -set-init-zero -prove equivalent 1 '
                              '-show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            if 'Induction step proven: SUCCESS!' not in log.read_text():
                raise RuntimeError(f'{label} 未完成时序归纳证明')
            results.append({'case': label, 'passed': True, 'bank_bytes': bank_bytes,
                            'banks': banks, 'shared_write_stage': stage,
                            'log_sha256': digest(log.read_bytes())})
            print('SHARED_ACCESS_PROOF_PASS', label, flush=True)
    if current != (source_root / SOURCE).read_bytes():
        raise RuntimeError('证明期间共享存储源码发生变化')
    report = {'passed': True, 'reference_revision': revision, 'input_constraints': None,
              'scope': '所有配置与返回选择寄存器；全部物理存储读写使能及有效命令的地址、写掩码、写数据',
              'memory_model': '物理存储数据返回置零；所有访问命令和读取选择均逐位比较',
              'source_sha256': {SOURCE: digest(current)},
              'reference_source_sha256': {SOURCE: digest(reference)},
              'runner_sha256': digest(Path(__file__).read_bytes()),
              'miter_sha256': digest(target.read_bytes()), 'cases': results}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
