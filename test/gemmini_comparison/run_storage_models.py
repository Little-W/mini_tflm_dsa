#!/usr/bin/env python3
"""在固定共享存储和 512 KiB arena 下测量完整模型，并核对逐节点输出。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--gcc', required=True)
    parser.add_argument('--verilator', required=True)
    parser.add_argument('--picorv32', type=Path, required=True)
    parser.add_argument('--shared-bank-bytes', type=int, choices=(2048, 4096, 8192))
    parser.add_argument('--shared-bank-count', type=int, choices=(6, 7, 8, 9))
    parser.add_argument('--im2col-cache-bytes', type=int)
    parser.add_argument('--capacity-budget-bytes', type=int)
    parser.add_argument('--capacity-report', type=Path)
    parser.add_argument('--arena-bytes', type=int, default=512 * 1024)
    parser.add_argument('--first-read-latency', type=int, default=8)
    parser.add_argument('--pe-count', type=int, choices=(8, 16), default=8,
                        help='向量乘累加单元数量，与容量统计及实际仿真参数交叉检查')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--run-jobs', type=int, default=2)
    parser.add_argument('--models', nargs='+')
    parser.add_argument('--samples', nargs='+', type=int, default=[0, 1])
    parser.add_argument('--modes', nargs='+', choices=('hw', 'sw'), default=['hw'])
    parser.add_argument('--kinds', nargs='+', choices=('perf', 'trace'), default=['perf', 'trace'])
    parser.add_argument('--firmware-only', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--skip-sim-build', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--cycle-limit', type=int, default=4_000_000_000)
    parser.add_argument('--seconds-limit', type=int, default=14400)
    args = parser.parse_args()
    if args.jobs < 1 or args.run_jobs < 1:
        parser.error('Job counts must be positive')
    if args.arena_bytes != 512 * 1024 or args.first_read_latency != 8:
        parser.error('This comparison uses a 512 KiB arena and an 8-cycle first-read latency')

    # 运行记录保存绝对路径，保证后续从其他工作目录核验时仍指向同一输入。
    for name in ('repo', 'out', 'prepared', 'picorv32', 'capacity_report'):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    repo, out, prepared = args.repo.resolve(), args.out.resolve(), args.prepared.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo))
    bench_dir = repo / 'test/model_benchmark'
    sys.path.insert(0, str(bench_dir))
    sys.path.insert(0, str(repo / 'test/ps_compression'))
    import build_firmware
    import build_sim
    import model_data
    import report
    import run as bench
    from scripts.capacity import model as capacity_model
    ps_runner = load_module('experiment_ps_checks', repo / 'test/ps_compression/run_soc.py')

    names = args.models or list(model_data.MODELS)
    if not set(names) <= set(model_data.MODELS):
        parser.error('Unknown model')
    model_manifests = {}
    for name in names:
        model_data.validate_model(prepared / name)
        model_manifests[name] = json.loads((prepared / name / 'manifest.json').read_text())
        if not set(args.samples) <= {s['sample_index'] for s in model_manifests[name]['samples']}:
            parser.error('Requested sample is absent from ' + name)

    source_commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if args.prepare_only:
        tools = {}
        for name, requested, version_arg in (
            ('gcc', args.gcc, '--version'), ('verilator', args.verilator, '--version')):
            executable = Path(shutil.which(requested) or requested).resolve()
            if not executable.is_file():
                parser.error('Missing executable: ' + str(executable))
            tools[name] = {'path': str(executable), 'sha256': bench.digest(executable),
                           'version': subprocess.check_output([str(executable), version_arg], text=True).strip()}
        pico_commit = subprocess.check_output(['git', '-C', str(args.picorv32), 'rev-parse', 'HEAD'], text=True).strip()
        if pico_commit != 'ef203c2b0a3fb793280f5114941416c425c5b461':
            parser.error('PicoRV32 revision differs from the required revision')
        runtime = {}
        for library in ('libstdc++.a', 'libm.a', 'libc.a', 'libgcc.a'):
            path = Path(subprocess.check_output(
                [args.gcc, '-march=rv32im_zicsr', '-mabi=ilp32', '-print-file-name=' + library], text=True).strip()).resolve()
            if not path.is_file():
                parser.error('Missing RV32IM runtime library: ' + str(path))
            runtime[library] = {'path': str(path), 'sha256': bench.digest(path)}
        preparation = {
            'passed': True, 'source_commit': source_commit,
            'runner_sha256': bench.digest(Path(__file__)), 'tools': tools, 'runtime_libraries': runtime,
            'picorv32_commit': pico_commit, 'picorv32_sha256': bench.digest(args.picorv32 / 'picorv32.v'),
            'models': names, 'samples': args.samples, 'modes': args.modes, 'kinds': args.kinds,
            'arena_bytes': args.arena_bytes, 'ram_bytes': 2 * 1024 * 1024,
            'cpu_profile': 'performance', 'bus_width': 64, 'first_read_latency': 8,
            'continuous_read_beat_cycles': 1, 'read_outstanding': 4, 'write_outstanding': 4,
            'vector_pe_count': args.pe_count,
            'axi_max_burst_beats': 256, 'expected_cases': len(names) * len(args.samples) * len(args.modes) * len(args.kinds),
            'prepared_manifest_sha256': {name: bench.digest(prepared / name / 'manifest.json') for name in names},
        }
        bench.write_json(out / 'preparation.json', preparation)
        print(json.dumps(preparation), flush=True)
        return 0
    if any(value is None for value in (args.shared_bank_bytes, args.shared_bank_count,
                                       args.im2col_cache_bytes, args.capacity_budget_bytes, args.capacity_report)):
        parser.error('Model execution requires explicit shared bank, window cache, capacity budget and elaboration report parameters')

    pool_bytes = (args.shared_bank_count - 1) * args.shared_bank_bytes
    execution_label = '_'.join(args.modes) + '_' + '_'.join(args.kinds)
    settings_path = out / f'settings_{execution_label}.json'
    capacity_report = json.loads(args.capacity_report.read_text())
    capacity_parameters = {'SHARED_BANK_BYTES': args.shared_bank_bytes,
                           'SHARED_BANK_COUNT': args.shared_bank_count,
                           'PS_POOL_BYTES': pool_bytes, 'IM2COL_CACHE_BYTES': args.im2col_cache_bytes,
                           'IA_CACHE_BLOCKS': 4, 'PS_FRAME_COUNT': 16, 'NPU_AXI_DATA_WIDTH': 64,
                           'AXI_READ_OUTSTANDING': 4, 'PS_FORCE_RAW': 1}
    if (capacity_report.get('elaboration_target') != 'generic' or
            not capacity_report['passed'] or not capacity_report['sources_unchanged'] or
            any(capacity_report['hardware_configuration'].get(key) != value for key, value in capacity_parameters.items()) or
            any(bench.digest(repo / path) != value for path, value in capacity_report['source_sha256'].items()) or
            capacity_report['elaborated_state']['total_bits'] > args.capacity_budget_bytes * 8):
        raise RuntimeError('The current NPU allocation does not match the validated storage capacity report')
    instances = capacity_report['elaborated_state']['module_instances']
    if instances.get('vector_engine') != 1 or instances.get('vector_pe') != args.pe_count:
        raise RuntimeError('容量报告中的向量计算单元数量与模型执行配置不一致')
    runner_sha = bench.digest(Path(__file__))
    # 固定当前源码身份、实际工具版本、输入内容和容量统计。
    settings = {
        'repo': str(repo),
        'source_commit': source_commit,
        'source_tree': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'], text=True).strip(),
        'working_tree_status': subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True),
        'runner_sha256': runner_sha,
        'arguments': {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        'prepared_manifest_sha256': {name: bench.digest(prepared / name / 'manifest.json') for name in names},
        'initial_ps_pool_bytes': pool_bytes,
        'cpu_profile': 'performance', 'cpu_icache': 1, 'ram_bytes': 2 * 1024 * 1024,
        'bus_width': 64, 'ram_first_read_latency': args.first_read_latency,
        'ram_fixed_latency': 0, 'ram_continuous_read_beat_cycles': 1,
        'axi_read_outstanding': 4, 'axi_write_outstanding': 4, 'dma_max_bytes': 2048,
        'vector_pe_count': args.pe_count,
        'rounding_mode': 'nearest_even',
        'timing': 'CPU rdcycle around complete MicroInterpreter::Invoke; initialization recorded separately',
        'ps_policy': 'raw32', 'dataflow_selection': 'production AUTO WS/IS',
        'total_storage_capacity_check': {
            'report_path': str(args.capacity_report.resolve()),
            'report_sha256': bench.digest(args.capacity_report),
            'logical_state_bits': capacity_report['elaborated_state']['total_bits'],
            'logical_state_bytes': capacity_report['elaborated_state']['total_bits'] / 8,
            'budget_bytes': args.capacity_budget_bytes, 'scope': capacity_report['scope'],
        },
    }
    settings['capacity_accounting'] = capacity_model.allocation(
        4, 16, pool_bytes, args.capacity_budget_bytes, 'buffer-ram', size=16, compressed=True,
        im2col_cache_bytes=args.im2col_cache_bytes,
        bank_bytes=args.shared_bank_bytes, bank_count=args.shared_bank_count)
    if settings['capacity_accounting']['unused_budget_bytes'] < 0:
        raise ValueError('The requested NPU buffer allocation exceeds the supplied capacity budget')
    bench.write_json(settings_path, settings)
    compiler = Path(shutil.which(args.gcc) or args.gcc).resolve()
    firmwares = {}
    for mode in args.modes:
        for kind in args.kinds:
            directory = out / f'firmware_{mode}_{kind}'
            expected = {
                'DSA_NN_CONV_ENABLE': int(mode == 'hw'),
                'DSA_NN_VECTOR_ENABLE': int(mode == 'hw'),
                'DSA_NN_FC_ENABLE': int(mode == 'hw'),
                'FULL_NETWORK_TRACE_ENABLED': int(kind == 'trace'),
                'DSA_PS_POOL_BYTES': pool_bytes, 'DSA_PS_COMPRESS': 1,
                'DSA_IA_CACHE_BLOCKS': 4, 'DSA_PS_FRAME_COUNT': 16,
                'DSA_PS_FORCE_RAW': 1, 'DSA_PS_ADAPTIVE_W': 1, 'DSA_DEFAULT_DATAFLOW': 2,
            }
            try:
                fw = json.loads((directory / 'firmware.json').read_text())
                bench.verify_sources(fw)
                if (not fw['passed'] or fw['arena_bytes'] != args.arena_bytes or
                    fw['compiler_sha256'] != bench.digest(compiler) or
                    any(fw['compile_defines'].get(key) != value for key, value in expected.items()) or
                    any(bench.digest(directory / file) != fw[key]
                        for file, key in [('cpu.elf', 'elf_sha256'), ('cpu.mem', 'mem_sha256')])):
                    raise ValueError('Firmware configuration differs')
            except (OSError, ValueError, KeyError, RuntimeError):
                fw = build_firmware.build_firmware(
                    directory, args.gcc, hardware=mode == 'hw', trace=kind == 'trace',
                    jobs=args.jobs, object_cache=out / 'firmware_objects', arena_bytes=args.arena_bytes,
                    ps_pool_bytes=pool_bytes, force_raw=True, adaptive_window=True, dataflow=2,
                    ia_cache_blocks=4, ps_frame_count=16)
            firmwares[mode, kind] = directory, fw
            print(json.dumps({'phase': 'firmware', 'mode': mode, 'kind': kind,
                              'passed': fw['passed'], 'elf_sha256': fw['elf_sha256']}), flush=True)
    if args.firmware_only:
        return 0

    binary = build_sim.build_sim(
        out / 'sim', args.verilator, args.jobs, skip=args.skip_sim_build,
        icache=1, ram_words=524288, pe_count=args.pe_count, picorv32=args.picorv32,
        ia_cache_blocks=4, ps_frame_count=16, ps_storage_rows=799, s16_output_banks=4,
        cpu_profile='performance', bus_width=64, first_read_latency=args.first_read_latency,
        ps_pool_bytes=pool_bytes, shared_bank_bytes=args.shared_bank_bytes,
        shared_bank_count=args.shared_bank_count, im2col_cache_bytes=args.im2col_cache_bytes, hardware_raw=True)
    sim_manifest = json.loads((out / 'sim/build.json').read_text())
    if not sim_manifest['profile']['shared_ia_ps']:
        raise RuntimeError('Shared IA/PS hardware is required')
    required_profile = {
        'cpu_profile': 'performance', 'cpu_icache_data_bytes': 1024, 'ram_words': 524288,
        'bus_width': 64, 'dma_max_bytes': 2048, 'ram_read_first_latency': 8,
        'ram_continuous_read_beat_cycles': 1, 'axi_read_outstanding': 4, 'axi_write_outstanding': 4,
        'cpu_enable_fast_mul': 1, 'cpu_enable_div': 1, 'cpu_barrel_shifter': 1,
        'shared_bank_bytes': args.shared_bank_bytes, 'shared_bank_count': args.shared_bank_count,
        'ps_pool_bytes': pool_bytes, 'im2col_cache_bytes': args.im2col_cache_bytes,
        'ps_storage_implementation': 'raw32',
        'vector_pe_count': args.pe_count,
    }
    if any(sim_manifest['profile'].get(key) != value for key, value in required_profile.items()):
        raise RuntimeError('The constructed simulator differs from the comparison configuration')
    vector_parameters = capacity_report['capability_parameters'].get('vector_engine', {})
    for parameter, field in (('PE_COUNT', 'vector_pe_count'),
                             ('QUANT_LANES', 'quantization_lanes'), ('WINDOW_LANES', 'window_lanes'),
                             ('SHARED_QUANT_ENABLE', 'shared_quant_enable')):
        if parameter in vector_parameters and vector_parameters[parameter] != sim_manifest['profile'][field]:
            raise RuntimeError('容量展开与模型仿真使用不同向量参数：' + parameter)
    if args.pe_count == 16 and not all(key in vector_parameters for key in (
            'PE_COUNT', 'QUANT_LANES', 'WINDOW_LANES', 'SHARED_QUANT_ENABLE')):
        raise RuntimeError('16 路向量计算需要记录计算、量化及窗口并行参数的容量报告')
    cache_parameters = capacity_report['capability_parameters']['npu_top']
    for parameter, field in (('CONV_LINE_BYTES', 'cache_line_bytes'),
                             ('CONV_CACHE_WAYS', 'cache_ways'), ('CONV_CACHE_SETS', 'cache_sets')):
        if cache_parameters.get(parameter) != sim_manifest['profile'].get(field):
            raise RuntimeError('容量展开与模型仿真使用不同缓存参数：' + parameter)
    settings['hardware_profile'] = sim_manifest['profile']
    settings['simulator_sha256'] = sim_manifest['binary_sha256']
    bench.write_json(settings_path, settings)
    if args.build_only:
        return 0

    # 每个输入分别运行普通推理与逐层记录，并逐字节检查输出。
    work, completed = [], []
    for mode in args.modes:
        for kind in args.kinds:
            fw_dir, fw = firmwares[mode, kind]
            for name in names:
                manifest = model_manifests[name]
                for sample in manifest['samples']:
                    if sample['sample_index'] not in args.samples:
                        continue
                    numeric_mode = bench.HARDWARE_MODE if mode == 'hw' else 0
                    directory = out / 'results/cases' / name / f'sample_{sample["sample_index"]:04d}' / f'{kind}_{numeric_mode}'
                    result_path = directory / 'result.json'
                    if result_path.exists():
                        saved = json.loads(result_path.read_text())
                        if not args.resume:
                            raise RuntimeError('Existing result requires --resume: ' + str(directory))
                        if (saved['passed'] and saved['firmware_elf_sha256'] == fw['elf_sha256'] and
                            saved['simulator']['simulator_sha256'] == sim_manifest['binary_sha256'] and
                            saved['input_sha256'] == sample['input']['sha256'] and
                            saved['model']['sha256'] == manifest['model']['sha256'] and
                            saved['ram_fixed_lat'] == 0 and saved.get('experiment_runner_sha256') == runner_sha):
                            completed.append(saved)
                            continue
                        raise RuntimeError('Saved result differs from requested execution: ' + str(directory))
                    case = bench.create_case(directory, prepared / name, manifest, sample,
                                             numeric_mode, fw_dir, fw, ps_force_raw=True)
                    work.append((directory, case, fw, mode))
    ps_runner_hash = bench.digest(repo / 'test/ps_compression/run_soc.py')

    def execute(item):
        directory, case, fw, mode = item
        started = time.monotonic()
        result = bench.execute_case(
            binary, directory, case, fw, latency=0, cycle_limit=args.cycle_limit,
            seconds_limit=args.seconds_limit, extra_plusargs=[f'+PS_EVENTS={directory / "ps_events.txt"}'])
        result['host_seconds'] = time.monotonic() - started
        if mode == 'hw':
            result = ps_runner.validate_result(result, 'raw', binary, ps_runner_hash)
        result['experiment_runner_sha256'] = runner_sha
        result['source_commit'] = settings['source_commit']
        result['hardware_profile'] = sim_manifest['profile']
        bench.write_json(directory / 'result.json', result)
        return result

    with ThreadPoolExecutor(max_workers=args.run_jobs) as pool:
        futures = [pool.submit(execute, item) for item in work]
        for future in as_completed(futures):
            result = future.result()
            completed.append(result)
            progress = [{'model': row['model_id'], 'sample': row['sample_index'],
                         'kind': row['kind'], 'mode': row['mode_name'], 'passed': row['passed'],
                         'invoke_cycles': row['result']['invoke_cycles'],
                         'init_cycles': row['result']['init_cycles'],
                         'case_dir': row['case_dir']} for row in completed]
            bench.write_json(out / f'progress_{execution_label}.json', {'completed_cases': len(completed), 'cases': progress})
            print(json.dumps(progress[-1]), flush=True)

    summary = report.summarize(out, prepared)
    requested = len(args.modes) * len(args.kinds) * len(names) * len(args.samples)
    outcome = {'functional_passed': summary['functional_passed'],
               'complete_requested_suite': summary['functional_passed'] and len(completed) == requested,
               'complete_software_hardware_suite': summary['complete'],
               'completed_requested_cases': len(completed), 'expected_requested_cases': requested,
               'models': summary['models']}
    bench.write_json(out / f'outcome_{execution_label}.json', outcome)
    print(json.dumps(outcome), flush=True)
    if not summary['functional_passed'] or len(completed) != requested:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
