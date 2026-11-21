#!/usr/bin/env python3
"""证明权重覆盖条件、实际生产发送控制以及默认计算单元行为。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]
TEST=ROOT/'test/weight_prefetch'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run(out,name,commands):
    folder=out/name;folder.mkdir(parents=True,exist_ok=True)
    script=folder/'prove.ys';script.write_text('\n'.join(commands)+'\n')
    with (folder/'prove.log').open('w') as log:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    text=(folder/'prove.log').read_text()
    if not ('SUCCESS!' in text or '0 are unproven' in text):raise RuntimeError('Proof result missing: '+name)
    lengths=re.findall(r'Trying induction with length (\d+)',text)
    return {'passed':True,'induction_length':int(lengths[-1]) if lengths else None,
            'script_sha256':digest(script)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='3a773d18')
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=re.search(r'^module LUT6_2\b.*?^endmodule',library.read_text(),re.M|re.S)
    if not model:raise RuntimeError('Official LUT6_2 model missing')
    model_path=out/'LUT6_2.sv';model_path.write_text(model[0]+'\n')
    cell=ROOT/'rtl/npu/compute/ws_systolic_cell.sv'
    array=ROOT/'rtl/npu/compute/ws_systolic_array.sv'
    controller=ROOT/'rtl/npu/control/npu_controller.sv'
    loader=ROOT/'rtl/npu/loaders/kernel_loader.sv'
    loader_control=ROOT/'rtl/npu/loaders/kernel_loader_ctrl.sv'
    loader_buffer=ROOT/'rtl/npu/loaders/kernel_loader_buffer.sv'
    helpers=[ROOT/'rtl/common'/p for p in ['add3_equal.sv','add_equal.sv','parallel_prefix_add.sv','regfile.v']]
    models=[TEST/(p+'.sv') for p in ['array_proof','producer_proof','ctrl_gating_proof','bridge_proof']]
    sources=[cell,array,controller,loader,loader_control,loader_buffer,*helpers,*models]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    common=['proc','flatten','opt -full','memory_map','async2sync','chformal -lower','opt -full']
    reports={}
    for size in (3,4,16):
        reports[f'array_{size}']=run(out,f'array_{size}',[
            f'read_slang -D ASIC_SYNTHESIS=1 --top array_proof -Gp_size={size} '+shlex.join(map(str,[models[0],array,cell])),
            *common,'sat -seq 2 -tempinduct -initsteps 1 -maxsteps 40 -set-at 1 rst_n 0 -set-assumes -prove-asserts -verify -timeout 30'])
        reports[f'producer_{size}']=run(out,f'producer_{size}',[
            f'read_slang -D ASIC_SYNTHESIS=1 --top producer_proof -Gp_size={size} '+shlex.join(map(str,[models[1],controller,loader_buffer,helpers[2]])),
            *common,'sat -seq 2 -tempinduct -initsteps 1 -maxsteps 40 -set-at 1 rst_n 0 -set-assumes -prove-asserts -verify -timeout 30'])
    reports['loader_send_control']=run(out,'loader_send_control',[
        'read_slang -D ASIC_SYNTHESIS=1 --top ctrl_gating_proof '+shlex.join(map(str,[models[2],loader_control,*helpers[:2]])),
        'proc','flatten','cutpoint w:u_control.state','opt -full','chformal -lower','opt -full','sat -prove-asserts -verify'])
    reports['loader_output_registers']=run(out,'loader_output_registers',[
        'read_slang -D ASIC_SYNTHESIS=1 --top bridge_proof '+shlex.join(map(str,[models[3],loader,loader_control,loader_buffer,*helpers])),
        'proc','flatten','cutpoint w:u_loader.buf_store_weight_req w:u_loader.buf_weight_sending_done',
        'opt -full','async2sync','chformal -lower','opt -full',
        'sat -seq 2 -tempinduct -maxsteps 4 -set-at 1 rst_n 0 -prove-asserts -verify'])
    original=read_rtl_source(args.reference+':rtl/npu/compute/ws_systolic_cell.sv', cwd=ROOT)
    reference=out/'reference.sv';reference.write_bytes(original)
    default=[]
    for data_width,weight_width,sum_width in [(1,1,2),(8,8,32),(16,8,32),(16,16,32),(17,17,40)]:
        parameters=f'-GDATA_IN_WIDTH={data_width} -GWEIGHT_WIDTH={weight_width} -GACC_WIDTH={sum_width}'
        result=run(out,f'default_d{data_width}_w{weight_width}_a{sum_width}',[
            f'read_slang --top ws_systolic_cell {parameters} '+shlex.join(map(str,[reference,model_path])),
            'proc','opt','rename ws_systolic_cell reference','design -stash reference',
            f'read_slang --top ws_systolic_cell {parameters} '+shlex.join(map(str,[cell,model_path])),
            'proc','opt','rename ws_systolic_cell current','design -stash current',
            'design -copy-from reference -as reference reference','design -copy-from current -as current current',
            'equiv_make reference current cell_equivalence','hierarchy -top cell_equivalence','opt_clean',
            'equiv_simple -undef -seq 2','equiv_induct -undef -seq 2','equiv_status -assert'])
        default.append({'data_width':data_width,'weight_width':weight_width,'sum_width':sum_width,**result})
    reference_named=out/'reference_named.sv'
    reference_named.write_text(original.decode().replace('module ws_systolic_cell #','module ws_systolic_cell_reference #'))
    executable=out/'four_state.vvp'
    command=[args.iverilog,'-g2012','-DSYNTHESIS=1','-s','tb_weight_mux','-o',str(executable),
             str(ROOT/'test/dip_array/tb_weight_mux_four_state.sv'),str(reference_named),str(cell),str(model_path)]
    with (out/'four_state_build.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=subprocess.run([args.vvp,str(executable)],cwd=ROOT,capture_output=True,text=True,check=True,timeout=60)
    (out/'four_state.log').write_text(result.stdout+result.stderr)
    if 'WEIGHT_MUX_FOUR_STATE_PASS cycles=100000 output_checks=200001' not in result.stdout:
        raise RuntimeError('Four-state comparison incomplete')
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in sources}:raise RuntimeError('Sources changed during proof')
    summary={'passed':True,'reference_commit':args.reference,'source_sha256':hashes,
        'primitive_library_sha256':digest(library),'proofs':reports,'default_exchange':default,
        'four_state':{'passed':True,'cycles':100000,'output_checks':200001},
        'array_proof_scope':{'weight_bit':'任意一位；各权重位独立使用同一写入与提交控制',
            'commit_condition':'提交前至少有 SIZE 次全局装载，允许同时开始下一块装载',
            'reset_and_load_gaps':'任意'},
        'producer_proof_scope':{'data_and_send_admission':'任意',
            'resident_mode':'INIT 边沿采样并保持至下一次初始化',
            'start_condition':'清空缓冲控制，或前一发送已完成',
            'reset':'任意'}}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'proofs':reports,'default_profiles':len(default)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
