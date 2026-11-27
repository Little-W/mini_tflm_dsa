#!/usr/bin/env python3
"""证明提前请求控制与完整地址候选的定宽行为。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']([
        ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',
        ROOT/'rtl/npu/conv/conv_im2col_row_lookahead.sv',
        Path(__file__).with_name('row_lookahead_reference.sv')],ROOT)
    hashes={str(p):digest(p) for p in sources};results=[]
    for mode,flags in [('generic',['-USYNTHESIS','-UXILINX_FPGA']),
                       ('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
        for enabled in (0,1):
            for shift in (3,4):
                name=f'{mode}_enabled{enabled}_shift{shift}'
                options=[*flags,f'-Gp_word_shift={shift}',f'-Gp_enabled={enabled}']
                commands=[]
                for label,top in [('reference','conv_im2col_row_lookahead_reference'),
                                   ('current','conv_im2col_row_lookahead')]:
                    commands+=['read_slang --top '+top+' '+shlex.join(options+list(map(str,sources))),
                        'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                        'prep -top '+top+' -flatten','async2sync','opt -full',
                        'rename -top '+label,'design -stash '+label]
                commands+=['design -copy-from reference -as reference reference',
                    'design -copy-from current -as current current','equiv_make reference current proof',
                    'hierarchy -top proof','opt -full','equiv_simple -seq 1',
                    'equiv_induct -seq 3','equiv_simple -seq 1','equiv_status -assert']
                script=out/(name+'.ys');script.write_text('\n'.join(commands)+'\n');log=out/(name+'.log')
                with log.open('w') as output:
                    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                        stdout=output,stderr=subprocess.STDOUT,check=True,timeout=180)
                counts=re.findall(r'Found (\d+) \$equiv cells',log.read_text())
                assert counts and 'Equivalence successfully proven!' in log.read_text()
                result=dict(mode=mode,enabled=enabled,word_shift=shift,passed=True,
                    bits=int(counts[-1]),input_constraints=[],log_sha256=digest(log))
                results.append(result);print(json.dumps(result),flush=True)
    assert all(digest(p)==expected for p,expected in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        results=results),indent=2)+'\n')


if __name__=='__main__':
    main()
