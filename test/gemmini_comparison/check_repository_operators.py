#!/usr/bin/env python3
"""核对共同任务的实际输出、访存条件和固定仓库版本的性能结果。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


RESOURCE_PROFILE_KEYS = (
    'size', 'bus_width', 'dma_max_bytes', 'ia_cache_blocks', 'ps_frame_count',
    'shared_bank_bytes', 'shared_bank_count', 'shared_total_bytes', 'im2col_cache_bytes',
    'vector_pe_count', 'quantization_lanes', 'window_lanes', 'shared_quant_enable',
    'ia_compact_enable', 'ia_cache_bytes', 'ps_pool_bytes', 'raw_only',
    'cache_line_bytes', 'cache_sets', 'cache_ways', 'memory_timing', 'planner_costs',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def records(text, prefix):
    return [{key: int(value) for key, value in re.findall(r'(\w+)=(-?\d+)', line)}
            for line in text.splitlines() if line.startswith(prefix + ' ')]


def require_same_resources(current, previous):
    """比较影响容量、计算并行度与外存服务的实际配置。"""
    for key in RESOURCE_PROFILE_KEYS:
        require(key in current and key in previous, 'Missing resource profile field: ' + key)
        require(current[key] == previous[key], 'Reference resource configuration differs: ' + key)


def verify_reference_sources(directory, reference, mode):
    """核对固定版本的生产文件；历史适配工具单独检查。"""
    directory = Path(directory)
    summary = load(directory / 'summary.json')
    build = load(directory / 'sim/build.json')
    planner = load(directory / 'planner/build.json')
    require(summary['passed'], 'Reference simulation failed')
    require(summary['profile'] == build['profile'] == planner['profile'], 'Reference profiles differ')
    observed = {}
    for manifest in (build, planner):
        require(manifest['returncode'] == 0 and manifest['sources_unchanged_during_build'],
                'Reference build failed or source changed')
        for path, checksum in manifest['source_sha256'].items():
            require(path not in observed or observed[path] == checksum, 'Reference manifests disagree: ' + path)
            observed[path] = checksum
    verification = directory / 'historical_source_verification.json'
    if verification.is_file():
        fixed = load(verification)
        expected_mode = {'fast': 'low-latency', 'registered': 'default'}[mode]
        require(fixed['passed'] and fixed['sources_unchanged'], 'Historical source verification failed')
        require(fixed['source_revision'] == reference['remote_commit'] and fixed['mode'] == expected_mode,
                'Historical source revision or mode differs')
        require(summary['source_commit'] == reference['remote_commit'], 'Reference source revision differs')
        root = Path(fixed['source_root'])
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        require(commit == reference['remote_commit'], 'Historical source checkout differs')
        require(not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                              '--untracked-files=no']).strip(), 'Historical source checkout changed')
        tree = {}
        for entry in subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', commit]).split(b'\0'):
            if entry:
                description, name = entry.split(b'\t', 1)
                file_mode, kind, blob = description.decode().split()
                if kind == 'blob':
                    tree[name.decode()] = (file_mode, blob)
        repository = fixed['compiled_and_planner_repository_sources']
        actual_repository = {str(Path(path).relative_to(root)): checksum for path, checksum in observed.items()
                             if Path(path).is_relative_to(root)}
        require(repository == actual_repository, 'Historical repository inputs differ from build manifests')
        for relative, checksum in repository.items():
            path = root / relative
            require(relative in tree and path.is_file(), 'Historical repository file is unavailable: ' + relative)
            require(tree[relative][0] != '120000', 'Compiled historical inputs must be regular files: ' + relative)
            data = path.read_bytes()
            git_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            require(git_blob == tree[relative][1] and hashlib.sha256(data).hexdigest() == checksum,
                    'Historical source differs from its Git object: ' + relative)
        production = {name: checksum for name, checksum in repository.items() if name.startswith('rtl/')}
        require(production == fixed['production_rtl_sha256'], 'Historical RTL input list differs')
        for required in ('rtl/npu/top/npu_top.sv', 'rtl/npu/conv/conv_im2col_frontend.sv'):
            require(required in production, 'Historical build does not include: ' + required)
        support = {name: checksum for name, checksum in observed.items() if not Path(name).is_relative_to(root)}
        require(support == fixed['verification_support_sha256'], 'Historical verification inputs differ')
        required_options = {'--assert', '-DSYNTHESIS=1', '-DXILINX_FPGA=1',
                            '-DTB_CONV_LOW_LATENCY=' + str(int(expected_mode == 'low-latency'))}
        require(required_options.issubset(build['command']), 'Historical compilation options differ')
        require(fixed['binary_sha256'] == build['binary_sha256'], 'Historical simulator checksum differs')
        return {'kind': 'fixed_git_replay', 'source_revision': commit,
                'source_verification_sha256': sha(verification), 'production_rtl_files': len(production),
                'repository_source_files': len(repository), 'binary_sha256': build['binary_sha256']}
    fixed = reference['source_verification'][mode]['compiled_and_planner_repository_sources']
    for relative, checksum in fixed.items():
        matches = [value for path, value in observed.items() if path.endswith('/' + relative)]
        require(matches and all(value == checksum for value in matches), 'Remote source differs: ' + relative)
    return {'kind': 'recorded_repository_sources', 'source_revision': reference['remote_commit'],
            'repository_source_files': len(fixed), 'binary_sha256': build['binary_sha256']}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--old-fast', type=Path, required=True)
    ap.add_argument('--old-default', type=Path, required=True)
    ap.add_argument('--reference', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--case-count', type=int, choices=(26,36), default=26)
    args = ap.parse_args()
    sys.path.insert(0, str(args.repo / 'test/gemmini_comparison'))
    from compare_fair_operators import memory_segment
    run = args.run.resolve()
    summary = load(run / 'summary.json')
    build = load(run / 'sim/build.json')
    planner = load(run / 'planner/build.json')
    reference = load(args.reference)
    binary = run / 'sim/obj/Vtb_latest_operators'
    require(summary['passed'] and build['returncode'] == 0, 'Simulation failed')
    require(build['sources_unchanged_during_build'], 'Sources changed during build')
    require(sha(binary) == build['binary_sha256'], 'Binary checksum differs')
    require('--assert' in build['command'], 'RTL assertions are required')
    require('-DSYNTHESIS=1' in build['command'] and '-DXILINX_FPGA=1' in build['command'],
            'Production and FPGA conditions are required')
    require(summary['profile'] == build['profile'] == planner['profile'], 'Profiles differ')
    for manifest in (build, planner):
        for path, expected in manifest['source_sha256'].items():
            require(sha(path) == expected, 'Source checksum differs: ' + path)
    tb = (run / 'sim/tb_latest_operators.sv').read_text()
    require('localparam int WORDS = 524288;' in tb, 'Full memory size differs')
    require('u_mem.mem[i] !== golden[i]' in tb and 'assert (errors == 0)' in tb,
            'Full memory comparison must remain active')
    reference_checks = {}
    for key, directory in (('fast', args.old_fast), ('registered', args.old_default)):
        require_same_resources(summary['profile'], load(directory/'summary.json')['profile'])
        reference_checks[key] = verify_reference_sources(directory, reference, key)
    rows = []
    for kind in ('gemm', 'conv'):
        group = load(run / kind / 'summary.json')
        require(group['passed'] and group['source_commit'] == summary['source_commit'], 'Group failed')
        require(group['build_manifest_sha256'] == sha(run/'sim/build.json'), 'Build record differs')
        old_fast = {r['name']: r for r in load(args.old_fast/kind/'summary.json')['cases']}
        old_default = {r['name']: r for r in load(args.old_default/kind/'summary.json')['cases']}
        require({r['name'] for r in group['cases']} == set(old_fast) == set(old_default), 'Case collection differs')
        for row in group['cases']:
            name = row['name']; folder = run/kind/'cases'/name
            fast, default = old_fast[name], old_default[name]
            require(row['passed'] and row['returncode'] == 0, 'Case failed: ' + name)
            for key in ('workload_manifest_sha256', 'input_tensor_sha256', 'output_sha256'):
                require(row[key] == fast[key] == default[key], key + ' differs: ' + name)
            require(row['command'][0] == str(binary) and '+NO_RANDOM_WAIT' in row['command'], 'Execution command differs')
            require([int(s,16) for s in (folder/'config.mem').read_text().split()] == row['configuration_words'],
                    'Configuration words differ')
            for filename, expected in row['files'].items():
                require(sha(folder/filename) == expected, 'Memory file checksum differs: ' + name)
            log = (folder/'run.log').read_text()
            for prefix, key in (('COMMON_OPERATOR_PASS','measurement'),('COMMON_TIMING','timing'),
                                ('COMMON_SCHEDULE','observed_schedule'),('COMMON_AR_INTERVAL','observed_ar_interval')):
                require(records(log,prefix) == [row[key]], prefix + ' differs: ' + name)
            m,t = row['measurement'],row['timing']; ar = row['observed_ar_interval']
            require(m['cycles'] == t['done'], 'Completion counter differs')
            require(t['read_latency_min'] >= 8, 'Read latency is below eight cycles')
            require(max(t['read_outstanding_max'],t['write_outstanding_max']) <= 4, 'Outstanding bound exceeded')
            require(max(t['read_burst_bytes_max'],t['write_burst_bytes_max']) <= 2048, 'Burst bound exceeded')
            require(t['read_beats'] <= m['ar_bytes'] <= 8*t['read_beats'], 'Read transfer sizes exceed AXI64 bounds')
            require(max(t['last_r'],t['last_b']) <= t['done'], 'External responses remain pending')
            require(ar['required'] == 1 and ar['accepted'] == t['read_commands'], 'Address interval measurement differs')
            require(ar['accepted'] < 2 or ar['minimum'] >= 1, 'Address interval is too short')
            output = (folder/'canonical_output.bin').read_bytes()
            expected = memory_segment(folder/'golden.mem',row['addresses']['c'],row.get('output_elements', row.get('m', 0) * row.get('n', 0)))
            require(output == expected, 'Actual output tensor differs from checked memory: ' + name)
            require(hashlib.sha256(output).hexdigest() == row['output_sha256'] == row['observed_output_sha256'],
                    'Checked output hash differs')
            cycles = m['cycles']; fcycles = fast['measurement']['cycles']; dcycles = default['measurement']['cycles']
            rows.append(dict(name=name,kind=kind,remote_default_cycles=dcycles,remote_low_latency_cycles=fcycles,
                             final_cycles=cycles,change_from_default_pct=100*(cycles/dcycles-1),
                             change_from_low_latency_pct=100*(cycles/fcycles-1),
                             output_sha256=row['output_sha256'],input_tensor_sha256=row['input_tensor_sha256'],
                             checked_memory_words=524288,all_external_responses_completed=True,
                             observed_ar_interval=ar,timing=t,measurement=m))
    require(len(rows)==args.case_count, 'Operator case count differs')
    total = {key:sum(r[key] for r in rows) for key in ('remote_default_cycles','remote_low_latency_cycles','final_cycles')}
    result=dict(source_commit=summary['source_commit'],remote_commit=reference['remote_commit'],
                reference_sha256=sha(args.reference),binary_sha256=sha(binary),build_manifest_sha256=sha(run/'sim/build.json'),
                numerical_and_timing_checks_passed=True,case_count=len(rows),checked_memory_words_per_case=524288,
                checked_memory_words_total=len(rows)*524288,profile=summary['profile'],
                reference_source_checks=reference_checks,totals=total,cases=rows)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'repository_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    fields=['name','kind','remote_default_cycles','remote_low_latency_cycles','final_cycles','change_from_default_pct','change_from_low_latency_pct','output_sha256']
    with (args.out/'repository_comparison.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({key:row[key] for key in fields})
    print(json.dumps({'passed':True,'cases':len(rows),'totals':total},indent=2))


if __name__ == '__main__':
    main()
