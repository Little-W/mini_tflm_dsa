#!/usr/bin/env python3
"""复用实际 NPU 连接的技术映射结果，执行生产面积成本的 LUT 映射。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
import open_fpga_synth as flow
from netlist_metrics import resources
from remap_fpga_luts import mapping_commands, physical_cost_library, verify_mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    saved = json.loads((source / 'summary.json').read_text())
    pre_lut = source / 'pre_lut.il'
    if flow.digest(pre_lut) != saved['pre_lut_sha256']:
        raise RuntimeError('The native NPU checkpoint differs from its saved hash')
    import pyosys
    library_root = Path(pyosys.__file__).parent / 'share/xilinx'
    for name, expected in saved['primitive_models']['library_sha256'].items():
        if flow.digest(library_root / name) != expected:
            raise RuntimeError('The installed primitive library differs: ' + name)
    environment = dict(os.environ)
    environment['PATH'] = str(Path(pyosys.__file__).parent) + os.pathsep + environment.get('PATH', '')
    flow.ROOT = out
    print('Waiting for mapping lock: ' + str(args.lock_file), flush=True)
    with args.lock_file.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        raw = out / 'native_lut_library.lut'
        library = out / 'physical_lut_cost.lut'
        prepare = out / '01_lut_library.ys'
        prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n' +
            'add -mod lut_library_top\nabc9_ops -prep_lut 0\n' +
            'abc9_ops -write_lut ' + shlex.quote(str(raw)) + '\n')
        flow.run_stage(prepare, out / '01_lut_library.log', environment)
        library_info = physical_cost_library(raw, library, 8, 1)
        script = out / '03_map_lut.ys'
        script.write_text(mapping_commands('npu_top', pre_lut, out,
                          'physical-cost', 6667, 300, library))
        stage = flow.run_stage(script, out / '03_map_lut.log', environment)
        proof = verify_mapping('physical-cost', out, environment)
    mapped = out / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['npu_top']
    report = dict(saved)
    report.update(resources=resources(module['cells']),
        mapped_sha256=flow.digest(mapped), pre_lut_source=str(pre_lut),
        mapping_profile=dict(mode='physical-cost', delay_target_ps=6667,
                             wire_delay_ps=300, max_lut_inputs=8),
        lut_library=library_info, stage=stage, functional_verification=proof)
    report.pop('paths', None)
    if flow.digest(pre_lut) != saved['pre_lut_sha256']:
        raise RuntimeError('The source checkpoint changed during mapping')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=proof['passed'],
        logic_luts=report['resources']['logic_lut_cells'], elapsed_seconds=stage['elapsed_seconds'])))


if __name__ == '__main__':
    main()
