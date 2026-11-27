#!/usr/bin/env python3
"""验证直连描述符的数据字匹配及寄存描述符的静态参数分支。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import dependencies
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=root/'rtl/npu/conv/conv_descriptor_addresses.sv'
    model=out/'direct_word.sv'
    model.write_text("""module comparison #(
 parameter int p_word_shift=3,
 parameter bit REGISTER_DESCRIPTOR=1'b0,
 parameter bit PREVIEW_REGISTERED=1'b0
)(
 input logic [31:0] row_base_addr,tap_step_bytes,tap_wrap_bytes,word_addr,addr,
 input logic incoming_q_equal,incoming_tap_wrap,
 output logic equivalent
);
 logic incoming_word_o_equal,incoming_live_word_o_equal;
 logic [31:0] expected_delta,expected_address;
 logic expected_saved,expected_live;
 conv_descriptor_addresses #(
   .p_word_shift(p_word_shift), .p_register_descriptor(REGISTER_DESCRIPTOR),
   .p_preview_registered(PREVIEW_REGISTERED)
 ) u_addresses (
   .i_word_addr(word_addr), .i_word_forward(1'b0), .i_addr(addr),
   .i_row_base_addr(row_base_addr), .i_row_group_base(32'd0),
   .i_window_addr(32'd0), .i_window_group_base(32'd0),
   .i_tap_step_bytes(tap_step_bytes), .i_tap_wrap_bytes(tap_wrap_bytes),
   .i_tap_pair_bytes(32'd0), .i_row_step_bytes(32'd0), .i_row_wrap_bytes(32'd0),
   .i_next_row_addr(32'd0), .i_kx0_q(16'd0), .i_row_wrap(1'b0),
   .i_incoming_tap_wrap(incoming_tap_wrap), .i_q_equal(incoming_q_equal),
   .i_position_previous_row(1'b0), .i_position_forward_tap(1'b0),
   .i_position_backward_tap(1'b0), .i_next_position_fast(1'b0), .i_next_tile_fast(1'b0),
   .o_candidate_address(), .o_incoming_word_equal(incoming_word_o_equal),
   .o_incoming_live_word_equal(incoming_live_word_o_equal),
   .o_next_row_word_match(), .o_incoming_advanced_word_match()
 );
 assign expected_delta=incoming_q_equal?32'd0:incoming_tap_wrap?tap_wrap_bytes:tap_step_bytes;
 assign expected_address=row_base_addr+expected_delta;
 assign expected_saved=expected_address[31:p_word_shift]==word_addr[31:p_word_shift];
 assign expected_live=expected_address[31:p_word_shift]==addr[31:p_word_shift];
 assign equivalent=(REGISTER_DESCRIPTOR&&!PREVIEW_REGISTERED)?
   {incoming_word_o_equal,incoming_live_word_o_equal}==2'b0:
   {incoming_word_o_equal,incoming_live_word_o_equal}=={expected_saved,expected_live};
endmodule
""")
    sources=dependencies(root,[source,model])
    source_paths=[path for path in sources if path.is_relative_to(root)]
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    cases=[]
    for shift in (1,2,3,4,5,6,7):
        for registered,preview in ((0,0),(0,1),(1,0),(1,1)):
            stem=f'shift{shift}_registered{registered}_preview{preview}';script,log=out/(stem+'.ys'),out/(stem+'.log')
            script.write_text(f'read_slang -DSYNTHESIS=1 --top comparison -Gp_word_shift={shift} -GREGISTER_DESCRIPTOR={registered} -GPREVIEW_REGISTERED={preview} '+
                              shlex.join(map(str,sources))+
                              '\nprep -top comparison -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as output:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                      cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
            if result.returncode or 'SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
            cases.append({'word_bytes':1<<shift,'register_descriptor':registered,'preview_registered':preview,'passed':True,
                          'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    assert hashes=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    report={'passed':True,'cases':cases,'source_sha256':hashes,'inputs_constrained':False,
            'input_bits':162,'output_bits':2,
            'scope':'实际直连描述符的保存字及返回字匹配表达式，完整三十二位地址回绕与参数静态分支',
            'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('DIRECT_DESCRIPTOR_WORD_PASS',len(cases))

if __name__=='__main__':main()
