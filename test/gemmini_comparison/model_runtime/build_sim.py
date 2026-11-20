#!/usr/bin/env python3
"""Build DWConv Gemmini with the production PicoRV32, interconnect and RAM."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMON_PATH = ROOT / 'test/model_benchmark/build_sim.py'
spec = importlib.util.spec_from_file_location('model_sim_common', COMMON_PATH)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
run_sim = common.run_sim


def build_sim(out, generated, verilator='verilator', jobs=2, *, skip=False, idle_clock_gating=True,first_read_latency=8):
    out, generated = Path(out).resolve(), Path(generated).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if first_read_latency<1:raise ValueError('First read latency must be positive')
    gem_manifest_path = generated / 'build_manifest.json'
    gem_manifest = json.loads(gem_manifest_path.read_text())
    cfg = gem_manifest['configuration']
    required = {'array_rows':16, 'array_columns':16, 'scratchpad_bytes':32768,
                'accumulator_bytes':32768, 'dma_bus_bits':64, 'dma_max_bytes':2048,
                'has_im2col':True, 'has_dwconv_dataflow':True, 'spad_read_delay':1}
    if any(cfg.get(k) != v for k, v in required.items()):
        raise ValueError('Gemmini configuration must use 16x16, SP32/ACC32, AXI64 with 256-beat bursts, DWConv and im2col')
    rtl = generated / 'GemminiCompare.v'
    if common.digest(rtl) != gem_manifest['generated_rtl_sha256']:
        raise ValueError('Gemmini RTL differs from its generation record')
    picorv32 = Path(os.environ.get('PICORV32_ROOT', ROOT/'picorv32')).resolve()
    cpu_commit = subprocess.check_output(['git','-C',str(picorv32),'rev-parse','HEAD'], text=True).strip()
    if cpu_commit != 'ef203c2b0a3fb793280f5114941416c425c5b461':
        raise ValueError('PicoRV32 revision differs from the model comparison')

    # Share the production SoC source. Only the accelerator instance and the
    # enclosing module name change; CPU, timing buffers, arbitration and RAM
    # remain the same implementation and parameter values.
    soc = (ROOT/'rtl/soc_top.sv').read_text()
    soc = soc.replace('module soc_top #(', 'module gemmini_soc_top #(', 1)
    pattern = r'    npu_axil_top #\(.*?\n    \) u_npu_axil_top \('
    replacement = ('    gemmini_mmio #(\n'
                   f'        .IDLE_CLOCK_GATING({int(idle_clock_gating)}),\n'
                   '        .AXIL_ADDR_WIDTH(AXIL_ADDR_WIDTH), .BUS_WIDTH(BUS_WIDTH), .DMA_MAX_BYTES(DMA_MAX_BYTES)\n'
                   '    ) u_gemmini_mmio (')
    soc, count = re.subn(pattern, replacement, soc, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Expected one production accelerator instance')
    soc_path = out/'gemmini_soc_top.sv'
    if not skip:
        soc_path.write_text(soc)
    elif soc_path.read_text() != soc:
        raise ValueError('Shared SoC source differs from the saved build')
    sources = [picorv32/'picorv32.v',picorv32/'picosoc/simpleuart.v',
               *[ROOT/'rtl/soc'/name for name in
                 ('pico_native_to_axi.sv','soc_axi_interconnect.sv','soc_axi_pingpong_buffer.sv',
                  'soc_axil_ctrl.sv','soc_axil_simpleuart.sv')],
               ROOT/'test/models/soc_axi_ram.sv',
               soc_path,HERE/'rtl/gemmini_mmio.sv',HERE/'rtl/tb_gemmini_model.sv',
               rtl,generated/'plusarg_reader.v',ROOT/'test/model_benchmark/sim_main.cpp']
    # 两侧模型仿真共用行为 RAM 及 SoC 观察模块，保留相同的事务时序检查。
    observer_selector = ROOT/'test/monitors/sources.py'
    sources = runpy.run_path(str(observer_selector))['with_observers'](sources)
    tracked = sources + [Path(__file__),COMMON_PATH,ROOT/'rtl/soc_top.sv',gem_manifest_path,observer_selector]
    hashes = {str(p):common.digest(p) for p in tracked}
    profile = dict(cpu_profile='performance',cpu_icache=1,cpu='PicoRV32',cpu_isa='RV32IM',
                   cpu_icache_data_bytes=1024,ram_words=524288,ram_read_first_latency=first_read_latency,
                   ram_read_latency_origin='accepted_AR',ram_continuous_read_beat_cycles=1,bus_width=64,cpu_axi_data_bits=32,dma_max_bytes=2048,
                   cpu_axi_read_timing_buffer=1,cpu_axi_write_timing_buffer=1,
                   npu_axi_timing_buffer=1,bypass_ram_pingpong=1,ram_write_timing_buffer=1,
                   accelerator='dwconv/gemmini-dwconv',scratchpad_bytes=32768,accumulator_bytes=32768,
                   spad_read_delay=cfg.get('spad_read_delay',4),
                   has_im2col=True,has_dwconv_dataflow=True,
                   gemmini_idle_clock_gating=bool(idle_clock_gating),
                   **common.CPU_PROFILES['performance'])
    binary, manifest_path = out/'obj/Vtb_model_benchmark', out/'build.json'
    if skip:
        manifest = json.loads(manifest_path.read_text())
        if (manifest['source_sha256'] != hashes or manifest['profile'] != profile or
            manifest.get('returncode') != 0 or common.digest(binary) != manifest['binary_sha256']):
            raise ValueError('Simulator or build inputs differ from the saved build')
        return binary
    args = [verilator,'--cc','--exe','--assert','-sv','-Wno-fatal',
            '--top-module','tb_model_benchmark','--Mdir',out/'obj',
            '--output-groups','0','--output-split','12000',
            '-DSOC_NETWORK_BUS_WIDTH=64','-DSOC_NETWORK_DMA_MAX_BYTES=2048',
            f'-DSOC_NETWORK_READ_FIRST_LATENCY={first_read_latency}',
            '-CFLAGS','-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
            *sources]
    rc = common.command(args,out/'elaborate.log',cwd=ROOT)
    compile_args = ['make','-C',out/'obj','-f','Vtb_model_benchmark.mk','-j',jobs,
                    'OPT_FAST=-O3','OPT_SLOW=-O0','OPT_GLOBAL=-O3',
                    'VK_PCH_I_FAST=','VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E']
    if rc == 0:
        rc = common.command(compile_args,out/'compile.log',cwd=ROOT,timeout=7200)
    manifest = dict(returncode=rc,profile=profile,source_sha256=hashes,
                    sources_unchanged_during_build=hashes=={str(p):common.digest(p) for p in tracked},
                    picorv32_commit=cpu_commit,gemmini_build=gem_manifest,
                    command=list(map(str,args)),compile_command=list(map(str,compile_args)),
                    verilator=subprocess.check_output([verilator,'--version'],text=True).strip())
    if rc == 0:
        manifest['binary_sha256'] = common.digest(binary)
    common.write_json(manifest_path,manifest)
    if rc or not manifest['sources_unchanged_during_build']:
        log = out/('compile.log' if (out/'compile.log').exists() else 'elaborate.log')
        raise RuntimeError(str(log)+'\n'+log.read_text()[-5000:])
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--gemmini-generated',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--first-read-latency',type=int,default=8)
    parser.add_argument('--idle-clock-gating',type=int,choices=(0,1),default=1)
    args = parser.parse_args()
    print(build_sim(args.out,args.gemmini_generated,args.verilator,args.jobs,
                    skip=args.skip_build,idle_clock_gating=bool(args.idle_clock_gating),first_read_latency=args.first_read_latency))


if __name__ == '__main__':
    main()
