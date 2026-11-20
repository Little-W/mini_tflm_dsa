#!/usr/bin/env python3
"""证明向量分组结束比较与完整配置检查的全部状态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]


def run(commands,folder):
    folder.mkdir(parents=True,exist_ok=True)
    script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
    with log.open('w') as stream:
        r=subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
    result={'passed':r.returncode==0 and 'Equivalence successfully proven' in text,
            'equivalent_bits':int(match[1]) if match else None,
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    print(json.dumps(result),flush=True)
    if not result['passed']:raise RuntimeError(text[-8000:])
    return result


def compare(paths,top,options,packages):
    commands=[]
    for label,path in paths:
        commands+=['read_slang --top '+top+' '+options+' '+' '.join(shlex.quote(str(p)) for p in packages+[path]),
                   'prep -top '+top+' -flatten','memory_map','async2sync','opt -full',
                   'rename '+top+' '+label,'design -stash '+label]
    commands+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
               'equiv_make reference candidate comparison','hierarchy -top comparison',
               'equiv_simple','equiv_induct -seq 2','equiv_status -assert']
    return commands


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--reference-rev',default='2f06471c');args=p.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    packages=[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    source=(ROOT/'rtl/npu/conv/vector_engine.sv').read_text()
    assert 'VECTOR_NEXT: if (vector_has_more)' in source
    declaration=re.search(r'  logic \[ACTIVE_COUNT_W:0\] vector_low_sum;.*?logic vector_has_more;',source,re.S)[0]
    body=re.search(r'  assign vector_low_sum.*?(?=  // 偏移)',source,re.S)[0]
    report={'inputs_constrained':False,'source_sha256':{},'group_comparison':[]}
    for tile in (1,3,16,32,64):
        folder=out/f'tile{tile}';folder.mkdir(exist_ok=True);paths=[]
        header=f'''module vector_group_compare #(
          parameter int ACTIVE_COUNT_W=$clog2({tile}+1)
        ) (
          input logic [31:0] vector_offset,
          input logic [ACTIVE_COUNT_W-1:0] active,
          input vector_engine_pkg::vector_engine_cfg_t c,
          output logic o_result
        );
        '''
        for label,logic in [('reference','assign o_result=(vector_offset+active<c.length);'),
                            ('candidate',declaration+body+'assign o_result=vector_has_more;')]:
            path=folder/(label+'.sv');path.write_text(header+logic+'\nendmodule\n');paths.append((label,path))
        result=run(compare(paths,'vector_group_compare','',packages),folder)
        result['tile']=tile;report['group_comparison'].append(result)
    relative='rtl/npu/conv/vector_config_check.sv'
    original=read_rtl_source(args.reference_rev+':'+relative, cwd=ROOT, text=True)
    reference=out/'config_reference.sv';reference.write_text(original)
    result=run(compare([('reference',reference),('candidate',ROOT/relative)],'vector_config_check','',packages),out/'config')
    report['configuration']=result
    for relative in ['rtl/npu/conv/vector_engine.sv','rtl/npu/conv/vector_config_check.sv']:
        report['source_sha256'][relative]=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
    report['reference_rev']=args.reference_rev
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
