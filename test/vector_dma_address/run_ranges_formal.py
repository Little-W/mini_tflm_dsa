#!/usr/bin/env python3
"""证明四组 DMA 范围的起点、末端和配置输出保持相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/conv/vector_engine.sv'


def fragment(source):
    marker='  logic [32:0] dma_range_size' if '  logic [32:0] dma_range_size' in source else '  // Parameter and cached-input phases configure'
    a=source.index(marker);b=source.index('  assign rd_req',a)
    state=re.search(r'typedef enum logic \[5:0\].*?state_t;',source,re.S)[0]
    return '''module vector_range_decode (
      input logic [5:0] state,
      input vector_engine_pkg::vector_engine_cfg_t c,
      input logic dma_cfg_ready,spatial,global_pool,input_range_mode,depthwise,binary_vector,softmax_s8,
      input logic [63:0] input_bytes,weight_bytes,parameter_bytes,
      output logic dma_cfg_valid,dma_conv_enable,dma_range_enable,
      output conv_im2col_pkg::conv_cfg_t dma_conv_cfg,
      output logic [31:0] dma_range_base [4],
      output logic [32:0] dma_range_end [4]
    );\n'''+state+'\n'+source[a:b]+'\nendmodule\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--reference-rev',default='2f06471c');args=p.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    ref=subprocess.check_output(['git','show',args.reference_rev+':'+SOURCE],cwd=ROOT,text=True)
    cand=(ROOT/SOURCE).read_text()
    packages=[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    commands=[];cases={}
    for label,source in [('reference',ref),('candidate',cand)]:
        path=out/(label+'.sv');path.write_text(fragment(source))
        commands+=['read_slang --top vector_range_decode '+' '.join(shlex.quote(str(p)) for p in packages+[path]),
                   'prep -top vector_range_decode -flatten','opt -full','rename vector_range_decode '+label,'design -stash '+label]
        cases[label]={'top':'vector_range_decode','options':[],'sources':[str(p) for p in packages+[path]],
                      'configuration':'4 allocation ranges with 32-bit bases and 33-bit ends'}
    commands+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
               'equiv_make reference candidate comparison','hierarchy -top comparison','equiv_simple','equiv_status -assert']
    script=out/'run.ys';script.write_text('\n'.join(commands)+'\n');log=out/'formal.log'
    with log.open('w') as stream:
        r=subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
    report={'reference_rev':args.reference_rev,'source_sha256':hashlib.sha256(cand.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(ref.encode()).hexdigest(),'inputs_constrained':False,
            'equivalent_bits':int(match[1]) if match else None,
            'passed':r.returncode==0 and 'Equivalence successfully proven' in text,
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    if not report['passed']:raise RuntimeError(text[-8000:])


if __name__=='__main__':
    main()
