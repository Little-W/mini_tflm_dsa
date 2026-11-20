#!/usr/bin/env python3
"""汇总核加载任务接收的同源证明、数值和局部映射结果。"""
import argparse
import json
from pathlib import Path

from model import ROOT, REFERENCE, SOURCES, KERNEL, TOP, digest


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path(__file__).with_name('measurement.json'))
    parser.add_argument('--independent-review', type=Path)
    args = parser.parse_args()
    folder = args.build.resolve()
    formal = read(folder/'formal/summary.json')
    mapping = read(folder/'local/summary.json')
    segments = read(folder/'local/segments.json')
    numeric = read(folder/'numeric/summary.json')
    assert formal['passed'] and mapping['passed'] and segments['passed'] and numeric['passed']
    current = {str(path): digest(ROOT/path) for path in SOURCES}
    assert formal['source_sha256']['current'] == mapping['source_sha256']['current'] == current
    assert len(formal['connected']) == 12 and len(formal['kernel']) == 4
    assert formal['inputs_constrained'] is False and formal['state_constraints'] is False
    for path, expected in numeric['source_sha256'].items():
        assert digest(ROOT/path) == expected, path
    for path, expected in formal['script_sha256'].items():
        assert digest(ROOT/path) == expected, path
    assert digest(Path(__file__).with_name('measure.py')) == mapping['script_sha256']
    assert digest(Path(__file__).with_name('segments.py')) == segments['script_sha256']
    for label in ('reference','current'):
        assert segments['results'][label]['mapped_sha256'] == mapping['results'][label]['mapped_sha256']
        assert mapping['results'][label]['functional_verification']['passed']
        assert mapping['results'][label]['all_paths']['graph_complete']
        assert mapping['results'][label]['mapping']['max_lut_inputs'] == 6
        assert mapping['results'][label]['mapping']['wire_delay_ps'] == 500
        assert mapping['results'][label]['mapping']['delay_target_ps'] == 6667
    prior_path = ROOT/'test/npu_admission_r23/measurement.json'
    prior = read(prior_path)['numeric']['kernel']
    assert prior['passed'] and prior['source_sha256'][str(KERNEL)] == formal['source_sha256']['reference'][str(KERNEL)]
    counters = [name for name, value in numeric.items() if isinstance(value, int)]
    assert all(numeric[name] == prior[name] for name in counters)
    assert numeric['parameters'] == prior['parameters']
    report = {'passed': True, 'reference_commit': REFERENCE,
              'source_sha256': formal['source_sha256'],
              'reference_sha256': formal['source_sha256']['reference'],
              'design': {'new_register_bits': 0, 'added_interface_cycles': 0,
                'request_lut_inputs': 6, 'request_lut_init': "64'h0010_0010_1010_0010",
                'quiescent': 'prefetch_state != PF_PENDING && !transfer_active && !prefetch_check_pending && !ext_dma_busy && response_slots_active == 0',
                'admission_request': '!prefetch_state[1] && !cache_flush && ctrl_load_req && (!command_mode_q || (buf_load_ready && !init_cfg))',
                'proved_relation': 'quiescent && load_weight_req == quiescent && o_admission_request',
                'top_use': 'admission_kernel_occupied = kernel_loader_o_admission_request && block_dma_arbiter_o_kernel_eligible'},
              'formal': formal, 'numeric': numeric, 'mapping': mapping, 'segments': segments,
              'numeric_comparison': {'passed': True, 'report': str(prior_path.relative_to(ROOT)),
                'report_sha256': digest(prior_path), 'checked_fields': counters,
                'all_statistics_identical': True},
              'scripts_sha256': {str(path.relative_to(ROOT)): digest(path) for path in sorted(Path(__file__).parent.glob('*.py'))},
              'artifacts_sha256': {name: digest(folder/name) for name in ('formal/summary.json','local/summary.json','local/segments.json','numeric/summary.json')},
              'whole_soc_result': None}
    if args.independent_review:
        review = read(args.independent_review)
        assert review['passed'] and review['source_sha256'] == {str(p): current[str(p)] for p in (KERNEL,TOP)}
        report['independent_review'] = review
        report['independent_review_sha256'] = digest(args.independent_review)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(args.out, digest(args.out))


if __name__ == '__main__':
    main()
