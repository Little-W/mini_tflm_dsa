#!/usr/bin/env python3
"""检查短地址步长的逐位求和与完整无符号加法一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    path=args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
    source=path.read_text();sha=hashlib.sha256(path.read_bytes()).hexdigest()
    function=re.search(r'      function automatic logic \[p_step_width:0\] add_byte_step\(.*?      endfunction',source,re.S).group()
    rows=[]
    for width in range(2,10):
        sv,ys,log=[args.out/f'width{width}{suffix}'for suffix in ('.sv','.ys','.log')]
        sv.write_text(f'''module proof(input logic[{width-1}:0]value,input logic[{width}:0]amount,output logic equivalent);
 localparam int p_step_width={width};
{function}
 assign equivalent=add_byte_step(value,amount)==({{1'b0,value}}+amount);
endmodule
''')
        ys.write_text('read_slang --top proof '+shlex.quote(str(sv))+'\nprep -top proof -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                                  stdout=stream,stderr=subprocess.STDOUT,timeout=90)
        if result.returncode or 'SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
        rows.append({'value_width':width,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    assert sha==hashlib.sha256(path.read_bytes()).hexdigest()
    report={'passed':True,'source_sha256':sha,'input_constraints':[],'runs':rows}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('SHORT_ADDRESS_SUM_PASS',len(rows))


if __name__=='__main__':main()
