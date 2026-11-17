#!/usr/bin/env python3
"""Verify per-layer shared-memory allocation and prepared RAW32 policies."""
from pathlib import Path
import argparse
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/memory_policy')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,pcr,nmsis in [('standalone',0,False),('standalone_pcr',1,False),('nmsis',0,True),('nmsis_pcr',1,True)]:
        nn=ROOT/'drivers/tflm/NMSIS/NN'
        source=nn/'Source/ExtraAccFunctions/dsa_accel.c' if nmsis else ROOT/'drivers/dsa_accel.c'
        include=nn/'Include' if nmsis else ROOT/'drivers'
        binary=args.out/name
        command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
            '-fsanitize=undefined','-fno-sanitize-recover=all','-DDSA_MMIO_CUSTOM',
            '-DDSA_PS_COMPRESS=1','-DDSA_PS_POOL_BYTES=12288',f'-DDSA_PCR_ENGINE={pcr}',
            *(['-DNPU_CONFIG_NPU_AXI_DATA_WIDTH=64'] if pcr else []),
            '-I',str(include),'-I',str(ROOT/'drivers'),str(ROOT/'test/capacity/test_memory_policy.c'),str(source),'-o',str(binary)]
        compiled=subprocess.run(command,text=True,capture_output=True)
        (args.out/f'{name}.build.log').write_text(compiled.stdout+compiled.stderr)
        if compiled.returncode: raise RuntimeError(compiled.stderr)
        run=subprocess.run([str(binary)],text=True,capture_output=True,timeout=60)
        (args.out/f'{name}.log').write_text(run.stdout+run.stderr)
        print(name,run.stdout,end='',flush=True)
        if run.returncode: raise RuntimeError(run.stderr)
        results.append(dict(profile=name,passed=True,observations=run.stdout.splitlines()))
    (args.out/'summary.json').write_text(json.dumps(dict(passed=True,profiles=results),indent=2)+'\n')

if __name__=='__main__': main()
