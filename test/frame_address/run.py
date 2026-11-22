#!/usr/bin/env python3
"""使用完整三十二位地址参考检查准备周期、结果等待和中止恢复。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--ready-mask-abort', type=int, choices=(0, 1), default=1,
                        help='选择地址就绪输出的中止屏蔽参数，默认值为1')
    parser.add_argument('--pipeline-products', type=int, choices=(0, 1), default=1)
    parser.add_argument('--asic', action='store_true', help='使用ASIC算术编译定义')
    parser.add_argument('--mapped', type=Path, help='使用实际综合网表验证 FPGA 实现')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model_names = []
    if args.mapped:
        netlist = json.loads(args.mapped.with_suffix('.json').read_text())['modules']['frame_address_prepare']
        mapped_parameters = dict(netlist.get('parameter_default_values', {}))
        manifest_file = args.mapped.parent / 'manifest.json'
        if manifest_file.is_file():
            manifest = json.loads(manifest_file.read_text())
            options = ' '.join(manifest.get('options', []))
            for name, value in re.findall(
                    r'(?:^|\s)-G\s*(p_ready_mask_abort|p_pipeline_products)=([01])(?=\s|$)', options):
                mapped_parameters[name] = value
        mapped_mask = int(mapped_parameters.get('p_ready_mask_abort', '1'), 2)
        if mapped_mask != args.ready_mask_abort:
            raise RuntimeError('Mapped netlist ready mask differs from the requested parameter')
        mapped_pipeline = int(mapped_parameters.get('p_pipeline_products', '1'), 2)
        if mapped_pipeline != args.pipeline_products:
            raise RuntimeError('Mapped netlist product pipeline differs from the requested parameter')
        model_names = sorted({cell['type'] for cell in netlist['cells'].values()} | {'DSP48E1','BUFG','IBUF','OBUF'})
    model = '\n\n'.join(re.search(r'^module '+name+r'\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
                          for name in model_names)
    model_file = out / 'dsp48e1.sv'
    if args.mapped:
        model_file.write_text(model + '\n')
    sources = [ROOT / 'rtl/npu/top/frame_address_prepare.sv',
               ROOT / 'test/frame_address/frame_address_tb.sv']
    if args.mapped:
        rtl = sources[0].read_text()
        mapped = out/'frame_address_prepare_mapped.v'
        mapped.write_text(args.mapped.read_text().replace('module frame_address_prepare(', 'module frame_address_prepare_mapped(', 1))
        header = rtl[rtl.index('module frame_address_prepare #('):rtl.index('\n);')+3]
        ports = re.search(r'\) \(\n(.*?)\n\);', header, re.S)[1]
        names = re.findall(r'(?:input|output)\s+(?:wire\s+)?logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
        if len(names) != len(re.findall(r'\b(?:input|output)\b', ports)):
            raise RuntimeError('Every declared port must have an explicit connection')
        connections = ',\n'.join('.'+name+'('+name+')' for name in names)
        wrapper = out/'frame_address_prepare.sv'
        wrapper.write_text(header+'\nframe_address_prepare_mapped u_impl('+connections+');\nendmodule\n')
        sources = [mapped,wrapper,sources[1],model_file]
    sources.append(ROOT / 'rtl/common/parallel_prefix_add.sv')
    recorded_sources = sources + [Path(__file__).resolve()]
    source_key = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    hashes = {source_key(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in recorded_sources}
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError('Cannot locate Verilator: ' + args.verilator)
    command = [verilator, '--binary', '--timing', '--assert', '-sv', '-Wno-fatal',
               '--top-module', 'frame_address_tb', '--Mdir', str(out / 'obj'),
               '-Gp_ready_mask_abort='+str(args.ready_mask_abort),
               '-Gp_pipeline_products='+str(args.pipeline_products),
               *(['-DASIC_SYNTHESIS=1'] if args.asic else []),
               '-j', str(args.jobs), '-CFLAGS', '-std=c++20 -O1',
               '-MAKEFLAGS', 'CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0',
               *map(str, sources)]
    with (out / 'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    binary = out / 'obj/Vframe_address_tb'
    with (out / 'run.log').open('w') as log:
        subprocess.run([str(binary)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    match = re.search(r'FRAME_ADDRESS_PASS (.*)', (out / 'run.log').read_text())
    if not match:
        raise RuntimeError('Completion marker missing')
    if hashes != {source_key(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in recorded_sources}:
        raise RuntimeError('Sources changed during validation')
    phases = [{'age': int(age), 'abort': int(abort), 'reset': int(reset)}
              for age, abort, reset in re.findall(
                  r'FRAME_ADDRESS_PHASE age=(\d+) abort=(\d+) reset=(\d+)',
                  (out / 'run.log').read_text())]
    if len(phases) != 11 + args.pipeline_products or any(row['abort'] == 0 or row['reset'] == 0 for row in phases):
        raise RuntimeError('Cancellation coverage is incomplete')
    summary = {'passed': True, 'size': 16, 'address_width': 32,
               'ready_mask_abort': args.ready_mask_abort, 'cancellation_phases': phases,
               'result_latency_cycles': 10 + args.pipeline_products,
               'pipeline_products': args.pipeline_products, 'asic': args.asic, 'source_sha256': hashes,
               'mapped_netlist': str(args.mapped.resolve()) if args.mapped else None,
               'mapped_netlist_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest() if args.mapped else None,
               'primitive_models': model_names,
               'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest() if args.mapped else None,
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'command': command,
               **{key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])}}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for path in (out / 'obj').iterdir():
        if path == binary:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
