#!/usr/bin/env python3
"""检查前端准备参数解析，以及严格模式和准备阶段周期比较模式。"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    operators = load('checked_storage_operators', ROOT / 'test/gemmini_comparison/run_storage_operators.py')
    regression = load('checked_timing_operators', ROOT / 'test/timing_operator_regression/run.py')
    cases = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        cases.append(dict(name=name, passed=True))

    source = """module dma;
    conv_im2col_frontend #(
        .REGISTER_DESCRIPTOR(1'b1), .REGISTER_ROW_ADDRESS(1'b0),
        .REGISTER_CACHE_REQUEST(1'b1), .CACHE_RESPONSE_DEPTH(2)
    ) u_frontend (.clk(clk));
    endmodule
    """
    with tempfile.TemporaryDirectory(prefix='frontend_profile_') as temporary:
        repo = Path(temporary)
        path = repo / 'rtl/npu/dma/axi_dual_block_dma.sv'
        path.parent.mkdir(parents=True)
        path.write_text(source)
        check('literal_parameters', operators.frontend_register_configuration(repo) == {
            'conv_register_descriptor': 1, 'conv_register_row_address': 0,
            'conv_register_cache_request': 1, 'conv_cache_demand_outstanding': 2})
        path.write_text('// ' + source.replace('\n', '\n// ') + '\n' + source)
        check('comments_excluded', operators.frontend_register_configuration(repo)['conv_register_descriptor'] == 1)
        for name, text in (
            ('expression_rejected', source.replace(".REGISTER_DESCRIPTOR(1'b1)", '.REGISTER_DESCRIPTOR(ENABLED)')),
            ('missing_rejected', source.replace(".REGISTER_ROW_ADDRESS(1'b0),", '')),
            ('duplicate_parameter_rejected', source.replace(".REGISTER_ROW_ADDRESS(1'b0)",
                ".REGISTER_ROW_ADDRESS(1'b0), .REGISTER_ROW_ADDRESS(1'b1)")),
            ('duplicate_instance_rejected', source + source),
            ('unknown_value_rejected', source.replace(".REGISTER_DESCRIPTOR(1'b1)", ".REGISTER_DESCRIPTOR(1'bx)")),
            ('depth_expression_rejected', source.replace('.CACHE_RESPONSE_DEPTH(2)', '.CACHE_RESPONSE_DEPTH(DEPTH)')),
            ('depth_zero_rejected', source.replace('.CACHE_RESPONSE_DEPTH(2)', '.CACHE_RESPONSE_DEPTH(0)')),
            ('depth_non_power_rejected', source.replace('.CACHE_RESPONSE_DEPTH(2)', '.CACHE_RESPONSE_DEPTH(3)')),
            ('depth_duplicate_rejected', source.replace('.CACHE_RESPONSE_DEPTH(2)',
                '.CACHE_RESPONSE_DEPTH(2), .CACHE_RESPONSE_DEPTH(4)')),
        ):
            path.write_text(text)
            rejected = False
            try:
                operators.frontend_register_configuration(repo)
            except ValueError:
                rejected = True
            check(name, rejected)

    reference = dict(passed=True, profile={
        'conv_register_descriptor': 0, 'conv_register_row_address': 0,
        'conv_register_cache_request': 1, 'conv_cache_demand_outstanding': 1, 'im2col_cache_bytes': 4096,
        'shared_total_bytes': 57344}, input_manifest_sha256='fixed_input',
        cases=[dict(name=f'case_{index:02}', collection='numeric', kind='conv',
                    cycles=100 + index, output_sha256=f'output_{index}') for index in range(62)])
    reference['total_cycles'] = sum(row['cycles'] for row in reference['cases'])
    check('strict_same_configuration', regression.compare(reference, copy.deepcopy(reference))['passed'])
    prepared = copy.deepcopy(reference)
    prepared['profile'].update(conv_register_descriptor=1, conv_register_row_address=1)
    prepared['cases'][0]['cycles'] += 7
    prepared['total_cycles'] += 7
    check('strict_configuration_change_rejected', not regression.compare(reference, prepared)['passed'])
    comparison = regression.compare(reference, prepared, allow_preparation_stage_change=True)
    check('preparation_changes_reported', comparison['passed'] and comparison['timing_result'] == 'increased'
          and not comparison['checks']['same_hardware_profile']
          and not comparison['checks']['all_cycles_not_increased']
          and comparison['increased_case_count'] == 1 and comparison['total_cycle_difference'] == 7
          and comparison['cases'][0]['cycle_difference'] == 7)
    earlier_reference = copy.deepcopy(reference)
    del earlier_reference['profile']['conv_register_row_address']
    comparison = regression.compare(earlier_reference, prepared, allow_preparation_stage_change=True)
    check('unrecorded_reference_field_reported', comparison['passed'] and not
          comparison['hardware_profile_changes']['conv_register_row_address']['reference_recorded'])
    for name, mutation in (
        ('capacity_change_rejected', lambda item: item['profile'].update(im2col_cache_bytes=8192)),
        ('request_stage_change_rejected', lambda item: item['profile'].update(conv_register_cache_request=0)),
        ('nonboolean_stage_rejected', lambda item: item['profile'].update(conv_register_descriptor=2)),
        ('output_change_rejected', lambda item: item['cases'][0].update(output_sha256='changed')),
        ('missing_case_rejected', lambda item: item['cases'].pop()),
        ('duplicate_case_rejected', lambda item: item['cases'].append(copy.deepcopy(item['cases'][0]))),
        ('input_change_rejected', lambda item: item.update(input_manifest_sha256='changed')),
        ('incomplete_run_rejected', lambda item: item.update(passed=False)),
    ):
        changed = copy.deepcopy(prepared)
        mutation(changed)
        check(name, not regression.compare(reference, changed, allow_preparation_stage_change=True)['passed'])
    slower = copy.deepcopy(reference)
    slower['cases'][0]['cycles'] += 1
    slower['total_cycles'] += 1
    check('strict_cycle_increase_rejected', not regression.compare(reference, slower)['passed'])
    queued = copy.deepcopy(prepared)
    queued['profile']['conv_cache_demand_outstanding'] = 2
    check('queue_change_requires_selection', not regression.compare(
        reference, queued, allow_preparation_stage_change=True)['passed'])
    check('preparation_change_requires_selection', not regression.compare(
        reference, queued, allow_cache_response_depth_change=True)['passed'])
    comparison = regression.compare(reference, queued, allow_preparation_stage_change=True,
                                    allow_cache_response_depth_change=True)
    check('selected_pipeline_changes_reported', comparison['passed']
          and comparison['hardware_profile_changes']['conv_cache_demand_outstanding']['current'] == 2
          and comparison['total_cycle_difference'] == 7 and comparison['timing_result'] == 'increased')
    for value in (None, 0, 3, True):
        invalid = copy.deepcopy(queued)
        invalid['profile']['conv_cache_demand_outstanding'] = value
        check('invalid_response_depth_' + str(value), not regression.compare(
            reference, invalid, allow_preparation_stage_change=True,
            allow_cache_response_depth_change=True)['passed'])
    capacity_changed = copy.deepcopy(queued)
    capacity_changed['profile']['im2col_cache_bytes'] = 8192
    check('pipeline_mode_keeps_cache_storage', not regression.compare(
        reference, capacity_changed, allow_preparation_stage_change=True,
        allow_cache_response_depth_change=True)['passed'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = dict(passed=True, case_count=len(cases), cases=cases,
                  current_parameters=operators.frontend_register_configuration(ROOT))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, case_count=len(cases), report=str(args.out))))


if __name__ == '__main__':
    main()
