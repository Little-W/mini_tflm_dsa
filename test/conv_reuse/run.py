#!/usr/bin/env python3
"""Count actual external AXI handshakes and byte addresses to verify reuse."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RTL=ROOT/'rtl/npu/conv'
RESULTS=ROOT/'build/conv_reuse'
RESULTS.mkdir(parents=True,exist_ok=True)
sim=shutil.which('verilator')
if not sim: raise SystemExit('Verilator is required')
report={'scope':'cache/frontend reuse measured on actual external AXI reads',
        'simulator':subprocess.check_output([sim,'--version'],text=True).strip(),'runs':[]}
reviewed={'BLKSEQ','PROCASSINIT','UNUSEDSIGNAL','UNUSEDPARAM','SYNCASYNCNET'}
sources=[(RTL.parent/'dma'/name if name.startswith('cache/') else RTL/name) for name in ['conv_im2col_pkg.sv','conv_udiv32.sv','cache/conv_sdp_ram.sv','cache/conv_next_use_predictor.sv',
                              'conv_axi_span_reader.sv','cache/conv_read_cache.sv','conv_im2col_frontend.sv']]
with tempfile.TemporaryDirectory(prefix='conv_reuse_',dir=os.environ.get('TMPDIR','/tmp')) as temporary:
    for kind in ['cache','frontend']:
        top=f'tb_conv_{kind}_reuse';build=Path(temporary)/kind;build.mkdir()
        log=RESULTS/f'{kind}.log'
        command=[sim,'--binary','--timing','--assert','-DCONV_ASSERT','-Wall','-Wno-fatal',
                 '--top-module',top,'--Mdir',str(build),'-j','2']
        command+=list(map(str,sources))+[str(HERE/'axi_counted_memory.sv'),str(HERE/f'{top}.sv')]
        status={'kind':kind,'status':'FAIL','command':command,'log':log.name}
        try:
            with log.open('w') as stream:
                subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
                subprocess.run([str(build/f'V{top}')],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
            output=log.read_text();warnings=[line for line in output.splitlines() if line.startswith('%Warning')]
            unexpected=[line for line in warnings if line.split(':',1)[0].removeprefix('%Warning-') not in reviewed]
            if unexpected: raise RuntimeError(f'unreviewed lint diagnostics: {unexpected}')
            status.update(status='PASS',warnings=warnings,
                          summary=next(line for line in output.splitlines() if f'{kind.upper()}_REUSE_PASS' in line),
                          external_byte_counts=[line for line in output.splitlines() if '_EXTERNAL_BYTE ' in line],
                          cases=[line for line in output.splitlines() if '_REUSE_CASE ' in line])
        except (OSError,RuntimeError,subprocess.SubprocessError,StopIteration) as exc:status['reason']=str(exc)
        report['runs'].append(status)
report['status']='PASS' if all(run['status']=='PASS' for run in report['runs']) else 'FAIL'
(RESULTS/'status.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['status']=='PASS' else 1)
