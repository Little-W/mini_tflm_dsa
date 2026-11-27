#!/usr/bin/env python3
"""测量十六位输出容量反馈经过控制器、部分和读取选择及实际共享 RAM 的完整路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='4927debf')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--candidate-map-name', default='candidate')
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=source, text=True).strip()
    wrapper = source/'test/fifo_s16_pressure/connected_measure.sv'
    original = wrapper.read_text()
    reference_wrapper = out/'reference_measure.sv'
    transformed = original.replace('logic s16_mode_q, s16_full, s16_issue_full;',
                                   'logic s16_mode_q, s16_full;')
    transformed = transformed.replace('.fifo_full_flag(s16_issue_full)',
        '.fifo_full_flag((s16_mode_q ? s16_full : fifo_full_flag_q) && output_conditions_q[2])')
    transformed = transformed.replace('''.fifo_full_flag(s16_full),
.i_full_select(s16_mode_q),.i_output_pending(output_conditions_q[2]),
.i_other_full(fifo_full_flag_q),.o_issue_full(s16_issue_full)''', '.fifo_full_flag(s16_full)')
    reference_wrapper.write_text(transformed)
    reference_fifo = out/'reference_s16.sv'
    reference_fifo.write_bytes(subprocess.check_output(
        ['git', 'show', revision+':rtl/npu/writeback/vec_s16_to_fifo.sv'], cwd=source))
    cases = {
        'reference': dict(top='measure', sources=[str(reference_wrapper), str(reference_fifo)],
                         options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1']),
        'candidate': dict(top='measure', sources=[str(wrapper),
                          str(source/'rtl/npu/writeback/vec_s16_to_fifo.sv')],
                          options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1']),
    }
    for config in cases.values():
        config['configuration'] = '十六位结果 FIFO、模式选择及控制器、部分和读取、共享 RAM 完整连接'
    case_file = out/'cases.json'
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    if args.prepare_only:
        return
    if not args.report_only:
        subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
            '--source-root', source, '--case-config', case_file, '--cases', 'reference', 'candidate',
            '--out', out/'pre', '--through', 'pre_lut'], cwd=source, check=True)
        for label in cases:
            name = args.candidate_map_name if label == 'candidate' else 'reference'
            subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
                '--source', out/'pre'/label, '--out', out/'mapped'/name,
                '--mode', 'physical-cost', '--delay-target-ps', '6667',
                '--wire-delay-ps', '300', '--max-lut-inputs', '8',
                '--discard-abc9-temporaries'], cwd=source, check=True)
    report = dict(reference_commit=revision, fifo=dict(vlen=16, banks=4, bus_width=64),
                  memory=dict(physical_banks=7, bank_bytes=8192, total_bytes=57344),
                  registered_external_boundaries=True,
                  s8_full_is_registered_input=True, whole_soc=False,
                  primitive_and_route_timing_measured=False,
                  mapping=dict(mode='physical-cost', delay_target_ps=6667, wire_delay_ps=300,
                               max_lut_inputs=8), cases={})
    for label in cases:
        name = args.candidate_map_name if label == 'candidate' else 'reference'
        folder = out/'mapped'/name
        manifest = json.loads((out/'pre'/label/'manifest.json').read_text())
        for filename, expected in manifest['sources_sha256'].items():
            path = Path(filename)
            if label == 'reference' and filename == 'test/fifo_s16_pressure/connected_measure.sv':
                path = reference_wrapper
            elif not path.is_absolute():
                path = source/path
            if digest(path) != expected:
                raise RuntimeError('技术映射输入内容与当前报告不一致：'+str(path))
        synthesis = json.loads((folder/'summary.json').read_text())
        metrics = json.loads((folder/'metrics.json').read_text())
        module = json.loads((folder/'mapped.json').read_text())['modules']['measure']
        pre_lut = out/'pre'/label/'pre_lut.il'
        for cell, origin in register_origins(pre_lut, 'measure').items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        complete = connected_paths(module, limit=4, group_limit=4)
        selected = {}
        for group, prefixes in {'s16_state': ('u_s16.',),
                                's8_capacity': ('fifo_full_flag_q',),
                                'format': ('s16_mode_q',),
                                'output_qualification': ('output_conditions_q',)}.items():
            selected[group] = connected_paths(module, limit=2, group_limit=2,
                root_filter=lambda name, cell, port, prefixes=prefixes:
                    cell.get('attributes', {}).get('fpga_register_origin', '').startswith(prefixes))
        if not complete['graph_complete'] or not synthesis['functional_verification']['passed']:
            raise RuntimeError('完整组合图或映射功能检查未通过')
        report['cases'][label] = dict(resources=metrics['resources'], complete_paths=complete,
            selected_paths=selected, abc9_functional_verification=True,
            source_sha256=manifest['sources_sha256'], mapped_sha256=digest(folder/'mapped.json'))
        print(label, metrics['resources']['logic_lut_cells'], complete['longest_register_path_cells'],
              {group: item['longest_register_path_cells'] for group, item in selected.items()}, flush=True)
    report['runner_sha256'] = digest(Path(__file__))
    (out/'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
