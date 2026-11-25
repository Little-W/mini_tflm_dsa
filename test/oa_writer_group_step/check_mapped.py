#!/usr/bin/env python3
"""用完整 FPGA 单元功能模型验证组步长映射后的全部输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from open_fpga_synth import run_stage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    mapped=json.loads(args.mapped.read_text())['modules']['writer_step']
    outputs=sum(len(p['bits']) for p in mapped['ports'].values() if p['direction']=='output')
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    script=out/'proof.ys'
    script.write_text('\n'.join([
        'read_slang --top writer_step -GREG_WIDTH=32 -GCOUNT_WIDTH=29 '+shlex.quote(str(args.source.resolve())),
        'prep -top writer_step -flatten','async2sync','opt -full',
        'rename -hide w:*','rename -top reference','design -stash reference',
        'read_json '+shlex.quote(str(args.mapped.resolve())),
        'delete =A:blackbox','read_verilog -overwrite +/xilinx/cells_sim.v',
        'rename writer_step current','setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
        'hierarchy -top current','flatten -wb','proc','memory_map','async2sync','opt -full',
        'rename -hide w:*','design -stash current',
        'design -copy-from reference -as reference reference',
        'design -copy-from current -as current current',
        'equiv_make reference current proof','hierarchy -top proof',
        'equiv_simple -seq 3','opt_clean','equiv_induct -seq 5','equiv_status -assert',
    ])+'\n')
    stage=run_stage(script,out/'proof.log',dict(os.environ))
    log=(out/'proof.log').read_text()
    count=re.search(r'Of those cells (\d+) are proven and 0 are unproven',log)
    if not count or int(count[1])!=outputs:raise RuntimeError('映射比较未完整覆盖公开输出')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report=dict(passed=True,compared_output_bits=outputs,proved_bits=int(count[1]),
                source_sha256=digest(args.source),mapped_sha256=digest(args.mapped),
                primitive_library_sha256=digest(library),runner_sha256=digest(Path(__file__)),
                input_value_constraints=None,primitive_model='完整 cells_sim.v 功能模型',**stage)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
