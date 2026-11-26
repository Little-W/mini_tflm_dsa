#!/usr/bin/env python3
"""验证地址、调度、坐标预测和历史位置减法的完整父模块。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'b4590508'
PROFILES = [
    ('address', 'rtl/npu/conv/vector_engine_address.sv', {
        'p_tile': 16, 'p_bus_width': 64, 'p_dma_size': 64, 'p_pe_count': 8,
        'p_window_lanes': 8, 'p_shared_quant_enable': 1,
        'p_shared_storage_enable': 1, 'p_registered_read_phase': 1}),
    ('scheduler_unbounded', 'rtl/npu/control/ps_window_scheduler.sv', {
        'SIZE': 16, 'FRAME_COUNT': 16, 'MAX_REUSE_TILES': 0}),
    ('scheduler_bounded', 'rtl/npu/control/ps_window_scheduler.sv', {
        'SIZE': 16, 'FRAME_COUNT': 16, 'MAX_REUSE_TILES': 32}),
    ('predictor', 'rtl/npu/dma/cache/conv_next_use_predictor.sv', {}),
    ('geometry_lanes2', 'rtl/npu/conv/conv_im2col_geometry.sv', {'p_lanes': 2}),
    ('geometry_lanes8', 'rtl/npu/conv/conv_im2col_geometry.sv', {'p_lanes': 8}),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--profiles', nargs='+', choices=[row[0] for row in PROFILES])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                      cwd=ROOT, text=True).strip()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    jobs, hashes = [], {}
    for name, relative_source, parameters in PROFILES:
        if args.profiles and name not in args.profiles:
            continue
        source = ROOT/relative_source
        module = source.stem
        reference = out/(name+'_reference.sv')
        reference.write_bytes(subprocess.check_output(
            ['git', 'show', f'{revision}:{relative_source}'], cwd=ROOT))
        for synthesis in (False, True):
            commands = []
            for label, path in [('reference', reference), ('candidate', source)]:
                dependencies = resolve([path], ROOT)
                hashes.update({str(p.relative_to(ROOT)): digest(p) for p in dependencies
                               if p.is_relative_to(ROOT) and not p.is_relative_to(out)})
                options = ['-I'+str(ROOT/'include'), '-I'+str(ROOT/'rtl/npu/ps_compact')]
                if synthesis:
                    options.append('-DSYNTHESIS=1')
                options += [f'-G{key}={value}' for key, value in parameters.items()]
                commands += ['read_slang --top '+module+' '+
                             shlex.join(options+list(map(str, dependencies))),
                             'setattr -mod -unset keep_hierarchy',
                             'setattr -unset keep_hierarchy',
                             'prep -top '+module+' -flatten', 'memory_map',
                             'async2sync', 'opt -full', 'rename -top '+label,
                             'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate proof', 'hierarchy -top proof',
                         'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                         'equiv_status -assert']
            key = name+('_synthesis' if synthesis else '_generic')
            script = out/(key+'.ys')
            script.write_text('\n'.join(commands)+'\n')
            jobs.append((key, module, parameters, synthesis, script))

    def prove(job):
        key, module, parameters, synthesis, script = job
        log = out/(key+'.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, check=True, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=600)
        assert 'Equivalence successfully proven' in log.read_text()
        print(key+' PASS', flush=True)
        return {'module': module, 'parameters': parameters, 'synthesis': synthesis,
                'passed': True, 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(prove, jobs))
    hashes['include/conv_im2col_prepared_tile.svh'] = digest(
        ROOT/'include/conv_im2col_prepared_tile.svh')
    assert hashes == {name: digest(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'inputs_constrained': False,
              'all_public_outputs_compared': True, 'source_sha256': hashes,
              'test_sha256': digest(Path(__file__)), 'profiles': results}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
