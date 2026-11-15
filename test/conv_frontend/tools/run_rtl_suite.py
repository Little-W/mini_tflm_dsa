#!/usr/bin/env python3
"""Reproduce the actual frontend/adapter/cache parameter and protocol regression."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
CONFIGS = [
    (4,128,2,16,False), (8,128,2,16,False), (16,128,2,16,False),
    (4,128,2,16,True), (4,2,1,8,False), (8,2,2,32,False),
    (16,2,1,32,True), (16,2,2,256,False),
]


def run(config):
    size,sets,ways,line,path = config
    name=f'rtl_s{size}_sets{sets}_ways{ways}_line{line}'+('_path' if path else '')
    args=[sys.executable,'tools/run_rtl.py','--size',str(size),'--cache-sets',str(sets),
          '--cache-ways',str(ways),'--line-bytes',str(line)]+(['--tile-path'] if path else [])
    with (OUTPUT/f'{name}_driver.log').open('w') as stream:
        process=subprocess.run(args,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    status_path=OUTPUT/f'{name}_status.json'
    if process.returncode or not status_path.exists():
        return {'config':config,'status':'FAIL','driver_log':f'{name}_driver.log'}
    status=json.loads(status_path.read_text())
    output=Path(status['log']).read_text()
    status['summary']=next(line for line in output.splitlines() if 'RTL_FRONTEND_PASS' in line)
    return status


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    simulator=shutil.which('verilator')
    if not simulator: raise SystemExit('Verilator is required')
    version=subprocess.check_output([simulator,'--version'],text=True).strip()
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses=list(executor.map(run,CONFIGS))
    with (OUTPUT/'directed_driver.log').open('w') as stream:
        process=subprocess.run([sys.executable,'tools/run_directed_rtl.py'],cwd=ROOT,
                               stdout=stream,stderr=subprocess.STDOUT)
    for test in ['span','control']:
        path=OUTPUT/f'rtl_{test}_status.json'
        statuses.append(json.loads(path.read_text()) if path.exists() else {'test':test,'status':'FAIL'})
    passed=process.returncode==0 and all(item['status']=='PASS' for item in statuses)
    report={'scope':'standalone frontend, tile adapter, exact AXI span, and control RTL; not original NPU end-to-end',
            'status':'PASS' if passed else 'FAIL','simulator_version':version,'runs':statuses}
    (OUTPUT/'frontend_rtl_suite_status.json').write_text(json.dumps(report,indent=2))
    for item in statuses: print(item.get('summary',item),flush=True)
    print(report['status'],version)
    return 0 if passed else 1


if __name__=='__main__': raise SystemExit(main())
