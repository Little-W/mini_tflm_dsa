#!/usr/bin/env python3
"""验证默认布局的实时模式输入及循环布局的普通首拍方向更新。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--verilator',default='verilator-modern')
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'rtl/npu/writeback/vec_s8_to_fifo.sv'
    old=subprocess.check_output(['git','show','b8b34d5:rtl/npu/writeback/vec_s8_to_fifo.sv'],cwd=ROOT,text=True)
    ref=out/'reference.sv'
    ref.write_text(old.replace('vec_s8_to_fifo','vec_s8_to_fifo_ref').replace('vec_s8_fifo_row_ram','vec_s8_fifo_row_ram_ref').replace('fifo_bank_watermark','fifo_bank_watermark_ref'))
    summary={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'reference_rev':'b8b34d5','runs':[]}
    for bus in (32,64):
        folder=out/f'bus{bus}';folder.mkdir(exist_ok=True)
        cmd=[args.verilator,'--binary','--timing','--assert','-Wno-fatal','--top-module','tb_fifo_modes',
            f'-DTB_BUS_WIDTH={bus}','--Mdir',str(folder/'obj'),'-j','2',str(path),str(ref),
            str(ROOT/'rtl/common/REGFILE.v'),str(Path(__file__).with_name('tb_fifo_modes.sv'))]
        with (folder/'build.log').open('w') as stream:subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([str(folder/'obj/Vtb_fifo_modes')],capture_output=True,text=True,timeout=120)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'FIFO_MODES_PASS bus_width=(\d+) cycles=(\d+) mode_changes=(\d+) first_wait_changes=(\d+)',result.stdout)
        if result.returncode or not match:raise RuntimeError(result.stdout+result.stderr)
        summary['runs'].append(dict(bus_width=bus,cycles=int(match[2]),mode_changes=int(match[3]),first_wait_changes=int(match[4]),passed=True))
        print(json.dumps(summary['runs'][-1]),flush=True)
    summary['passed']=hashlib.sha256(path.read_bytes()).hexdigest()==summary['source_sha256']
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not summary['passed']:raise RuntimeError('Source changed during verification')


if __name__=='__main__':main()
