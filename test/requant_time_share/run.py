#!/usr/bin/env python3
"""验证整组缓存、参数装载顺序、完整量化结果和复位清空。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--verilator',default='verilator')
    p.add_argument('--source-root',type=Path,default=ROOT)
    p.add_argument('--vlen',type=int,default=16);p.add_argument('--lanes',type=int,default=4)
    p.add_argument('--reuse',type=int,default=32);p.add_argument('--bus',type=int,default=64)
    p.add_argument('--parameter-output',type=int,choices=(0,1),default=1)
    p.add_argument('--xilinx',action='store_true');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_root=a.source_root.resolve()
    relative_sources=['rtl/npu/writeback/requant_pkg.sv','rtl/npu/writeback/requant_shift_pipeline.sv','test/requant_time_share/tb.sv','test/requant_time_share/main.cpp',
        'rtl/npu/writeback/vec_requant.sv','rtl/npu/writeback/requant_compute_lane.sv', 'rtl/npu/writeback/requant_round_add.sv',
        'rtl/npu/writeback/requant_group_buffer.sv','rtl/npu/conv/registered_multiplier_s32.sv','rtl/common/regfile.v',
        'rtl/common/parallel_prefix_add.sv','test/monitors/requant_group_buffer_observer.sv']
    source_paths={name:(source_root if name.startswith('rtl/') else ROOT)/name for name in relative_sources}
    sources=list(source_paths.values())
    hashes={name:sha(path) for name,path in source_paths.items()};options=[]
    if a.xilinx:
        import pyosys
        library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v';content=library.read_text()
        model=out/'primitives.sv';model.write_text('\n'.join(re.search(r'^module '+n+r'\b.*?^endmodule',content,re.M|re.S)[0] for n in ('LUT6_2','DSP48E1','FDRE','CARRY4'))+'\n')
        options=['-DSYNTHESIS','-DXILINX_FPGA',str(model)]
    flags=f'-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_VLEN={a.vlen} -DTEST_LANES={a.lanes} -DTEST_REUSE={a.reuse} -DTEST_BUS={a.bus} --param=ggc-min-expand=10 --param=ggc-min-heapsize=32768'
    cmd=[a.verilator,'--cc','--exe','--build','-j','1','--assert','-Wno-fatal','--top-module','requant_time_share_tb',
         '--output-split','20000','--output-split-cfuncs','100','--Mdir',str(out/'obj'),
         f'-Gp_vlen={a.vlen}',f'-Gp_lanes={a.lanes}',f'-Gp_reuse={a.reuse}',f'-Gp_bus_width={a.bus}',
         f'-Gp_parameter_output={a.parameter_output}',
         '-CFLAGS',flags,'-LDFLAGS','-fsanitize=undefined',
         '-MAKEFLAGS','CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',*map(str,sources),*options]
    with (out/'build.log').open('w') as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
    binary=out/'obj/Vrequant_time_share_tb'
    result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=300)
    (out/'run.log').write_text(result.stdout+result.stderr);result.check_returncode()
    record=json.loads(result.stdout.strip().splitlines()[-1])
    if hashes!={name:sha(path) for name,path in source_paths.items()}:raise RuntimeError('Sources changed during verification')
    summary={'passed':True,'source_sha256':hashes,'command':cmd,'binary_sha256':sha(binary),'result':record,'xilinx':a.xilinx,
             'parameter_output':a.parameter_output}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(record))
if __name__=='__main__':main()
