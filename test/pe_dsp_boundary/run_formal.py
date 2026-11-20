#!/usr/bin/env python3
"""比较生产计算单元的全部状态与输出，并检查两种权重模式的四态行为。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RTL = Path('rtl/npu/compute/ws_systolic_cell.sv')
sys.path.insert(0,str(ROOT/'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='e379425d783c7a134e165eb180f0bbf6c0c1a4b0')
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    current=ROOT/RTL
    old=read_rtl_source(f'{args.reference}:{RTL}',cwd=ROOT,text=True)
    reference=out/'reference.sv'
    reference.write_text(old)
    reference_named=out/'reference_named.sv'
    reference_named.write_text(old.replace('module ws_systolic_cell #','module ws_systolic_cell_reference #'))
    source_hash=digest(current)
    report={'passed':False,'reference':args.reference,'source_sha256':{str(RTL):source_hash},
            'reference_sha256':digest(reference),'formal':[],'four_state':[]}
    for data_width,weight_width,acc_width in ((1,1,2),(8,8,32),(16,8,32),(16,16,32),(17,17,40)):
        for exchange in (0,1):
            folder=out/f'd{data_width}_w{weight_width}_a{acc_width}_e{exchange}'
            folder.mkdir(exist_ok=True)
            options=(f'-GDATA_IN_WIDTH={data_width} -GWEIGHT_WIDTH={weight_width} '
                     f'-GACC_WIDTH={acc_width} -Gp_exchange_weights={exchange}')
            commands=[]
            for name,path in (('reference',reference),('current',current)):
                commands += [f'read_slang --top ws_systolic_cell -DXILINX_FPGA=1 {options} {shlex.quote(str(path))}',
                             'proc','opt',f'rename ws_systolic_cell {name}',f'design -stash {name}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current cell_equivalence','hierarchy -top cell_equivalence',
                         'opt_clean','equiv_simple -undef -seq 2','equiv_induct -undef -seq 2',
                         'equiv_status -assert']
            script=folder/'run.ys'
            script.write_text('\n'.join(commands)+'\n')
            log=folder/'formal.log'
            with log.open('w') as stream:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                       '--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            text=log.read_text()
            if result.returncode or 'Equivalence successfully proven' not in text:
                raise RuntimeError('Cell equivalence did not complete: '+str(log))
            count=re.search(r'Of those cells (\d+) are proven and 0 are unproven',text)
            entry=dict(data_width=data_width,weight_width=weight_width,acc_width=acc_width,
                       exchange=exchange,passed=True,equivalent_bits=int(count[1]) if count else None,
                       script_sha256=digest(script),log_sha256=digest(log))
            report['formal'].append(entry)
            print(json.dumps(entry),flush=True)

    source_bench=ROOT/'test/dip_array/tb_weight_mux_four_state.sv'
    for exchange in (0,1):
        bench=out/f'four_state_e{exchange}.sv'
        text=source_bench.read_text().replace('.ACC_WIDTH(32))',f'.ACC_WIDTH(32), .p_exchange_weights({exchange}))')
        text=text.replace("            #1; check(); clk = 1;", "            if (cycle % 23 == 0) commit_weight = 1'bx;\n"
                          "            if (cycle % 29 == 0) store_weight_req = 1'bz;\n"
                          "            #1; check(); clk = 1;")
        bench.write_text(text)
        binary=out/f'four_state_e{exchange}.vvp'
        with (out/f'four_state_e{exchange}_build.log').open('w') as log:
            subprocess.run([args.iverilog,'-g2012','-DXILINX_FPGA=1','-s','tb_weight_mux',
                            '-o',str(binary),str(bench),str(reference_named),str(current)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([args.vvp,str(binary)],cwd=ROOT,text=True,capture_output=True,check=True,timeout=60)
        log=out/f'four_state_e{exchange}.log'
        log.write_text(result.stdout+result.stderr)
        if 'WEIGHT_MUX_FOUR_STATE_PASS cycles=100000 output_checks=200001' not in result.stdout:
            raise RuntimeError('Four-state output count missing')
        report['four_state'].append(dict(exchange=exchange,passed=True,cycles=100000,
                                         output_checks=200001,bench_sha256=digest(bench),log_sha256=digest(log)))
    if digest(current)!=source_hash:
        raise RuntimeError('RTL changed during comparison')
    report['passed']=True
    report['all_input_sequences_constrained']=False
    report['state_reset_assumptions']='none'
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,formal_profiles=len(report['formal']),
                         four_state_cycles=sum(case['cycles'] for case in report['four_state']))))


if __name__=='__main__':
    main()
