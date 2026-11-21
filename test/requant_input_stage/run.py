#!/usr/bin/env python3
"""验证量化输入增加一个寄存边沿后的容量预留、参数等待和完整数值结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from open_fpga_synth import run_stage


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_formal(out):
    sources = [ROOT/'rtl/npu/writeback/requant_group_buffer.sv',
               ROOT/'rtl/common/regfile.v', HERE/'buffer_proof.sv',
               ROOT/'test/monitors/requant_group_buffer_observer.sv']
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    results = []
    for rows in (1, 3, 16, 512, 1024):
        script = out/f'rows_{rows}.ys'
        script.write_text(f'read_slang --top requant_input_stage_proof -Gp_rows={rows} '+
            ' '.join(map(str, sources))+'\n'+
            'proc\nflatten\nopt -full\nmemory_map\nasync2sync\nchformal -lower\nopt -full\n'+
            'sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 '+
            '-set-assumes -prove-asserts -verify -timeout 30\n')
        stage = run_stage(script, out/f'rows_{rows}.log', dict(os.environ))
        results.append({'rows': rows, 'passed': True, **stage})
    assert hashes == {str(path.relative_to(ROOT)): sha(path) for path in sources}
    summary = {
        'passed': True, 'source_sha256': hashes, 'results': results,
        'assumptions': ['组开始时已就绪且行数在容量以内', '生产者不超过已预留行数',
                        '输出只释放已经发射的行'],
        'arbitrary_inputs': ['生产者间隔', '缓存读取暂停', '量化输出等待', '复位与清空'],
        'invariant': '未完成预留等于未产生行、生产者寄存行、RAM行、读出行与已发射行之和'
    }
    (out/'formal_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    return summary


def prepare_driver(out):
    source = (ROOT/'test/requant_time_share/main.cpp').read_text()
    changes = {
        'commands_count=0;': 'commands_count=0,parameter_wait_cycles=0;',
        'return (dut.group_ready&2U) && dut.params_ready==3;': 'return dut.group_ready==3;',
        'dut.input_valid=0;dut.input_tile_done=0;idle(random()%8);':
            'dut.input_valid=0;dut.input_tile_done=0;',
        'dut.clk=1;dut.eval();++cycles;':
            'dut.clk=1;dut.eval();++cycles;\n'
            '        if(dut.input_valid && dut.params_ready!=3)++parameter_wait_cycles;',
        'require(groups && outputs && clears && resets && full_groups,"Coverage incomplete");':
            'require(groups && outputs && clears && resets && full_groups && parameter_wait_cycles,'
            '"Coverage incomplete");',
        '<<",\\"dma_commands\\":"<<commands_count':
            '<<",\\"parameter_wait_cycles\\":"<<parameter_wait_cycles'
            '<<",\\"dma_commands\\":"<<commands_count'
    }
    for original, replacement in changes.items():
        assert source.count(original) == 1, original
        source = source.replace(original, replacement)
    driver = out/'main.cpp'
    driver.write_text(source)
    return driver


def run_simulation(out, args):
    sources = [HERE/'tb.sv',
               ROOT/'rtl/npu/writeback/vec_requant.sv',
               ROOT/'rtl/npu/writeback/requant_compute_lane.sv',
               ROOT/'rtl/npu/writeback/requant_group_buffer.sv',
               ROOT/'rtl/npu/conv/vector_scalar_multiplier.sv', ROOT/'rtl/common/regfile.v',
               ROOT/'rtl/common/parallel_prefix_add.sv',
               ROOT/'test/monitors/requant_group_buffer_observer.sv']
    checked = sources+[ROOT/'test/requant_time_share/main.cpp', Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in checked}
    driver = prepare_driver(out)
    options = []
    if args.xilinx:
        import pyosys
        library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
        content = library.read_text()
        model = out/'primitives.sv'
        model.write_text('\n'.join(re.search(r'^module '+name+r'\b.*?^endmodule', content,
                         re.M|re.S)[0] for name in ('LUT6_2', 'DSP48E1', 'FDRE', 'CARRY4'))+'\n')
        options = ['-DSYNTHESIS', '-DXILINX_FPGA', str(model)]
    flags = (f'-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all '
             f'-DTEST_VLEN={args.vlen} -DTEST_LANES={args.lanes} '
             f'-DTEST_REUSE={args.reuse} -DTEST_BUS={args.bus} '
             '--param=ggc-min-expand=10 --param=ggc-min-heapsize=32768')
    command = [args.verilator, '--cc', '--exe', '--build', '-j', '1', '--assert', '-Wno-fatal',
               '--top-module', 'requant_time_share_tb', '--output-split', '20000',
               '--output-split-cfuncs', '100', '--Mdir', str(out/'obj'),
               f'-Gp_vlen={args.vlen}', f'-Gp_lanes={args.lanes}',
               f'-Gp_reuse={args.reuse}', f'-Gp_bus_width={args.bus}',
               '-CFLAGS', flags, '-LDFLAGS', '-fsanitize=undefined',
               '-MAKEFLAGS', 'CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
               *map(str, sources), str(driver), *options]
    command_path = out/'build.command.json'
    command_path.write_text(json.dumps(command, indent=2)+'\n')
    build = run_stage(command_path, out/'build.log', dict(os.environ), command=command)
    binary = out/'obj/Vrequant_time_share_tb'
    result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True,
                            check=True, timeout=300)
    (out/'run.log').write_text(result.stdout+result.stderr)
    record = json.loads(result.stdout.strip().splitlines()[-1])
    assert record['parameter_wait_cycles'] > 0
    assert hashes == {str(path.relative_to(ROOT)): sha(path) for path in checked}
    summary = {'passed': True, 'source_sha256': hashes, 'xilinx': args.xilinx,
               'input_register_cycles': [0, 1], 'compute_lanes': [args.lanes, args.lanes],
               'group_start_waits_for_parameters': False, 'result': record,
               'driver_sha256': sha(driver), 'binary_sha256': sha(binary), 'build': build}
    (out/'simulation_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    retained = out/binary.name
    shutil.copy2(binary, retained)
    shutil.rmtree(out/'obj')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--vlen', type=int, default=16)
    parser.add_argument('--lanes', type=int, default=2)
    parser.add_argument('--reuse', type=int, default=32)
    parser.add_argument('--bus', type=int, default=64)
    parser.add_argument('--xilinx', action='store_true')
    parser.add_argument('--formal-only', action='store_true')
    parser.add_argument('--simulation-only', action='store_true')
    args = parser.parse_args()
    assert not (args.formal_only and args.simulation_only)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    if not args.simulation_only:
        summary['formal'] = run_formal(out)
        print('容量预留形式检查通过', flush=True)
    if not args.formal_only:
        summary['simulation'] = run_simulation(out, args)
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
