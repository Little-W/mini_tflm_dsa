#!/usr/bin/env python3
"""Exercise shared IA/PS allocation registers with actual AXI-Lite transactions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--out',type=Path,default=ROOT/'build/shared_bank_registers')
    args=parser.parse_args()
    executable=shutil.which(args.verilator) or args.verilator
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/conv/00_conv_im2col_pkg.sv',ROOT/'rtl/axi_top/npu_axil_reg_if.sv',
             ROOT/'test/capacity/tb_shared_bank_registers.sv']
    dependencies=sources+[Path(__file__).resolve()]
    before={str(p.relative_to(ROOT)):sha(p) for p in dependencies}
    command=[executable,'--binary','--timing','--assert','--top-module','tb_shared_bank_registers',
             '-Wall','-Wno-fatal','-Wno-PINMISSING','--Mdir',str(out/'obj'),'-j','1',
             '-CFLAGS','-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all',
             '-LDFLAGS','-fsanitize=undefined',*map(str,sources)]
    start=time.monotonic()
    with (out/'build.log').open('w') as log:
        status=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if status.returncode:
        raise RuntimeError((out/'build.log').read_text()[-8000:])
    binary=out/'obj/Vtb_shared_bank_registers'
    run=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=30)
    (out/'run.log').write_text(run.stdout+run.stderr)
    if run.returncode:
        raise RuntimeError(run.stdout+run.stderr)
    result=[json.loads(s) for s in run.stdout.splitlines() if s.startswith('{"passed":')]
    if len(result)!=1 or not result[0]['passed']:
        raise RuntimeError('Missing successful register result')
    after={str(p.relative_to(ROOT)):sha(p) for p in dependencies}
    if before!=after:
        raise RuntimeError('Register sources changed during testing')
    warnings=[s for s in (out/'build.log').read_text().splitlines() if s.startswith('%Warning')]
    unexpected=[s for s in warnings if s.split(':',1)[0].removeprefix('%Warning-') not in
                {'DECLFILENAME','UNUSEDSIGNAL','UNUSEDPARAM','BLKSEQ','PROCASSINIT','SYNCASYNCNET'}]
    if unexpected:
        raise RuntimeError('Unexpected diagnostics: '+repr(unexpected))
    report=dict(**result[0],source_sha256=before,sources_unchanged=True,
        compile_command=command,run_command=[str(binary)],binary_sha256=sha(binary),
        undefined_behavior_sanitizer=True,warnings=warnings,elapsed_seconds=time.monotonic()-start)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','profiles','register_reads','register_writes',
                                          'rejected_writes','checks','elapsed_seconds')}))


if __name__=='__main__':
    main()
