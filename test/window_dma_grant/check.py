#!/usr/bin/env python3
"""证明窗口授予的保持、转交、取消和其它请求方的状态更新。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')
PORTS = '''    input logic [2:0] rd_grant_client, // 当前保存的请求方编号
    input logic [2:0] rd_next_client, // 原优先级计算的后续请求方编号
    input logic rst_n, // 低有效复位
    input logic rd_dma_start, // 普通读取描述符已接收
    input logic local_abort, // 当前任务中止
    input logic conv_cfg_valid, // 卷积任务配置请求有效
    input logic win_req_valid, // 窗口描述符有效
    input logic win_req_ready, // 窗口描述符可接收
    input logic win_busy, // 窗口队列仍有未完成描述符
    input logic ia_req, // 输入激活读取请求有效
    input logic kernel_req, // 权重读取请求有效
    input logic bias_req, // 偏置读取请求有效
    input logic quant_req_eff, // 启用的量化读取请求有效
    input logic dw_req, // 向量读取请求有效
'''


def region(text):
    anchor = text.index('rd_grant_client <= C_NONE;')
    first = text.rfind('    always_ff @(posedge clk) begin', 0, anchor)
    end = text.index('    // 每个请求方', anchor)
    body = text[first:end].replace('always_ff @(posedge clk) begin',
                                  'always_comb begin\n        o_next = rd_grant_client;', 1)
    body = body.replace('rd_grant_client <=', 'o_next =')
    assert 'always_ff' not in body
    return body


def module(name, text):
    constants = re.search(r'    typedef enum logic \[2:0\] \{.*?\} client_e;', text, re.S).group(0)
    return f'''// 从实际仲裁寄存器更新块提取任意输入下的下一状态。
module {name} (
{PORTS}    output logic [2:0] o_next // 下一边沿保存的请求方编号
);
{constants}
{region(text)}
endmodule
'''


PROOF = '''// 同时证明窗口授予的八项转移条件和普通请求方的状态保持关系。
module grant_proof (
''' + PORTS + '''    output logic o_correct // 全部状态转移性质成立
);
    localparam [2:0] WINDOW=3'd5, NONE=3'd7;
    wire [2:0] current_next, reference_next;
    wire active=rst_n && !rd_dma_start;
    wire window_active=active && rd_grant_client==WINDOW && !local_abort && !conv_cfg_valid;
    wire [7:0] property_ok;
    grant_current current_design (.*,.o_next(current_next));
    grant_reference reference_design (.*,.o_next(reference_next));
    // 其它请求方保留原有全部更新，包含仲裁保留及各自的撤销条件。
    assign property_ok[0] = rd_grant_client==WINDOW || current_next==reference_next;
    // 在途窗口遇到请求间隔时保持授予。
    assign property_ok[1] = !(window_active && !win_req_valid && win_busy && rd_next_client==NONE) || current_next==WINDOW;
    // 窗口队列排空且没有新授予时恢复空闲。
    assign property_ok[2] = !(window_active && !win_req_valid && !win_busy && rd_next_client==NONE) || current_next==NONE;
    // 已有其它可服务请求时，在间隔周期转交授予。
    assign property_ok[3] = !(window_active && !win_req_valid && rd_next_client!=NONE) || current_next==rd_next_client;
    // 已接收窗口按原仲裁结果选择后续请求。
    assign property_ok[4] = !(window_active && win_req_valid && win_req_ready) || current_next==rd_next_client;
    // 接收方反压期间保存窗口授予。
    assign property_ok[5] = !(window_active && win_req_valid && !win_req_ready) || current_next==WINDOW;
    // 复位、开始普通命令、取消与重新配置均释放对应窗口授予。
    assign property_ok[6] = !(!active || (rd_grant_client==WINDOW && (local_abort || conv_cfg_valid))) || current_next==NONE;
    // 空闲状态接收已经由原优先级计算的后续授予。
    assign property_ok[7] = !(active && rd_grant_client==NONE) || current_next==rd_next_client;
    assign o_correct=&property_ok;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8be3489c')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)],
                                        cwd=ROOT, text=True)
    source = out / 'grant_proof.sv'
    source.write_text(module('grant_current', current) + module('grant_reference', reference) + PROOF)
    script = out / 'prove.ys'
    script.write_text(f'read_slang --top grant_proof {source}\n'
                      'prep -top grant_proof -flatten\ncheck -assert\n'
                      'sat -verify -prove o_correct 1 -show-inputs -show-outputs\n')
    log = out / 'prove.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
    assert current == (ROOT / SOURCE).read_text()
    report = {'passed': True, 'properties': 8, 'inputs_constrained': False,
              'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT,
                                                          text=True).strip(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'formal_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'proof_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
