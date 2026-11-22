#!/usr/bin/env python3
"""验证直连描述符的数据字匹配及寄存描述符的静态参数分支。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import read_module
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
    source,text=read_module(root,'descriptor')
    helper=root/'rtl/common/add_equal.sv'
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,helper]}
    first=text.index('  if (!REGISTER_DESCRIPTOR) begin : g_direct_incoming_word')
    last=text.index('  // 七种地址候选',first) if source.name=='conv_im2col_descriptor.sv' else text.index('  if (CHUNK_COUNT_W + 1 < 32)',first)
    actual=text[first:last]
    model=out/'direct_word.sv'
    model.write_text("""module comparison #(
 parameter int p_word_shift=3,
 parameter bit REGISTER_DESCRIPTOR=1'b0
)(
 input logic [31:0] row_base_addr,tap_step_bytes,tap_wrap_bytes,word_addr,addr,
 input logic incoming_q_equal,incoming_tap_wrap,
 output logic equivalent
);
 logic incoming_word_o_equal,incoming_live_word_o_equal;
 logic [31:0] expected_delta,expected_address;
 logic expected_saved,expected_live;
"""+actual+"""
 assign expected_delta=incoming_q_equal?32'd0:incoming_tap_wrap?tap_wrap_bytes:tap_step_bytes;
 assign expected_address=row_base_addr+expected_delta;
 assign expected_saved=expected_address[31:p_word_shift]==word_addr[31:p_word_shift];
 assign expected_live=expected_address[31:p_word_shift]==addr[31:p_word_shift];
 assign equivalent=REGISTER_DESCRIPTOR?
   {incoming_word_o_equal,incoming_live_word_o_equal}==2'b0:
   {incoming_word_o_equal,incoming_live_word_o_equal}=={expected_saved,expected_live};
endmodule
""")
    cases=[]
    for shift in (1,2,3,4,5,6,7):
        for registered in (0,1):
            stem=f'shift{shift}_registered{registered}';script,log=out/(stem+'.ys'),out/(stem+'.log')
            script.write_text(f'read_slang --top comparison -Gp_word_shift={shift} -GREGISTER_DESCRIPTOR={registered} '+
                              shlex.join(map(str,[helper,model]))+
                              '\nprep -top comparison -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as output:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                      cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
            if result.returncode or 'SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
            cases.append({'word_bytes':1<<shift,'register_descriptor':registered,'passed':True,
                          'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    assert hashes=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,helper]}
    report={'passed':True,'cases':cases,'source_sha256':hashes,'inputs_constrained':False,
            'input_bits':162,'output_bits':2,
            'scope':'实际直连描述符的保存字及返回字匹配表达式，完整三十二位地址回绕与参数静态分支',
            'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('DIRECT_DESCRIPTOR_WORD_PASS',len(cases))

if __name__=='__main__':main()
