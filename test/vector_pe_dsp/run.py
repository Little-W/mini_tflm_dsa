#!/usr/bin/env python3
"""逐周期比较 DSP、通用 RTL 与独立有符号整数结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def run(command, log):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-10000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    model_file = out / 'DSP48E1.sv'
    model_file.write_text(model + '\n')
    sources = [ROOT/'rtl/npu/conv/vector_pe.sv',HERE/'pe_test_top.sv',HERE/'main.cpp']
    hashes = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    run([args.verilator,'--cc','--exe','--assert','--top-module','pe_test_top','-Wno-fatal',
         '--Mdir',out/'obj','--output-split','12000','-CFLAGS','-std=c++17',
         *sources,model_file],out/'verilate.log')
    run(['make','-C',out/'obj','-f','Vpe_test_top.mk','-j','1',
         'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
         'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E'],out/'build.log')
    binary = out/'obj/Vpe_test_top'
    run([binary],out/'functional.log')
    log = (out/'functional.log').read_text()
    match = re.search(r'VECTOR_PE_DSP_PASS cycles=(\d+) comparisons=(\d+) enabled=(\d+) stalled=(\d+)',log)
    assert match
    assert hashes == {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report = {'passed':True,'source_sha256':hashes,
              'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
              'executable_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
              **dict(zip(['cycles','comparisons','enabled_cycles','stalled_cycles'],map(int,match.groups()))),
              'operations':{int(op):int(count) for op,count in re.findall(r'OP (\d+) cycles=(\d+)',log)}}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(log)


if __name__ == '__main__':
    main()
