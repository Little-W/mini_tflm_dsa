#!/usr/bin/env python3
"""Check discovered im2col capacities and independent spatial-set counts."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'build/im2col_config/driver')
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'test/im2col_cache_config/test_driver.c'
    tracked=[source,Path(__file__),*sorted((ROOT/'drivers').glob('*.h')),
             ROOT/'drivers/dsa_accel.c',ROOT/'drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/dsa_accel.c']
    hashes={str(path.relative_to(ROOT)):digest(path) for path in tracked}
    results=[]
    for api in ('standalone','nmsis'):
        for fallback in (4096,8192):
            name=f'{api}_{fallback}';binary=out/name
            command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
                     '-fsanitize=undefined','-fno-sanitize-recover=all','-DDSA_MMIO_CUSTOM',
                     '-DDSA_PS_COMPRESS=1','-DDSA_PS_POOL_BYTES=12288',
                     f'-DNPU_CONFIG_IM2COL_CACHE_BYTES={fallback}',
                     '-I',str(ROOT/'drivers')]
            if api=='nmsis':
                command[1:1]=['-DTEST_NMSIS','-I',str(ROOT/'drivers/tflm/NMSIS/NN/Include')]
            command+=[str(source),'-o',str(binary)]
            compiled=subprocess.run(command,capture_output=True,text=True)
            (out/f'{name}.build.log').write_text(compiled.stdout+compiled.stderr)
            if compiled.returncode:raise RuntimeError(compiled.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=120)
            (out/f'{name}.log').write_text(run.stdout+run.stderr)
            if run.returncode:raise RuntimeError(run.stdout+run.stderr)
            counts={key:int(value) for key,value in re.findall(r'(fallback|query_checks|plans|footprints|address_plans|image_costs)=(\d+)',run.stdout)}
            assert counts and counts['fallback']==fallback
            results.append(dict(profile=name,passed=True,command=command,counts=counts,
                                executable_sha256=digest(binary),run_log_sha256=digest(out/f'{name}.log')))
            print(run.stdout.strip(),flush=True)
    current={str(path.relative_to(ROOT)):digest(path) for path in tracked}
    assert current==hashes
    report=dict(passed=True,profiles=results,source_sha256=hashes,sources_unchanged=True,
                compiler=subprocess.check_output(['gcc','--version'],text=True).splitlines()[0])
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
