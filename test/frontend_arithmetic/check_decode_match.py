#!/usr/bin/env python3
"""验证分组解码匹配及完整使用模块的输出和保存状态。"""
from __future__ import annotations

from formal_compilation import slang_command
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, bench, digest, run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--sources',type=Path,nargs='+',required=True)
    parser.add_argument('--helpers',type=Path,nargs='*',default=[])
    parser.add_argument('--reference',default='54a96b45')
    parser.add_argument('--reference-source-dir', type=Path)
    parser.add_argument('--compilation',choices=('generic','synthesis','both'),default='both')
    parser.add_argument('--lanes', type=int, nargs='+')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    dependencies=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    inputs=[p.resolve() for p in args.sources];hashes={};cases=[]
    for actual in inputs:
        top=actual.stem;reference=out/('reference_'+actual.name)
        if args.reference_source_dir is None:
            original=subprocess.check_output(['git','show',args.reference+':rtl/npu/conv/'+actual.name],cwd=ROOT,text=True)
        else:
            original=(args.reference_source_dir.resolve()/actual.name).read_text()
        # 形式模型采用标准 case 的顺序语义，禁止将状态位互斥作为额外优化条件。
        reference.write_text(original.replace('unique case', 'case'))
        formal_actual=out/('actual_'+actual.name)
        formal_actual.write_text(actual.read_text().replace('unique case', 'case'))
        actual_sources=dependencies([formal_actual,*[path.resolve() for path in args.helpers]],ROOT)
        reference_sources=dependencies([reference],ROOT)
        hashes.update({str(p):digest(p) for p in [actual,*actual_sources,*reference_sources]})
        registered_values=(0,1) if re.search(r'parameter\s+bit\s+p_register_descriptor\b',actual.read_text()) else (None,)
        modes=(0,1) if args.compilation=='both' else (int(args.compilation=='synthesis'),)
        lane_values=args.lanes if args.lanes and re.search(r'parameter\s+int\s+p_lanes\b',actual.read_text()) else (None,)
        for lanes in lane_values:
            for registered in registered_values:
                for synthesis in modes:
                    name=top+('' if lanes is None else f'_lanes{lanes}')+f'_registered{registered}_synthesis{synthesis}'
                    options=['-I'+str(ROOT/'include')]
                    if lanes is not None:options += ['-Gp_lanes='+str(lanes)]
                    if registered is not None:options += ['-Gp_register_descriptor='+str(registered)]
                    if synthesis:options += ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
                    script=out/(name+'.ys');text=[]
                    for label,sources in [('reference',reference_sources),('candidate',actual_sources)]:
                        text += [slang_command(options)+'--top '+top+' '+shlex.join([*options,*map(str,sources)]),
                            'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                            'prep -top '+top+' -flatten','memory_map','async2sync','opt -full','opt_clean -purge',
                            'rename -top '+label,'design -stash '+label]
                    text += ['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
                        'equiv_make reference candidate proof','hierarchy -top proof','equiv_simple -seq 2',
                        'opt_clean','equiv_induct -seq 3','equiv_status -assert']
                    script.write_text('\n'.join(text)+'\n');cases.append((name,script))
    def execute(item):
        name,script=item;log=out/(name+'.log')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        if 'Equivalence successfully proven!' not in log.read_text():raise ValueError('完整模块等价证明未完成：'+name)
        counts=re.findall(r'Found (\d+) \$equiv cells',log.read_text())
        print(name+' PASS',flush=True)
        return dict(name=name,passed=True,equivalence_cells=int(counts[-1]) if counts else None,log_sha256=digest(log))
    with ThreadPoolExecutor(max_workers=2) as pool:formal=list(pool.map(execute,cases))
    match=out/'match.sv';match.write_text('''module match_proof(input logic [31:0] i_a,i_b,output logic equivalent);
logic actual;
conv_descriptor_match #(.p_width(32),.p_preserve_groups(1'b1)) u_actual(.i_a,.i_b,.o_equal(actual));
assign equivalent=actual===(i_a==i_b);
endmodule
''')
    sources=dependencies([match],ROOT);hashes.update({str(p):digest(p) for p in sources})
    tb=out/'tb.sv';tb.write_text(bench(32));binary=out/'simulation.vvp'
    run(['iverilog','-g2012','-s','tb','-o',binary,*sources,tb],out/'compile.log')
    sim=out/'simulation.log';run(['vvp',binary],sim)
    if 'WORD_MATCH_PASS width=32 checks=4194' not in sim.read_text():raise ValueError('解码匹配四态比较未完成')
    assert all(digest(path)==value for path,value in hashes.items())
    reference_label=args.reference if args.reference_source_dir is None else str(args.reference_source_dir.resolve())
    report=dict(passed=True,reference=reference_label,compilation=args.compilation,lanes=args.lanes,input_assumptions=[],case_semantics='标准 case 顺序选择，不使用状态互斥假设',source_sha256=hashes,
        formal=formal,four_state=dict(passed=True,checks=4194,log_sha256=digest(sim)))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('DECODE_MATCH_PASS formal='+str(len(formal))+' four_state=4194')


if __name__=='__main__':main()
