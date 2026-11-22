#!/usr/bin/env python3
"""验证 CPU 与 NPU 并发读取、目标译码、突发、背压及错误响应。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--profiles',nargs='+',default=['64:0:4','32:0:4','64:1:4','64:0:1'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    source = ROOT/'rtl/soc/soc_axi_interconnect.sv'
    frozen = out/source.name
    frozen.write_text(read_rtl_text(source))
    harness = out/'main.cpp'
    shutil.copyfile(Path(__file__).with_name('main.cpp'),harness)
    header = read_rtl_text(frozen).split('\n);',1)[0]
    inputs = re.findall(r'^\s*input\s+(?:(?:wire|logic)\s+)*(?:\[[^\]]+\]\s*)?(\w+)\s*[,\n]',header+'\n',re.M)
    (out/'initialize.hpp').write_text('static void initialize(Vsoc_axi_interconnect &dut) {\n'+
        ''.join(f'    dut.{name}=0;\n' for name in inputs)+'}\n')
    report=dict(source_sha256=digest(frozen),test_sha256=digest(harness),profiles=[])
    for profile in args.profiles:
        width,overlap,outstanding=map(int,profile.split(':'))
        folder=out/f'd{width}_o{overlap}_n{outstanding}'
        folder.mkdir()
        objects=folder/'obj'
        command=['verilator','--cc','--exe','--build','-j','1','-Wno-fatal','--assert',
            '--top-module','soc_axi_interconnect','--Mdir',str(objects),
            f'-GDATA_WIDTH={width}','-GCPU_MEM_DP=65536',f'-Gp_cpu_read_overlap={overlap}',
            f'-GREAD_OUTSTANDING={outstanding}',f'-GWRITE_OUTSTANDING={outstanding}',
            '-CFLAGS',f'-std=c++20 -O1 -DTEST_DATA_WIDTH={width} -DTEST_OVERLAP={overlap} '+
                f'-DTEST_OUTSTANDING={outstanding} -fsanitize=undefined -fno-sanitize-recover=all',
            '-LDFLAGS','-fsanitize=undefined','-MAKEFLAGS','CXX=g++ OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
            str(frozen),str(harness)]
        (folder/'command.json').write_text(json.dumps(command,indent=2)+'\n')
        with (folder/'build.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
        with (folder/'run.log').open('w') as log:
            subprocess.run([str(objects/'Vsoc_axi_interconnect')],stdout=log,stderr=subprocess.STDOUT,
                check=True,cwd=ROOT,timeout=120)
        rows=[json.loads(line.split(' ',1)[1]) for line in read_rtl_text(folder/'run.log').splitlines()
              if line.startswith('INTERCONNECT_TRANSACTIONS_PASS ')]
        if len(rows)!=1 or not rows[0]['passed']:
            raise RuntimeError('互连事务检查没有完成')
        rows[0]['log_sha256']=digest(folder/'run.log')
        report['profiles'].append(rows[0])
        print(json.dumps(rows[0]),flush=True)
        for path in objects.iterdir():
            if path.suffix in ('.o','.a','.gch'):path.unlink()
    if hashlib.sha256(read_rtl_text(source).encode()).hexdigest()!=report['source_sha256']:
        raise RuntimeError('验证期间源码发生变化')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
