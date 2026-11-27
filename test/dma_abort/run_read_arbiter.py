#!/usr/bin/env python3
"""Verify read cancellation, accepted-context drain and subsequent commands."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--bus-width',type=int,choices=(32,64),default=64)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    dependency_tools=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    rtl=dependency_tools['with_dependencies']([ROOT/'rtl/npu/dma/axi_block_dma_arbiter.sv'],ROOT)
    tracked=dependency_tools['input_files'](rtl,ROOT)
    sources=[Path(__file__).resolve(),ROOT/'test/dma_abort/arbiter_read_tb.sv',*tracked]
    hashes={str(p.relative_to(ROOT)):sha(p) for p in sources}
    command=[args.verilator,'--binary','--timing','--assert','-Wno-fatal','-Wno-PINMISSING',
        '--top-module','arbiter_read_tb',f'-GBUS_WIDTH={args.bus_width}',
        '-I'+str(ROOT/'include'),
        '--Mdir',str(out/'obj'),'--output-groups','0','--output-split','10000','-j','1',
        '-CFLAGS','-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all',
        '-LDFLAGS','-fsanitize=undefined',*map(str,rtl),str(sources[1])]
    with (out/'compile.log').open('w') as f:result=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError((out/'compile.log').read_text()[-6000:])
    binary=out/'obj/Varbiter_read_tb'
    run=subprocess.run([str(binary)],cwd=ROOT,text=True,capture_output=True,timeout=30)
    (out/'run.log').write_text(run.stdout+run.stderr)
    if run.returncode:raise RuntimeError(run.stdout+run.stderr)
    reports=[json.loads(s) for s in run.stdout.splitlines() if s.startswith('{"passed":')]
    assert len(reports)==1 and reports[0]['passed']
    assert hashes=={str(p.relative_to(ROOT)):sha(p) for p in sources}
    report=dict(**reports[0],source_sha256=hashes,binary_sha256=sha(binary),
        compile_command=command,run_command=[str(binary)],undefined_behavior_sanitizer=True)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(reports[0]))

if __name__=='__main__':main()
