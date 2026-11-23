#!/usr/bin/env python3
"""检查实际 PE 接入及无效通道的第二乘数选择。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-rev',default='caace9471dafe0236f0e2a9a40b8ddb48bdb844d')
    parser.add_argument('--engine-summary',type=Path)
    args=parser.parse_args()
    root=args.source_root.resolve()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    engine_runner=ROOT/'test/vector_pe_dsp/run_engine_formal.py'
    summary=args.engine_summary.resolve() if args.engine_summary else out/'engine/summary.json'
    if not args.engine_summary:
        subprocess.run([sys.executable,str(engine_runner),'--source-root',str(root),
                        '--reference-rev',args.reference_rev,'--out',str(summary.parent)],check=True,cwd=ROOT)
    engine=json.loads(summary.read_text())
    if not engine.get('passed') or engine.get('reference_revision')!=args.reference_rev:
        raise RuntimeError('PE 接入检查未完成或参考版本不一致')
    for name in ('rtl/npu/conv/vector_engine.sv','rtl/npu/conv/vector_pe.sv'):
        path=root/name
        if engine['source_sha256'].get(str(path))!=digest(path):
            raise RuntimeError('PE 接入检查的源码已变化')
    if engine['source_sha256'].get(str(engine_runner))!=digest(engine_runner):
        raise RuntimeError('PE 接入检查脚本已变化')
    wrapper=out/'b_selection.sv'
    wrapper.write_text(r'''
module b_selection #(parameter bit VALID_LANE=1'b0)(
  input logic clk,i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] raw_a,raw_b,
  input logic signed [31:0] raw_acc,
  output logic equal
);
  wire signed [15:0] selected_a=VALID_LANE ? raw_a : 16'sd0;
  wire signed [15:0] selected_b=VALID_LANE ? raw_b : 16'sd0;
  wire signed [31:0] selected_acc=VALID_LANE ? raw_acc : 32'sd0;
  wire signed [31:0] reference_result,current_result;
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b1)) u_reference(
    .clk,.i_en,.i_op,.i_a(selected_a),.i_b(selected_b),.i_acc(selected_acc),.o_result(reference_result));
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b1)) u_current(
    .clk,.i_en,.i_op,.i_a(selected_a),.i_b(raw_b),.i_acc(selected_acc),.o_result(current_result));
  assign equal=reference_result==current_result;
endmodule
''')
    pe=root/'rtl/npu/conv/vector_pe.sv'
    pe_hash=digest(pe)
    runs=[]
    for valid in (0,1):
        script,log=out/f'valid{valid}.ys',out/f'valid{valid}.log'
        script.write_text(f'read_slang --top b_selection -GVALID_LANE={valid} '+
                          shlex.join(map(str,[pe,wrapper]))+
                          '\nprep -top b_selection -flatten\nopt -full\n'+
                          'sat -verify -seq 4 -set-at 1 i_en 1 -prove-skip 1 -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=240)
        runs.append({'valid_lane':valid,'operation_codes':8,'passed':True,'log_sha256':digest(log)})
    if pe_hash!=digest(pe):
        raise RuntimeError('验证期间 PE 源码变化')
    report={'passed':True,'engine_summary':str(summary),'engine_summary_sha256':digest(summary),
            'engine':engine,'arithmetic':runs,'source_sha256':{str(pe):pe_hash},
            'test_sha256':digest(Path(__file__)),
            'initialization':{'first_cycle_i_en':1,'later_cycle_inputs':'unconstrained'}}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'validity_operation_cases':16}),flush=True)


if __name__=='__main__':
    main()
