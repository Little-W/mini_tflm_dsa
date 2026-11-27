#!/usr/bin/env python3
"""验证提前读取的完整地址顺序、空间边界与四态停止条件。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']([
        ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',
        ROOT/'rtl/npu/conv/conv_im2col_row_lookahead.sv',
        Path(__file__).with_name('row_lookahead_reference.sv'),
        Path(__file__).with_name('tb_row_lookahead.sv')],ROOT)
    hashes={str(p):digest(p) for p in sources};results=[]
    for mode,flags in [('generic',[]),('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
        for shift in (3,4):
            name=f'{mode}_shift{shift}';binary=out/(name+'.vvp');log=out/(name+'.log')
            with (out/(name+'_build.log')).open('w') as output:
                subprocess.run(['iverilog','-g2012',*flags,'-s','tb_row_lookahead',
                    f'-Ptb_row_lookahead.p_word_shift={shift}','-o',str(binary),*map(str,sources)],
                    stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
            with log.open('w') as output:
                subprocess.run(['vvp',str(binary)],stdout=output,stderr=subprocess.STDOUT,
                               check=True,timeout=180)
            match=re.search(r'LOOKAHEAD_SEQUENCE_PASS shift=(\d+) checks=(\d+) captures=(\d+) stalls=(\d+) clears=(\d+) four_state=(\d+)',log.read_text())
            assert match
            result=dict(mode=mode,passed=True,word_shift=int(match[1]),checks=int(match[2]),
                captures=int(match[3]),stalls=int(match[4]),clears=int(match[5]),
                four_state_checks=int(match[6]),log_sha256=digest(log))
            results.append(result);print(json.dumps(result),flush=True)
    assert all(digest(Path(p))==expected for p,expected in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        results=results),indent=2)+'\n')


if __name__=='__main__':
    main()
