#!/usr/bin/env python3
"""以完整数据存储比较 FIFO 的数值、反压和所有公开输出的逐周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
REFERENCE='8fe8b96991259ef9c7f0e18ad9fc326a1353fa8e'
FAMILY=('vec_s8_to_fifo','vec_s8_to_fifo_full','vec_s8_to_fifo_linear','vec_s8_fifo_row_ram',
        'fifo_bank_watermark','fifo_ready_threshold','vec_s16_to_fifo')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--verilator',required=True)
    parser.add_argument('--banks',type=int,choices=(16,32),required=True)
    parser.add_argument('--bus-width',type=int,choices=(32,64),required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources=resolver([ROOT/'rtl/npu/writeback/vec_s8_to_fifo.sv',
                      ROOT/'rtl/npu/writeback/vec_s16_to_fifo.sv'],ROOT)
    hashes={str(p):digest(p) for p in sources}
    reference_hashes={}
    pattern=re.compile(r'\b('+'|'.join(sorted(FAMILY,key=len,reverse=True))+r')\b')
    for name in FAMILY:
        relative='rtl/npu/writeback/'+name+'.sv'
        original=subprocess.check_output(['git','show',args.reference+':'+relative],cwd=ROOT,text=True)
        reference_hashes[relative]=hashlib.sha256(original.encode()).hexdigest()
        target=out/(name+'_ref.sv')
        target.write_text(pattern.sub(lambda match:match[0]+'_ref',original))
        sources.append(target)
    original_bench=ROOT/'test/writeback_bus/tb_writeback_bus.sv'
    text=original_bench.read_text().replace('localparam int BANKS = 16;',f'localparam int BANKS = {args.banks};')
    for name in ('vec_s8_to_fifo','vec_s8_to_fifo_ref'):
        text=text.replace(name+' #(',name+" #(.p_cyclic_storage(1'b1), .p_precomputed_watermark(1'b1), ")
    text=text.replace(".reserve_banks(32'd1),", ".reserve_banks(32'd1), .i_ready_bank_threshold(32'(BANKS-1)),")
    text=text.replace('    int tests = 0;','''    integer compared_cycles=0;
    always @(posedge clk) if(rst_n) compared_cycles<=compared_cycles+1;
    final $display("FIFO_CO_ROW_CYCLE_PASS compared_cycles=%0d",compared_cycles);
    int tests = 0;''')
    bench=out/'tb.sv';bench.write_text(text)
    command=[args.verilator,'--binary','--timing','--assert','-Wno-fatal',
        '--top-module','tb_writeback_bus',f'-DTB_BUS_WIDTH={args.bus_width}',
        '-DSYNTHESIS=1','-DXILINX_FPGA=1','-DWRITEBACK_COMPARE_REFERENCE',
        '--Mdir',str(out/'obj'),'-j','1','--output-groups','0','--output-split','12000',
        '-CFLAGS','-std=c++20 -O1','-MAKEFLAGS',
        'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
        *map(str,sources),str(bench)]
    with (out/'build.log').open('w') as stream:
        subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=900)
    executable=out/'obj/Vtb_writeback_bus'
    result=subprocess.run([str(executable)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    log=out/'run.log';log.write_text(result.stdout+result.stderr);result.check_returncode()
    numerical=re.search(r'WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)',result.stdout)
    cycles=re.search(r'FIFO_CO_ROW_CYCLE_PASS compared_cycles=(\d+)',result.stdout)
    assert numerical and cycles
    assert all(digest(p)==h for p,h in hashes.items())
    report=dict(passed=True,bus_width=args.bus_width,banks=args.banks,cyclic_storage=1,
        precomputed_watermark=1,mode='fpga_synthesis',reference_commit=args.reference,
        cases=int(numerical[2]),checked_bytes=int(numerical[3]),compared_cycles=int(cycles[1]),
        extra_cycles=0,source_sha256=hashes,reference_sha256=reference_hashes,
        original_testbench_sha256=digest(original_bench),generated_testbench_sha256=digest(bench),
        log_sha256=digest(log),executable_sha256=digest(executable),runner_sha256=digest(__file__),
        tool_version=subprocess.check_output([args.verilator,'--version'],text=True).strip(),command=command)
    shutil.copy2(executable,out/'fifo_cycle_test')
    shutil.rmtree(out/'obj')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','bus_width','banks','cases','checked_bytes','compared_cycles','extra_cycles']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
