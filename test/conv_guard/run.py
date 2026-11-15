#!/usr/bin/env python3
"""Run the production read guard with an address-mapped AXI responder."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RESULTS=ROOT/'build/conv_guard'
RESULTS.mkdir(parents=True,exist_ok=True)
sim=shutil.which('verilator')
if not sim: raise SystemExit('Verilator is required')
status={'scope':'production conv_axi_read_guard standalone RTL',
        'simulator':subprocess.check_output([sim,'--version'],text=True).strip(),'status':'FAIL'}
log=RESULTS/'guard.log'
with tempfile.TemporaryDirectory(prefix='conv_guard_',dir=os.environ.get('TMPDIR','/tmp')) as temporary:
    command=[sim,'--binary','--timing','--assert','-Wall','-Wno-fatal',
             '--top-module','tb_conv_axi_read_guard','--Mdir',temporary,'-j','2',
             str(ROOT/'rtl/npu/conv/conv_axi_read_guard.sv'),str(HERE/'tb_conv_axi_read_guard.sv')]
    status['command']=command
    try:
        with log.open('w') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            subprocess.run([str(Path(temporary)/'Vtb_conv_axi_read_guard')],cwd=ROOT,
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
        text=log.read_text()
        warnings=[line for line in text.splitlines() if line.startswith('%Warning')]
        reviewed={'BLKSEQ','PROCASSINIT','UNUSEDSIGNAL','UNUSEDPARAM','SYNCASYNCNET'}
        unexpected=[line for line in warnings if line.split(':',1)[0].removeprefix('%Warning-') not in reviewed]
        if unexpected: raise RuntimeError(f'unreviewed lint diagnostics: {unexpected}')
        status['warnings']=warnings
        status['summary']=next(line for line in text.splitlines() if 'CONV_READ_GUARD_PASS' in line)
        status['status']='PASS'
    except (OSError,RuntimeError,subprocess.SubprocessError,StopIteration) as exc:
        status['reason']=str(exc)
(RESULTS/'status.json').write_text(json.dumps(status,indent=2))
print(json.dumps(status,indent=2))
raise SystemExit(0 if status['status']=='PASS' else 1)
