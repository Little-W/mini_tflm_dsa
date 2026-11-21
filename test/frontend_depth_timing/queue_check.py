#!/usr/bin/env python3
"""证明窗口队列的待返回计数、描述符顺序及有效响应标签。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')

PROOF = r'''
module queue_check #(
  parameter int DEPTH=4, OUTSTANDING=2, LANES=4,
  PTR_W=$clog2(DEPTH), COUNT_W=$clog2(DEPTH+1)
)(
  input logic clk, rst_n, configure, enable, req_valid, rsp_ready,
  input logic frontend_ready, frontend_rsp_valid, frontend_rsp_last, frontend_error,
  input logic [31:0] req_p0, req_q0, req_cols,
  input logic [2:0] req_tag,
  input logic [3:0] frontend_rsp_col,
  input logic signed [15:0] frontend_rsp_data[LANES],
  input logic [LANES-1:0] frontend_rsp_mask,
  output logic equivalent
);
  logic req_ready, rsp_valid, rsp_last, rsp_error, busy;
  logic [2:0] rsp_tag;
  logic [3:0] rsp_col;
  logic signed [15:0] rsp_data[LANES];
  logic [LANES-1:0] rsp_mask;
  logic frontend_valid, frontend_active, frontend_rsp_ready, frontend_cols_valid;
  logic [31:0] frontend_p0, frontend_q0, frontend_cols;
  conv_window_queue #(.DEPTH(DEPTH), .TAG_W(3), .COL_W(4), .WINDOW_LANES(LANES),
    .p_max_cols(16), .p_frontend_outstanding(OUTSTANDING)) dut (.*);

  logic initialized=0;
  logic [PTR_W-1:0] model_head, model_tail;
  logic [COUNT_W:0] model_count, model_launched;
  logic model_failed;
  logic [95:0] model_payload[DEPTH];
  logic [2:0] model_tag[DEPTH];
  logic [DEPTH-1:0] written;
  logic accept, launch, retire;
  logic [PTR_W-1:0] model_present;
  logic [COUNT_W+PTR_W+1:0] present_sum;
  logic state_valid, payload_valid, output_valid, memory_valid;

  assign accept=req_valid && req_ready;
  assign launch=frontend_valid && frontend_ready;
  assign retire=rsp_valid && rsp_ready && rsp_last;
  assign present_sum=(COUNT_W+PTR_W+2)'(model_head)+(COUNT_W+PTR_W+2)'(model_launched);
  assign model_present=PTR_W'(present_sum % (COUNT_W+PTR_W+2)'(DEPTH));

  // 独立事务模型只在公开接口握手时记录接收、发送和完成。
  always_ff @(posedge clk) begin
    if (!rst_n) initialized<=1'b1;
    if (!rst_n || configure) begin
      model_head<=0;
      model_tail<=0;
      model_count<=0;
      model_launched<=0;
      model_failed<=0;
      written<=0;
    end else begin
      model_count<=model_count+(COUNT_W+1)'(accept)-(COUNT_W+1)'(retire);
      model_launched<=model_launched+(COUNT_W+1)'(launch)-
        (COUNT_W+1)'(retire && model_launched!=0);
      if (accept) begin
        model_payload[model_tail]<={req_p0,req_q0,req_cols};
        model_tag[model_tail]<=req_tag;
        written[model_tail]<=1'b1;
        model_tail<=model_tail==PTR_W'(DEPTH-1) ? '0 : model_tail+1'b1;
      end
      if (retire) model_head<=model_head==PTR_W'(DEPTH-1) ? '0 : model_head+1'b1;
      if (frontend_error) model_failed<=1'b1;
    end
  end

  always_comb begin
    state_valid=model_count<=DEPTH && model_launched<=OUTSTANDING &&
      model_launched<=model_count && dut.count==model_count &&
      dut.active_count==model_launched && dut.head==model_head && dut.tail==model_tail &&
      dut.present==model_present && dut.failed==model_failed &&
      busy==(model_count!=0) && frontend_active==(model_launched!=0);
    state_valid &= int'(model_tail)==(int'(model_head)+int'(model_count))%DEPTH;
    state_valid &= !launch || model_count>model_launched;
    state_valid &= !retire || model_count!=0;
    output_valid=req_ready==(enable && !configure && !model_failed && !frontend_error &&
      (model_count<DEPTH || retire));
    output_valid &= rsp_error==(model_failed || frontend_error);
    output_valid &= rsp_valid==(model_count!=0 &&
      (model_failed || frontend_error || (model_launched!=0 && frontend_rsp_valid)));
    output_valid &= frontend_rsp_ready==(model_launched!=0 && rsp_ready);
    output_valid &= frontend_valid==(enable && !configure && !model_failed && !frontend_error &&
      model_count!=0 && (model_launched<OUTSTANDING || retire) && dut.descriptor_prepared);
    if (rsp_valid) begin
      output_valid &= rsp_tag==model_tag[model_head] && written[model_head];
      output_valid &= rsp_last==(rsp_error || frontend_rsp_last);
      output_valid &= rsp_col==(rsp_error ? 0 : frontend_rsp_col);
      output_valid &= rsp_mask==(rsp_error ? 0 : frontend_rsp_mask);
      for (int lane=0;lane<LANES;lane++)
        output_valid &= rsp_data[lane]==(rsp_error ? 16'sd0 : frontend_rsp_data[lane]);
    end
    payload_valid=1'b1;
    if (dut.descriptor_prepared && !model_failed) begin
      payload_valid &= model_count>model_launched && written[model_present];
      payload_valid &= {frontend_p0,frontend_q0,frontend_cols}==model_payload[model_present];
      payload_valid &= frontend_cols_valid==(frontend_cols>0 && frontend_cols<=32'd16);
    end
    memory_valid=1'b1;
    for (int slot=0;slot<DEPTH;slot++) begin
      if (written[slot]) begin
        memory_valid &= {dut.g_descriptor[0].u_value.mem[slot],
                         dut.g_descriptor[1].u_value.mem[slot],
                         dut.g_descriptor[2].u_value.mem[slot]}==model_payload[slot];
        memory_valid &= dut.tags[slot]==model_tag[slot];
        memory_valid &= dut.cols_valid[slot]==
          (model_payload[slot][31:0]>0 && model_payload[slot][31:0]<=32'd16);
      end
      if (slot<int'(model_count))
        memory_valid &= written[(int'(model_head)+slot)%DEPTH];
    end
    equivalent=!initialized || !rst_n || (state_valid && output_valid && payload_valid && memory_valid);
  end
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--depths', type=int, nargs='+', default=[2, 3, 4, 7, 8])
    parser.add_argument('--outstanding', type=int, nargs='+', default=[1, 2, 3])
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = out / 'proof.sv'
    proof.write_text(PROOF)
    paths = [source_root / SOURCE, source_root / 'rtl/common/regfile.v', proof]
    hashes = {str(path): digest(path) for path in paths}
    records = []
    for depth in args.depths:
        for outstanding in args.outstanding:
            if outstanding > depth:
                continue
            name = f'depth{depth}_active{outstanding}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text(f'read_slang --top queue_check -D SYNTHESIS=1 -GDEPTH={depth} '
                f'-GOUTSTANDING={outstanding} ' + ' '.join(shlex.quote(str(p)) for p in paths) +
                '\nprep -top queue_check -flatten\nasync2sync\nmemory_map\nopt_clean\n' +
                'sat -seq 3 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -verify '
                '-maxsteps 12 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                         '--worker', str(script)], cwd=ROOT,
                                        stdout=stream, stderr=subprocess.STDOUT)
            text = log.read_text()
            if result.returncode or 'Induction step proven: SUCCESS!' not in text:
                raise RuntimeError(f'窗口队列证明未完成：{log}')
            records.append({'depth': depth, 'outstanding': outstanding, 'passed': True,
                'induction_steps': int(re.findall(r'\[induction step (\d+)\]', text)[-1]),
                'log_sha256': digest(log)})
            print('WINDOW_QUEUE_INDUCTION_PASS', name, flush=True)
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('证明期间输入源码发生变化')
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': records,
        'source_sha256': hashes, 'initial_reset': True, 'input_assumptions_after_reset': [],
        'properties': ['待返回计数守恒', '准备描述符与发送顺序', '响应标签及有效内容',
                       '同拍接收、发送与完成', '错误排空和重新配置']},
        ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
