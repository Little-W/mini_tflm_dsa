#!/usr/bin/env python3
"""验证输出掩码和独热传输数量选择的完整输入关系。"""
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
    path,source=read_module(root,'stream')
    predicate=re.search(r'  localparam bit p_contiguous_chunk\s*=([^,;\n]+)',source)[1]
    start=source.index('  assign chunk_selected[0]')
    following=('  logic incoming_request','  if (CHUNK_COUNT_W + 1 < 32)')
    stop=min(source.index(marker,start) for marker in following if marker in source[start:])
    selection='localparam bit p_contiguous_chunk = '+predicate+';\n'+source[start:stop]
    start=source.index('  for (genvar output_lane = 0; output_lane < LANES; output_lane++) begin : g_output_mask')
    output=source[start:source.index('  always_comb begin',start)]
    model=out/'chunk_mask.sv'
    model.write_text("""module comparison #(parameter int SIZE=16,LANES=8)(
 input logic [LANES-1:0] chunk_lane_allowed,
 output logic equivalent
);
 localparam int TILE_COUNT_W=$clog2(SIZE+1),CHUNK_COUNT_W=$clog2(LANES+1);
 logic [LANES:0] chunk_selected,expected_selection;
 logic [LANES-1:0] wr_mask,expected_mask;
 logic [CHUNK_COUNT_W-1:0] expected_count;
 logic prefix_mask;
"""+selection+output+"""
 always_comb begin
   expected_count='0;
   for(int lane=0;lane<LANES;lane++)begin
     if(chunk_lane_allowed[lane])expected_count=CHUNK_COUNT_W'(lane+1);
   end
 end
 for(genvar lane=0;lane<LANES;lane++)begin:g_expected_mask
   assign expected_mask[lane]=CHUNK_COUNT_W'(lane)<expected_count;
 end
 for(genvar step=0;step<=LANES;step++)begin:g_expected_count
   assign expected_selection[step]=expected_count==CHUNK_COUNT_W'(step);
 end
 assign prefix_mask=(chunk_lane_allowed&(chunk_lane_allowed+LANES'(1)))=='0;
 assign equivalent=(p_contiguous_chunk&&!prefix_mask)||
                   (wr_mask==expected_mask&&chunk_selected==expected_selection);
endmodule
""")
    cases=[]
    for size in (2,4,8,16):
        for lanes in (1,2,4,8,16):
            stem=f's{size}_l{lanes}';script=out/(stem+'.ys');log=out/(stem+'.log')
            script.write_text(f'read_slang --top comparison -GSIZE={size} -GLANES={lanes} '+shlex.quote(str(model))+
                              '\nprep -top comparison -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w')as stream:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                      cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
            if result.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
            cases.append({'size':size,'lanes':lanes,'passed':True,
                          'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    report={'passed':True,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cases':cases,
            'range_invariant':'连续通道优化适用时，通道资格形成从最低通道开始的连续前缀；其余参数检查任意掩码',
            'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('CHUNK_MASK_PASS',len(cases))

if __name__=='__main__':main()
