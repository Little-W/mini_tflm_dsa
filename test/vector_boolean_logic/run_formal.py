#!/usr/bin/env python3
"""验证向量偏移限幅、舍入、完整写回接口及读取地址算术。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(folder, commands):
    folder.mkdir(parents=True, exist_ok=True)
    script, log = folder/'run.ys', folder/'formal.log'
    script.write_text('\n'.join(commands)+'\n')
    with log.open('w') as output:
        result=subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                               '--worker', str(script)], cwd=ROOT, stdout=output,
                              stderr=subprocess.STDOUT, timeout=180)
    text=log.read_text()
    if result.returncode or not ('Equivalence successfully proven' in text or 'SUCCESS!' in text):
        raise RuntimeError(str(log)+'\n'+text[-3000:])
    return {'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)}


def offset_body(source):
    declarations=re.search(r'  logic \[\d+:0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;',
                           source,re.S).group(0)
    names=('q_offset_low','q_offset_increment','q_offset_decrement','q_rounded_fits_s9',
           'q_before_offset_below','q_before_offset_above','q_positive_overflow',
           'q_negative_overflow','q_below_min','q_above_max','q_clamped_data')
    body=declarations+'\n'
    for name in ('q_minimum_before_offset','q_maximum_before_offset'):
        value=re.search(r'\b'+name+r'\s*<=\s*(.*?);',source,re.S).group(1)
        body+='assign '+name+' = '+value+';\n'
    for name in names:
        body+=re.search(r'  assign '+name+r'\s*=.*?;',source,re.S).group(0)+'\n'
    return body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference',default='ef0dc75')
    parser.add_argument('--only',choices=('offset','round','writeback','address'))
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    selected=[args.only] if args.only else ['offset','round','writeback','address']
    hashes={}
    def track(relative):
        path=root/relative
        hashes[relative]=digest(path)
        return path
    report={'passed':False,'source_sha256':hashes,'checks':[]}
    if 'offset' in selected:
        source=track('rtl/npu/conv/vector_engine.sv')
        packages=[track('rtl/npu/conv/conv_im2col_pkg.sv'),track('rtl/npu/conv/vector_engine_pkg.sv')]
        model=out/'offset.sv'
        model.write_text("""module comparison(
 input logic signed [63:0] q_rounded,
 input logic signed [7:0] offset,minimum,maximum,
 output logic equivalent
);
 vector_engine_pkg::vector_engine_cfg_t c;
 logic signed [63:0] complete_sum;
 logic expected_below,expected_above;
 logic signed [31:0] expected_result;
 always_comb begin
   c='0;
   c.output_offset=32'(offset);
   c.activation_min=32'(minimum);
   c.activation_max=32'(maximum);
 end
"""+offset_body(source.read_text())+"""
 assign complete_sum=q_rounded+64'(offset);
 assign expected_below=complete_sum<64'(minimum);
 assign expected_above=complete_sum>64'(maximum);
 assign expected_result=expected_below?32'(minimum):
                        expected_above?32'(maximum):complete_sum[31:0];
 assign equivalent={q_below_min,q_above_max,q_clamped_data}==
                   {expected_below,expected_above,expected_result};
endmodule
""")
        item=execute(out/'offset',[
            'read_slang --top comparison '+shlex.join(map(str,[*packages,model])),
            'prep -top comparison -flatten','check -assert',
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs'])
        item.update(module='offset_clamp',input_bits=88,output_bits=34,
                    context='配置检查接受的 S8 偏移与激活界限；阈值寄存器保存当前稳定配置')
        report['checks'].append(item)
    profiles=[]
    if 'round' in selected:
        profiles += [('vector_round_shift',{'REGISTER_INPUT':a,'REGISTER_MIDDLE':m})
                     for a in (0,1) for m in (0,1)]
    if 'writeback' in selected:
        profiles += [('vector_writeback',{'TILE':tile,'BUS_WIDTH':bus})
                     for tile,bus in ((8,32),(16,32),(16,64),(16,128),(32,64))]
    for index,(top,parameters) in enumerate(profiles):
        path=track('rtl/npu/conv/'+top+'.sv')
        reference=out/(top+'_reference.sv')
        reference.write_text(read_rtl_source(args.reference+':rtl/npu/conv/'+top+'.sv',cwd=ROOT,text=True))
        options=' '.join('-G'+name+'='+str(value) for name,value in parameters.items())
        commands=[]
        for label,source in [('reference',reference),('current',path)]:
            commands += [f'read_slang -D ASIC_SYNTHESIS=1 --top {top} {options} {shlex.quote(str(source))}',
                         f'prep -top {top} -flatten','memory_map','async2sync','opt -full',
                         f'rename {top} {label}',f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current comparison','hierarchy -top comparison',
                     'equiv_simple -seq 2','opt_clean','equiv_induct -seq 3','equiv_status -assert']
        item=execute(out/(top+'_'+str(index)),commands)
        item.update(module=top,parameters=parameters,reference=args.reference,
                    reference_sha256=digest(reference),all_public_outputs_compared=True)
        report['checks'].append(item)
        print(json.dumps(item),flush=True)
    if 'address' in selected:
        helpers=runpy.run_path(str(ROOT/'test/conv_portable/run.py'))
        module,body=helpers['FORMAL']['address']
        sources=[track('rtl/npu/conv/'+module+'.sv'),track('rtl/common/parallel_prefix_add.sv')]
        model=out/'address.sv';model.write_text('module comparison(\n'+body)
        item=execute(out/'address',[
            'read_slang --top comparison '+shlex.join(map(str,[*sources,model])),
            'prep -top comparison -flatten','check -assert',
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs'])
        item.update(module=module,input_bits=80,output_bits=34,inputs_constrained=False)
        report['checks'].append(item)
    assert all(digest(root/path)==value for path,value in hashes.items())
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':len(report['checks'])}))


if __name__=='__main__':
    main()
