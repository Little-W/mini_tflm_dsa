#!/usr/bin/env python3
"""复用已核对的技术映射阶段，比较 LUT 成本和 ABC 映射并验证功能。"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys

import open_fpga_synth as flow
from module_resources import attribute_resources, register_sources
from netlist_fanout import analyze_fanout
from netlist_metrics import analyze, register_origins


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def physical_cost_library(source, output, maximum_width, small_lut_area_cost=1):
    """只改变面积成本，逐项保留 Yosys 原语模型的引脚延迟。"""
    if not math.isfinite(small_lut_area_cost) or not 0 < small_lut_area_cost <= 1:
        raise ValueError('The small LUT area cost must be greater than zero and no greater than one')
    costs = {str(width): small_lut_area_cost if width <= 5 else 1 if width == 6 else 2 ** (width - 6)
             for width in range(1, maximum_width + 1)}
    rows = []
    delays = {}
    for line in source.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split()
        width = int(fields[0])
        if width > maximum_width:
            continue
        if len(fields) not in (3, width + 2):
            raise ValueError('Unexpected LUT library row: ' + line)
        delays[str(width)] = fields[2:]
        fields[1] = format(costs[str(width)], 'g')
        rows.append(' '.join(fields))
    if set(delays) != {str(i) for i in range(1, maximum_width + 1)}:
        raise ValueError('The primitive models do not contain every requested LUT width')
    output.write_text('\n'.join(rows) + '\n')
    return {'source_library_sha256': flow.digest(source), 'library_sha256': flow.digest(output),
            'area_cost_by_input_count': costs,
            'pin_delays_ps': delays, 'pin_delays_preserved': True}


def mapping_commands(top, pre_lut, folder, mode, delay_target, wire_delay, library):
    commands = [f'read_rtlil {shlex.quote(str(pre_lut))}',
                'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v',
                'read_verilog -lib -overwrite +/xilinx/cells_xtra.v',
                'opt_expr -mux_undef -noclkinv']
    if mode == 'legacy':
        commands.append('abc -luts 2:2,3,6:5,10,20 -nocleanup -showtmp')
    else:
        commands += ['read_verilog -icells -lib -specify +/xilinx/abc9_model.v',
                     'scratchpad -set abc9.xaiger 1', 'scratchpad -set abc9.verify 1',
                     'scratchpad -set abc9.nocleanup 1', 'scratchpad -set abc9.showtmp 1']
        abc = f'abc9 -W {wire_delay}'
        if library is not None:
            abc += ' -lut ' + shlex.quote(str(library))
        if delay_target is not None:
            abc += f' -D {delay_target}'
        commands.append(abc)
    commands += ['clean', 'xilinx_srl -fixed -minlen 3',
                 'techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6',
                 'xilinx_dffopt', 'opt_lut_ins -tech xilinx',
                 f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run finalize:',
                 'check -assert', f'write_json {shlex.quote(str(folder / "mapped.json"))}',
                 'clkbufmap -buf BUFG O:I', 'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O',
                 'clean', 'check -assert', 'blackbox =A:whitebox',
                 f'write_verilog -noattr -noexpr {shlex.quote(str(folder / "mapped.v"))}']
    return '\n'.join(commands) + '\n'


def verify_mapping(mode, folder, environment):
    log = (folder / '03_map_lut.log').read_text()
    if mode != 'legacy':
        if 'Networks are equivalent.' not in log:
            if 'Executing ABC9.' in log:
                raise RuntimeError('ABC9 did not report a successful equivalence check')
            if 'Extracted 0 AND gates' not in log:
                raise RuntimeError('No ABC9 equivalence result or empty logic network was recorded')
        return {'passed': True, 'method': 'ABC9 &verify', 'log_sha256': flow.digest(folder / '03_map_lut.log')}
    directories = list(dict.fromkeys(re.findall(r'Running ABC script: (.+)/abc\.script', log)))
    if not directories:
        if 'Extracted 0 gates' not in log:
            raise RuntimeError('The ABC extraction directory is absent')
        return {'passed': True, 'method': 'No extracted combinational logic'}
    import pyosys
    abc = Path(pyosys.__file__).parent / 'yosys-abc'
    results = []
    for index, directory in enumerate(directories):
        temporary = Path(directory)
        if not temporary.is_absolute():
            temporary = folder / temporary
        old, new = temporary / 'input.blif', temporary / 'output.blif'
        # 按名称匹配所有边界信号，分区覆盖完整组合网络。
        command = [str(abc), '-c', f'cec -p -P 500 -T 120 {old} {new}']
        script = folder / f'04_cec_{index}.command.json'
        write_json(script, command)
        log_path = folder / f'04_cec_{index}.log'
        result = flow.run_stage(script, log_path, environment, command)
        if 'Networks are equivalent' not in log_path.read_text():
            raise RuntimeError('ABC CEC did not prove the complete network equivalent')
        result.update(input_blif_sha256=flow.digest(old), output_blif_sha256=flow.digest(new),
                      command=command, log_sha256=flow.digest(log_path))
        results.append(result)
    return {'passed': True, 'method': 'ABC CEC with name matching and automatic partitions', 'runs': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='包含 pre_lut.il、manifest.json 和 stages.json 的测量目录')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('native-xaiger1', 'physical-cost', 'legacy'), default='physical-cost')
    parser.add_argument('--delay-target-ps', type=int)
    parser.add_argument('--wire-delay-ps', type=int, default=300)
    parser.add_argument('--max-lut-inputs', type=int, choices=(6, 8), default=8)
    parser.add_argument('--small-lut-area-cost', type=float, default=1,
                        help='一至五输入 LUT 的面积成本；六输入成本保持 1，七/八输入保持 2/4')
    parser.add_argument('--lock-file', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.delay_target_ps is not None and args.delay_target_ps <= 0:
        parser.error('--delay-target-ps must be positive')
    if args.wire_delay_ps < 0:
        parser.error('--wire-delay-ps must be nonnegative')
    if not math.isfinite(args.small_lut_area_cost) or not 0 < args.small_lut_area_cost <= 1:
        parser.error('--small-lut-area-cost must be greater than zero and no greater than one')
    if args.mode != 'physical-cost' and args.small_lut_area_cost != 1:
        parser.error('--small-lut-area-cost is used with --mode physical-cost')
    if args.mode == 'legacy' and args.delay_target_ps is not None:
        parser.error('Legacy ABC uses unit LUT delay; use a native mode for a picosecond target')
    if args.mode != 'physical-cost' and args.max_lut_inputs != 8:
        parser.error('--max-lut-inputs is used with --mode physical-cost')
    source, folder = args.source.resolve(), args.out.resolve()
    if source == folder:
        parser.error('Keep the source checkpoint and remapped output in separate directories')
    folder.mkdir(parents=True, exist_ok=True)
    flow.ROOT = folder
    environment = os.environ.copy()
    import pyosys
    library_directory = Path(pyosys.__file__).parent / 'share/xilinx'
    original = json.loads((source / 'manifest.json').read_text())
    stages = json.loads((source / 'stages.json').read_text())
    pre_lut = source / 'pre_lut.il'
    expected = stages['02_pre_lut']['output_sha256']
    if flow.digest(pre_lut) != expected:
        raise RuntimeError('pre_lut.il differs from its saved stage digest')
    for name, expected_library in original['primitive_models']['library_sha256'].items():
        if flow.digest(library_directory / name) != expected_library:
            raise RuntimeError('The installed primitive library differs from the source checkpoint: ' + name)
    delay_target = args.delay_target_ps
    if args.mode == 'physical-cost' and delay_target is None:
        delay_target = 6667
    configuration = {'mode': args.mode, 'wire_delay_ps': args.wire_delay_ps if args.mode != 'legacy' else None,
                     'delay_target_ps': delay_target, 'max_lut_inputs': args.max_lut_inputs,
                     'functional_verification_required': True}
    if args.small_lut_area_cost != 1:
        configuration['small_lut_area_cost'] = args.small_lut_area_cost
    manifest = {**original, 'lut_mapping': configuration,
                'pre_lut_origin': {'directory': str(source), 'sha256': expected,
                                   'manifest_sha256': flow.digest(source / 'manifest.json')},
                'mapping_tools_sha256': {name: flow.digest(Path(pyosys.__file__).parent / name)
                                         for name in ('libyosys.so', 'yosys-abc')}}
    manifest_path = folder / 'manifest.json'
    if args.resume and manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise RuntimeError('Mapping inputs differ from the saved manifest')
    write_json(manifest_path, manifest)
    state_path = folder / 'job_state.json'
    state = {'pid': os.getpid(), 'state': 'waiting', 'configuration': configuration,
             'pre_lut_sha256': expected, 'source_manifest_sha256': manifest['pre_lut_origin']['manifest_sha256']}

    def save_state():
        old = json.loads(state_path.read_text()) if state_path.exists() else {}
        if 'session_id' in old:
            state['session_id'] = old['session_id']
        write_json(state_path, state)

    save_state()
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        print('Waiting for mapping lock:', args.lock_file, flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        library = None
        library_metadata = None
        if args.mode == 'physical-cost':
            prepare = folder / '01_lut_library.ys'
            raw = folder / 'native_lut_library.lut'
            prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                               'add -mod lut_library_top\n'
                               f'abc9_ops -prep_lut 0\nabc9_ops -write_lut {shlex.quote(str(raw))}\n')
            flow.run_stage(prepare, folder / '01_lut_library.log', environment)
            library = folder / 'physical_lut_cost.lut'
            library_metadata = physical_cost_library(raw, library, args.max_lut_inputs, args.small_lut_area_cost)
            write_json(folder / 'lut_library.json', library_metadata)
        script = folder / '03_map_lut.ys'
        script.write_text(mapping_commands(original['top'], pre_lut, folder, args.mode,
                                           delay_target, args.wire_delay_ps, library))
        state.update(state='mapping', command=[sys.executable, str(Path(flow.__file__)), '--worker', str(script)],
                     script_sha256=flow.digest(script))
        save_state()
        stage_path = folder / 'mapping_stage.json'
        previous = json.loads(stage_path.read_text()) if args.resume and stage_path.exists() else {}
        mapped, verilog = folder / 'mapped.json', folder / 'mapped.v'
        library_sha = flow.digest(library) if library is not None else None
        reusable = (previous.get('script_sha256') == flow.digest(script) and mapped.exists() and verilog.exists()
                    and previous.get('mapped_json_sha256') == flow.digest(mapped)
                    and previous.get('mapped_verilog_sha256') == flow.digest(verilog)
                    and previous.get('input_library_sha256') == library_sha
                    and (folder / '03_map_lut.log').exists()
                    and previous.get('log_sha256') == flow.digest(folder / '03_map_lut.log'))
        if reusable:
            stage = previous
        else:
            stage = flow.run_stage(script, folder / '03_map_lut.log', environment)
            stage.update(script_sha256=flow.digest(script), mapped_json_sha256=flow.digest(mapped),
                         mapped_verilog_sha256=flow.digest(verilog), input_library_sha256=library_sha,
                         log_sha256=flow.digest(folder / '03_map_lut.log'))
            write_json(stage_path, stage)
        state['state'] = 'verifying'
        save_state()
        proof = verify_mapping(args.mode, folder, environment)
        write_json(folder / 'verification.json', proof)
        state['state'] = 'analyzing'
        save_state()
        design = json.loads(mapped.read_text())
        module = design['modules'][original['top']]
        origins = register_origins(pre_lut)
        for name, origin in origins.items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        metrics = analyze(module)
        if not metrics['paths']['graph_complete']:
            raise RuntimeError('Mapped register path graph is incomplete')
        write_json(folder / 'metrics.json', metrics)
        write_json(folder / 'fanout.json', analyze_fanout(module, metrics['paths']))
        write_json(folder / 'module_resources.json', attribute_resources(module, origins, register_sources(pre_lut, origins)))
        budget = original.get('wide_alu_mapping')
        if budget and metrics['resources']['dsp48e1'] + budget['reserved_dsp_cells'] > budget['total_dsp_budget']:
            raise RuntimeError('The mapped design exceeds the saved DSP budget')
        if flow.digest(pre_lut) != expected:
            raise RuntimeError('The source checkpoint changed during LUT mapping')
        result = {'manifest_sha256': flow.digest(manifest_path), 'lut_mapping': configuration,
                  'lut_library': library_metadata, 'mapping_stage': stage, 'functional_verification': proof,
                  'resources': metrics['resources'], 'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                  'register_path_requirement': metrics['register_path_requirement'],
                  'physical_lut_positions': None, 'timing_150mhz_confirmed': None}
        log_text = (folder / '03_map_lut.log').read_text()
        delays = [float(value) for value in re.findall(r'ABC: [PFA]:\s+Del =\s+([0-9]+(?:\.[0-9]+)?)', log_text)]
        result['abc_mapping_delay'] = {
            'iteration_values': delays, 'unit': 'unit_lut' if args.mode == 'legacy' else 'ps',
            'last_iteration_value': delays[-1] if delays else None,
            'target_met': delays[-1] <= delay_target if delays and delay_target is not None else None,
            'scope': 'ABC 映射阶段的引脚和连线成本模型，实际器件频率须由布线后的完整时序模型检查。'}
        write_json(folder / 'summary.json', result)
        state.update(state='complete', summary_sha256=flow.digest(folder / 'summary.json'))
        save_state()
        print(json.dumps({'logic_lut_cells': metrics['resources']['logic_lut_cells'],
                          'longest_register_path_cells': result['longest_register_path_cells'],
                          'functional_verification': True}), flush=True)
    except BaseException as error:
        state.update(state='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                     exception_type=type(error).__name__)
        save_state()
        raise
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    main()
