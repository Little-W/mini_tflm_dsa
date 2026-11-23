#!/usr/bin/env python3
"""独立核查完整模型结果、原始输出字节与参考张量。"""
import hashlib
import argparse
import json
from pathlib import Path
import struct
from collections import defaultdict

if not __debug__:
    raise SystemExit('Run this audit with Python assertions enabled; remove -O or -OO.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--experiment-runner', type=Path)
    parser.add_argument('--prepared-root', type=Path,
                        help='Root containing the prepared model directories; overrides recorded paths')
    args = parser.parse_args()
    root, out = args.results_root.resolve(), args.out.resolve()
    expected_runner_sha = sha(args.experiment_runner.read_bytes()) if args.experiment_runner else None
    files = sorted(root.rglob('result.json'))
    assert len(files) == 16
    entries = []
    profiles = {}
    for path in files:
        raw = path.read_bytes()
        data = json.loads(raw)
        case = json.loads((path.parent / 'case.json').read_text())
        result = data['result']
        prepared = ((args.prepared_root.resolve() / data['model_id'])
                    if args.prepared_root else Path(case['prepared_dir']))
        assert data['passed'] is True and data['simulator']['passed'] is True
        assert all(value is True for value in data['checks'].values())
        assert data['simulator']['returncode'] == 0
        assert data['sim_binary_sha256'] == data['simulator']['simulator_sha256']
        assert data['firmware_elf_sha256'] == case['firmware_elf_sha256']
        assert sha((path.parent / 'run.log').read_bytes()) == data['run_log_sha256']
        if expected_runner_sha is not None:
            assert data['experiment_runner_sha256'] == expected_runner_sha
        assert result['complete'] == 1 and result['status'] == result['error'] == result['mismatches'] == 0
        assert result['end_cycle'] - result['start_cycle'] == result['invoke_cycles']
        words = list(struct.unpack('<27I', (path.parent / 'result.bin').read_bytes()))
        assert words == data['simulator']['result_words']
        assert sha((path.parent / 'result.bin').read_bytes()) == data['simulator']['result_sha256']
        for key, index in [('invoke_cycles', 10), ('init_cycles', 11), ('arena_used_bytes', 12), ('trace_records', 25)]:
            assert words[index] == result[key]
        actual = (path.parent / 'output.bin').read_bytes()
        expected = (prepared / case['sample']['output']['path']).read_bytes()
        assert actual == expected
        assert sha(actual) == data['output_comparison']['actual_sha256'] == data['output_comparison']['expected_sha256']
        assert sha(actual) == data['simulator']['output_sha256']
        assert len(actual) == result['output_bytes'] == result['compared_outputs']
        assert sha((path.parent / 'model_after.bin').read_bytes()) == data['model']['sha256']
        assert sha((path.parent / 'input_after.bin').read_bytes()) == data['input_sha256']
        assert data['network']['npu_errors'] == data['network']['axi_errors'] == 0
        assert data['network']['jobs'] == data['network']['done_jobs']
        assert result['predicted_label'] == result['expected_label']
        assert data['network']['cycles'] >= result['invoke_cycles']
        profile_text = json.dumps(data['hardware_profile'], sort_keys=True)
        profile_sha = sha(profile_text.encode())
        profiles[profile_sha] = data['hardware_profile']
        row = dict(path=str(path.relative_to(root)), result_sha256=sha(raw),
                   model_id=data['model_id'], sample_index=data['sample_index'], kind=data['kind'],
                   source_commit=data['source_commit'], hardware_profile_sha256=profile_sha,
                   sim_binary_sha256=data['sim_binary_sha256'],
                   firmware_elf_sha256=data['firmware_elf_sha256'],
                   experiment_runner_sha256=data['experiment_runner_sha256'],
                   configuration=data['configuration'],
                   passed=True, checks_count=len(data['checks']), checks=data['checks'],
                   invoke_cycles=result['invoke_cycles'], init_cycles=result['init_cycles'],
                   planning_cycles=result['planning_cycles'], arena_used_bytes=result['arena_used_bytes'],
                   network_counter_cycles=data['network']['cycles'],
                   final_output_bytes=len(actual), final_output_sha256=sha(actual),
                   predicted_label=result['predicted_label'], expected_label=result['expected_label'],
                   operator_count=result['operator_count'], trace_records=result['trace_records'],
                   intermediate_tensor_count=0, trace_tensor_count=0, trace_tensor_bytes=0,
                   intermediate_tensor_bytes=0, verified_tensors=[])
        if data['kind'] == 'trace':
            assert result['trace_enabled'] == 1
            traces = data['trace']
            assert len(traces) == result['trace_records'] == result['operator_count'] == len(case['sample']['nodes'])
            for item, node in zip(traces, case['sample']['nodes']):
                ordinal = item['descriptor']['ordinal']
                tensor = (path.parent / 'tensors' / f'tensor_{ordinal}.bin').read_bytes()
                reference = (prepared / node['path']).read_bytes()
                comp = item['comparison']
                assert tensor == reference
                assert len(tensor) == item['descriptor']['bytes'] == comp['actual_bytes'] == comp['expected_bytes']
                assert sha(tensor) == comp['actual_sha256'] == comp['expected_sha256'] == node['sha256']
                assert item['passed'] is True and comp['passed'] is True and comp['mismatches'] == 0
                assert item['descriptor']['operator_index'] == node['operator_index']
                assert item['descriptor']['tensor_index'] == node['tensor_index']
                row['verified_tensors'].append(dict(ordinal=ordinal, operator_index=node['operator_index'],
                    op=item['op'], tensor_index=node['tensor_index'], bytes=len(tensor), sha256=sha(tensor)))
                row['trace_tensor_bytes'] += len(tensor)
            assert (path.parent / 'tensors' / f"tensor_{traces[-1]['descriptor']['ordinal']}.bin").read_bytes() == actual
            row['trace_tensor_count'] = len(traces)
            row['intermediate_tensor_count'] = len(traces) - 1
            row['intermediate_tensor_bytes'] = row['trace_tensor_bytes'] - len(actual)
        else:
            assert data['kind'] == 'perf' and result['trace_enabled'] == 0
            assert not data['trace'] and result['trace_records'] == 0
        assert path.read_bytes() == raw
        entries.append(row)
    perf = [x for x in entries if x['kind'] == 'perf']
    trace = [x for x in entries if x['kind'] == 'trace']
    assert len(perf) == len(trace) == 8
    assert {row['model_id'] for row in entries} == {
        'ds_cnn_kws', 'mnist_cnn', 'mobilenet_v1_vww', 'resnet8_cifar10'}
    grouped = defaultdict(dict)
    for row in entries:
        grouped[(row['model_id'], row['sample_index'])][row['kind']] = row
    for pair in grouped.values():
        assert pair['perf']['final_output_sha256'] == pair['trace']['final_output_sha256']
        assert pair['perf']['arena_used_bytes'] == pair['trace']['arena_used_bytes']
        assert pair['perf']['sim_binary_sha256'] == pair['trace']['sim_binary_sha256']
    assert len(grouped) == 8
    summary = dict(result_count=16, perf_runs=8, trace_runs=8,
        model_count=len({x['model_id'] for x in entries}), all_passed=True,
        perf_invoke_cycles_sum=sum(x['invoke_cycles'] for x in perf),
        perf_init_cycles_sum=sum(x['init_cycles'] for x in perf),
        perf_planning_cycles_sum=sum(x['planning_cycles'] for x in perf),
        perf_arena_used_bytes_max=max(x['arena_used_bytes'] for x in perf),
        trace_tensor_count=sum(x['trace_tensor_count'] for x in trace),
        intermediate_tensor_count_excluding_final=sum(x['intermediate_tensor_count'] for x in trace),
        final_tensor_count_in_trace=8,
        trace_tensor_bytes=sum(x['trace_tensor_bytes'] for x in trace),
        intermediate_tensor_bytes_excluding_final=sum(x['intermediate_tensor_bytes'] for x in trace),
        perf_check_occurrences=sum(x['checks_count'] for x in perf),
        trace_check_occurrences=sum(x['checks_count'] for x in trace),
        total_check_occurrences=sum(x['checks_count'] for x in entries),
        all_output_bytes_verified=all(x['passed'] for x in entries),
        source_commits=sorted({x['source_commit'] for x in entries}),
        hardware_profile_count=len(profiles))
    audit=dict(scope='Read-only audit of 16 result records and raw result/output/tensor files',
        results_root=str(root), audit_script_sha256=sha(Path(__file__).read_bytes()),
        prepared_root_override=str(args.prepared_root.resolve()) if args.prepared_root else None,
        expected_experiment_runner_sha256=expected_runner_sha,
        primary_timing_metric='result.invoke_cycles from the eight perf runs',
        trace_count_definition='trace_tensor_count includes the final output once per run; intermediate_tensor_count_excluding_final excludes it',
        summary=summary, hardware_profiles=profiles, entries=entries)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for row in perf:
        print(row['model_id'], row['sample_index'], row['invoke_cycles'], row['init_cycles'], row['arena_used_bytes'])


if __name__ == '__main__':
    main()
