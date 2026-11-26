#!/usr/bin/env python3
"""检查容量错误资格在接受、取消及四态条件下的结果。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/ps_compact/ps_frame_store.sv')
FLAGS=('frame_accept','frame_ready','frame_request','prepare_start',
       'configuration_ready','request_pending_q','request_legal','write_frame_end',
       'command_accepted','replay_armed','frame_final_q','capture_length_match',
       'replay_active','replay_consume','command_present')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='8b3728c0')
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source=ROOT/RTL
    current=source.read_text()
    original=subprocess.check_output(['git','show',f'{args.reference}:{RTL}'],cwd=ROOT,text=True)
    conditions=re.findall(r'if\(([^\n]+?)\)capacity_fault<=1;',original)
    if len(conditions)!=4:
        raise RuntimeError('参考容量错误条件数量不符')
    start=current.index('    logic capacity_set,')
    body=current[start:current.index('    always_ff',start)]
    cancel=re.search(r'    wire cancel_prepared =.*?;',current,re.S)[0]
    model=out/'fault.sv'
    model.write_text(f'''// 使用生产错误资格和参考顺序条件，检查接受脉冲与取消优先级。
module fault_proof #(parameter int F=4, W={len(FLAGS)}+3*F) (
    input logic [W-1:0] stimulus, // 任意控制标志和三个帧编号
    output logic equivalent // 容量错误置位资格的四态结果相同
);
    logic {', '.join(FLAGS)};
    logic [F-1:0] frame_id,frame_id_q,request_id;
    typedef struct packed {{logic [F-1:0] id; logic legal;}} request_t;
    request_t request_q;
    logic reference_set;
    assign {{{', '.join(FLAGS)},frame_id,frame_id_q,request_id}}=stimulus;
    assign request_q.id=request_id;
    assign request_q.legal=request_legal;
{cancel}
{body}
    always_comb begin
        reference_set=1'b0;
        if (cancel_prepared) begin
        end else begin
            if ({conditions[0]}) reference_set=1'b1;
            if (frame_accept) begin
                if ({conditions[1]}) reference_set=1'b1;
            end
            if (write_frame_end) begin
                if ({conditions[2]}) reference_set=1'b1;
            end
            if (replay_active) begin
                if ({conditions[3]}) reference_set=1'b1;
            end
        end
    end
    assign equivalent=(capacity_set===reference_set);
endmodule
''')
    runs=[]
    for frame_bits in (2,4):
        folder=out/f'f{frame_bits}'
        folder.mkdir(exist_ok=True)
        script,log=folder/'proof.ys',folder/'proof.log'
        script.write_text(f'read_slang --top fault_proof -GF={frame_bits} {model}\n'
            'prep -top fault_proof -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'容量错误资格证明未完成：{log}')
        width=len(FLAGS)+3*frame_bits
        bench=folder/'four_state.sv'
        bench.write_text(f'''// 覆盖错误并发、接受与取消、未知标志及高阻标志。
module tb;
    logic [{width-1}:0] stimulus;
    logic equivalent;
    integer checks=0;
    fault_proof #(.F({frame_bits})) u_proof(.stimulus(stimulus),.equivalent(equivalent));
    task automatic check;
        #1;
        if (equivalent!==1'b1) $fatal(1,"Capacity fault differs: %b",stimulus);
        checks++;
    endtask
    initial begin
        stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
        for (int sample=0;sample<20000;sample++) begin
            for (int b=0;b<{width};b++) stimulus[b]=1'($urandom);
            check();stimulus[sample%{width}]=1'bx;check();
            stimulus[sample%{width}]=1'bz;check();
        end
        $display("PS_CAPACITY_FAULT_PASS checks=%0d",checks);
        $finish;
    end
endmodule
''')
        binary=folder/'four_state.vvp'
        with (folder/'compile.log').open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(model),str(bench)],
                stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,check=True,timeout=300)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'PS_CAPACITY_FAULT_PASS checks=(\d+)',result.stdout)
        if match is None or int(match[1])!=60004:
            raise RuntimeError('容量错误资格四态比较未完成')
        row={'frame_id_bits':frame_bits,'formal':True,'four_state_checks':int(match[1]),
             'formal_log_sha256':digest(log),'simulation_log_sha256':digest(folder/'run.log')}
        runs.append(row)
        print(json.dumps(row),flush=True)
    report={'passed':True,'reference':args.reference,'input_constraints':None,'runs':runs,
            'source_sha256':digest(source),'model_sha256':digest(model),
            'reference_sha256':hashlib.sha256(original.encode()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
