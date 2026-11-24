#!/usr/bin/env python3
"""逐周期比较缓存和预测器的完整状态、存储内容及公开输出。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CACHE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
PREDICTOR = Path('rtl/npu/dma/cache/conv_next_use_predictor.sv')
PROFILES = {
    'direct': {'SETS': 8, 'WAYS': 2, 'LINE_BYTES': 16, 'BUS_WIDTH': 32,
               'READ_WIDTH': 32, 'DEMAND_DEPTH': 1},
    'single_way': {'SETS': 8, 'WAYS': 1, 'LINE_BYTES': 16, 'BUS_WIDTH': 64,
                   'READ_WIDTH': 32, 'DEMAND_DEPTH': 4},
    'production': {'SETS': 16, 'WAYS': 2, 'LINE_BYTES': 128, 'BUS_WIDTH': 64,
                   'READ_WIDTH': 64, 'DEMAND_DEPTH': 2, 'p_defer_retire_shift': 1},
    'production_read128': {'SETS': 16, 'WAYS': 2, 'LINE_BYTES': 128, 'BUS_WIDTH': 64,
                           'READ_WIDTH': 128, 'DEMAND_DEPTH': 2, 'p_defer_retire_shift': 1},
    'production_direct': {'SETS': 16, 'WAYS': 2, 'LINE_BYTES': 128, 'BUS_WIDTH': 64,
                          'READ_WIDTH': 128, 'DEMAND_DEPTH': 1, 'p_defer_retire_shift': 1},
}
ARRAYS = {
    **{f'tap_s{i}': (f'tap_pipe[{i}]', 5) for i in range(2)},
    **{f'coordinate_good_s{i}': (f'coordinate_good[{i}]', 1) for i in range(3)},
    **{f'candidate_good_s{i}': (f'candidate_good[{i}]', 1) for i in range(3, 7)},
    **{f'block_s{i}': (f'block_pipe[{i}]', 32) for i in range(3, 5)},
    **{f'local_s{i}': (f'local_pipe[{i}]', 32) for i in range(3, 6)},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response_qualification_reference(source: str) -> str:
    """为缓存参考接口补充成功、错误响应的规范布尔表达式。"""
    if re.search(r'output\s+logic\s+rsp_success\b', source):
        return source
    port = re.search(r'output\s+logic\s+rsp_error\s*,', source)
    if port is None:
        raise ValueError('缓存参考接口缺少 rsp_error 输出')
    source = source[:port.end()] + '\n  output logic rsp_success, rsp_failure,' + source[port.end():]
    return source.replace('endmodule',
        '  assign rsp_success = rsp_valid && !rsp_error;\n'
        '  assign rsp_failure = rsp_valid && rsp_error;\nendmodule', 1)


def worker(script: Path, log: Path) -> str:
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=600)
    text = log.read_text()
    if result.returncode:
        raise RuntimeError(f'完整模块证明未完成：{log}\n{text[-5000:]}')
    return text


def canonicalize(path: Path, top: str) -> dict:
    """将移入子模块的已有存储状态恢复为同一比较名称。"""
    design = json.loads(path.read_text())
    module = design['modules'][top]
    counts = {}
    public_ports = set(module['ports'])
    unused_aliases = 0
    metadata_input_aliases = 0
    for section in ('cells', 'netnames'):
        values = {}
        changed = 0
        for name, value in module[section].items():
            # 未使用的内部别名可以被综合删除；公开输出和实际存储状态继续完整比较。
            if section == 'netnames' and name not in public_ports and any(
                    bit in ('x', 'z') for bit in value['bits'] if isinstance(bit, str)):
                unused_aliases += 1
                continue
            target = re.sub(r'(g_metadata_way\[\d+\]\.)u_metadata\.', r'\1', name)
            # 逐路命中资格允许在调用端合并；实际写入控制、存储状态和公开输出仍完整比较。
            if section == 'netnames' and re.fullmatch(
                    r'g_metadata_way\[\d+\]\.(i_metadata_hit|i_hit_selected)', target):
                metadata_input_aliases += 1
                continue
            if target in values:
                raise ValueError(f'比较名称重复：{target}')
            values[target] = value
            changed += target != name
        module[section] = values
        counts[section] = changed
    path.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    counts['unused_aliases'] = unused_aliases
    counts['metadata_input_aliases'] = metadata_input_aliases
    counts['state_bits'] = sum(len(cell['connections'].get('Q', []))
        for cell in module['cells'].values() if cell['type'].startswith(('$dff', '$adff', '$sdff')))
    return counts


def archive(path: Path) -> dict:
    item = {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
    compressed = path.with_suffix(path.suffix + '.gz')
    with path.open('rb') as source, gzip.open(compressed, 'wb', compresslevel=6) as target:
        shutil.copyfileobj(source, target)
    with gzip.open(compressed, 'rb') as source:
        if hashlib.sha256(source.read()).hexdigest() != item['sha256']:
            raise RuntimeError('压缩后的比较模型内容不同')
    path.unlink()
    item['compressed_path'] = str(compressed)
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--units', nargs='+', choices=('cache', 'predictor'), default=('cache', 'predictor'))
    parser.add_argument('--cases', nargs='+', choices=tuple(PROFILES), default=tuple(PROFILES))
    parser.add_argument('--configurations', nargs='+', choices=('fpga', 'asic'), default=('fpga', 'asic'))
    parser.add_argument('--allow-state-count-change', action='store_true',
                        help='允许寄存器数量改变，仍证明全部对应状态和公开输出等价')
    parser.add_argument('--preview-request', action='store_true',
                        help='在缓存比较中启用请求预读接口')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    with_dependencies = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    report = {'passed': False, 'external_inputs_constrained': False,
              'scope': '全部公开输出、对应状态和实际存储内容', 'profiles': []}

    for unit in args.units:
        relative = CACHE if unit == 'cache' else PREDICTOR
        top = 'conv_windowed_cache' if unit == 'cache' else 'conv_next_use_predictor'
        profiles = PROFILES if unit == 'cache' else {'pipeline_arrays': {}}
        names = args.cases if unit == 'cache' else ('pipeline_arrays',)
        for configuration in args.configurations:
            for name in names:
                parameters = dict(profiles[name])
                if unit == 'cache' and args.preview_request:
                    parameters['p_preview_request'] = 1
                folder = out / f'{unit}_{configuration}_{name}'
                folder.mkdir(exist_ok=True)
                records, paths, source_hashes = {}, {}, {}
                for label, root in roots.items():
                    main_source = root / relative
                    original_source = main_source
                    if unit == 'cache' and label == 'reference' and re.search(
                            r'output\s+logic\s+rsp_success\b', (roots['current']/CACHE).read_text()):
                        text = response_qualification_reference(main_source.read_text())
                        main_source = folder / 'reference_cache.sv'
                        main_source.write_text(text)
                    if unit == 'predictor' and label == 'current':
                        text = main_source.read_text()
                        aliases = '\n'.join(f'  (* keep *) wire [{width-1}:0] {old} = {new};'
                                            for old, (new, width) in ARRAYS.items())
                        main_source = folder / 'current_predictor.sv'
                        main_source.write_text(text.replace('endmodule', aliases + '\nendmodule'))
                    files = with_dependencies([main_source], root)
                    source_hashes[label] = {str(path): digest(path) for path in files}
                    source_hashes[label][str(original_source)] = digest(original_source)
                    model = folder / (label + '.json')
                    paths[label] = model
                    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1' if configuration == 'fpga'
                               else '-DASIC_SYNTHESIS=1']
                    options += [f'-G{key}={value}' for key, value in parameters.items()]
                    script = folder / (label + '_prepare.ys')
                    script.write_text(f'read_slang --top {top} ' +
                        shlex.join(options + list(map(str, files))) +
                        f'\nprep -top {top} -flatten\nmemory_map\nasync2sync\nopt -full\n' +
                        f'write_json {shlex.quote(str(model))}\n')
                    worker(script, folder / (label + '_prepare.log'))
                    records[label] = canonicalize(model, top)
                if not args.allow_state_count_change and \
                        records['reference']['state_bits'] != records['current']['state_bits']:
                    raise ValueError(f'寄存状态数量不同：{records}')

                commands = []
                for label in roots:
                    commands += [f'read_json {shlex.quote(str(paths[label]))}',
                                 f'rename {top} {label}', f'design -stash {label}']
                commands += ['design -copy-from reference reference', 'design -copy-from current current',
                    'equiv_make reference current comparison', 'hierarchy -top comparison',
                    'equiv_simple -short -seq 1', 'opt -full', 'equiv_simple -short -seq 1',
                    'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
                script, log = folder / 'compare.ys', folder / 'compare.log'
                script.write_text('\n'.join(commands) + '\n')
                text = worker(script, log)
                match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
                if not match or 'Equivalence successfully proven' not in text:
                    raise RuntimeError(f'完整等价结果缺失：{log}')
                row = {'unit': unit, 'configuration': configuration, 'name': name,
                       'parameters': parameters, 'passed': True,
                       'equivalent_bits': int(match[1]), 'canonical_names': records,
                       'source_sha256': source_hashes, 'log_sha256': digest(log),
                       'models': [archive(path) for path in paths.values()]}
                report['profiles'].append(row)
                (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
                print(json.dumps({key: value for key, value in row.items()
                                  if key not in ('source_sha256', 'models')}), flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
