#!/usr/bin/env python3
"""验证实际窗口槽位控制的提前预约、返回等待、失败排空和四态资格。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_control(source):
    """直接提取生产表达式及全部槽位状态更新，保留原始优先级。"""
    text = source.read_text()
    names = ('input_slot_release', 'window_request_idle',
             'window_request_release_enabled', 'win_rsp_ready',
             'window_request_fire', 'window_response_fire', 'input_ready_release')
    statements = []
    for name in names:
        matches = re.findall(r'  assign\s+' + name + r'\s*=.*?;', text, re.S)
        if len(matches) != 1:
            raise ValueError('需要唯一的生产表达式：' + name)
        statements.append(matches[0])
    qualifier = re.search(r'  vector_window_request_qualify u_window_request_qualify \(.*?\n  \);', text, re.S)
    if qualifier is None:
        raise ValueError('缺少窗口请求资格实例')
    response_start = text.index('  always_ff @(posedge clk or negedge rst_n) begin',
                                text.index('assign window_request_fire='))
    response_end = text.index('  assign window_response_fault', response_start)
    state_start = text.index('  for (genvar bank = 0; bank < 4; bank++) begin : g_input_ready')
    state_end = text.index('  // 相邻通道成对求和', state_start)
    return '''`default_nettype none
// 从生产模块提取的窗口槽位控制，位置范围和任务清空作为外部资格输入。
module window_control #(
  parameter bit p_input_bank_storage=0,
  parameter int p_pe_count=8
) (
  input wire logic clk, // 工作时钟。
  input wire logic rst_n, // 低有效复位。
  input wire logic depthwise, // 当前任务采用深度卷积。
  input wire logic state_failed, // 当前任务正在排空失败操作。
  input wire logic window_slot_available, // 当前候选窗口已经通过范围检查。
  input wire logic window_response_fault, // 已保存返回发现错误。
  input wire logic win_req_ready, // 窗口队列允许接收请求。
  input wire logic [1:0] wf_bank, // 候选请求的目标槽号。
  input wire logic [1:0] read_bank, // 当前计算读取的槽号。
  input wire logic dw_issue_fire, // 当前乘加组已经捕获操作数。
  input wire logic dw_group_last, // 当前乘加组为窗口末组。
  input wire logic state_compute_commit, // 池化计算正在提交。
  input wire logic compute_group_last_q, // 池化当前组为末组。
  input wire logic global_pool, // 当前任务使用全局池化。
  input wire logic spatial, // 当前任务使用空间窗口。
  input wire logic clear_all, // 已排空任务初始化或结束时清空槽位。
  input wire logic win_rsp_valid, // 返回数据有效。
  input wire logic win_rsp_last, // 当前返回结束该窗口。
  input wire logic win_rsp_error, // 当前返回报告错误。
  input wire logic [1:0] win_rsp_tag, // 当前返回的目标槽号。
  output logic win_req_valid, // 当前窗口请求有效。
  output logic win_rsp_ready, // 当前槽位可以接收返回数据。
  output logic window_request_fire, // 本周期接受窗口请求。
  output logic window_response_fire, // 本周期接受窗口响应。
  output logic [3:0] input_ready, // 各槽位中已有完整窗口数据。
  output logic [3:0] input_reserved // 各槽位已有尚未完成的窗口请求。
);
  logic input_slot_release, window_request_idle, window_request_release_enabled;
  logic input_ready_release;
  wire input_ready_clear_all=clear_all;
  wire input_reservations_clear=clear_all;
  logic window_response_last_q, window_response_error_q, window_response_count_ok_q;
  logic [1:0] window_response_tag;
  wire window_count_o_equal=1'b1;
''' + '\n'.join(statements) + '\n' + qualifier[0] + '\n' + text[response_start:response_end] + text[state_start:state_end] + '''
endmodule
`default_nettype wire
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/conv/vector_engine_address.sv'
    qualifier = ROOT / 'rtl/npu/conv/vector_window_request_qualify.sv'
    checked = [source, qualifier, Path(__file__), HERE / 'tb_control.sv']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in checked}
    actual = out / 'window_control.sv'
    actual.write_text(extract_control(source))
    results = []
    for pe_count, registered in ((8, 0), (8, 1), (16, 0)):
        folder = out / f'pe{pe_count}_storage{registered}'
        folder.mkdir(exist_ok=True)
        commands = [
            [args.iverilog, '-g2012', '-s', 'tb', f'-Ptb.REGISTERED={registered}', f'-Ptb.PE_COUNT={pe_count}',
             '-o', str(folder / 'simulation'), str(qualifier), str(actual), str(HERE / 'tb_control.sv')],
            [args.vvp, str(folder / 'simulation')],
        ]
        for command, name in zip(commands, ('compile.log', 'run.log')):
            with (folder / name).open('w') as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        log = (folder / 'run.log').read_text()
        match = re.search(r'WINDOW_CONTROL_PASS checks=(\d+) four_state=(\d+) early=(\d+) held=(\d+) failed=(\d+) blocked=(\d+) released=(\d+)', log)
        if not match:
            raise ValueError('缺少完整测试结果')
        counts = dict(zip(('checks', 'four_state', 'early_requests', 'held_responses', 'failed_drains',
                           'occupied_requests_blocked', 'consume_edge_requests'), map(int, match.groups())))
        required = ('checks', 'four_state', 'failed_drains')
        required += ('early_requests', 'held_responses') if pe_count < 16 else (
            'occupied_requests_blocked', 'consume_edge_requests')
        if min(counts[name] for name in required) <= 0:
            raise ValueError('必要控制情形未执行')
        results.append({'pe_count': pe_count, 'registered_storage': registered, 'passed': True, **counts,
                        'commands': commands, 'log_sha256': digest(folder / 'run.log')})
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in checked}:
        raise ValueError('执行期间源码发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'extracted_sha256': digest(actual), 'results': results}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
