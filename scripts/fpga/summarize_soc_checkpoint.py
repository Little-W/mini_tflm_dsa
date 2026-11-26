#!/usr/bin/env python3
"""核对固定 SoC 源码、映射结果和实际回归，生成提交检查记录。"""
from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def original_digest(path):
    if path.exists():
        return digest(path)
    with gzip.open(path.with_suffix(path.suffix+'.gz'), 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(root, *arguments):
    return subprocess.check_output(['git', '-C', str(root), *arguments])


def require(condition, description):
    if not condition:
        raise RuntimeError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--reference-prefix', type=Path, required=True)
    parser.add_argument('--uploaded-performance', type=Path,
                        help='上传环境的当前 68 项实际运行结果')
    parser.add_argument('--uploaded-reference', type=Path,
                        help='上传环境的 449e3fe4 实际重建结果')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.uploaded_performance) != bool(args.uploaded_reference):
        parser.error('两个上传环境结果目录必须同时提供')
    source, prefix = args.source_root.resolve(), args.prefix.resolve()
    mapped = Path(str(prefix)+'_cost')
    initial = Path(str(args.reference_prefix.resolve())+'_cost')
    revision = git(source, 'rev-parse', 'HEAD^{commit}').decode().strip()
    tree = git(source, 'rev-parse', 'HEAD^{tree}').decode().strip()
    require(not git(source, 'status', '--porcelain'), '固定源码包含未提交修改')
    pico = source/'picorv32'
    pico_commit = git(source, 'rev-parse', revision+':picorv32').decode().strip()
    require(git(pico, 'rev-parse', 'HEAD').decode().strip() == pico_commit,
            'PicoRV32 的检出提交与父仓库不同')
    require(not git(pico, 'status', '--porcelain'), 'PicoRV32 包含未提交修改')
    manifest = read(mapped/'manifest.json')
    summary = read(mapped/'summary.json')
    paths = read(mapped/'long_paths.json')['paths']
    first_manifest = read(initial/'manifest.json')
    first_summary = read(initial/'summary.json')
    require(manifest['parameters'] == first_manifest['parameters'] and
            manifest['build_configuration'] == first_manifest['build_configuration'],
            '比较版本的生产配置不同')
    require(summary['manifest_sha256'] == digest(mapped/'manifest.json'), '映射输入摘要不一致')
    for name, expected in manifest['sources_sha256'].items():
        require(digest(source/name) == expected, '映射源码摘要不同：'+name)
        if name.startswith('picorv32/'):
            content = git(pico, 'show', pico_commit+':'+name[len('picorv32/'):])
        else:
            content = git(source, 'show', revision+':'+name)
        require(hashlib.sha256(content).hexdigest() == expected, '映射源码与 Git 对象不同：'+name)
    config = manifest['build_configuration']
    require(digest(source/config['path']) == config['sha256'], '生产配置文件摘要不同')
    require(original_digest(mapped/'mapped.json') == summary['mapping_stage']['mapped_json_sha256'],
            '映射网表摘要不同')
    require(original_digest(prefix/'soc_top/pre_lut.il') == manifest['pre_lut_origin']['sha256'],
            '预综合网表摘要不同')
    require(summary['functional_verification']['passed'], '映射功能检查未通过')
    require(paths['graph_complete'] and not paths['unclassified_cell_types'] and
            not paths['combinational_cycle_nodes'], '组合路径分析图不完整')
    require(paths['longest_register_path_cells'] == summary['longest_register_path_cells'],
            '两份完整路径统计不同')
    regressions = {}
    for kind in ('fpga', 'asic', 'operators'):
        directory = Path(str(prefix)+'_'+kind)
        result = read(directory/'validation_summary.json')
        require(result['passed'] and result['source_commit'] == revision, '回归来源或状态不同：'+kind)
        build_path = directory/('sim/build.json' if kind == 'operators' else 'npu/s16/build.json')
        build = read(build_path)
        require(build['returncode'] == 0 and build['sources_unchanged_during_build'],
                '回归构建未完成或输入发生变化：'+kind)
        for name, expected in build['source_sha256'].items():
            require(digest(source/name) == expected, '回归源码摘要不同：'+kind+':'+name)
        binary = directory/('sim/obj/Vtb_latest_operators' if kind == 'operators' else 'npu/s16/obj/Vtb_conv_npu')
        require(digest(binary) == result['binary_sha256'] == build['binary_sha256'],
                '回归执行文件摘要不同：'+kind)
        checks = (('all_cases.json', 'all_cases_sha256'), ('comparison.json', 'comparison_sha256')) \
            if kind == 'operators' else (('summary.json', 'summary_sha256'), ('npu/s16/build.json', 'build_sha256'))
        for name, key in checks:
            require(digest(directory/name) == result[key], '回归结果摘要不同：'+kind+':'+name)
        regressions[kind] = {'summary': result, 'validation_summary_sha256': digest(directory/'validation_summary.json'),
                             'build_sha256': digest(build_path), 'independently_rechecked': True}
    performance_passed = None
    if args.uploaded_performance:
        # 性能实验采用上传环境的容量配置，与生产 SoC 资源测量分别核对。
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'test/uploaded_performance'))
        from audit import audit
        performance = audit(source, args.uploaded_performance.resolve(), args.uploaded_reference.resolve())
        regressions['uploaded_performance'] = performance
        performance_passed = performance['performance_passed']
    resources = summary['resources']
    targets = {'nominal_lut_sites': 50000, 'maximum_combinational_cells': 10,
               'important_path_preferred_maximum_cells': 6, 'clock_frequency_mhz': 150}
    record = {
        'schema_version': 1, 'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'source': {'commit': revision, 'tree': tree, 'picorv32_commit': pico_commit,
                   'sources_sha256': manifest['sources_sha256'],
                   'source_count': len(manifest['sources_sha256']),
                   'all_source_hashes_match_git_blobs': True, 'clean_worktree': True},
        'targets': targets,
        'target_results': {'nominal_lut_sites_met': resources['lut_sites_nominal_before_packing'] <= 50000,
                           'maximum_combinational_cells_met': paths['longest_register_path_cells'] <= 10,
                           'uploaded_performance_cycles_met': performance_passed,
                           'routed_150mhz_confirmed': None},
        'mapping': {'manifest': manifest, 'manifest_sha256': digest(mapped/'manifest.json'),
                    'summary_sha256': digest(mapped/'summary.json'),
                    'mapping_stage': summary['mapping_stage'], 'lut_library': summary['lut_library'],
                    'functional_verification': summary['functional_verification']},
        'resources': resources,
        'paths': {key: paths[key] for key in ('longest_register_path_cells', 'graph_complete',
                    'graph_nodes', 'visited_graph_nodes', 'combinational_cycle_nodes',
                    'unclassified_cell_types', 'path_method', 'report_limits')},
        'long_paths': paths['distinct_register_path_groups'],
        'long_paths_sha256': digest(mapped/'long_paths.json'),
        'regressions': regressions,
        'comparison': {'configuration_identical': True, 'initial_resources': first_summary['resources'],
            'initial_longest_register_path_cells': first_summary['longest_register_path_cells'],
            'initial_manifest_sha256': digest(initial/'manifest.json'),
            'initial_summary_sha256': digest(initial/'summary.json'),
            'nominal_lut_reduction': first_summary['resources']['lut_sites_nominal_before_packing']-
                                     resources['lut_sites_nominal_before_packing']},
        'physical_timing': {'place_and_route_executed': False, 'frequency_confirmed_mhz': None,
            'clock_constraint_ns': manifest['clock_period_ns'],
            'description': '本记录为 FPGA 映射资源和组合路径检查；实际 150 MHz 时序由目标器件布局布线后的报告确认。'},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'source_commit': revision, 'sources_checked': len(manifest['sources_sha256']),
        'nominal_lut_sites': resources['lut_sites_nominal_before_packing'],
        'maximum_combinational_cells': paths['longest_register_path_cells'],
        'all_numeric_regressions_passed': True, 'target_results': record['target_results']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
