#!/usr/bin/env python3
"""比较完整前端运行寄存器的公开端口、共有状态及坐标更新。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_im2col_runtime_registers.sv')
REFERENCE = '8e522969c7a94cc2ee13188ce41d438a84de8a12'
PROFILES = (
    (16, 6, 5, 5, 35, 128, 4, 16, 1),
    (16, 6, 5, 4, 35, 64, 3, 8, 1),
    (8, 3, 4, 3, 33, 32, 2, 4, 0),
    (4, 2, 3, 2, 40, 32, 2, 2, 0),
)
PARAMETERS = ('p_size', 'p_slot_width', 'p_count_width', 'p_chunk_width',
              'p_coord_width', 'p_read_width', 'p_word_shift',
              'p_saved_group_lanes', 'p_register_descriptor')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile_name(values):
    return f'n{values[0]}_l{values[7]}_c{values[4]}_r{values[5]}_d{values[8]}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--profile')
    parser.add_argument('--mode', choices=('generic', 'fpga', 'all'), default='all')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out/'reference.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT))
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    # 顺序 case 保留语言定义的首个匹配分支；完整输入证明覆盖任意事件组合。
    semantic_sources = {}
    for label, original in [('reference', reference), ('current', ROOT/SOURCE)]:
        path = out/(label+'_sequential_case.sv')
        path.write_text(re.sub(r'\bunique\s+case\b', 'case', original.read_text()))
        semantic_sources[label] = path
    sources = {label: resolver['with_dependencies']([path], ROOT)
               for label, path in semantic_sources.items()}
    files = resolver['input_files']([ROOT/SOURCE, *[p for paths in sources.values() for p in paths]], ROOT)
    hashes = {str(p): digest(p) for p in files}
    runs = []
    for mode, flags in {'generic': ['-USYNTHESIS', '-UXILINX_FPGA'],
                        'fpga': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']}.items():
        if args.mode != 'all' and mode != args.mode:
            continue
        for values in PROFILES:
            profile = profile_name(values)
            if args.profile and args.profile != profile:
                continue
            parameters = dict(zip(PARAMETERS, values))
            parameters.update(p_row_high_width=27, p_cache_sets=16, p_cache_ways=2)
            options = ['-G'+name+'='+str(value) for name, value in parameters.items()]
            commands = []
            for label, paths in sources.items():
                commands += [shlex.join(['read_slang', '--top', 'conv_im2col_runtime_registers',
                    '-I'+str(ROOT/'include'), *flags, *options, *map(str, paths)]),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'setattr -unset keep', 'prep -top conv_im2col_runtime_registers -flatten',
                    'async2sync', 'opt_clean', 'rename conv_im2col_runtime_registers '+label,
                    'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current comparison', 'hierarchy -top comparison',
                         'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                         'equiv_status -assert']
            label = mode+'_'+profile
            script, log = out/(label+'.ys'), out/(label+'.log')
            script.write_text('\n'.join(commands)+'\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=480)
            contents = log.read_text()
            if 'Equivalence successfully proven!' not in contents:
                raise RuntimeError('完整运行寄存器等价证明未完成：'+label)
            points = re.findall(r'Found (\d+) \$equiv cells', contents)
            run = dict(mode=mode, parameters=parameters, passed=True,
                       equivalence_points=int(points[-1]), log_sha256=digest(log))
            runs.append(run)
            print(json.dumps(dict(profile=profile, **run)), flush=True)
    if not runs or any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError('验证配置为空或运行期间源码发生变化')
    report = dict(passed=True, reference_commit=args.reference, source_sha256=hashes,
                  inputs_constrained=False, unique_case_first_match_semantics=True,
                  public_ports_and_common_state_compared=True,
                  runner_sha256=digest(__file__), runs=runs)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
