#!/usr/bin/env python3
"""提取实际请求表达式，证明末端槽位选择与完整需求、预取表达式等价。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/loaders/kernel_loader.sv'
    original = source.read_text()
    statements = []
    for name in ('managed_request_eligible', 'managed_request_available',
                 'demand_data_available', 'prefetch_available'):
        match = re.search(r'\bassign\s+'+name+r'\s*=.*?;', original, re.S)
        if match is None:
            raise RuntimeError('实际请求表达式不存在：'+name)
        statements.append(match[0])
    model = out/'request_check.sv'
    model.write_text('''// 请求条件全部独立取值，不限制预取状态或输入顺序。
module request_check(
 input logic [6:0] controls, // 槽位、传输、需求和预取的任意状态
 output logic equal // 两种请求计算得到相同四态结果
);
wire buf_load_ready=controls[0],transfer_active=controls[1],ext_dma_busy=controls[2];
wire managed_demand_available=controls[3],command_waiting=controls[4];
wire [1:0] prefetch_state=controls[6:5];
localparam [1:0] PF_EMPTY=0,PF_PENDING=1,PF_LOADING=2,PF_CACHED=3;
wire managed_request_eligible,managed_request_available,demand_data_available,prefetch_available;
'''+ '\n'.join(statements)+'''
assign equal=managed_request_available===
 ((managed_demand_available&&demand_data_available)||prefetch_available);
endmodule
''')
    script, log = out/'request.ys', out/'request_formal.log'
    script.write_text('read_slang --top request_check -USYNTHESIS -UXILINX_FPGA '+
        shlex.quote(str(model))+'\nprep -top request_check -flatten\n'+
        'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
            stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
        raise RuntimeError('请求资格任意输入证明未完成')
    bench, binary = out/'tb.sv', out/'tb.vvp'
    bench.write_text('''module tb;
logic [6:0] controls;wire equal;request_check dut(.*);
initial begin
 for(integer sample=0;sample<16384;sample++)begin
  for(integer bit_index=0;bit_index<7;bit_index++)begin
   case((sample>>(2*bit_index))&3)
    0:controls[bit_index]=1'b0;1:controls[bit_index]=1'b1;
    2:controls[bit_index]=1'bx;3:controls[bit_index]=1'bz;
   endcase
  end
  #1;if(equal!==1'b1)$fatal(1,"Request qualification differs sample=%0d",sample);
 end
 $display("REQUEST_QUALIFICATION_PASS checks=16384");$finish;
end
endmodule
''')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, model, bench],
            stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.check_output(['vvp', binary], text=True, timeout=120)
    (out/'four_state.log').write_text(result)
    if 'REQUEST_QUALIFICATION_PASS checks=16384' not in result or source.read_text() != original:
        raise RuntimeError('请求资格检查未完成或源文件发生变化')
    report = {'passed': True, 'inputs_constrained': False, 'logic_extracted_from_source': True,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'formal_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
        'four_state_exhaustive': True, 'four_state_comparisons': 16384,
        'four_state_log_sha256': hashlib.sha256(result.encode()).hexdigest()}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(result.strip())


if __name__ == '__main__':
    main()
