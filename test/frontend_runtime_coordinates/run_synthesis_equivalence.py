#!/usr/bin/env python3
"""在生产前端已经证明的事件唯一性条件下比较完整综合模型的周期行为。"""
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

from run_formal import ROOT, SOURCE, REFERENCE, PARAMETERS, PROFILES, profile_name
from protocol_model import case_conditions, observed_runtime


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--production-report',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--profile')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    production=json.loads(args.production_report.read_text())
    if not production['passed'] or not production['next_state_onehot_preserved']:
        raise RuntimeError('需要已通过的生产连接事件唯一性证明')
    current=(ROOT/SOURCE).read_text()
    reference=subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    if case_conditions(current)!=production['runtime_case_conditions'] or case_conditions(reference)!=case_conditions(current):
        raise RuntimeError('综合证明的事件集合与生产前端证明不同')
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources={}
    for label,source in [('reference',reference),('current',current)]:
        path=out/(label+'.sv');path.write_text(observed_runtime(source))
        sources[label]=resolver['with_dependencies']([path],ROOT)
    files=resolver['input_files']([ROOT/SOURCE,*[p for paths in sources.values() for p in paths]],ROOT)
    hashes={str(path):digest(path) for path in files}
    runs=[]
    for mode,flags in [('generic',['-USYNTHESIS','-UXILINX_FPGA']),
                       ('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
        for values in PROFILES:
            profile=profile_name(values)
            if args.profile and args.profile!=profile:continue
            parameters=dict(zip(PARAMETERS,values))
            parameters.update(p_row_high_width=27,p_cache_sets=16,p_cache_ways=2)
            options=['-G'+name+'='+str(value) for name,value in parameters.items()]
            commands=[]
            for label,paths in sources.items():
                commands += [shlex.join(['read_slang','--top','conv_im2col_runtime_registers',
                    '-I'+str(ROOT/'include'),*flags,*options,*map(str,paths)]),
                    'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy','setattr -unset keep',
                    'prep -top conv_im2col_runtime_registers -flatten','async2sync','opt_clean',
                    'rename conv_im2col_runtime_registers '+label,'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'expose -dff -shared reference/w:* current/w:*',
                'miter -equiv -make_outputs -make_outcmp -flatten reference current comparison',
                'hierarchy -top comparison','opt_clean',
                'sat -verify -seq 2 -tempinduct -maxsteps 5 -set-init-zero '+
                '-set gold_formal_main_unique 1 -set gold_formal_arithmetic_unique 1 -prove trigger 0']
            label=mode+'_'+profile;script=out/(label+'.ys');log=out/(label+'.log')
            script.write_text('\n'.join(commands)+'\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=480)
            text=log.read_text()
            if 'Induction step proven: SUCCESS!' not in text:
                raise RuntimeError('完整综合模型的状态归纳未完成')
            steps=re.findall(r'\[induction step (\d+)\]',text)
            row=dict(profile=profile,mode=mode,parameters=parameters,passed=True,
                     induction_steps=int(steps[-1]),log_sha256=digest(log))
            runs.append(row);print(json.dumps(row),flush=True)
    if not runs or any(digest(path)!=value for path,value in hashes.items()):
        raise RuntimeError('证明配置为空或运行期间源码发生变化')
    report=dict(passed=True,reference_commit=args.reference,
        input_conditions=production['runtime_case_conditions'],
        condition_rule='每组最多一个条件为1',condition_production_proof_sha256=digest(args.production_report),
        complete_public_outputs_and_common_state_compared=True,source_sha256=hashes,
        runner_sha256=digest(__file__),runs=runs)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
