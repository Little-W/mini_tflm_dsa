#!/usr/bin/env python3
"""Run full NPU convolution/GEMM checks using VCS and physical SRAM models."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--sram-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--force-raw',action='store_true')
    args=parser.parse_args();root=args.source_root.resolve();out=args.out.resolve()
    spec=importlib.util.spec_from_file_location('sram_npu_test',root/'test/conv_npu/run.py')
    npu=importlib.util.module_from_spec(spec);spec.loader.exec_module(npu)

    def command(arguments,log,cwd=None,timeout=900):
        log.parent.mkdir(parents=True,exist_ok=True)
        try:
            result=subprocess.run(list(map(str,arguments)),cwd=cwd or log.parent,stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,text=True,timeout=timeout)
            text=result.stdout;status=result.returncode
        except subprocess.TimeoutExpired as error:
            text=(error.stdout or b'').decode() if isinstance(error.stdout,bytes) else error.stdout or ''
            text+='\nTIMEOUT\n';status=124
        log.write_text(text)
        return status

    npu.command=command

    def build(directory,size,verilator,jobs,**options):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        sources,includes,tracked=npu.source_files()
        sources=[p for p in sources if not p.is_relative_to(root/'rtl/axi_top')]
        sources += [root/'asic/rtl/smic40_sram_1r1w.sv',
            args.sram_root.resolve()/'RAMTP128X16/verilog/RAMTP128X16.v',
            args.sram_root.resolve()/'RAMTP1024X16/verilog/RAMTP1024X16.v']
        tracked += sources[-3:]
        observer=root/'test/monitors/smic40_sram_1r1w_observer.sv'
        sources.append(observer);tracked.append(observer)
        original=root/'test/conv_npu/tb_conv_npu.sv'
        text=original.read_text()
        declaration='    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;'
        assert text.count(declaration)==1
        text=text.replace(declaration+'\n','').replace('module tb_conv_npu;',
            'module tb_conv_npu;\n'+declaration)
        prepared=directory/'tb_conv_npu.sv'
        prepared.write_text(text)
        sources=[prepared if p==original else p for p in sources]
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        executable=directory/'simv'
        defines=['ASIC_SRAM','CONV_ASSERT','NPU_SIM_ASSERT','GEMPACT_PS_COMPRESS','GEMMORA_PS_POOL_BYTES=16384',
                 'TB_SIZE=16','TB_BUS_WIDTH=64','TB_SHARED_BANK_BYTES=2048',
                 'TB_SHARED_BANK_COUNT=9','TB_PS_FRAME_COUNT=4',
                 'TB_CONV_CACHE_SETS=128','TB_CONV_CACHE_POLICY=3']
        if args.force_raw:defines.append('GEMMORA_PS_FORCE_RAW')
        command=['vcs','-full64','-sverilog','-timescale=1ns/1ps','-top','tb_conv_npu',
                 '+define+'+'+'.join(defines),*['+incdir+'+str(p) for p in includes],
                 '-Mdir='+str(directory/'csrc'),'-o',str(executable),*map(str,sources)]
        result=subprocess.run(command,cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (directory/'compile.log').write_text(result.stdout)
        if result.returncode:raise RuntimeError('VCS compilation failed; see compile.log')
        wrapper=directory/'run_simulator.sh'
        wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(str(root/'veri/sim/run_simv_lxc.sh'))+
                           ' '+shlex.quote(str(executable))+' +notimingcheck "$@"\n')
        wrapper.chmod(0o755)
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        (directory/'sram_build.json').write_text(json.dumps(dict(source_sha256=hashes,
            binary_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),compile_command=command),indent=2)+'\n')
        return wrapper

    npu.build=build
    sys.argv=[str(root/'test/conv_npu/run.py'),'--sizes','16','--out',str(out),
        '--ps-compress','--pool-bytes','16384','--shared-bank-bytes','2048',
        '--shared-bank-count','9','--bus-width','64','--keep-objects']
    if args.force_raw:sys.argv.append('--force-raw')
    status=npu.main()
    summary=json.loads((out/'summary.json').read_text())
    summary.pop('verilator',None)
    summary['simulator']='VCS with SRAM macro models'
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return status


if __name__=='__main__':
    raise SystemExit(main())
