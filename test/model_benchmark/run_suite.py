#!/usr/bin/env python3
"""Build and measure four complete networks with identical SoC resources."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from build_firmware import build_firmware
from build_sim import CPU_PROFILES, build_sim
from model_data import MODELS, validate_model
from run import HARDWARE_MODE, create_case, digest, execute_case, verify_sources, write_json
from report import summarize


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--gcc', default='riscv-none-elf-gcc')
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--picorv32', type=Path)
    p.add_argument('--cpu-profile', choices=CPU_PROFILES, default='performance')
    p.add_argument('--icache', type=int, choices=(0,1), default=1)
    p.add_argument('--first-read-latency',type=int,default=8)
    p.add_argument('--bus-width', type=int, choices=(32,64), default=64)
    p.add_argument('--ia-cache-blocks', type=int, default=8)
    p.add_argument('--ps-storage-rows', type=int, default=799)
    p.add_argument('--s16-output-banks', type=int, default=4)
    p.add_argument('--ps-pool-bytes', type=int, default=0)
    p.add_argument('--ps-frame-count', type=int)
    p.add_argument('--force-raw', action='store_true')
    p.add_argument('--shared-bank-bytes', type=int, choices=(2048,4096,8192))
    p.add_argument('--shared-bank-count', type=int, choices=range(6,10))
    p.add_argument('--jobs', type=int, default=1)
    p.add_argument('--run-jobs', type=int, default=4)
    p.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    p.add_argument('--modes', nargs='+', choices=('sw','hw'), default=['sw','hw'])
    p.add_argument('--kinds', nargs='+', choices=('perf','trace'), default=['perf','trace'])
    p.add_argument('--samples', nargs='+', type=int)
    p.add_argument('--skip-build', action='store_true')
    p.add_argument('--build-only', action='store_true')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--latency', type=int, default=0)
    p.add_argument('--cycle-limit', type=int, default=4000000000)
    p.add_argument('--seconds-limit', type=int, default=10800)
    a = p.parse_args()
    if a.jobs < 1 or a.run_jobs < 1:
        p.error('Job counts must be positive')
    if a.ps_frame_count is not None and not 1 <= a.ps_frame_count <= 64:
        p.error('--ps-frame-count must be in 1..64')
    if a.force_raw and not a.ps_pool_bytes:
        p.error('--force-raw requires --ps-pool-bytes')
    out = a.out.resolve(); prepared_root = a.prepared.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prepared = {}
    for name in a.models:
        validate_model(prepared_root/name)
        prepared[name] = json.loads((prepared_root/name/'manifest.json').read_text())
    binary = build_sim(out/'sim', a.verilator, a.jobs, skip=a.skip_build,
                       icache=a.icache, ram_words=524288, pe_count=8, picorv32=a.picorv32,
                       ia_cache_blocks=a.ia_cache_blocks,ps_storage_rows=a.ps_storage_rows,
                       s16_output_banks=a.s16_output_banks,cpu_profile=a.cpu_profile,
                       bus_width=a.bus_width,first_read_latency=a.first_read_latency,
                       ps_pool_bytes=a.ps_pool_bytes,ps_frame_count=a.ps_frame_count,hardware_raw=a.force_raw,
                       shared_bank_bytes=a.shared_bank_bytes,shared_bank_count=a.shared_bank_count)
    firmwares = {}
    for mode in a.modes:
        for kind in a.kinds:
            directory = out/f'firmware_{mode}_{kind}'
            if a.skip_build:
                manifest = json.loads((directory/'firmware.json').read_text())
                verify_sources(manifest)
                if digest(directory/'cpu.elf') != manifest['elf_sha256'] or digest(directory/'cpu.mem') != manifest['mem_sha256']:
                    raise RuntimeError('Firmware payload differs from its manifest')
            else:
                manifest = build_firmware(directory, a.gcc, hardware=mode=='hw',
                    trace=kind=='trace', jobs=a.jobs, object_cache=out/'firmware_objects',
                    ps_pool_bytes=a.ps_pool_bytes,force_raw=a.force_raw,
                    ia_cache_blocks=a.ia_cache_blocks if a.ps_pool_bytes else None,
                    ps_frame_count=a.ps_frame_count)
            if (not manifest['passed'] or manifest['supported_modes'] != ([HARDWARE_MODE] if mode=='hw' else [0]) or
                manifest['trace_enabled'] != (kind=='trace') or manifest['hardware'] != (mode=='hw') or
                manifest.get('rounding_mode') != 'nearest_even' or
                (a.ps_frame_count is not None and manifest['compile_defines']['DSA_PS_FRAME_COUNT'] != a.ps_frame_count) or
                manifest['compile_defines']['DSA_PS_POOL_BYTES'] != a.ps_pool_bytes or
                manifest['compile_defines']['DSA_PS_FORCE_RAW'] != int(a.force_raw)):
                raise RuntimeError('Firmware mode does not match the selected build')
            firmwares[mode,kind] = directory,manifest
    if a.build_only:
        print('MODEL_BENCHMARK_BUILD_PASS', flush=True)
        return 0
    work = []
    for mode in a.modes:
        for kind in a.kinds:
            fw_directory, fw = firmwares[mode,kind]
            for name, model in prepared.items():
                for sample in model['samples']:
                    if a.samples is not None and sample['sample_index'] not in a.samples:
                        continue
                    directory = out/'results/cases'/name/f'sample_{sample["sample_index"]:04d}'/f'{kind}_{HARDWARE_MODE if mode=="hw" else 0}'
                    if (directory/'result.json').exists():
                        old = json.loads((directory/'result.json').read_text())
                        if not a.resume:
                            raise RuntimeError('Run already exists; select --resume: '+str(directory))
                        if (old['passed'] and old['firmware_elf_sha256']==fw['elf_sha256'] and
                            old['simulator']['simulator_sha256']==digest(binary) and
                            old['input_sha256']==sample['input']['sha256'] and
                            old['model']['sha256']==model['model']['sha256'] and
                            old['ram_fixed_lat']==a.latency):
                            continue
                        raise RuntimeError('Existing run does not match this execution: '+str(directory))
                    case = create_case(directory,prepared_root/name,model,sample,
                                       HARDWARE_MODE if mode=='hw' else 0,fw_directory,fw,ps_force_raw=a.force_raw)
                    work.append((directory,case,fw))
    def execute(item):
        directory,case,fw = item
        start = time.monotonic()
        value = execute_case(binary,directory,case,fw,latency=a.latency,
            cycle_limit=a.cycle_limit,seconds_limit=a.seconds_limit)
        value['host_seconds']=time.monotonic()-start
        write_json(directory/'result.json',value)
        return value
    with ThreadPoolExecutor(max_workers=a.run_jobs) as pool:
        for future in as_completed([pool.submit(execute,item) for item in work]):
            value=future.result()
            print(json.dumps({'model':value['model_id'],'sample':value['sample_index'],
                'mode':value['mode_name'],'kind':value['kind'],'passed':value['passed'],
                'cycles':value.get('result',{}).get('invoke_cycles'),
                'seconds':round(value['host_seconds'],2),
                'failed_checks':[key for key,ok in value['checks'].items() if not ok],
                'failure':value.get('failure')}),flush=True)
            summarize(out,prepared_root)
    result=summarize(out,prepared_root)
    return 0 if result['functional_passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
