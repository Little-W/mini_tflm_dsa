#!/usr/bin/env python3
"""证明实际通道偏移、组内位置与传输数量的完整求和。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    path,source=read_module(root,'geometry')
    assignments='\n'.join(re.search(r'  assign '+name+r' = .*?;',source,re.S).group(0)
                          for name in ('stream_epoch_xor','stream_epoch_carry'))
    assignments=assignments.replace('c.group_offset','group_offset')
    first=source.index('      logic [17:0] channel_sum;')
    last=source.index('    end else begin : g_general',first)
    actual=source[first:last].replace('epoch_i_a[candidate][17:0]','stream_epoch_xor[17:0]')
    actual=actual.replace('epoch_i_b[candidate][17:0]','stream_epoch_carry[17:0]')
    actual=actual.replace('epoch_o_sum[candidate]','current_sum')
    actual=re.sub(r"      assign unused_epoch_carry\[candidate\] = 1'b0;\n",'',actual)
    model=out/'epoch.sv'
    model.write_text("""module comparison #(parameter int LANES=8,CHUNK_COUNT_W=$clog2(LANES+1))(
 input logic [15:0] group_offset,ch_q,
 input logic [CHUNK_COUNT_W-1:0] chunk_count,
 output logic equivalent
);
 logic [31:0] ch,stream_epoch_xor,stream_epoch_carry,current_sum,expected;
 assign ch={16'd0,ch_q};
"""+assignments+actual+"""
 assign expected={16'd0,group_offset}+{16'd0,ch_q}+32'(chunk_count);
 assign equivalent=int'(chunk_count)>LANES || current_sum==expected;
endmodule
""")
    cases=[]
    for lanes in range(1,9):
        script,log=out/f'l{lanes}.ys',out/f'l{lanes}.log'
        script.write_text(f'read_slang --top comparison -GLANES={lanes} '+shlex.quote(str(model))+
                          '\nprep -top comparison -flatten\ncheck -assert\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                  cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
        if result.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
        cases.append({'lanes':lanes,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    report={'passed':True,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cases':cases,
            'input_scope':'group_offset 和 ch_q 为完整十六位值，chunk_count 为零至 LANES',
            'result_bits':32,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('EPOCH_SHARED_PASS',len(cases))

if __name__=='__main__':main()
